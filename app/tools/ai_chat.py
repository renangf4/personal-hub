import asyncio
import json
import os
import platform
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
CONTEXT_PADRAO = 32768
# Folga minima pra o SO nao travar (Ollama nao expoe teto de RAM nativo).
RAM_FOLGA_BYTES = 500 * 1024 * 1024


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
            import re

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


CONTEXTOS = [
    {
        "tokens": 4096,
        "label": "4k",
        "nome": "Perguntas curtas",
        "descricao": "Pouco uso de memoria. Historico curto.",
        "indicado": False,
        "ram": "~2 GB",
        "ram_gb": 2,
    },
    {
        "tokens": 8192,
        "label": "8k",
        "nome": "Uso leve",
        "descricao": "Chat simples e trechos pequenos de codigo.",
        "indicado": False,
        "ram": "~4 GB",
        "ram_gb": 4,
    },
    {
        "tokens": 16384,
        "label": "16k",
        "nome": "Codigo moderado",
        "descricao": "Arquivos medios. Bom em maquinas com ~8 GB de RAM.",
        "indicado": False,
        "ram": "~8 GB",
        "ram_gb": 8,
    },
    {
        "tokens": 32768,
        "label": "32k",
        "nome": "Equilibrado",
        "descricao": "Codigo + historico. Equilibrio tipico (~16 GB RAM).",
        "indicado": False,
        "ram": "~16 GB",
        "ram_gb": 16,
    },
    {
        "tokens": 65536,
        "label": "64k",
        "nome": "Logs / multi-arquivo",
        "descricao": "Logs grandes e varios arquivos. Usa bastante RAM (e VRAM se o modelo estiver na GPU).",
        "indicado": False,
        "ram": "~20 GB",
        "ram_gb": 20,
    },
    {
        "tokens": 131072,
        "label": "128k",
        "nome": "Contexto maximo",
        "descricao": "Projetos grandes. Exige muita RAM; com GPU, tambem consome VRAM.",
        "indicado": False,
        "ram": "~32 GB",
        "ram_gb": 32,
    },
]

CONTEXTOS_PERMITIDOS = {c["tokens"] for c in CONTEXTOS}


def sugerir_contexto(ram: dict | None) -> int:
    """Maior contexto cuja estimativa + folga de 500 MB cabe na RAM livre."""
    fallback = next(
        (c["tokens"] for c in CONTEXTOS if c["tokens"] == CONTEXT_PADRAO),
        CONTEXTOS[0]["tokens"],
    )
    if not ram or not ram.get("disponivel"):
        return fallback
    livre_gb = ram["disponivel"] / (1024 ** 3)
    folga_gb = RAM_FOLGA_BYTES / (1024 ** 3)
    cabem = [
        c for c in CONTEXTOS
        if c.get("ram_gb", 0) + folga_gb <= livre_gb
    ]
    if not cabem:
        return CONTEXTOS[0]["tokens"]
    return cabem[-1]["tokens"]


def limitar_contexto(num_ctx: int, ram: dict | None = None) -> tuple[int | None, dict | None]:
    """Ajusta num_ctx pra caber na RAM livre com folga.

    Retorna (ctx_ou_None, aviso_ou_erro).
    """
    ram = ram if ram is not None else obter_ram()
    pedido = num_ctx if num_ctx in CONTEXTOS_PERMITIDOS else CONTEXT_PADRAO
    if not ram or not ram.get("disponivel"):
        return pedido, None

    livre = int(ram["disponivel"])
    if livre < RAM_FOLGA_BYTES:
        livre_gb = livre / (1024 ** 3)
        return None, {
            "erro": True,
            "msg": (
                f"RAM livre critica ({livre_gb:.1f} GB). "
                "Libere memoria (feche programas) antes de gerar — "
                "folga minima de 500 MB pra nao travar o PC."
            ),
        }

    seguro = sugerir_contexto(ram)
    meta = next((c for c in CONTEXTOS if c["tokens"] == pedido), None)
    need = int((meta or {}).get("ram_gb", 16) * (1024 ** 3))
    if livre - need >= RAM_FOLGA_BYTES:
        return pedido, None

    aviso = {
        "tipo": "aviso",
        "hub": True,
        "pedido": pedido,
        "usado": seguro,
        "msg": (
            f"Contexto reduzido de {_label_ctx(pedido)} para {_label_ctx(seguro)} "
            f"pra preservar ~500 MB de RAM livre e evitar travar o PC."
        ),
    }
    return seguro, aviso


