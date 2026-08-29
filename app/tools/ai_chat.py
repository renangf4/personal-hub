import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator

import httpx

OLLAMA_BASE_URL = "http://localhost:11434"
MODELO_PADRAO = "qwen2.5-coder:3b"
# Default alinhado ao uso diario de codigo (Ollama tipico: 4k–16k).
CONTEXT_PADRAO = 16384
# Folga do SO/browser/Ollama — 500 MB era apertado demais.
RAM_FOLGA_BYTES = int(1.5 * 1024 * 1024 * 1024)
# Com modelo quase todo na GPU, ainda precisa de um pouco de RAM de sistema.
RAM_FOLGA_COM_GPU_BYTES = int(0.8 * 1024 * 1024 * 1024)
# Folga na VRAM (driver / fragmentacao).
VRAM_FOLGA_BYTES = int(0.5 * 1024 * 1024 * 1024)
# Reserva de tokens pra resposta do modelo dentro do num_ctx.
CTX_RESERVA_RESPOSTA = 0.22

_pull_lock = asyncio.Lock()
_pull_task: asyncio.Task | None = None
_pull_state: dict = {
    "ativo": False,
    "modelo": "",
    "status": "",
    "completed": 0,
    "total": 0,
    "erro": None,
}


def snapshot_pull() -> dict:
    return {
        "ativo": bool(_pull_state["ativo"]),
        "modelo": _pull_state["modelo"] or "",
        "status": _pull_state["status"] or "",
        "completed": int(_pull_state["completed"] or 0),
        "total": int(_pull_state["total"] or 0),
        "erro": _pull_state["erro"],
    }


def obter_ram() -> dict | None:
    """Memoria fisica: total / disponivel / usada (bytes). Sem deps extras."""
    try:
        sistema = platform.system()
        if sistema == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return None
            total = int(stat.ullTotalPhys)
            livre = int(stat.ullAvailPhys)
            return {"total": total, "disponivel": livre, "usada": total - livre}

        if sistema == "Linux":
            info: dict[str, int] = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for linha in f:
                    partes = linha.split(":")
                    if len(partes) != 2:
                        continue
                    chave = partes[0].strip()
                    valor = partes[1].strip().split()[0]
                    if chave in ("MemTotal", "MemAvailable"):
                        info[chave] = int(valor) * 1024
            total = info.get("MemTotal")
            livre = info.get("MemAvailable")
            if total is None or livre is None:
                return None
            return {"total": total, "disponivel": livre, "usada": total - livre}

        if sistema == "Darwin":
            total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
            vm = subprocess.check_output(["vm_stat"], text=True)
            page = 4096
            m = re.search(r"page size of (\d+)", vm)
            if m:
                page = int(m.group(1))
            livres = 0
            for chave in ("Pages free", "Pages inactive", "Pages speculative"):
                m = re.search(rf"{chave}:\s+(\d+)", vm)
                if m:
                    livres += int(m.group(1))
            livre = livres * page
            return {"total": total, "disponivel": livre, "usada": total - livre}
    except Exception:
        return None
    return None


def obter_vram() -> dict | None:
    """VRAM NVIDIA livre (Windows/Linux via nvidia-smi). Escolhe a GPU com mais livre."""
    if platform.system() not in ("Windows", "Linux"):
        return None
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    kwargs: dict = {
        "text": True,
        "timeout": 3,
        "stderr": subprocess.DEVNULL,
    }
    if platform.system() == "Windows":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        out = subprocess.check_output(
            [
                exe,
                "--query-gpu=name,memory.total,memory.free,memory.used",
                "--format=csv,noheader,nounits",
            ],
            **kwargs,
        )
    except Exception:
        return None

    melhor: dict | None = None
    for linha in out.strip().splitlines():
        partes = [p.strip() for p in linha.split(",")]
        if len(partes) < 4:
            continue
        try:
            nome = partes[0]
            total = int(float(partes[1]) * 1024 * 1024)
            livre = int(float(partes[2]) * 1024 * 1024)
            usada = int(float(partes[3]) * 1024 * 1024)
        except (TypeError, ValueError):
            continue
        cand = {
            "nome": nome,
            "total": total,
            "disponivel": livre,
            "usada": usada,
        }
        if melhor is None or livre > melhor["disponivel"]:
            melhor = cand
    return melhor


def memoria_suficiente(
    need_bytes: int,
    ram: dict | None,
    vram: dict | None,
) -> bool:
    """True se a estimativa cabe: preferindo VRAM, com overflow parcial na RAM."""
    need = max(0, int(need_bytes))
    if vram and vram.get("disponivel", 0) > 0:
        gpu_cap = max(0, int(vram["disponivel"]) - VRAM_FOLGA_BYTES)
        on_gpu = min(need, gpu_cap)
        on_ram = need - on_gpu
        if on_ram <= 0:
            # Quase tudo na GPU — so exige folga menor de RAM de sistema.
            if not ram or not ram.get("disponivel"):
                return True
            return int(ram["disponivel"]) >= RAM_FOLGA_COM_GPU_BYTES
        if not ram or not ram.get("disponivel"):
            return False
        return int(ram["disponivel"]) - on_ram >= RAM_FOLGA_BYTES

    if not ram or not ram.get("disponivel"):
        return False
    return int(ram["disponivel"]) - need >= RAM_FOLGA_BYTES


def _modo_memoria(vram: dict | None) -> str:
    if vram and vram.get("disponivel", 0) > 0:
        return "gpu"
    return "cpu"


CONTEXTOS = [
    {
        "tokens": 4096,
        "label": "4k",
        "nome": "Perguntas curtas",
        "descricao": "Pouco uso de memoria. Historico curto.",
        "indicado": False,
        "ram": "",
        "ram_gb": 0,
    },
    {
        "tokens": 8192,
        "label": "8k",
        "nome": "Uso leve",
        "descricao": "Chat simples e trechos pequenos de codigo.",
        "indicado": False,
        "ram": "",
        "ram_gb": 0,
    },
    {
        "tokens": 16384,
        "label": "16k",
        "nome": "Codigo diario",
        "descricao": "Arquivos medios. Bom equilibrio na maioria dos PCs.",
        "indicado": False,
        "ram": "",
        "ram_gb": 0,
    },
    {
        "tokens": 32768,
        "label": "32k",
        "nome": "Historico longo",
        "descricao": "Codigo + historico. Exige mais RAM livre.",
        "indicado": False,
        "ram": "",
        "ram_gb": 0,
    },
    {
        "tokens": 65536,
        "label": "64k",
        "nome": "Logs / multi-arquivo",
        "descricao": "Logs grandes e varios arquivos. Pesado em RAM/VRAM.",
        "indicado": False,
        "ram": "",
        "ram_gb": 0,
    },
    {
        "tokens": 131072,
        "label": "128k",
        "nome": "Contexto maximo",
        "descricao": "Projetos grandes. So com muita RAM/VRAM livre.",
        "indicado": False,
        "ram": "",
        "ram_gb": 0,
    },
]

