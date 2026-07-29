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
    from .cleanup import ESCOPOS_ARQUIVO, ESCOPOS_VAULT, ESCOPO_AI, info_armazenamento

    def _fmt_bytes(n: int) -> str:
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n / (1024 * 1024):.2f} MB"

    itens: list[dict] = []
    if "video" in CATEGORIAS:
        itens.append({**CATEGORIAS["video"], "href": "/categoria/video", "escopo": "video"})
    if "imagem" in CATEGORIAS:
        itens.append({**CATEGORIAS["imagem"], "href": "/categoria/imagem", "escopo": "imagem"})
    for slug in (
        "wp-screenshot",
        "unlock-pdf",
        "ai-chat",
        "rede-lookup",
        "gcm-crypto",
        "cofre-senhas",
        "fake-data",
        "totp-auth",
    ):
        if slug in TOOLS:
            itens.append({**TOOLS[slug], "href": f"/tool/{slug}", "escopo": slug})

    for item in itens:
        escopo = item.get("escopo") or ""
        info = info_armazenamento(escopo)
        bytes_total = int(info.get("bytes") or 0)
        arquivos = int(info.get("arquivos") or 0)
        chats = int(info.get("chats") or 0)
        item["dados_bytes"] = bytes_total
        item["dados_arquivos"] = arquivos
        item["tem_dados"] = False

        if escopo == ESCOPO_AI:
            item["dados_label"] = f"{chats} conversa(s)" if chats else "0 conversas"
            item["tem_dados"] = chats > 0
            item["storage_title"] = "Conversas salvas no SQLite"
            item["mostra_storage"] = True
        elif escopo in ESCOPOS_ARQUIVO:
            senhas = int(info.get("senhas") or 0)
            partes: list[str] = []
            if bytes_total > 0 or arquivos > 0:
                partes.append(_fmt_bytes(bytes_total))
            if escopo == "unlock-pdf" and senhas > 0:
                partes.append(f"{senhas} senha(s)")
            item["dados_label"] = " · ".join(partes) if partes else "0 B"
            item["tem_dados"] = bytes_total > 0 or arquivos > 0 or (
                escopo == "unlock-pdf" and senhas > 0
            )
            item["storage_title"] = (
                "PDFs temporarios e senhas cadastradas"
                if escopo == "unlock-pdf"
                else "Uploads e arquivos gerados"
            )
            item["mostra_storage"] = True
        elif escopo in ESCOPOS_VAULT:
            item["dados_label"] = _fmt_bytes(bytes_total)
            item["tem_dados"] = bytes_total > 0 or arquivos > 0
            item["storage_title"] = "Arquivos criptografados em disco"
            item["mostra_storage"] = True
        elif escopo == "rede-lookup":
            keys = int(info.get("keys") or 0)
            item["dados_label"] = f"{keys} key(s)" if keys else "0 keys"
            item["tem_dados"] = keys > 0
            item["storage_title"] = "API keys (Shodan, AbuseIPDB, VirusTotal)"
            item["mostra_storage"] = True
        else:
            # gcm-crypto — nada em disco
            item["dados_label"] = ""
            item["tem_dados"] = False
            item["storage_title"] = ""
            item["mostra_storage"] = False

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
    from .cleanup import info_armazenamento

    def _fmt_bytes(n: int) -> str:
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n / (1024 * 1024):.2f} MB"

    itens = []
    for slug, extra in EXTRAS.items():
        escopo = extra.get("escopo_dados", slug)
        info = info_armazenamento(escopo)
        persist = extra.get("persistencia") or {
            "tipo": "nenhum",
            "rotulo": "Nada gravado em disco",
            "caminho": "—",
        }
        arquivos = info.get("arquivos", 0)
        bytes_total = info.get("bytes", 0)
        chats = info.get("chats", 0)
        if persist.get("tipo") == "nenhum":
            dados_resumo = "Sem persistencia"
            tem_dados = False
        elif escopo == "ai-chat":
            dados_resumo = f"{chats} conversa(s)" if chats else "Vazio"
            tem_dados = chats > 0
        elif arquivos > 0:
            dados_resumo = f"{arquivos} arquivo(s) · {_fmt_bytes(bytes_total)}"
            tem_dados = True
        else:
            dados_resumo = "Vazio"
            tem_dados = False

        itens.append({
            "slug": slug,
            "nome": extra["nome"],
            "descricao": extra["descricao"],
            "icone": extra["icone"],
            "packages": list(extra["packages"]),
            "instalado": extra_instalado(slug),
            "escopo_dados": escopo,
            "dados_arquivos": arquivos,
            "dados_bytes": bytes_total,
            "dados_chats": chats,
            "dados_resumo": dados_resumo,
            "tem_dados": tem_dados,
            "persistencia": {
                "tipo": persist.get("tipo", "nenhum"),
                "rotulo": persist.get("rotulo", ""),
                "caminho": persist.get("caminho", "—"),
            },
        })
    return itens


rebuild()