def _label_ctx(tokens: int) -> str:
    meta = next((c for c in CONTEXTOS if c["tokens"] == tokens), None)
    return meta["label"] if meta else str(tokens)

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
        "tamanho": "~4.7 GB",
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
    info = {
        "ollama_ativo": False,
        "ollama_instalado": bool(exe),
        "ollama_exe": exe,
        "sistema": platform.system(),
        "modelo_padrao": modelo,
        "modelo_disponivel": False,
        "modelos": [],
        "focos": list(FOCOS.values()),
        "contextos": [{**c} for c in CONTEXTOS],
        "contexto_padrao": CONTEXT_PADRAO,
        "contexto_sugerido": CONTEXT_PADRAO,
        "presets": [
            {**preset, "baixado": False} for preset in MODELOS_PRESET
        ],
        "msg": "",
    }
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            info["ollama_ativo"] = True
            modelos = [m.get("name", "") for m in data.get("models", [])]
            info["modelos"] = modelos
            info["modelo_disponivel"] = _modelo_disponivel(modelo, modelos)
            for preset in info["presets"]:
                preset["baixado"] = _modelo_disponivel(preset["slug"], modelos)
    except httpx.ConnectError:
        info["msg"] = "Ollama nao esta rodando em localhost:11434"
    except Exception as e:
        info["msg"] = f"Erro ao consultar Ollama: {e}"
    info["ram"] = obter_ram()
    sugerido = sugerir_contexto(info["ram"])
    info["contexto_sugerido"] = sugerido
    info["ram_folga_bytes"] = RAM_FOLGA_BYTES
    for c in info["contextos"]:
        c["indicado"] = c["tokens"] == sugerido
    info["contexto_padrao"] = sugerido
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
        yield enviar({
            "erro": True,
            "status": "Instalacao automatica nao suportada no Linux por este app.",
            "detalhe": "Rode no terminal: curl -fsSL https://ollama.com/install.sh | sh",
        })
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

        for _ in range(180):
            await asyncio.sleep(2)
            exe = detectar_ollama_instalado()
            if not exe:
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
                "status": "Instalador aberto. Aguardando conclusao...",
                "exe": exe,
            })

        yield enviar({
            "erro": True,
            "status": "Tempo esgotado aguardando instalacao. Tente novamente apos concluir o instalador.",
        })
    except httpx.ConnectError:
        yield enviar({"erro": True, "status": "Sem conexao com a internet para baixar o instalador."})
    except Exception as e:
        yield enviar({"erro": True, "status": f"Erro inesperado: {e}"})


async def stream_pull(modelo: str = MODELO_PADRAO) -> AsyncIterator[bytes]:
    """Faz pull do modelo retransmitindo os eventos de progresso como ndjson."""
    payload = {"name": modelo, "stream": True}
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/pull",
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    erro = await resp.aread()
                    yield (
                        json.dumps(
                            {
                                "erro": True,
                                "status": f"HTTP {resp.status_code}",
                                "detalhe": erro.decode("utf-8", errors="ignore"),
                            }
                        )
                        + "\n"
                    ).encode("utf-8")
                    return

                async for linha in resp.aiter_lines():
                    if not linha:
                        continue
                    yield (linha + "\n").encode("utf-8")
    except httpx.ConnectError:
        yield (
            json.dumps(
                {
                    "erro": True,
                    "status": "Ollama nao esta rodando em localhost:11434",
                }
            )
            + "\n"
        ).encode("utf-8")
    except Exception as e:
        yield (
            json.dumps({"erro": True, "status": f"Falha no pull: {e}"}) + "\n"
        ).encode("utf-8")


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
    ctx, aviso = limitar_contexto(num_ctx, ram)
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

    payload = {
        "model": modelo,
        "messages": msgs,
        "stream": True,
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

                ultimo_check = time.monotonic()
                async for linha in resp.aiter_lines():
                    agora = time.monotonic()
                    if agora - ultimo_check >= 1.5:
                        ultimo_check = agora
                        atual = obter_ram()
                        if atual and atual["disponivel"] < RAM_FOLGA_BYTES:
                            livre_gb = atual["disponivel"] / (1024 ** 3)
                            yield {
                                "erro": True,
                                "parcial": True,
                                "msg": (
                                    f"Geracao interrompida: so restavam {livre_gb:.1f} GB de RAM "
                                    "(folga minima 500 MB). Assim o PC nao trava — "
                                    "feche programas ou use um contexto menor."
                                ),
                            }
                            return

                    if not linha:
                        continue
                    try:
                        data = json.loads(linha)
                    except json.JSONDecodeError:
                        continue
                    yield data
    except httpx.ConnectError:
        yield {"erro": True, "msg": "Ollama nao esta rodando em localhost:11434"}
    except Exception as e:
        yield {"erro": True, "msg": f"Falha no chat: {e}"}


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