CONTEXTOS_PERMITIDOS = {c["tokens"] for c in CONTEXTOS}


def _parse_tamanho_gb(texto: str | None) -> float | None:
    if not texto:
        return None
    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*GB", str(texto), re.I)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def _tamanho_modelo_gb(modelo: str, tamanhos: dict[str, float] | None = None) -> float:
    """Estima GB em disco/carregado do modelo (preset ou mapa do /api/tags)."""
    nome = (modelo or "").strip()
    low = nome.lower()
    if tamanhos:
        if nome in tamanhos:
            return tamanhos[nome]
        for k, v in tamanhos.items():
            kl = k.lower()
            if kl == low or kl.startswith(low + ":") or low.startswith(kl.split(":")[0]):
                return v
    for preset in MODELOS_PRESET:
        slug = preset["slug"].lower()
        if low == slug or low.startswith(slug + ":") or slug in low:
            gb = _parse_tamanho_gb(preset.get("tamanho"))
            if gb:
                return gb
    # fallback conservador (7B Q4 típico)
    return 4.7


def estimar_ram_gb(modelo: str, num_ctx: int, tamanhos: dict[str, float] | None = None) -> float:
    """Heuristica: pesos do modelo + KV cache proporcional ao contexto.

    Nao e exato (arquitetura/quantizacao variam), mas acompanha o que se ve
    no `ollama ps` bem melhor que uma tabela fixa so por num_ctx.
    """
    modelo_gb = _tamanho_modelo_gb(modelo, tamanhos)
    ctx = max(512, int(num_ctx or CONTEXT_PADRAO))
    pesos = modelo_gb * 1.2
    # KV cresce com ctx e com tamanho do modelo
    kv = (ctx / 4096.0) * modelo_gb * 0.42
    return round(max(1.0, pesos + kv), 1)


def _fmt_ram_gb(gb: float) -> str:
    if gb >= 10:
        return f"~{gb:.0f} GB"
    return f"~{gb:.1f} GB"


