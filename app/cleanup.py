import re
import shutil
from pathlib import Path

from .extras import FORMATOS_IMAGEM, FORMATOS_VIDEO

STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
OUTPUTS_DIR = STORAGE_DIR / "outputs"

ESCOPO_POR_SLUG = {
    **{f["slug"]: "video" for f in FORMATOS_VIDEO},
    **{f["slug"]: "imagem" for f in FORMATOS_IMAGEM},
    "wp-screenshot": "wp-screenshot",
    "unlock-pdf": "unlock-pdf",
}

ESCOPOS_ARQUIVO = ("video", "imagem", "wp-screenshot", "unlock-pdf")
ESCOPO_AI = "ai-chat"
ESCOPO_LAN_DM = "lan-dm"
ESCOPO_COFRE = "cofre-senhas"
ESCOPO_FAKE = "fake-data"
ESCOPO_TOTP = "totp-auth"
ESCOPOS_VAULT = {
    ESCOPO_COFRE: "cofre",
    ESCOPO_FAKE: "fake",
    ESCOPO_TOTP: "totp",
}

_SESSAO_RE = re.compile(r"^\d+_[a-f0-9]+$", re.I)
_VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"}
_PDF_EXT = {".pdf"}
_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif"}


def escopo_de_slug(slug: str) -> str:
    return ESCOPO_POR_SLUG.get(slug, slug)


def _iter_arquivos(pasta: Path):
    if not pasta.exists():
        return
    for item in pasta.rglob("*"):
        if item.name == ".gitkeep" or not item.is_file():
            continue
        yield item


def _extensoes_sessao(sessao_id: str) -> set[str]:
    exts: set[str] = set()
    for base in (UPLOADS_DIR, OUTPUTS_DIR):
        pasta = base / sessao_id
        if not pasta.is_dir():
            continue
        for item in _iter_arquivos(pasta):
            exts.add(item.suffix.lower())
    return exts


def _adivinhar_escopo(sessao_id: str) -> str:
    exts = _extensoes_sessao(sessao_id)
    if exts & _VIDEO_EXT:
        return "video"
    if exts & _PDF_EXT:
        return "unlock-pdf"
    if exts & _IMG_EXT:
        # PNG 1200x900 tipico de screenshot WP
        for base in (UPLOADS_DIR, OUTPUTS_DIR):
            pasta = base / sessao_id
            if not pasta.is_dir():
                continue
            for item in _iter_arquivos(pasta):
                if item.suffix.lower() != ".png":
                    continue
                try:
                    from PIL import Image
                    with Image.open(item) as img:
                        if img.size == (1200, 900):
                            return "wp-screenshot"
                except Exception:
                    continue
        return "imagem"
    return "imagem"


def migrar_sessoes_legado() -> None:
    """Move sessoes antigas (raiz) para pastas por ferramenta."""
    sessoes: set[str] = set()
    for base in (UPLOADS_DIR, OUTPUTS_DIR):
        if not base.exists():
            continue
        for item in base.iterdir():
            if item.is_dir() and _SESSAO_RE.match(item.name):
                sessoes.add(item.name)

    for sessao_id in sessoes:
        escopo = _adivinhar_escopo(sessao_id)
        for base in (UPLOADS_DIR, OUTPUTS_DIR):
            origem = base / sessao_id
            if not origem.is_dir():
                continue
            destino = base / escopo / sessao_id
            if destino.exists():
                continue
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origem), str(destino))


def _info_pastas(*pastas: Path) -> dict:
    arquivos = 0
    bytes_total = 0
    for pasta in pastas:
        for item in _iter_arquivos(pasta):
            try:
                bytes_total += item.stat().st_size
                arquivos += 1
            except OSError:
                continue
    return {"arquivos": arquivos, "bytes": bytes_total}


