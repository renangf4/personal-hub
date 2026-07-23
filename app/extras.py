"""Catalogo de extras opcionais do Personal Hub."""

from __future__ import annotations

EXTRAS: dict[str, dict] = {
    "video": {
        "slug": "video",
        "nome": "Video",
        "descricao": "Conversao de videos para MP4, WebM, GIF, MKV ou MOV.",
        "icone": "bi-camera-video",
        "packages": ["imageio-ffmpeg==0.5.1"],
        "imports": ["imageio_ffmpeg"],
        "modulos": ["convert_video"],
    },
    "imagem": {
        "slug": "imagem",
        "nome": "Imagem",
        "descricao": "Conversao de imagens para WebP, PNG, JPEG, GIF, BMP e TIFF.",
        "icone": "bi-image",
        "packages": ["pillow==11.0.0"],
        "imports": ["PIL"],
        "modulos": ["convert_image"],
    },
    "wp-screenshot": {
        "slug": "wp-screenshot",
        "nome": "Screenshot WordPress",
        "descricao": "Padroniza imagens em 1200x900 PNG otimizado (usa Pillow).",
        "icone": "bi-window",
        "packages": ["pillow==11.0.0"],
        "imports": ["PIL"],
        "modulos": ["wp_screenshot"],
    },
    "pdf": {
        "slug": "pdf",
        "nome": "Desbloquear PDF",
        "descricao": "Remove senha de PDFs com lista persistente cadastrada.",
        "icone": "bi-file-earmark-lock",
        "packages": ["pikepdf==9.4.2"],
        "imports": ["pikepdf"],
        "modulos": ["unlock_pdf"],
    },
    "ai": {
        "slug": "ai",
        "nome": "Assistente de IA",
        "descricao": "Chat local com Ollama — carteiras por foco (codigo, seguranca, geral...).",
        "icone": "bi-robot",
        "packages": ["httpx==0.27.2"],
        "imports": ["httpx"],
        "modulos": ["ai_chat"],
    },
}

# Formatos das categorias (slug da tool -> chave do modulo)
FORMATOS_VIDEO = [
    {"slug": "convert-mp4", "label": "MP4 (H.264)", "formato": "mp4", "padrao": True},
    {"slug": "convert-webm", "label": "WebM (VP9)", "formato": "webm", "padrao": False},
    {"slug": "convert-gif", "label": "GIF animado", "formato": "gif", "padrao": False},
    {"slug": "convert-mkv", "label": "MKV (H.264)", "formato": "mkv", "padrao": False},
    {"slug": "convert-mov", "label": "MOV (H.264)", "formato": "mov", "padrao": False},
]

FORMATOS_IMAGEM = [
    {"slug": "convert-webp", "label": "WebP", "formato": "webp", "padrao": True},
    {"slug": "convert-png", "label": "PNG", "formato": "png", "padrao": False},
    {"slug": "convert-jpeg", "label": "JPEG", "formato": "jpeg", "padrao": False},
    {"slug": "convert-gif-img", "label": "GIF", "formato": "gif", "padrao": False},
    {"slug": "convert-bmp", "label": "BMP", "formato": "bmp", "padrao": False},
    {"slug": "convert-tiff", "label": "TIFF", "formato": "tiff", "padrao": False},
]

TOOL_META: dict[str, dict] = {
    "wp_screenshot": {
        "slug": "wp-screenshot",
        "nome": "Screenshot WordPress",
        "descricao": "Padroniza imagens em 1200x900 PNG otimizado.",
        "icone": "bi-window",
        "aceita": "image/*",
        "controles": "none",
        "extra": "wp-screenshot",
    },
    "unlock_pdf": {
        "slug": "unlock-pdf",
        "nome": "Desbloquear PDF",
        "descricao": "Remove senha de PDFs usando lista persistente cadastrada.",
        "icone": "bi-file-earmark-lock",
        "aceita": ".pdf,application/pdf",
        "controles": "unlock",
        "extra": "pdf",
    },
    "ai_chat": {
        "slug": "ai-chat",
        "nome": "Assistente de IA Local",
        "descricao": "Chat local com Ollama — carteira por foco (codigo, seguranca, geral...).",
        "icone": "bi-robot",
        "aceita": "",
        "controles": "ai",
        "extra": "ai",
    },
}