def estimar_tokens(texto: str) -> int:
    """Estimativa barata (~4 chars/token) pra PT + codigo."""
    if not texto:
        return 0
    return max(1, len(texto) // 4)


def encaixar_historico(mensagens: list[dict], num_ctx: int) -> tuple[list[dict], dict | None]:
    """Mantem system + mensagens mais recentes dentro do orcamento do contexto.

    Equivalente leve ao truncation/compaction das UIs locais: nao resume com
    outro modelo, so omite turnos antigos (e trunca o mais recente se preciso).
    """
    ctx = max(1024, int(num_ctx or CONTEXT_PADRAO))
    budget = max(512, int(ctx * (1.0 - CTX_RESERVA_RESPOSTA)))

    system = [m for m in mensagens if m.get("role") == "system"]
    resto = [m for m in mensagens if m.get("role") != "system"]

    usados = sum(estimar_tokens(str(m.get("content") or "")) for m in system)
    mantidas: list[dict] = []
    omitidas = 0

    for msg in reversed(resto):
        conteudo = str(msg.get("content") or "")
        tokens = estimar_tokens(conteudo)
        if mantidas and usados + tokens > budget:
            omitidas += 1
            continue
        if not mantidas and usados + tokens > budget:
            # garante ao menos o ultimo turno (truncado)
            chars = max(800, (budget - usados) * 4)
            if len(conteudo) > chars:
                conteudo = (
                    conteudo[:chars]
                    + "\n\n[... truncado pra caber no contexto ...]"
                )
            mantidas.append({**msg, "content": conteudo})
            usados = budget
            break
        mantidas.append(msg)
        usados += tokens

    mantidas.reverse()
    resultado = system + mantidas
    aviso = None
    if omitidas:
        aviso = {
            "tipo": "aviso",
            "hub": True,
            "msg": (
                f"Historico antigo omitido ({omitidas} mensagem(ns)) "
                f"pra caber no contexto {_label_ctx(ctx)} — padrao das UIs locais."
            ),
        }
    return resultado, aviso


def _contextos_com_estimativa(
    modelo: str,
    tamanhos: dict[str, float] | None = None,
    ram: dict | None = None,
    vram: dict | None = None,
) -> list[dict]:
    out = []
    for c in CONTEXTOS:
        gb = estimar_ram_gb(modelo, c["tokens"], tamanhos)
        need = int(gb * (1024 ** 3))
        item = {
            **c,
            "ram_gb": gb,
            "ram": _fmt_ram_gb(gb),
            "cabe": memoria_suficiente(need, ram, vram),
        }
        out.append(item)
    return out


def sugerir_contexto(
    ram: dict | None,
    modelo: str = MODELO_PADRAO,
    tamanhos: dict[str, float] | None = None,
    vram: dict | None = None,
) -> int:
    """Maior contexto cuja estimativa cabe (VRAM preferencial + overflow em RAM)."""
    fallback = CONTEXT_PADRAO if CONTEXT_PADRAO in CONTEXTOS_PERMITIDOS else CONTEXTOS[0]["tokens"]
    if (not ram or not ram.get("disponivel")) and (not vram or not vram.get("disponivel")):
        return fallback
    cabem = []
    for c in CONTEXTOS:
        need = int(estimar_ram_gb(modelo, c["tokens"], tamanhos) * (1024 ** 3))
        if memoria_suficiente(need, ram, vram):
            cabem.append(c["tokens"])
    if not cabem:
        return CONTEXTOS[0]["tokens"]
    return cabem[-1]


def limitar_contexto(
    num_ctx: int,
    ram: dict | None = None,
    modelo: str = MODELO_PADRAO,
    tamanhos: dict[str, float] | None = None,
    vram: dict | None = None,
) -> tuple[int | None, dict | None]:
    """Ajusta num_ctx pra caber na memoria disponivel (GPU/RAM), sem matar mid-gen."""
    ram = ram if ram is not None else obter_ram()
    vram = vram if vram is not None else obter_vram()
    pedido = num_ctx if num_ctx in CONTEXTOS_PERMITIDOS else CONTEXT_PADRAO

    need_pedido = int(estimar_ram_gb(modelo, pedido, tamanhos) * (1024 ** 3))
    if memoria_suficiente(need_pedido, ram, vram):
        return pedido, None

    seguro = sugerir_contexto(ram, modelo, tamanhos, vram)
    need_min = int(estimar_ram_gb(modelo, CONTEXTOS[0]["tokens"], tamanhos) * (1024 ** 3))
    if not memoria_suficiente(need_min, ram, vram):
        partes = []
        if ram and ram.get("disponivel") is not None:
            partes.append(f"RAM livre {ram['disponivel'] / (1024 ** 3):.1f} GB")
        if vram and vram.get("disponivel") is not None:
            partes.append(
                f"VRAM livre {vram['disponivel'] / (1024 ** 3):.1f} GB"
                + (f" ({vram.get('nome')})" if vram.get("nome") else "")
            )
        onde = " / ".join(partes) if partes else "sem leitura de memoria"
        return None, {
            "erro": True,
            "msg": (
                f"Memoria baixa ({onde}). "
                "Feche programas / outras apps na GPU, ou escolha um modelo mais leve "
                "antes de gerar."
            ),
        }

    modo = "GPU/VRAM" if _modo_memoria(vram) == "gpu" else "RAM"
    return seguro, {
        "tipo": "aviso",
        "hub": True,
        "pedido": pedido,
        "usado": seguro,
        "msg": (
            f"Contexto reduzido de {_label_ctx(pedido)} para {_label_ctx(seguro)} "
            f"(estimativa {_fmt_ram_gb(estimar_ram_gb(modelo, pedido, tamanhos))} "
            f"com `{modelo}`) pra caber com folga em {modo}."
        ),
    }


def _label_ctx(tokens: int) -> str:
    meta = next((c for c in CONTEXTOS if c["tokens"] == tokens), None)
    return meta["label"] if meta else str(tokens)


async def descarregar_modelo(modelo: str) -> dict:
    """Remove o modelo da RAM/VRAM do Ollama (CLI stop primeiro — API keep_alive:0 pode travar)."""
    if not modelo:
        return {"ok": False, "msg": "Modelo vazio"}

    erros: list[str] = []
    ok_cli = False
    ok_api = False
    nomes = _variantes_nome_modelo(modelo)

    # 1) CLI `ollama stop` — mais confiavel e nao enfileira atras de /api/chat
    exe = detectar_ollama_instalado()
    if exe:
        flags = _create_no_window() if platform.system() == "Windows" else 0
        for nome in nomes:
            try:
                r = subprocess.run(
                    [exe, "stop", nome],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    creationflags=flags,
                )
                if r.returncode == 0:
                    ok_cli = True
                    break
                if r.stderr or r.stdout:
                    erros.append((r.stderr or r.stdout).strip()[:120])
            except Exception as e:
                erros.append(f"cli:{e}")

    # 2) API keep_alive 0 — timeout curto pra nao segurar o hub se o runner estiver preso
    if not ok_cli:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=2.0)) as client:
                for nome in nomes:
                    try:
                        resp = await client.post(
                            f"{OLLAMA_BASE_URL}/api/generate",
                            json={
                                "model": nome,
                                "prompt": "",
                                "keep_alive": 0,
                                "stream": False,
                            },
                        )
                        if resp.status_code < 400:
                            ok_api = True
                            break
                        erros.append(f"api:{resp.status_code}")
                    except Exception as e:
                        erros.append(f"api:{e}")
        except httpx.ConnectError:
            return {"ok": False, "msg": "Ollama nao esta rodando"}
        except Exception as e:
            erros.append(f"http:{e}")

    # 3) Confirma /api/ps; se ainda estiver la, mata llama-server no Windows
    ainda = await _modelo_ainda_carregado(nomes)
    if ainda and platform.system() == "Windows":
        try:
            await _matar_llama_server_se_inchado(limite_mb=200)
            ainda = await _modelo_ainda_carregado(nomes)
        except Exception as e:
            erros.append(f"kill:{e}")

    if ok_cli or ok_api or not ainda:
        return {
            "ok": True,
            "modelo": modelo,
            "via": "cli" if ok_cli else ("api" if ok_api else "kill"),
        }
    return {"ok": False, "msg": "; ".join(erros) or "Falha ao descarregar"}


def _variantes_nome_modelo(modelo: str) -> list[str]:
    """DeepHat/... e DeepHat/...:latest — o Ollama oscila entre os dois."""
    m = (modelo or "").strip()
    if not m:
        return []
    out = [m]
    if ":" not in m.split("/")[-1]:
        out.append(m + ":latest")
    elif m.endswith(":latest"):
        out.append(m[: -len(":latest")])
    # únicos preservando ordem
    vistos: set[str] = set()
    uniq: list[str] = []
    for n in out:
        if n not in vistos:
            vistos.add(n)
            uniq.append(n)
    return uniq


async def _modelo_ainda_carregado(nomes: list[str]) -> bool:
    alvos = {n.lower() for n in nomes}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            ps = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
            if ps.status_code != 200:
                return False
            for m in (ps.json() or {}).get("models") or []:
                nome = (m.get("name") or m.get("model") or "").lower()
                if not nome:
                    continue
                if nome in alvos or any(nome.startswith(a + ":") or a.startswith(nome) for a in alvos):
                    return True
                base = nome.split(":")[0]
                if any(a.split(":")[0] == base for a in alvos):
                    return True
    except Exception:
        return False
    return False


