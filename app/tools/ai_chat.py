import asyncio
import json
import math
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


def _ram_folga_bytes(ram: dict | None) -> int:
    """Folga proporcional ao total — 1,5 GB fixo era pesado demais em PCs de 8 GB."""
    if not ram or not ram.get("total"):
        return RAM_FOLGA_BYTES
    total = int(ram["total"])
    pct = int(total * 0.10)
    minimo = int(0.5 * 1024 ** 3)
    return min(RAM_FOLGA_BYTES, max(minimo, pct))

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
    folga_ram: int | None = None,
) -> bool:
    """True se a estimativa cabe: preferindo VRAM, com overflow parcial na RAM."""
    need = max(0, int(need_bytes))
    folga = folga_ram if folga_ram is not None else _ram_folga_bytes(ram)
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
        return int(ram["disponivel"]) - on_ram >= folga

    if not ram or not ram.get("disponivel"):
        return False
    return int(ram["disponivel"]) - need >= folga


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


def _params_b_do_modelo(modelo: str, preset: dict | None = None) -> float | None:
    if preset and preset.get("parametros"):
        m = re.search(r"([\d.]+)\s*B", str(preset["parametros"]), re.I)
        if m:
            return float(m.group(1))
    m = re.search(r"v?(\d+(?:\.\d+)?)\s*b", (modelo or "").lower())
    if m:
        return float(m.group(1))
    return None


def _slug_casa_preset(modelo: str, slug: str) -> bool:
    low = (modelo or "").strip().lower()
    s = slug.lower()
    if low == s or low.startswith(s + ":"):
        return True
    if s == low.split(":", 1)[0]:
        return True
    return bool("/" in s and s in low)


def _preset_do_modelo(modelo: str) -> dict | None:
    melhor: tuple[int, dict] | None = None
    for preset in MODELOS_PRESET:
        slug = preset["slug"]
        if _slug_casa_preset(modelo, slug):
            n = len(slug)
            if melhor is None or n > melhor[0]:
                melhor = (n, preset)
    return melhor[1] if melhor else None


def _inferir_quant_label(tamanho_gb: float, params_b: float | None) -> str:
    """Infere Q4/Q8/FP16 pelo tamanho em disco vs bilhoes de parametros."""
    if not params_b or params_b <= 0 or tamanho_gb <= 0:
        return ""
    gpb = tamanho_gb / params_b
    if gpb <= 0.62:
        return "Q4"
    if gpb <= 0.85:
        return "Q5"
    if gpb <= 1.05:
        return "Q8"
    if gpb <= 1.45:
        return "Q6_K"
    return "FP16+"


def _kv_cache_gb(params_b: float, num_ctx: int, quant_label: str = "") -> float:
    """KV cache: ~2 GB para 7B @ 4k FP16; escala por params, contexto e quant."""
    fatores = {"Q4": 0.45, "Q5": 0.55, "Q6_K": 0.65, "Q8": 0.75, "FP16+": 1.0}
    fator = fatores.get(quant_label, 0.7)
    ctx = max(512, int(num_ctx or 4096))
    return 2.0 * (params_b / 7.0) * (ctx / 4096.0) * fator


def _overhead_gb(pesos_gb: float) -> float:
    if pesos_gb < 5:
        return 1.2
    if pesos_gb < 9:
        return 2.0
    return 2.5


def _ram_total_gb(
    pesos_gb: float,
    params_b: float | None,
    num_ctx: int = 4096,
    quant_label: str = "",
) -> float:
    """Pesos (arquivo) + KV cache + margem SO/Ollama — contexto 4k por padrao."""
    pb = params_b if params_b and params_b > 0 else 7.0
    kv = _kv_cache_gb(pb, num_ctx, quant_label)
    return max(1.0, pesos_gb + kv + _overhead_gb(pesos_gb))


def _ram_nota_leiga(ram_gb: float) -> str:
    r = int(math.ceil(ram_gb))
    if r <= 6:
        return "Notebooks e PCs modestos"
    if r <= 9:
        return "PC com 8 GB ou mais"
    if r <= 12:
        return "PC com 16 GB recomendado"
    return "Maquina robusta (16 GB ou mais)"


