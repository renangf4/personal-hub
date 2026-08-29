"""Instalacao e remocao de extras via pip."""

from __future__ import annotations

import asyncio
import importlib
import json
import re
import subprocess
import sys
from typing import AsyncIterator

from . import db, registry
from .extras import EXTRAS, eh_browser_only

_lock = asyncio.Lock()
_pkg_name_re = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _nome_pacote(spec: str) -> str:
    m = _pkg_name_re.match(spec.strip())
    if not m:
        raise ValueError(f"Pacote invalido: {spec}")
    return m.group(1)


def _import_ok(nome: str) -> bool:
    try:
        importlib.import_module(nome)
        return True
    except ImportError:
        return False


def _deps_ok(extra: dict) -> bool:
    return all(_import_ok(nome) for nome in extra["imports"])


def _pacotes_em_uso(exceto: str | None = None) -> set[str]:
    usados: set[str] = set()
    ativos = db.listar_extras_instalados()
    for slug in ativos:
        if slug == exceto:
            continue
        extra = EXTRAS.get(slug)
        if not extra:
            continue
        for spec in extra["packages"]:
            usados.add(_nome_pacote(spec).lower())
    return usados


def _limpar_imports(extra: dict) -> None:
    for nome in extra["imports"]:
        sys.modules.pop(nome, None)
        if nome == "PIL":
            for k in list(sys.modules):
                if k == "PIL" or k.startswith("PIL."):
                    sys.modules.pop(k, None)
        if nome == "imageio_ffmpeg":
            for k in list(sys.modules):
                if k == "imageio_ffmpeg" or k.startswith("imageio_ffmpeg."):
                    sys.modules.pop(k, None)


def _pip_sync(args: list[str]) -> tuple[int, list[str]]:
    """Roda pip de forma sincrona (compatível com Windows/uvicorn)."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "pip", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    linhas: list[str] = []
    assert proc.stdout is not None
    for linha in proc.stdout:
        texto = linha.rstrip()
        if texto:
            linhas.append(texto)
    codigo = proc.wait()
    return codigo, linhas


async def _stream_pip(args: list[str]) -> AsyncIterator[dict]:
    codigo, linhas = await asyncio.to_thread(_pip_sync, args)
    for texto in linhas:
        yield {"tipo": "log", "linha": texto}
    yield {"tipo": "codigo", "codigo": codigo}


async def instalar(slug: str) -> AsyncIterator[bytes]:
    extra = EXTRAS.get(slug)
    if not extra:
        yield (json.dumps({"tipo": "erro", "msg": "Extra desconhecido"}) + "\n").encode()
        return

    if _lock.locked():
        yield (json.dumps({"tipo": "erro", "msg": "Outra operacao em andamento"}) + "\n").encode()
        return

    async with _lock:
        yield (json.dumps({"tipo": "inicio", "acao": "instalar", "slug": slug}) + "\n").encode()

        if eh_browser_only(extra):
            yield (
                json.dumps({
                    "tipo": "log",
                    "linha": "Ativando ferramenta (roda no navegador).",
                })
                + "\n"
            ).encode()
        elif _deps_ok(extra):
            yield (
                json.dumps({
                    "tipo": "log",
                    "linha": "Dependencias ja presentes — ativando ferramenta.",
                })
                + "\n"
            ).encode()
        elif extra["packages"]:
            codigo = 1
            async for evento in _stream_pip(
                ["install", "--disable-pip-version-check", *extra["packages"]]
            ):
                if evento["tipo"] == "codigo":
                    codigo = evento["codigo"]
                else:
                    yield (json.dumps(evento) + "\n").encode()
            if codigo != 0:
                yield (
                    json.dumps({"tipo": "erro", "msg": "Falha ao instalar dependencias"}) + "\n"
                ).encode()
                return
        else:
            yield (json.dumps({"tipo": "erro", "msg": "Extra sem pacotes e sem deps"}) + "\n").encode()
            return

        _limpar_imports(extra)
        db.marcar_extra(slug)
        registry.rebuild()
        ok = registry.extra_instalado(slug)
        yield (
            json.dumps({
                "tipo": "fim",
                "ok": ok,
                "slug": slug,
                "msg": "Instalado com sucesso" if ok else "Instalado, mas o modulo nao carregou",
            })
            + "\n"
        ).encode()


async def desinstalar(slug: str) -> AsyncIterator[bytes]:
    extra = EXTRAS.get(slug)
    if not extra:
        yield (json.dumps({"tipo": "erro", "msg": "Extra desconhecido"}) + "\n").encode()
        return

    if _lock.locked():
        yield (json.dumps({"tipo": "erro", "msg": "Outra operacao em andamento"}) + "\n").encode()
        return

    async with _lock:
        yield (json.dumps({"tipo": "inicio", "acao": "desinstalar", "slug": slug}) + "\n").encode()

        db.desmarcar_extra(slug)
        ainda_usados = _pacotes_em_uso()
        para_remover = [
            _nome_pacote(p)
            for p in extra["packages"]
            if _nome_pacote(p).lower() not in ainda_usados
        ]

        if para_remover:
            codigo = 1
            async for evento in _stream_pip(
                ["uninstall", "-y", "--disable-pip-version-check", *para_remover]
            ):
                if evento["tipo"] == "codigo":
                    codigo = evento["codigo"]
                else:
                    yield (json.dumps(evento) + "\n").encode()
            if codigo != 0:
                db.marcar_extra(slug)
                yield (json.dumps({"tipo": "erro", "msg": "Falha ao desinstalar"}) + "\n").encode()
                return
            yield (
                json.dumps({
                    "tipo": "log",
                    "linha": f"Pacotes removidos: {', '.join(para_remover)}",
                })
                + "\n"
            ).encode()
        elif eh_browser_only(extra):
            yield (
                json.dumps({
                    "tipo": "log",
                    "linha": "Ferramenta desativada (roda no navegador, sem pacotes pip).",
                })
                + "\n"
            ).encode()
        else:
            yield (
                json.dumps({
                    "tipo": "log",
                    "linha": "Dependencias compartilhadas mantidas (outras ferramentas ainda usam).",
                })
                + "\n"
            ).encode()

        _limpar_imports(extra)
        registry.descartar_modulos(extra["modulos"])
        registry.rebuild()
        ok = not registry.extra_instalado(slug)
        yield (
            json.dumps({
                "tipo": "fim",
                "ok": ok,
                "slug": slug,
                "msg": "Removido com sucesso" if ok else "Removido, reinicie se a ferramenta ainda aparecer",
            })
            + "\n"
        ).encode()