async def descarregar_todos() -> dict:
    """Descarrega todos os modelos residentes; no Windows pode matar llama-server."""
    nomes: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            ps = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
            if ps.status_code == 200:
                for m in (ps.json() or {}).get("models") or []:
                    nome = m.get("name") or m.get("model") or ""
                    if nome:
                        nomes.append(nome)
    except httpx.ConnectError:
        return {"ok": False, "msg": "Ollama nao esta rodando"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

    if not nomes:
        # Mesmo sem entrada no /ps, llama-server orfao pode segurar RAM
        if platform.system() == "Windows":
            await _matar_llama_server_se_inchado(limite_mb=200)
        return {"ok": True, "msg": "Nenhum modelo carregado", "modelos": []}

    resultados = []
    for nome in nomes:
        resultados.append(await descarregar_modelo(nome))

    ainda = []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            ps = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
            if ps.status_code == 200:
                ainda = [
                    (m.get("name") or m.get("model"))
                    for m in (ps.json() or {}).get("models") or []
                    if m.get("name") or m.get("model")
                ]
    except Exception:
        pass

    if ainda and platform.system() == "Windows":
        await _matar_llama_server_se_inchado(limite_mb=200)
        ainda = []

    ok = all(r.get("ok") for r in resultados) and not ainda
    return {
        "ok": ok,
        "msg": "Memoria liberada" if ok else "Parcial — ainda ha modelo carregado",
        "modelos": nomes,
        "detalhe": resultados,
    }


async def _matar_llama_server_se_inchado(limite_mb: int = 800) -> None:
    """Ultimo recurso: encerra llama-server.exe se ainda estiver comendo RAM."""
    if platform.system() != "Windows":
        return
    flags = _create_no_window()
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=flags,
        )
    except Exception:
        return
    texto = (out.stdout or "").strip()
    if not texto or "llama-server.exe" not in texto.lower():
        return
    # CSV: "llama-server.exe","pid","session","session#","mem"
    for linha in texto.splitlines():
        partes = [p.strip().strip('"') for p in linha.split(",")]
        if len(partes) < 5:
            continue
        mem_raw = partes[-1].replace(".", "").replace(",", "").replace("K", "").replace(" ", "")
        try:
            mem_kb = int(mem_raw)
        except ValueError:
            mem_kb = limite_mb * 1024
        if mem_kb >= limite_mb * 1024:
            subprocess.run(
                ["taskkill", "/F", "/IM", "llama-server.exe", "/T"],
                capture_output=True,
                timeout=15,
                creationflags=flags,
            )
            return

FOCOS = {
    "codigo": {
        "id": "codigo",
        "nome": "Codigo",
        "icone": "bi-code-slash",
        "descricao": "Programacao, refatoracao e arquitetura.",
    },
    "seguranca": {
        "id": "seguranca",
        "nome": "Seguranca",
        "icone": "bi-shield-lock",
        "descricao": "Cybersecurity, red team e DevSecOps.",
    },
    "geral": {
        "id": "geral",
        "nome": "Geral",
        "icone": "bi-chat-dots",
        "descricao": "Chat, escrita e tarefas do dia a dia.",
    },
    "raciocinio": {
        "id": "raciocinio",
        "nome": "Raciocinio",
        "icone": "bi-lightbulb",
        "descricao": "Logica, matematica e problemas complexos.",
    },
    "leve": {
        "id": "leve",
        "nome": "Leve / Rapido",
        "icone": "bi-lightning-charge",
        "descricao": "Respostas rapidas com pouco uso de RAM.",
    },
}

MODELOS_PRESET = [
    # Codigo
    {
        "slug": "qwen2.5-coder:1.5b",
        "nome": "Qwen Coder 1.5B",
        "descricao": "Autocomplete e snippets. Muito rapido.",
        "tamanho": "~1.0 GB",
        "icone": "bi-lightning-charge",
        "foco": "codigo",
    },
    {
        "slug": "qwen2.5-coder:3b",
        "nome": "Qwen Coder 3B",
        "descricao": "Equilibrio ideal pra codigo no dia a dia.",
        "tamanho": "~2.0 GB",
        "icone": "bi-stars",
        "foco": "codigo",
    },
    {
        "slug": "qwen2.5-coder:7b",
        "nome": "Qwen Coder 7B",
        "descricao": "Melhor qualidade em codigo e debug.",
        "tamanho": "~4.7 GB",
        "icone": "bi-gem",
        "foco": "codigo",
    },
    {
        "slug": "deepseek-coder-v2:16b",
        "nome": "DeepSeek Coder V2",
        "descricao": "Forte em codigo longo e multi-linguagem. Mais pesado.",
        "tamanho": "~8.9 GB",
        "icone": "bi-braces",
        "foco": "codigo",
    },
    {
        "slug": "codellama:7b",
        "nome": "Code Llama 7B",
        "descricao": "Classico da Meta focado em programacao.",
        "tamanho": "~3.8 GB",
        "icone": "bi-filetype-py",
        "foco": "codigo",
    },
    # Seguranca
    {
        "slug": "DeepHat/DeepHat-V1-7B",
        "nome": "DeepHat",
        "descricao": "Cybersecurity / red team (deephat.ai). Nao censurado.",
        "tamanho": "~14 GB",
        "icone": "bi-shield-lock",
        "foco": "seguranca",
    },
    # Geral
    {
        "slug": "llama3.2:3b",
        "nome": "Llama 3.2 3B",
        "descricao": "Chat leve e versatil da Meta.",
        "tamanho": "~2.0 GB",
        "icone": "bi-chat-dots",
        "foco": "geral",
    },
    {
        "slug": "llama3.1:8b",
        "nome": "Llama 3.1 8B",
        "descricao": "Bom all-rounder pra conversa e tarefas gerais.",
        "tamanho": "~4.7 GB",
        "icone": "bi-chat-square-text",
        "foco": "geral",
    },
    {
        "slug": "qwen2.5:7b",
        "nome": "Qwen 2.5 7B",
        "descricao": "Multilingual forte, bom em instrucoes.",
        "tamanho": "~4.7 GB",
        "icone": "bi-globe2",
        "foco": "geral",
    },
    {
        "slug": "mistral:7b",
        "nome": "Mistral 7B",
        "descricao": "Rapido e competente pra chat geral.",
        "tamanho": "~4.1 GB",
        "icone": "bi-cloud",
        "foco": "geral",
    },
    {
        "slug": "gemma2:9b",
        "nome": "Gemma 2 9B",
        "descricao": "Google DeepMind, bom em seguir instrucoes.",
        "tamanho": "~5.4 GB",
        "icone": "bi-diamond",
        "foco": "geral",
    },
    # Raciocinio
    {
        "slug": "deepseek-r1:7b",
        "nome": "DeepSeek R1 7B",
        "descricao": "Raciocinio passo a passo, math e logica.",
        "tamanho": "~4.7 GB",
        "icone": "bi-lightbulb",
        "foco": "raciocinio",
    },
    {
        "slug": "deepseek-r1:14b",
        "nome": "DeepSeek R1 14B",
        "descricao": "Raciocinio mais profundo. Exige mais RAM.",
        "tamanho": "~9.0 GB",
        "icone": "bi-cpu",
        "foco": "raciocinio",
    },
    {
        "slug": "phi4-mini",
        "nome": "Phi-4 Mini",
        "descricao": "Microsoft: denso e forte em STEM no tamanho pequeno.",
        "tamanho": "~2.5 GB",
        "icone": "bi-mortarboard",
        "foco": "raciocinio",
    },
    {
        "slug": "phi4",
        "nome": "Phi-4 14B",
        "descricao": "STEM e raciocinio analitico de alto nivel.",
        "tamanho": "~9.1 GB",
        "icone": "bi-mortarboard-fill",
        "foco": "raciocinio",
    },
    # Leve
    {
        "slug": "llama3.2:1b",
        "nome": "Llama 3.2 1B",
        "descricao": "Minimo absoluto. Ideal pra testes rapidos.",
        "tamanho": "~1.3 GB",
        "icone": "bi-lightning",
        "foco": "leve",
    },
    {
        "slug": "gemma2:2b",
        "nome": "Gemma 2 2B",
        "descricao": "Leve da Google, surpreende pelo tamanho.",
        "tamanho": "~1.6 GB",
        "icone": "bi-lightning-charge-fill",
        "foco": "leve",
    },
    {
        "slug": "qwen2.5:1.5b",
        "nome": "Qwen 2.5 1.5B",
        "descricao": "Chat multilingual ultra leve.",
        "tamanho": "~1.0 GB",
        "icone": "bi-speedometer",
        "foco": "leve",
    },
]