def _ram_detalhe_tecnico(
    pesos_gb: float,
    params_b: float | None,
    num_ctx: int,
    quant_label: str,
) -> str:
    pb = params_b if params_b and params_b > 0 else 7.0
    kv = _kv_cache_gb(pb, num_ctx, quant_label)
    ov = _overhead_gb(pesos_gb)
    q = f" · {quant_label}" if quant_label else ""
    ctx_k = num_ctx // 1024 if num_ctx >= 1024 else num_ctx
    ctx_txt = f"{ctx_k}k" if num_ctx >= 1024 else str(num_ctx)
    return (
        f"Pesos ~{pesos_gb:.1f} GB{q} + contexto {ctx_txt} (~{kv:.1f} GB) "
        f"+ margem do sistema (~{ov:.1f} GB)."
    )


def _enriquecer_preset(preset: dict, tamanhos: dict[str, float] | None) -> dict:
    """Calcula RAM/quant para UI leiga + detalhes tecnicos sob demanda."""
    slug = preset["slug"]
    tamanhos = tamanhos or {}
    params_b = _params_b_do_modelo(slug, preset)
    tamanho_gb = _tamanho_modelo_gb(slug, tamanhos)
    baixado = bool(preset.get("baixado"))
    ctx_ref = CONTEXTOS[0]["tokens"]

    out = {**preset}
    out["tamanho_real_gb"] = round(tamanho_gb, 1) if baixado else None

    if baixado and tamanho_gb > 0:
        quant = _inferir_quant_label(tamanho_gb, params_b)
        total = _ram_total_gb(tamanho_gb, params_b, ctx_ref, quant)
        out["quant_label"] = quant
        out["ram_estimada_gb"] = round(total, 1)
        out["ram_minima_gb"] = int(math.ceil(total))
        out["ram_nota"] = _ram_nota_leiga(total)
        out["ram_detalhe"] = _ram_detalhe_tecnico(tamanho_gb, params_b, ctx_ref, quant)
        return out

    quant_preset = str(preset.get("quant_label") or "").strip()
    if quant_preset and params_b:
        peso = _parse_tamanho_gb(preset.get("tamanho")) or round(params_b * 0.55, 1)
        total = _ram_total_gb(peso, params_b, ctx_ref, quant_preset)
        out["quant_label"] = quant_preset
        out["ram_estimada_gb"] = round(total, 1)
        out["ram_minima_gb"] = int(math.ceil(total))
        out["ram_nota"] = _ram_nota_leiga(total)
        out["ram_detalhe"] = _ram_detalhe_tecnico(peso, params_b, ctx_ref, quant_preset)
        return out

    # Ainda nao baixado — faixa tipica Q4 a FP16
    if params_b:
        peso_q4 = round(params_b * 0.55, 1)
        peso_fp = round(params_b * 2.0, 1)
        ram_min = int(math.ceil(_ram_total_gb(peso_q4, params_b, ctx_ref, "Q4")))
        ram_max = int(math.ceil(_ram_total_gb(peso_fp, params_b, ctx_ref, "FP16+")))
        out["ram_minima_gb"] = ram_min
        out["ram_maxima_gb"] = ram_max
        out["ram_nota"] = f"De ~{ram_min} GB (compacto) a ~{ram_max} GB (completo)"
        out["ram_detalhe"] = (
            f"Depende da versao que o Ollama baixar. Estimativa: compacta (Q4) "
            f"~{peso_q4} GB no disco; completa (FP16) ~{peso_fp} GB. "
            f"Calculo: pesos + contexto 4k + margem do sistema."
        )
        return out

    tamanho_preset = _parse_tamanho_gb(preset.get("tamanho")) or tamanho_gb
    total = _ram_total_gb(tamanho_preset, params_b, ctx_ref, "")
    out["ram_minima_gb"] = int(math.ceil(total))
    out["ram_nota"] = _ram_nota_leiga(total)
    out["ram_detalhe"] = _ram_detalhe_tecnico(tamanho_preset, params_b, ctx_ref, "")
    return out


