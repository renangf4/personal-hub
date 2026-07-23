import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import AsyncIterator

import httpx

OLLAMA_BASE_URL = "http://localhost:11434"
MODELO_PADRAO = "qwen2.5-coder:3b"
CONTEXT_PADRAO = 32768

CONTEXTOS = [
    {
        "tokens": 4096,
        "label": "4k",
        "nome": "Perguntas curtas",
        "descricao": "Pouco uso de RAM. Historico curto.",
        "indicado": False,
        "ram": "baixo",
    },
    {
        "tokens": 8192,
        "label": "8k",
        "nome": "Uso leve",
        "descricao": "Chat simples e trechos pequenos de codigo.",
        "indicado": False,
        "ram": "baixo",
    },
    {
        "tokens": 16384,
        "label": "16k",
        "nome": "Codigo moderado",
        "descricao": "Arquivos medios. Bom em 8 GB RAM.",
        "indicado": False,
        "ram": "8 GB",
    },
    {
        "tokens": 32768,
        "label": "32k",
        "nome": "Recomendado",
        "descricao": "Codigo + historico. Equilibrio ideal.",
        "indicado": True,
        "ram": "16 GB",
    },
    {
        "tokens": 65536,
        "label": "64k",
        "nome": "Logs / multi-arquivo",
        "descricao": "Logs grandes e varios arquivos juntos.",
        "indicado": False,
        "ram": "16 GB+",
    },
    {
        "tokens": 131072,
        "label": "128k",
        "nome": "Contexto maximo",
        "descricao": "Projetos grandes. Exige muita RAM/VRAM.",
        "indicado": False,
        "ram": "32 GB+",
    },
]

CONTEXTOS_PERMITIDOS = {c["tokens"] for c in CONTEXTOS}

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
        "contextos": CONTEXTOS,
        "contexto_padrao": CONTEXT_PADRAO,
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
    return info


def iniciar_servico_ollama() -> dict:
    """Sobe `ollama serve` em background se o binario estiver instalado."""
    exe = detectar_ollama_instalado()
    if not exe:
        return {"ok": False, "msg": "Ollama nao esta instalado"}
    try:
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([exe, "serve"], **kwargs)
        return {"ok": True, "exe": exe}
    except Exception as e:
        return {"ok": False, "msg": f"Falha ao iniciar Ollama: {e}"}


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

    ctx = num_ctx if num_ctx in CONTEXTOS_PERMITIDOS else CONTEXT_PADRAO

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
    except Exception as e:
        yield {"erro": True, "msg": f"Falha no chat: {e}"}