def _modelo_disponivel(modelo: str, modelos: list[str]) -> bool:
    return _nome_instalado(modelo, modelos) is not None


def _nome_instalado(modelo: str, modelos: list[str]) -> str | None:
    """Retorna o nome exato instalado no Ollama correspondente ao slug do preset."""
    m = modelo.lower()
    for nome in modelos:
        n = nome.lower()
        base = n.split(":", 1)[0]
        if n == m or n.startswith(m + ":") or base == m:
            return nome
    return None


OLLAMA_DOWNLOAD = {
    "Windows": "https://ollama.com/download/OllamaSetup.exe",
    "Darwin": "https://ollama.com/download/Ollama-darwin.zip",
    "Linux": "https://ollama.com/install.sh",
}


def _caminhos_ollama_windows() -> list[Path]:
    candidatos = []
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        candidatos.append(Path(local_app) / "Programs" / "Ollama" / "ollama.exe")
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidatos.append(Path(program_files) / "Ollama" / "ollama.exe")
    return candidatos


def detectar_ollama_instalado() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    if platform.system() == "Windows":
        for caminho in _caminhos_ollama_windows():
            if caminho.is_file():
                return str(caminho)
    return None

SYSTEM_PROMPT_CODIGO = (
    "Voce e um assistente senior especialista em engenharia de software, "
    "arquitetura de sistemas, infraestrutura, Docker e desenvolvimento full-stack. "
    "Seja direto, pratico, evite explicacoes excessivamente teoricas e foque em "
    "fornecer codigo limpo, performatico e bem documentado em portugues."
)

SYSTEM_PROMPT_SEGURANCA = (
    "Voce e DeepHat, um assistente especializado em cybersecurity, red team, "
    "DevSecOps e analise ofensiva/defensiva. Seja direto e tecnico. "
    "Forneca orientacao pratica, comandos, payloads e raciocinio de ataque/defesa "
    "quando solicitado. Responda em portugues."
)

SYSTEM_PROMPT_GERAL = (
    "Voce e um assistente util, claro e objetivo. Responda em portugues, "
    "com foco em praticidade. Quando fizer sentido, use listas e exemplos curtos."
)

SYSTEM_PROMPT_RACIOCINIO = (
    "Voce e um assistente de raciocinio analitico. Pense passo a passo, "
    "mostre a logica de forma clara e chegue a uma conclusao objetiva. "
    "Responda em portugues."
)

SYSTEM_PROMPT_LEVE = (
    "Voce e um assistente conciso. Respostas curtas e diretas em portugues."
)

SYSTEM_PROMPTS_FOCO = {
    "codigo": SYSTEM_PROMPT_CODIGO,
    "seguranca": SYSTEM_PROMPT_SEGURANCA,
    "geral": SYSTEM_PROMPT_GERAL,
    "raciocinio": SYSTEM_PROMPT_RACIOCINIO,
    "leve": SYSTEM_PROMPT_LEVE,
}


def _foco_do_modelo(modelo: str) -> str:
    m = modelo.lower()
    for preset in MODELOS_PRESET:
        slug = preset["slug"].lower()
        if m == slug or m.startswith(slug + ":") or slug == m.split(":", 1)[0]:
            return preset.get("foco", "geral")
        if "/" in slug and slug in m:
            return preset.get("foco", "geral")
    if "deephat" in m:
        return "seguranca"
    if "coder" in m or "codellama" in m:
        return "codigo"
    if "r1" in m or "phi" in m:
        return "raciocinio"
    return "geral"


def _system_prompt_para(modelo: str) -> str:
    return SYSTEM_PROMPTS_FOCO.get(_foco_do_modelo(modelo), SYSTEM_PROMPT_GERAL)


async def verificar_status(modelo: str = MODELO_PADRAO) -> dict:
    """Verifica se o Ollama esta rodando e quais modelos preset ja foram baixados."""
    exe = detectar_ollama_instalado()
    modelo = (modelo or MODELO_PADRAO).strip() or MODELO_PADRAO
    info = {
        "ollama_ativo": False,
        "ollama_instalado": bool(exe),
        "ollama_exe": exe,
        "sistema": platform.system(),
        "modelo_padrao": modelo,
        "modelo_disponivel": False,
        "modelos": [],
        "focos": list(FOCOS.values()),
        "contextos": [],
        "contexto_padrao": CONTEXT_PADRAO,
        "contexto_sugerido": CONTEXT_PADRAO,
        "presets": [
            {**preset, "baixado": False} for preset in MODELOS_PRESET
        ],
        "msg": "",
    }
    tamanhos: dict[str, float] = {}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            info["ollama_ativo"] = True
            modelos = []
            for m in data.get("models", []):
                nome = m.get("name", "")
                if not nome:
                    continue
                modelos.append(nome)
                size = m.get("size")
                if isinstance(size, (int, float)) and size > 0:
                    tamanhos[nome] = size / (1024 ** 3)
            info["modelos"] = modelos
            info["modelo_disponivel"] = _modelo_disponivel(modelo, modelos)
            for preset in info["presets"]:
                preset["baixado"] = _modelo_disponivel(preset["slug"], modelos)
    except httpx.ConnectError:
        info["msg"] = "Ollama nao esta rodando em localhost:11434"
    except Exception as e:
        info["msg"] = f"Erro ao consultar Ollama: {e}"

    info["ram"] = obter_ram()
    info["vram"] = obter_vram()
    info["memoria_modo"] = _modo_memoria(info["vram"])
    sugerido = sugerir_contexto(info["ram"], modelo, tamanhos, info["vram"])
    info["contexto_sugerido"] = sugerido
    info["contexto_padrao"] = sugerido
    info["ram_folga_bytes"] = RAM_FOLGA_BYTES
    info["vram_folga_bytes"] = VRAM_FOLGA_BYTES
    info["modelo_tamanho_gb"] = round(_tamanho_modelo_gb(modelo, tamanhos), 1)
    info["contextos"] = _contextos_com_estimativa(
        modelo, tamanhos, info["ram"], info["vram"]
    )
    for c in info["contextos"]:
        c["indicado"] = c["tokens"] == sugerido
    info["pull"] = snapshot_pull()
    return info


