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

MODELOS_PRESET = [
    {
        "slug": "qwen2.5-coder:1.5b",
        "nome": "Rapido",
        "descricao": "Mais leve e veloz. Bom pra perguntas simples.",
        "tamanho": "~1.0 GB",
        "icone": "bi-lightning-charge",
    },
    {
        "slug": "qwen2.5-coder:3b",
        "nome": "Equilibrado",
        "descricao": "Otimo custo-beneficio entre qualidade e velocidade.",
        "tamanho": "~2.0 GB",
        "icone": "bi-stars",
    },
    {
        "slug": "qwen2.5-coder:7b",
        "nome": "Melhor qualidade",
        "descricao": "Respostas mais precisas. Mais lento em CPU.",
        "tamanho": "~4.7 GB",
        "icone": "bi-gem",
    },
]


def _modelo_disponivel(modelo: str, modelos: list[str]) -> bool:
    return any(
        nome == modelo or nome.startswith(modelo + ":") or modelo in nome
        for nome in modelos
    )

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

SYSTEM_PROMPT = (
    "Voce e um assistente senior especialista em engenharia de software, "
    "arquitetura de sistemas, infraestrutura, Docker e desenvolvimento full-stack. "
    "Seja direto, pratico, evite explicacoes excessivamente teoricas e foque em "
    "fornecer codigo limpo, performatico e bem documentado em portugues."
)


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


async def stream_chat(
    modelo: str,
    mensagens: list[dict],
    incluir_system: bool = True,
) -> AsyncIterator[dict]:
    """Streama a resposta do Ollama em chunks (dicts decodificados)."""
    msgs = []
    if incluir_system:
        msgs.append({"role": "system", "content": SYSTEM_PROMPT})
    msgs.extend(mensagens)

    payload = {
        "model": modelo,
        "messages": msgs,
        "stream": True,
        "options": {"temperature": 0.3},
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
