"""Registro dinamico de ferramentas conforme extras instalados."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import Any

from .extras import EXTRAS, FORMATOS_IMAGEM, FORMATOS_VIDEO, TOOL_META

_modulos: dict[str, ModuleType | None] = {}
TOOLS: dict[str, dict] = {}
CATEGORIAS: dict[str, dict] = {}


def _import_ok(nome: str) -> bool:
    try:
        importlib.import_module(nome)
        return True
    except ImportError:
        return False


def extra_instalado(slug: str) -> bool:
    extra = EXTRAS.get(slug)
    if not extra:
        return False
    from . import db
    if slug not in db.listar_extras_instalados():
        return False
    return all(_import_ok(nome) for nome in extra["imports"])


def _carregar_modulo(nome: str) -> ModuleType | None:
    full = f"app.tools.{nome}"
    try:
        if full in sys.modules:
            return importlib.reload(sys.modules[full])
        return importlib.import_module(f".tools.{nome}", "app")
    except ImportError:
        sys.modules.pop(full, None)
        return None


def descartar_modulos(nomes: list[str]) -> None:
    for nome in nomes:
        full = f"app.tools.{nome}"
        sys.modules.pop(full, None)
        if nome == "convert_video":
            sys.modules.pop("app.tools._video_common", None)


def rebuild() -> None:
    global TOOLS, CATEGORIAS, _modulos
    importlib.invalidate_caches()

    novos: dict[str, ModuleType | None] = {}
    tools: dict[str, dict] = {}

    for slug, extra in EXTRAS.items():
        pronto = extra_instalado(slug)
        for mod_name in extra["modulos"]:
            if not pronto:
                descartar_modulos([mod_name])
                novos[mod_name] = None
                continue
            modulo = _carregar_modulo(mod_name)
            novos[mod_name] = modulo

    # Ferramentas avulsas (nao-categoria)
    for mod_name, meta in TOOL_META.items():
        modulo = novos.get(mod_name)
        if modulo is None:
            continue
        tools[meta["slug"]] = {"modulo": modulo, **meta}

    # Formatos de video / imagem compartilham o mesmo modulo
    if novos.get("convert_video") is not None:
        for fmt in FORMATOS_VIDEO:
            tools[fmt["slug"]] = {
                "slug": fmt["slug"],
                "nome": f"Converter para {fmt['label']}",
                "descricao": f"Converte videos para {fmt['label']}.",
                "icone": "bi-camera-video",
                "aceita": "video/*,.mkv,.mov,.avi,.webm,.gif,.m4v",
                "controles": "video",
                "extra": "video",
                "familia": "video",
                "formato": fmt["formato"],
                "modulo": novos["convert_video"],
            }

    if novos.get("convert_image") is not None:
        for fmt in FORMATOS_IMAGEM:
            tools[fmt["slug"]] = {
                "slug": fmt["slug"],
                "nome": f"Converter para {fmt['label']}",
                "descricao": f"Converte imagens para {fmt['label']}.",
                "icone": "bi-image",
                "aceita": "image/*",
                "controles": "imagem",
                "extra": "imagem",
                "familia": "imagem",
                "formato": fmt["formato"],
                "modulo": novos["convert_image"],
            }

    categorias: dict[str, dict] = {}
    if any(f["slug"] in tools for f in FORMATOS_VIDEO):
        categorias["video"] = {
            "slug": "video",
            "nome": "Video",
            "descricao": EXTRAS["video"]["descricao"],
            "icone": "bi-camera-video",
            "aceita": "video/*,.mkv,.mov,.avi,.webm,.gif,.m4v",
            "controles": "video",
            "formatos": [
                {"slug": f["slug"], "label": f["label"], "padrao": f["padrao"]}
                for f in FORMATOS_VIDEO
                if f["slug"] in tools
            ],
        }
    if any(f["slug"] in tools for f in FORMATOS_IMAGEM):
        categorias["imagem"] = {
            "slug": "imagem",
            "nome": "Imagem",
            "descricao": "Conversao de imagens para WebP, PNG, JPEG e outros.",
            "icone": "bi-image",
            "aceita": "image/*",
            "controles": "imagem",
            "formatos": [
                {"slug": f["slug"], "label": f["label"], "padrao": f["padrao"]}
                for f in FORMATOS_IMAGEM
                if f["slug"] in tools
            ],
        }

    _modulos = novos
    TOOLS = tools
    CATEGORIAS = categorias


def modulo(nome: str) -> ModuleType | None:
    return _modulos.get(nome)


def home_itens() -> list[dict]:
    itens: list[dict] = []
    if "video" in CATEGORIAS:
        itens.append({**CATEGORIAS["video"], "href": "/categoria/video", "escopo": "video"})
    if "imagem" in CATEGORIAS:
        itens.append({**CATEGORIAS["imagem"], "href": "/categoria/imagem", "escopo": "imagem"})
    for slug in ("wp-screenshot", "unlock-pdf", "ai-chat"):
        if slug in TOOLS:
            itens.append({**TOOLS[slug], "href": f"/tool/{slug}", "escopo": slug})

    from . import db
    ordem = db.listar_ordem_home()
    if not ordem:
        return itens

    por_escopo = {t["escopo"]: t for t in itens}
    ordenados: list[dict] = []
    vistos: set[str] = set()
    for slug in ordem:
        item = por_escopo.get(slug)
        if item:
            ordenados.append(item)
            vistos.add(slug)
    for item in itens:
        if item["escopo"] not in vistos:
            ordenados.append(item)
    return ordenados


def listar_loja() -> list[dict[str, Any]]:
    return [
        {
            "slug": slug,
            "nome": extra["nome"],
            "descricao": extra["descricao"],
            "icone": extra["icone"],
            "packages": list(extra["packages"]),
            "instalado": extra_instalado(slug),
        }
        for slug, extra in EXTRAS.items()
    ]


rebuild()