def _ollama_ja_responde() -> bool:
    try:
        with httpx.Client(timeout=1.5) as client:
            r = client.get(f"{OLLAMA_BASE_URL}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def _create_no_window() -> int:
    return 0x08000000 if platform.system() == "Windows" else 0


def _exe_app_ollama_windows(cli_exe: str) -> str | None:
    """App de bandeja (GUI) — evita o flash de terminal do `ollama serve`."""
    pasta = Path(cli_exe).resolve().parent
    app = pasta / "ollama app.exe"
    if app.is_file():
        return str(app)
    return None


def _processos_comando(nome_exe: str) -> list[str]:
    if platform.system() != "Windows":
        return []
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-CimInstance Win32_Process -Filter \"Name='{nome_exe}'\" "
                "| Select-Object -ExpandProperty CommandLine",
            ],
            text=True,
            errors="ignore",
            creationflags=_create_no_window(),
            timeout=8,
        )
        return [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def _ollama_app_rodando() -> bool:
    return bool(_processos_comando("ollama app.exe"))


def _ollama_eh_serve_cli() -> bool:
    """True se ha `ollama.exe serve` sem o app de bandeja (modo que abre terminais)."""
    if platform.system() != "Windows":
        return False
    if _ollama_app_rodando():
        return False
    for linha in _processos_comando("ollama.exe"):
        low = linha.lower()
        if "serve" in low:
            return True
    return False


def _encerrar_ollama_windows() -> None:
    flags = _create_no_window()
    for imagem in ("llama-server.exe", "ollama.exe"):
        subprocess.run(
            ["taskkill", "/F", "/IM", imagem, "/T"],
            capture_output=True,
            creationflags=flags,
            timeout=15,
        )


def _iniciar_app_bandeja(app: str) -> dict:
    """Sobe o Ollama pelo app GUI (sem janela preta nos runners)."""
    os.startfile(app)  # type: ignore[attr-defined]
    for _ in range(30):
        time.sleep(0.5)
        if _ollama_ja_responde():
            return {"ok": True, "exe": app, "modo": "app"}
    return {"ok": True, "exe": app, "modo": "app", "aguardando": True}


def iniciar_servico_ollama() -> dict:
    """Sobe o Ollama em background se o binario estiver instalado."""
    exe = detectar_ollama_instalado()
    if not exe:
        return {"ok": False, "msg": "Ollama nao esta instalado"}

    try:
        if platform.system() == "Windows":
            app = _exe_app_ollama_windows(exe)
            if app:
                # `ollama serve` faz o llama-server abrir terminal a cada pergunta.
                # Se estiver nesse modo, encerra e sobe pelo app de bandeja.
                if _ollama_ja_responde() and not _ollama_eh_serve_cli():
                    return {"ok": True, "exe": app, "ja_ativo": True, "modo": "app"}
                if _ollama_ja_responde() and _ollama_eh_serve_cli():
                    _encerrar_ollama_windows()
                    time.sleep(0.8)
                return _iniciar_app_bandeja(app)

        if _ollama_ja_responde():
            return {"ok": True, "exe": exe, "ja_ativo": True}

        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | _create_no_window()
                | 0x00000008
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([exe, "serve"], **kwargs)
        return {"ok": True, "exe": exe, "modo": "serve"}
    except Exception as e:
        return {"ok": False, "msg": f"Falha ao iniciar Ollama: {e}"}


def corrigir_modo_console_windows() -> dict | None:
    """Se o Ollama estiver em `serve` (CLI), troca pelo app de bandeja.

    Retorna dict com resultado, ou None se nao aplicavel.
    """
    if platform.system() != "Windows":
        return None
    exe = detectar_ollama_instalado()
    if not exe:
        return None
    app = _exe_app_ollama_windows(exe)
    if not app or not _ollama_ja_responde() or not _ollama_eh_serve_cli():
        return None
    try:
        _encerrar_ollama_windows()
        time.sleep(0.8)
        return _iniciar_app_bandeja(app)
    except Exception as e:
        return {"ok": False, "msg": str(e)}


async def _iter_aguardar_ollama(enviar) -> AsyncIterator[bytes]:
    """Poll ate Ollama responder em localhost:11434."""
    for _ in range(120):
        await asyncio.sleep(2)
        exe = detectar_ollama_instalado()
        if exe and not _ollama_ja_responde():
            iniciar_servico_ollama()
        if not exe:
            yield enviar({
                "etapa": "instalando",
                "status": "Aguardando instalacao...",
            })
            continue
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if r.status_code == 200:
                    yield enviar({
                        "etapa": "concluido",
                        "status": "Ollama instalado e em execucao.",
                        "exe": exe,
                    })
                    return
        except Exception:
            pass
        yield enviar({
            "etapa": "instalando",
            "status": "Aguardando Ollama em localhost:11434...",
            "exe": exe,
        })
    yield enviar({
        "erro": True,
        "status": "Tempo esgotado aguardando o Ollama.",
        "detalhe": "curl -fsSL https://ollama.com/install.sh | sh",
    })


async def _stream_install_linux(enviar) -> AsyncIterator[bytes]:
    yield enviar({
        "etapa": "instalando",
        "status": "Baixando e instalando Ollama no servidor...",
    })
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash",
            "-c",
            "curl -fsSL https://ollama.com/install.sh | sh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as e:
        yield enviar({"erro": True, "status": f"Nao foi possivel iniciar instalacao: {e}"})
        return

    saida_final = ""
    if proc.stdout:
        while True:
            linha = await proc.stdout.readline()
            if not linha:
                break
            texto = linha.decode("utf-8", errors="replace").rstrip()
            if texto:
                saida_final = texto
                yield enviar({"etapa": "instalando", "status": texto})

    codigo = await proc.wait()
    if codigo != 0:
        yield enviar({
            "erro": True,
            "status": f"Instalacao falhou (codigo {codigo}).",
            "detalhe": (
                saida_final
                or "No terminal do servidor: curl -fsSL https://ollama.com/install.sh | sh"
            ),
        })
        return

    yield enviar({"etapa": "instalando", "status": "Iniciando servico Ollama..."})
    iniciar_servico_ollama()
    async for chunk in _iter_aguardar_ollama(enviar):
        yield chunk


async def stream_install_ollama() -> AsyncIterator[bytes]:
    """Baixa e dispara o instalador do Ollama, retransmitindo progresso em ndjson."""

    def enviar(obj: dict) -> bytes:
        return (json.dumps(obj) + "\n").encode("utf-8")

    sistema = platform.system()
    url = OLLAMA_DOWNLOAD.get(sistema)
    if not url:
        yield enviar({"erro": True, "status": f"SO nao suportado: {sistema}"})
        return

    if sistema == "Linux":
        async for chunk in _stream_install_linux(enviar):
            yield chunk
        return

    if sistema == "Darwin":
        yield enviar({
            "erro": True,
            "status": "Instalacao automatica nao suportada no macOS por este app.",
            "detalhe": "Baixe em https://ollama.com/download e instale o app Ollama.",
        })
        return

    tmp_dir = Path(tempfile.gettempdir())
    destino = tmp_dir / "OllamaSetup.exe"

    try:
        yield enviar({"status": "Baixando instalador do Ollama...", "etapa": "download"})
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    yield enviar({
                        "erro": True,
                        "status": f"HTTP {resp.status_code} ao baixar instalador",
                    })
                    return
                total = int(resp.headers.get("content-length") or 0)
                baixado = 0
                ultimo_pct = -1
                with destino.open("wb") as f:
                    async for bloco in resp.aiter_bytes(chunk_size=64 * 1024):
                        if not bloco:
                            continue
                        f.write(bloco)
                        baixado += len(bloco)
                        if total:
                            pct = int((baixado / total) * 100)
                            if pct != ultimo_pct:
                                ultimo_pct = pct
                                yield enviar({
                                    "etapa": "download",
                                    "status": f"Baixando... {pct}%",
                                    "completed": baixado,
                                    "total": total,
                                })
                        else:
                            yield enviar({
                                "etapa": "download",
                                "status": "Baixando...",
                                "completed": baixado,
                            })

        yield enviar({
            "etapa": "instalando",
            "status": "Executando instalador. Aceite o assistente do Ollama na sua tela.",
        })

        try:
            subprocess.Popen(
                [str(destino)],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except Exception as e:
            yield enviar({"erro": True, "status": f"Falha ao abrir instalador: {e}"})
            return

        async for chunk in _iter_aguardar_ollama(enviar):
            yield chunk
    except httpx.ConnectError:
        yield enviar({"erro": True, "status": "Sem conexao com a internet para baixar o instalador."})
    except Exception as e:
        yield enviar({"erro": True, "status": f"Erro inesperado: {e}"})


def _evento_pull(extra: dict | None = None) -> bytes:
    snap = snapshot_pull()
    payload = {
        "status": snap["status"],
        "completed": snap["completed"],
        "total": snap["total"],
        "modelo": snap["modelo"],
    }
    if snap["erro"]:
        payload["erro"] = True
        payload["status"] = snap["erro"]
    if extra:
        payload.update(extra)
    return (json.dumps(payload) + "\n").encode("utf-8")


async def _rodar_pull(modelo: str) -> None:
    _pull_state.update(
        {
            "ativo": True,
            "modelo": modelo,
            "status": "Baixando...",
            "completed": 0,
            "total": 0,
            "erro": None,
        }
    )
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/pull",
                json={"name": modelo, "stream": True},
            ) as resp:
                if resp.status_code != 200:
                    erro = await resp.aread()
                    _pull_state["erro"] = (
                        f"HTTP {resp.status_code}: "
                        f"{erro.decode('utf-8', errors='ignore')[:400]}"
                    )
                    return
                async for linha in resp.aiter_lines():
                    if not linha:
                        continue
                    try:
                        ev = json.loads(linha)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("error"):
                        _pull_state["erro"] = str(ev["error"])
                        return
                    if ev.get("status"):
                        _pull_state["status"] = ev["status"]
                    if isinstance(ev.get("total"), (int, float)):
                        _pull_state["total"] = int(ev["total"])
                    if isinstance(ev.get("completed"), (int, float)):
                        _pull_state["completed"] = int(ev["completed"])
    except httpx.ConnectError:
        _pull_state["erro"] = "Ollama nao esta rodando em localhost:11434"
    except Exception as e:
        _pull_state["erro"] = f"Falha no pull: {e}"
    finally:
        _pull_state["ativo"] = False


async def _garantir_pull(modelo: str) -> dict:
    global _pull_task
    async with _pull_lock:
        if _pull_state["ativo"]:
            if _pull_state["modelo"] and _pull_state["modelo"] != modelo:
                return {
                    **snapshot_pull(),
                    "erro": f"Ja baixando {_pull_state['modelo']}",
                    "conflito": True,
                }
            return snapshot_pull()
        _pull_state.update(
            {
                "ativo": True,
                "modelo": modelo,
                "status": "Baixando...",
                "completed": 0,
                "total": 0,
                "erro": None,
            }
        )
        _pull_task = asyncio.create_task(_rodar_pull(modelo))
        return snapshot_pull()


async def stream_pull(modelo: str = MODELO_PADRAO) -> AsyncIterator[bytes]:
    """Inicia o pull em background e retransmite progresso. Recarregar a pagina nao cancela."""
    st = await _garantir_pull(modelo)
    if st.get("conflito"):
        yield _evento_pull({"erro": True, "status": st["erro"]})
        return
    last = b""
    while True:
        chunk = _evento_pull()
        if chunk != last:
            yield chunk
            last = chunk
        snap = snapshot_pull()
        if not snap["ativo"]:
            if not snap["erro"]:
                yield _evento_pull({"status": snap["status"] or "success"})
            break
        await asyncio.sleep(0.3)


async def deletar_modelo(modelo: str) -> dict:
    """Remove um modelo local via API do Ollama."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp_tags = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp_tags.raise_for_status()
            instalados = [m.get("name", "") for m in resp_tags.json().get("models", [])]
            nome = _nome_instalado(modelo, instalados)
            if not nome:
                return {"ok": False, "msg": "Modelo nao encontrado localmente"}

            resp = await client.request(
                "DELETE",
                f"{OLLAMA_BASE_URL}/api/delete",
                json={"name": nome},
            )
            if resp.status_code not in (200, 204):
                return {
                    "ok": False,
                    "msg": f"HTTP {resp.status_code}: {resp.text}",
                }
            return {"ok": True, "nome": nome}
    except httpx.ConnectError:
        return {"ok": False, "msg": "Ollama nao esta rodando em localhost:11434"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


async def stream_chat(
    modelo: str,
    mensagens: list[dict],
    incluir_system: bool = True,
    num_ctx: int = CONTEXT_PADRAO,
) -> AsyncIterator[dict]:
    """Streama a resposta do Ollama em chunks (dicts decodificados)."""
    msgs = []
    if incluir_system:
        msgs.append({"role": "system", "content": _system_prompt_para(modelo)})
    msgs.extend(mensagens)

    ram = obter_ram()
    vram = obter_vram()
    ctx, aviso = limitar_contexto(num_ctx, ram, modelo, vram=vram)
    if aviso and aviso.get("erro"):
        yield aviso
        return
    if ctx is None:
        yield {
            "erro": True,
            "msg": "Nao foi possivel escolher um contexto seguro com a RAM atual.",
        }
        return
    if aviso:
        yield aviso

    msgs, aviso_hist = encaixar_historico(msgs, ctx)
    if aviso_hist:
        yield aviso_hist

    payload = {
        "model": modelo,
        "messages": msgs,
        "stream": True,
        "keep_alive": "30s",
        "options": {
            "temperature": 0.3,
            "num_ctx": ctx,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    erro = await resp.aread()
                    yield {
                        "erro": True,
                        "msg": f"HTTP {resp.status_code}: {erro.decode('utf-8', errors='ignore')}",
                    }
                    return

                async for linha in resp.aiter_lines():
                    if not linha:
                        continue
                    try:
                        data = json.loads(linha)
                    except json.JSONDecodeError:
                        continue
                    yield data
    except httpx.ConnectError:
        yield {"erro": True, "msg": "Ollama nao esta rodando em localhost:11434"}
        return
    except Exception as e:
        yield {"erro": True, "msg": f"Falha no chat: {e}"}
        return


EXTENSOES_TEXTO = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".html", ".htm",
    ".css", ".scss", ".less", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".py", ".pyw", ".rb", ".php", ".go", ".rs", ".java", ".kt", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".swift", ".sql", ".yml", ".yaml", ".toml", ".ini",
    ".cfg", ".conf", ".env", ".sh", ".bash", ".zsh", ".bat", ".ps1", ".log",
    ".vue", ".svelte", ".r", ".lua", ".pl", ".dockerfile",
}

MAX_ANEXO_BYTES = 4 * 1024 * 1024
MAX_ANEXOS = 5
MAX_TEXTO_TOTAL = 120_000
MAX_TEXTO_POR_ARQUIVO = 80_000


def extrair_texto_bytes(nome: str, dados: bytes) -> dict:
    """Extrai texto de um anexo. Retorna {ok, nome, texto, msg?}."""
    nome = Path(nome).name or "anexo"
    ext = Path(nome).suffix.lower()
    if len(dados) > MAX_ANEXO_BYTES:
        return {"ok": False, "nome": nome, "texto": "", "msg": "Arquivo maior que 4 MB"}

    if ext == ".pdf":
        try:
            from io import BytesIO
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(dados))
            partes = []
            for page in reader.pages:
                t = page.extract_text() or ""
                if t.strip():
                    partes.append(t)
            texto = "\n\n".join(partes).strip()
            if not texto:
                return {"ok": False, "nome": nome, "texto": "", "msg": "PDF sem texto extraivel (pode ser so imagem)"}
            if len(texto) > MAX_TEXTO_POR_ARQUIVO:
                texto = texto[:MAX_TEXTO_POR_ARQUIVO] + "\n\n[... truncado ...]"
            return {"ok": True, "nome": nome, "texto": texto}
        except ImportError:
            return {
                "ok": False,
                "nome": nome,
                "texto": "",
                "msg": "Suporte a PDF ausente — reinstale o Assistente na Loja (instala pypdf)",
            }
        except Exception as e:
            return {"ok": False, "nome": nome, "texto": "", "msg": f"Falha ao ler PDF: {e}"}

    if ext in EXTENSOES_TEXTO or ext == "":
        try:
            texto = dados.decode("utf-8")
        except UnicodeDecodeError:
            try:
                texto = dados.decode("latin-1")
            except Exception as e:
                return {"ok": False, "nome": nome, "texto": "", "msg": str(e)}
        texto = texto.replace("\x00", "")
        if len(texto) > MAX_TEXTO_POR_ARQUIVO:
            texto = texto[:MAX_TEXTO_POR_ARQUIVO] + "\n\n[... truncado ...]"
        return {"ok": True, "nome": nome, "texto": texto}

    return {"ok": False, "nome": nome, "texto": "", "msg": f"Tipo nao suportado ({ext or 'sem extensao'})"}


def montar_mensagem_com_anexos(conteudo: str, anexos: list[dict]) -> str:
    """Monta o texto final com anexos ok. anexos: resultados de extrair_texto_bytes."""
    partes = [conteudo.strip()] if conteudo and conteudo.strip() else []
    usados = 0
    for a in anexos:
        if not a.get("ok") or not a.get("texto"):
            continue
        bloco = a["texto"]
        if usados + len(bloco) > MAX_TEXTO_TOTAL:
            restante = MAX_TEXTO_TOTAL - usados
            if restante < 200:
                partes.append(f"\n[anexo omitido por limite de contexto: {a['nome']}]")
                continue
            bloco = bloco[:restante] + "\n\n[... truncado por limite total ...]"
        usados += len(bloco)
        partes.append(f"\n[anexo: {a['nome']}]\n{bloco}\n[/anexo]")
    return "\n".join(partes).strip()