def _inferir_gb_do_nome(modelo: str) -> float | None:
    """Heuristica Q4: ~0,67 GB por bilhao de parametros (7B -> ~4,7 GB)."""
    m = re.search(r"v?(\d+(?:\.\d+)?)\s*b", (modelo or "").lower())
    if not m:
        return None
    params_b = float(m.group(1))
    return round(max(0.8, params_b * 0.67), 1)


def _tamanho_modelo_gb(modelo: str, tamanhos: dict[str, float] | None = None) -> float:
    """Estima GB em RAM ao carregar (tamanho real do Ollama ou preset)."""
    nome = (modelo or "").strip()
    low = nome.lower()
    if tamanhos:
        if nome in tamanhos:
            return tamanhos[nome]
        for k, v in tamanhos.items():
            kl = k.lower()
            if kl == low or kl.startswith(low + ":") or low.startswith(kl.split(":")[0]):
                return v
            if low.startswith(kl.rsplit(":", 1)[0] + ":") or kl.startswith(low.rsplit(":", 1)[0] + ":"):
                return v
    preset = _preset_do_modelo(nome)
    if preset:
        gb = _parse_tamanho_gb(preset.get("tamanho"))
        if gb:
            return gb
    inferido = _inferir_gb_do_nome(nome)
    if inferido:
        return inferido
    return 4.7


def estimar_need_bytes(
    modelo: str,
    num_ctx: int,
    tamanhos: dict[str, float] | None = None,
    carregado: dict | None = None,
) -> int:
    """Bytes necessarios: pesos + KV + margem (ou custo marginal se ja carregado)."""
    preset = _preset_do_modelo(modelo)
    params_b = _params_b_do_modelo(modelo, preset)

    if carregado and int(carregado.get("size") or 0) > 0:
        modelo_gb = int(carregado["size"]) / (1024 ** 3)
    else:
        modelo_gb = _tamanho_modelo_gb(modelo, tamanhos)

    ctx = max(512, int(num_ctx or CONTEXT_PADRAO))
    quant = _inferir_quant_label(modelo_gb, params_b)

    if carregado and int(carregado.get("size") or 0) > 0:
        ctx_atual = max(512, int(carregado.get("context_length") or 4096))
        need_atual = _ram_total_gb(modelo_gb, params_b, ctx_atual, quant)
        need_novo = _ram_total_gb(modelo_gb, params_b, ctx, quant)
        if ctx <= ctx_atual:
            marginal_gb = max(0.3, modelo_gb * 0.06)
        else:
            marginal_gb = max(0.35, need_novo - need_atual + 0.2)
        return int(marginal_gb * (1024 ** 3))

    total_gb = _ram_total_gb(modelo_gb, params_b, ctx, quant)
    return int(total_gb * (1024 ** 3))


