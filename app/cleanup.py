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
        from . import db
        chats = db.listar_chats()
        info["chats"] = len(chats)
        info["mensagens"] = sum(c.get("total_mensagens", 0) for c in chats)
        return info

    if escopo == ESCOPO_AI:
        from . import db
        chats = db.listar_chats()
        msgs = sum(c.get("total_mensagens", 0) for c in chats)
        return {"arquivos": len(chats), "bytes": 0, "chats": len(chats), "mensagens": msgs}

    if escopo not in ESCOPOS_ARQUIVO:
        return {"arquivos": 0, "bytes": 0}

    return _info_pastas(UPLOADS_DIR / escopo, OUTPUTS_DIR / escopo)


def executar_limpeza(escopo: str | None = None) -> dict:
    migrar_sessoes_legado()

    if escopo is None:
        arquivos = 0
        bytes_total = 0
        for pasta in (UPLOADS_DIR, OUTPUTS_DIR):
            a, b = _limpar_pasta(pasta)
            arquivos += a
            bytes_total += b
        from . import db
        chats = db.limpar_chats()
        return {"arquivos": arquivos, "bytes": bytes_total, "chats": chats}

    if escopo == ESCOPO_AI:
        from . import db
        chats = db.limpar_chats()
        return {"arquivos": 0, "bytes": 0, "chats": chats}

    if escopo not in ESCOPOS_ARQUIVO:
        return {"arquivos": 0, "bytes": 0}

    a1, b1 = _limpar_pasta(UPLOADS_DIR / escopo)
    a2, b2 = _limpar_pasta(OUTPUTS_DIR / escopo)
    return {"arquivos": a1 + a2, "bytes": b1 + b2}