def _limpar_pasta(pasta: Path) -> tuple[int, int]:
    if not pasta.exists():
        return 0, 0
    removidos = 0
    bytes_liberados = 0
    for item in list(_iter_arquivos(pasta)):
        try:
            size = item.stat().st_size
            item.unlink(missing_ok=True)
            removidos += 1
            bytes_liberados += size
        except OSError:
            continue

    for sub in sorted(
        [p for p in pasta.rglob("*") if p.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            if not any(sub.iterdir()):
                sub.rmdir()
        except OSError:
            continue
    return removidos, bytes_liberados


def info_armazenamento(escopo: str | None = None) -> dict:
    migrar_sessoes_legado()

    if escopo is None:
        info = _info_pastas(UPLOADS_DIR, OUTPUTS_DIR)
        from . import db, vault_store
        chats = db.listar_chats()
        info["chats"] = len(chats)
        info["mensagens"] = sum(c.get("total_mensagens", 0) for c in chats)
        for kind in ESCOPOS_VAULT.values():
            vault = vault_store.info_bytes(kind)
            info["arquivos"] += vault["arquivos"]
            info["bytes"] += vault["bytes"]
        return info

    if escopo == ESCOPO_AI:
        from . import db
        chats = db.listar_chats()
        msgs = sum(c.get("total_mensagens", 0) for c in chats)
        return {"arquivos": len(chats), "bytes": 0, "chats": len(chats), "mensagens": msgs}

    if escopo == ESCOPO_LAN_DM:
        from . import db
        from .tools.lan_dm import ARQUIVOS_DIR
        info = db.info_lan_dm()
        arquivos = _info_pastas(ARQUIVOS_DIR)
        return {
            "arquivos": arquivos["arquivos"],
            "bytes": arquivos["bytes"],
            "mensagens": info["mensagens"],
        }

    if escopo in ESCOPOS_VAULT:
        from . import vault_store
        return vault_store.info_bytes(ESCOPOS_VAULT[escopo])

    if escopo == "unlock-pdf":
        from . import db
        info = _info_pastas(UPLOADS_DIR / escopo, OUTPUTS_DIR / escopo)
        info["senhas"] = len(db.listar_senhas())
        return info

    if escopo == "rede-lookup":
        from . import db
        keys = (
            "shodan_api_key",
            "abuseipdb_api_key",
            "virustotal_api_key",
        )
        salvas = sum(1 for k in keys if (db.obter_setting(k) or "").strip())
        return {"arquivos": 0, "bytes": 0, "keys": salvas}

    if escopo not in ESCOPOS_ARQUIVO:
        return {"arquivos": 0, "bytes": 0}

    return _info_pastas(UPLOADS_DIR / escopo, OUTPUTS_DIR / escopo)


def executar_limpeza(escopo: str | None = None) -> dict:
    migrar_sessoes_legado()

    if escopo is None:
        # Destruir tudo: temporarios + chats + vaults + senhas PDF + API keys
        arquivos = 0
        bytes_total = 0
        for pasta in (UPLOADS_DIR, OUTPUTS_DIR):
            a, b = _limpar_pasta(pasta)
            arquivos += a
            bytes_total += b
        from . import db, vault_store
        for kind in ESCOPOS_VAULT.values():
            vault = vault_store.limpar_todos(kind)
            arquivos += vault["arquivos"]
            bytes_total += vault["bytes"]
        chats = db.limpar_chats()
        senhas = db.limpar_senhas_pdf()
        keys = db.limpar_settings_api()
        lan = db.limpar_lan_dm()
        from .tools.lan_dm import ARQUIVOS_DIR
        a_lan, b_lan = _limpar_pasta(ARQUIVOS_DIR)
        return {
            "arquivos": arquivos + a_lan,
            "bytes": bytes_total + b_lan + lan["bytes"],
            "chats": chats,
            "senhas": senhas,
            "keys": keys,
            "mensagens_lan": lan["mensagens"],
        }

    if escopo == ESCOPO_AI:
        from . import db
        chats = db.limpar_chats()
        return {"arquivos": 0, "bytes": 0, "chats": chats}

    if escopo == ESCOPO_LAN_DM:
        from . import db
        from .tools.lan_dm import ARQUIVOS_DIR
        info = db.limpar_lan_dm()
        a, b = _limpar_pasta(ARQUIVOS_DIR)
        return {
            "arquivos": a,
            "bytes": b + info["bytes"],
            "mensagens": info["mensagens"],
        }

    if escopo in ESCOPOS_VAULT:
        # Vaults so excluem um a um na propria ferramenta
        return {"arquivos": 0, "bytes": 0}

    if escopo not in ESCOPOS_ARQUIVO:
        return {"arquivos": 0, "bytes": 0}

    a1, b1 = _limpar_pasta(UPLOADS_DIR / escopo)
    a2, b2 = _limpar_pasta(OUTPUTS_DIR / escopo)
    return {"arquivos": a1 + a2, "bytes": b1 + b2}


def info_temporarios() -> dict:
    migrar_sessoes_legado()
    arquivos = 0
    bytes_total = 0
    for escopo in ESCOPOS_ARQUIVO:
        info = _info_pastas(UPLOADS_DIR / escopo, OUTPUTS_DIR / escopo)
        arquivos += info["arquivos"]
        bytes_total += info["bytes"]
    return {"arquivos": arquivos, "bytes": bytes_total}


def executar_limpeza_temporarios() -> dict:
    """So uploads/saidas de video, imagem, wp-screenshot e unlock-pdf."""
    migrar_sessoes_legado()
    arquivos = 0
    bytes_total = 0
    for escopo in ESCOPOS_ARQUIVO:
        a1, b1 = _limpar_pasta(UPLOADS_DIR / escopo)
        a2, b2 = _limpar_pasta(OUTPUTS_DIR / escopo)
        arquivos += a1 + a2
        bytes_total += b1 + b2
    return {"arquivos": arquivos, "bytes": bytes_total}


def caminho_storage(escopo: str, kind: str, sessao_id: str, nome: str) -> Path:
    if escopo not in ESCOPOS_ARQUIVO:
        raise ValueError("Escopo invalido")
    if kind not in ("upload", "output"):
        raise ValueError("Tipo invalido")
    if not _SESSAO_RE.match(sessao_id or ""):
        raise ValueError("Sessao invalida")
    if not nome or "/" in nome or "\\" in nome or nome in (".", "..") or ".." in nome:
        raise ValueError("Nome invalido")
    base = UPLOADS_DIR if kind == "upload" else OUTPUTS_DIR
    root = (base / escopo).resolve()
    caminho = (base / escopo / sessao_id / nome).resolve()
    if caminho != root and root not in caminho.parents:
        raise ValueError("Caminho invalido")
    return caminho


def listar_arquivos(escopo: str) -> dict:
    migrar_sessoes_legado()
    if escopo not in ESCOPOS_ARQUIVO:
        return {"escopo": escopo, "itens": [], "arquivos": 0, "bytes": 0}

    itens: list[dict] = []
    for kind, base in (("upload", UPLOADS_DIR / escopo), ("output", OUTPUTS_DIR / escopo)):
        if not base.exists():
            continue
        for item in _iter_arquivos(base):
            try:
                rel = item.relative_to(base)
                if len(rel.parts) != 2:
                    continue
                sessao_id = rel.parts[0]
                if not _SESSAO_RE.match(sessao_id):
                    continue
                st = item.stat()
                itens.append({
                    "kind": kind,
                    "sessao_id": sessao_id,
                    "nome": item.name,
                    "bytes": st.st_size,
                    "mtime": int(st.st_mtime),
                    "ext": item.suffix.lower(),
                })
            except (OSError, ValueError):
                continue

    itens.sort(key=lambda x: x["mtime"], reverse=True)
    return {
        "escopo": escopo,
        "itens": itens,
        "arquivos": len(itens),
        "bytes": sum(i["bytes"] for i in itens),
    }


def remover_arquivo(escopo: str, kind: str, sessao_id: str, nome: str) -> dict:
    migrar_sessoes_legado()
    caminho = caminho_storage(escopo, kind, sessao_id, nome)
    if not caminho.is_file():
        raise FileNotFoundError("Arquivo nao encontrado")
    size = caminho.stat().st_size
    caminho.unlink(missing_ok=True)

    pasta = caminho.parent
    try:
        if pasta.is_dir() and not any(pasta.iterdir()):
            pasta.rmdir()
    except OSError:
        pass

    return {"ok": True, "bytes": size, "nome": nome}