def estimar_ram_gb(
    modelo: str,
    num_ctx: int,
    tamanhos: dict[str, float] | None = None,
    carregado: dict | None = None,
) -> float:
    """Heuristica: pesos do modelo + KV cache proporcional ao contexto.

    Com modelo ja carregado (`carregado` do /api/ps), estima so o custo marginal.
    """
    return round(estimar_need_bytes(modelo, num_ctx, tamanhos, carregado) / (1024 ** 3), 1)


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
    carregado: dict | None = None,
) -> list[dict]:
    out = []
    for c in CONTEXTOS:
        gb = estimar_ram_gb(modelo, c["tokens"], tamanhos, carregado)
        need = estimar_need_bytes(modelo, c["tokens"], tamanhos, carregado)
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
    carregado: dict | None = None,
) -> int:
    """Maior contexto cuja estimativa cabe (VRAM preferencial + overflow em RAM)."""
    fallback = CONTEXT_PADRAO if CONTEXT_PADRAO in CONTEXTOS_PERMITIDOS else CONTEXTOS[0]["tokens"]
    if (not ram or not ram.get("disponivel")) and (not vram or not vram.get("disponivel")):
        return fallback
    cabem = []
    for c in CONTEXTOS:
        need = estimar_need_bytes(modelo, c["tokens"], tamanhos, carregado)
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
    carregado: dict | None = None,
) -> tuple[int | None, dict | None]:
    """Ajusta num_ctx pra caber na memoria disponivel (GPU/RAM), sem matar mid-gen."""
    ram = ram if ram is not None else obter_ram()
    vram = vram if vram is not None else obter_vram()
    pedido = num_ctx if num_ctx in CONTEXTOS_PERMITIDOS else CONTEXT_PADRAO
    residente = bool(carregado and int(carregado.get("size") or 0) > 0)

    need_pedido = estimar_need_bytes(modelo, pedido, tamanhos, carregado)
    if memoria_suficiente(need_pedido, ram, vram):
        return pedido, None

    seguro = sugerir_contexto(ram, modelo, tamanhos, vram, carregado)
    need_min = estimar_need_bytes(modelo, CONTEXTOS[0]["tokens"], tamanhos, carregado)
    if residente:
        if seguro != pedido:
            modo = "GPU/VRAM" if _modo_memoria(vram) == "gpu" else "RAM"
            return seguro, {
                "tipo": "aviso",
                "hub": True,
                "pedido": pedido,
                "usado": seguro,
                "msg": (
                    f"Contexto reduzido de {_label_ctx(pedido)} para {_label_ctx(seguro)} "
                    f"pra caber com folga em {modo} (modelo ja carregado no Ollama)."
                ),
            }
        return pedido, {
            "tipo": "aviso",
            "hub": True,
            "msg": (
                "Memoria apertada, mas o modelo ja esta carregado — "
                "se travar, reduza o contexto ou troque o modelo."
            ),
        }

    if not memoria_suficiente(need_min, ram, vram):
        need_gb = need_min / (1024 ** 3)
        folga_gb = _ram_folga_bytes(ram) / (1024 ** 3)
        partes = []
        if ram and ram.get("disponivel") is not None:
            partes.append(f"RAM livre {ram['disponivel'] / (1024 ** 3):.1f} GB")
        if vram and vram.get("disponivel") is not None:
            partes.append(
                f"VRAM livre {vram['disponivel'] / (1024 ** 3):.1f} GB"
                + (f" ({vram.get('nome')})" if vram.get("nome") else "")
            )
        onde = " / ".join(partes) if partes else "sem leitura de memoria"
        ja = " (modelo ja carregado no Ollama)" if carregado else ""
        return None, {
            "erro": True,
            "msg": (
                f"O modelo `{modelo}` precisa de ~{need_gb:.1f} GB livres no servidor "
                f"(folga ~{folga_gb:.1f} GB){ja}, mas so ha {onde}. "
                "Troque para um modelo menor (ex.: qwen2.5-coder:3b)."
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
            f"(estimativa {_fmt_ram_gb(estimar_ram_gb(modelo, pedido, tamanhos, carregado))} "
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


def _match_modelo_ps(nome: str, alvos: set[str]) -> bool:
    nome = (nome or "").lower()
    if not nome or not alvos:
        return False
    if nome in alvos:
        return True
    if any(nome.startswith(a + ":") or a.startswith(nome) for a in alvos):
        return True
    base = nome.split(":")[0]
    return any(a.split(":")[0] == base for a in alvos)


def _parse_modelo_carregado_ps(entry: dict) -> dict | None:
    nome = entry.get("name") or entry.get("model") or ""
    size = int(entry.get("size") or 0)
    if not nome or size <= 0:
        return None
    ctx_len = entry.get("context_length")
    if not ctx_len:
        opts = entry.get("options") or {}
        ctx_len = opts.get("num_ctx")
    return {
        "name": nome,
        "size": size,
        "context_length": int(ctx_len) if ctx_len else 4096,
    }


async def obter_modelo_carregado(modelo: str) -> dict | None:
    """Modelo residente no Ollama (/api/ps) — evita contar pesos duas vezes na RAM."""
    alvos = {n.lower() for n in _variantes_nome_modelo(modelo)}
    if not alvos:
        return None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            ps = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
            if ps.status_code != 200:
                return None
            for m in (ps.json() or {}).get("models") or []:
                nome = m.get("name") or m.get("model") or ""
                if _match_modelo_ps(nome, alvos):
                    return _parse_modelo_carregado_ps(m)
    except Exception:
        return None
    return None


async def _modelo_ainda_carregado(nomes: list[str]) -> bool:
    alvos = {n.lower() for n in nomes}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            ps = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
            if ps.status_code != 200:
                return False
            for m in (ps.json() or {}).get("models") or []:
                nome = m.get("name") or m.get("model") or ""
                if _match_modelo_ps(nome, alvos):
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
    "codigo-leve": {
        "id": "codigo-leve",
        "nome": "Codigo — leve",
        "icone": "bi-lightning-charge",
        "descricao": "Snippets, autocomplete e duvidas rapidas.",
    },
    "codigo": {
        "id": "codigo",
        "nome": "Codigo — dia a dia",
        "icone": "bi-code-slash",
        "descricao": "Programacao, refatoracao, debug e arquitetura.",
    },
    "seguranca": {
        "id": "seguranca",
        "nome": "Seguranca / DevSecOps",
        "icone": "bi-shield-lock",
        "descricao": "Cybersecurity, red team e analise ofensiva.",
    },
    "codigo-pesado": {
        "id": "codigo-pesado",
        "nome": "Codigo — pesado",
        "icone": "bi-braces-asterisk",
        "descricao": "Projetos grandes e multi-arquivo. Exige mais RAM.",
    },
}

MODELOS_PRESET = [
    # Codigo leve
    {
        "slug": "qwen2.5-coder:1.5b",
        "nome": "Qwen Coder",
        "parametros": "1.5B",
        "descricao": (
            "Agente ultraleve para autocomplete, corrigir sintaxe e tirar duvidas "
            "pontuais sem travar o PC."
        ),
        "tamanho": "~1.0 GB",
        "icone": "bi-lightning-charge",
        "foco": "codigo-leve",
    },
    {
        "slug": "starcoder2:3b",
        "nome": "StarCoder2",
        "parametros": "3B",
        "descricao": (
            "Treinado em repositorios reais (BigCode). Bom para varias linguagens, "
            "boilerplate e scripts curtos."
        ),
        "tamanho": "~1.7 GB",
        "icone": "bi-stars",
        "foco": "codigo-leve",
    },
    {
        "slug": "codegemma:2b",
        "nome": "CodeGemma",
        "parametros": "2B",
        "descricao": (
            "Google focado em codigo. Responde rapido em notebooks e ajuda com "
            "funcoes pequenas e explicacoes de trecho."
        ),
        "tamanho": "~1.6 GB",
        "icone": "bi-lightning",
        "foco": "codigo-leve",
    },
    # Codigo dia a dia
    {
        "slug": "qwen2.5-coder:3b",
        "nome": "Qwen Coder",
        "parametros": "3B",
        "descricao": (
            "Padrao do hub. Explica logica, refatora funcoes, sugere testes e revisa "
            "trechos em Python, JS, SQL, shell e configs."
        ),
        "tamanho": "~2.0 GB",
        "icone": "bi-stars",
        "foco": "codigo",
    },
    {
        "slug": "qwen2.5-coder:7b",
        "nome": "Qwen Coder",
        "parametros": "7B",
        "descricao": (
            "Mais contexto e precisao em debug, arquitetura leve e documentacao "
            "tecnica. Indicado com 8 GB+ de RAM."
        ),
        "tamanho": "~4.7 GB",
        "icone": "bi-gem",
        "foco": "codigo",
    },
    {
        "slug": "deepseek-coder:6.7b",
        "nome": "DeepSeek Coder",
        "parametros": "6.7B",
        "descricao": (
            "Forte em Python e JavaScript: refatoracao, APIs, tipos e raciocinio "
            "passo a passo em problemas de codigo."
        ),
        "tamanho": "~3.8 GB",
        "icone": "bi-filetype-js",
        "foco": "codigo",
    },
    {
        "slug": "codellama:7b",
        "nome": "Code Llama",
        "parametros": "7B",
        "descricao": (
            "Classico da Meta para programacao. Bom em C/C++, Python e completar "
            "funcoes com estilo consistente."
        ),
        "tamanho": "~3.8 GB",
        "icone": "bi-filetype-py",
        "foco": "codigo",
    },
    {
        "slug": "starcoder2:7b",
        "nome": "StarCoder2",
        "parametros": "7B",
        "descricao": (
            "Versao maior para repos extensos, multi-arquivo e padroes de projeto "
            "em varias linguagens."
        ),
        "tamanho": "~4.0 GB",
        "icone": "bi-git",
        "foco": "codigo",
    },
    {
        "slug": "codegemma:7b",
        "nome": "CodeGemma",
        "parametros": "7B",
        "descricao": (
            "Segue instrucoes complexas, gera modulos inteiros e ajuda a manter "
            "codigo legivel e bem estruturado."
        ),
        "tamanho": "~5.0 GB",
        "icone": "bi-code-square",
        "foco": "codigo",
    },
    # Seguranca (DeepHat)
    {
        "slug": "hf.co/liodon-ai/DeepHat-V1-7B-imatrix-GGUF:Q4_K_M",
        "nome": "DeepHat",
        "parametros": "7B · leve",
        "quant_label": "Q4",
        "descricao": (
            "Mesmo DeepHat em Q4 (~5 GB). Pentest, red team, payloads e recon — "
            "feito para PCs com 8 GB de RAM."
        ),
        "tamanho": "~4.7 GB",
        "icone": "bi-shield-lock",
        "foco": "seguranca",
    },
    {
        "slug": "DeepHat/DeepHat-V1-7B",
        "nome": "DeepHat",
        "parametros": "7B · completo",
        "quant_label": "FP16+",
        "descricao": (
            "Pesos completos, maxima qualidade. Cybersecurity e analise ofensiva — "
            "exige 16 GB+ de RAM; com 8 GB use o leve."
        ),
        "tamanho": "~14 GB",
        "icone": "bi-shield-lock",
        "foco": "seguranca",
    },
    # Codigo pesado
    {
        "slug": "deepseek-coder-v2:16b",
        "nome": "DeepSeek Coder V2",
        "parametros": "16B",
        "descricao": (
            "Para codebases grandes, migracoes e varios arquivos abertos. "
            "Entende dependencias cruzadas e refatoracoes amplas."
        ),
        "tamanho": "~8.9 GB",
        "icone": "bi-braces",
        "foco": "codigo-pesado",
    },
    {
        "slug": "qwen2.5-coder:14b",
        "nome": "Qwen Coder",
        "parametros": "14B",
        "descricao": (
            "Maxima qualidade em codigo: design de sistemas, reviews profundos "
            "e geracao longa com poucos erros."
        ),
        "tamanho": "~9.0 GB",
        "icone": "bi-cpu",
        "foco": "codigo-pesado",
    },
]


def _modelo_disponivel(modelo: str, modelos: list[str]) -> bool:
    return _nome_instalado(modelo, modelos) is not None


def _nome_instalado(modelo: str, modelos: list[str]) -> str | None:
    """Retorna o nome exato instalado no Ollama correspondente ao slug do preset."""
    m = modelo.lower().strip()
    if not m:
        return None
    m_base = m.split(":", 1)[0]
    for nome in modelos:
        n = nome.lower()
        base = n.split(":", 1)[0]
        if n == m or n.startswith(m + ":") or base == m or base == m_base:
            return nome
        if m_base in n and ("deephat" in m or "gguf" in m):
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


def _foco_prompt_key(foco: str) -> str:
    if foco.startswith("codigo"):
        return "codigo"
    return foco


def _foco_do_modelo(modelo: str) -> str:
    preset = _preset_do_modelo(modelo)
    if preset:
        return _foco_prompt_key(preset.get("foco", "codigo"))
    m = modelo.lower()
    if "deephat" in m:
        return "seguranca"
    if any(
        k in m
        for k in ("coder", "codellama", "starcoder", "codegemma", "magicoder", "granite-code")
    ):
        return "codigo"
    return "codigo"


def _system_prompt_para(modelo: str) -> str:
    return SYSTEM_PROMPTS_FOCO.get(_foco_do_modelo(modelo), SYSTEM_PROMPT_CODIGO)


async def obter_tamanhos_ollama() -> dict[str, float]:
    """Mapa nome -> GB (tamanho em disco do /api/tags, ajustado pra estimativa de RAM)."""
    tamanhos: dict[str, float] = {}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if resp.status_code != 200:
                return tamanhos
            for m in (resp.json() or {}).get("models") or []:
                nome = m.get("name", "")
                size = m.get("size")
                if nome and isinstance(size, (int, float)) and size > 0:
                    tamanhos[nome] = size / (1024 ** 3)
    except Exception:
        pass
    return tamanhos


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
            info["modelos"] = modelos
            info["modelo_disponivel"] = _modelo_disponivel(modelo, modelos)
            for preset in info["presets"]:
                preset["baixado"] = _modelo_disponivel(preset["slug"], modelos)
        tamanhos = await obter_tamanhos_ollama()
    except httpx.ConnectError:
        info["msg"] = "Ollama nao esta rodando em localhost:11434"
    except Exception as e:
        info["msg"] = f"Erro ao consultar Ollama: {e}"

    info["presets"] = [_enriquecer_preset(p, tamanhos) for p in info["presets"]]

    info["ram"] = obter_ram()
    info["vram"] = obter_vram()
    info["memoria_modo"] = _modo_memoria(info["vram"])
    carregado = await obter_modelo_carregado(modelo) if info["ollama_ativo"] else None
    info["modelo_carregado"] = bool(carregado)
    sugerido = sugerir_contexto(info["ram"], modelo, tamanhos, info["vram"], carregado)
    info["contexto_sugerido"] = sugerido
    info["contexto_padrao"] = sugerido
    info["ram_folga_bytes"] = _ram_folga_bytes(info["ram"])
    info["vram_folga_bytes"] = VRAM_FOLGA_BYTES
    info["modelo_tamanho_gb"] = round(_tamanho_modelo_gb(modelo, tamanhos), 1)
    need_modelo = estimar_need_bytes(modelo, CONTEXTOS[0]["tokens"], tamanhos, carregado)
    info["modelo_ram_estimada_gb"] = round(need_modelo / (1024 ** 3), 1)
    info["modelo_cabe"] = memoria_suficiente(need_modelo, info["ram"], info["vram"])
    info["contextos"] = _contextos_com_estimativa(
        modelo, tamanhos, info["ram"], info["vram"], carregado
    )
    for c in info["contextos"]:
        c["indicado"] = c["tokens"] == sugerido and c.get("cabe", False)
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
    total_passos = 120
    for passo in range(total_passos):
        await asyncio.sleep(2)
        exe = detectar_ollama_instalado()
        if exe and not _ollama_ja_responde():
            iniciar_servico_ollama()
        if not exe:
            yield enviar({
                "etapa": "instalando",
                "status": "Aguardando instalacao...",
                "completed": passo + 1,
                "total": total_passos,
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
                        "completed": total_passos,
                        "total": total_passos,
                    })
                    return
        except Exception:
            pass
        yield enviar({
            "etapa": "instalando",
            "status": "Aguardando Ollama em localhost:11434...",
            "exe": exe,
            "completed": passo + 1,
            "total": total_passos,
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
    tamanhos = await obter_tamanhos_ollama()
    carregado = await obter_modelo_carregado(modelo)
    ctx, aviso = limitar_contexto(
        num_ctx, ram, modelo, tamanhos, vram=vram, carregado=carregado
    )
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
