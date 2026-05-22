import shutil
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .cleanup import (
    OUTPUTS_DIR,
    UPLOADS_DIR,
    executar_limpeza,
    iniciar_cleanup_em_background,
)
from .tools import convert_mp4, convert_webm, convert_webp, unlock_pdf, wp_screenshot

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Personal Hub", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

TOOLS = {
    "convert-mp4": {
        "slug": "convert-mp4",
        "nome": "Converter para MP4",
        "descricao": "Converte videos (mov, avi, mkv, webm) para MP4 H.264.",
        "icone": "bi-film",
        "aceita": "video/*,.mkv,.mov,.avi,.webm",
        "modulo": convert_mp4,
    },
    "convert-webm": {
        "slug": "convert-webm",
        "nome": "Converter para WebM",
        "descricao": "Converte videos (mp4, mov, avi, mkv) para WebM VP9.",
        "icone": "bi-camera-video",
        "aceita": "video/*,.mkv,.mov,.avi",
        "modulo": convert_webm,
    },
    "convert-webp": {
        "slug": "convert-webp",
        "nome": "Converter para WebP",
        "descricao": "Converte imagens para WebP (largura maxima configuravel).",
        "icone": "bi-image",
        "aceita": "image/*",
        "modulo": convert_webp,
    },
    "unlock-pdf": {
        "slug": "unlock-pdf",
        "nome": "Desbloquear PDF",
        "descricao": "Remove senha de PDFs usando lista pessoal cadastrada.",
        "icone": "bi-file-earmark-lock",
        "aceita": ".pdf,application/pdf",
        "modulo": unlock_pdf,
    },
    "wp-screenshot": {
        "slug": "wp-screenshot",
        "nome": "Screenshot WordPress",
        "descricao": "Padroniza imagens em 1200x900 PNG otimizado.",
        "icone": "bi-window",
        "aceita": "image/*",
        "modulo": wp_screenshot,
    },
}


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    iniciar_cleanup_em_background()


def _criar_sessao() -> tuple[Path, Path, str]:
    sessao_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    upload_dir = UPLOADS_DIR / sessao_id
    output_dir = OUTPUTS_DIR / sessao_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir, output_dir, sessao_id


def _salvar_uploads(arquivos: list[UploadFile], destino: Path) -> list[Path]:
    salvos: list[Path] = []
    for arq in arquivos:
        if not arq.filename:
            continue
        nome_seguro = Path(arq.filename).name
        caminho = destino / nome_seguro
        with caminho.open("wb") as f:
            shutil.copyfileobj(arq.file, f)
        salvos.append(caminho)
    return salvos


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "tools": list(TOOLS.values())},
    )


@app.get("/tool/{slug}", response_class=HTMLResponse)
def tool_page(request: Request, slug: str):
    tool = TOOLS.get(slug)
    if not tool:
        raise HTTPException(status_code=404)

    if slug == "unlock-pdf":
        return templates.TemplateResponse(
            "unlock_pdf.html",
            {"request": request, "tool": tool, "senhas": db.listar_senhas()},
        )

    extra = {}
    if slug == "convert-webp":
        extra["mostrar_largura"] = True

    return templates.TemplateResponse(
        "tool.html",
        {"request": request, "tool": tool, **extra},
    )


@app.post("/tool/{slug}/processar")
async def processar(
    slug: str,
    arquivos: list[UploadFile] = File(...),
    max_width: int | None = Form(None),
):
    tool = TOOLS.get(slug)
    if not tool:
        raise HTTPException(status_code=404)

    upload_dir, output_dir, sessao_id = _criar_sessao()
    entradas = _salvar_uploads(arquivos, upload_dir)

    if not entradas:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado")

    if slug == "convert-webp":
        largura = max_width if max_width and max_width > 0 else None
        resultados = tool["modulo"].processar(entradas, output_dir, max_width=largura)
    elif slug == "unlock-pdf":
        resultados = tool["modulo"].processar(entradas, output_dir, senhas=db.senhas_como_lista())
    else:
        resultados = tool["modulo"].processar(entradas, output_dir)

    for r in resultados:
        if r["ok"] and r["saida"]:
            r["download_url"] = f"/download/{sessao_id}/{r['saida']}"

    return JSONResponse({"sessao_id": sessao_id, "resultados": resultados})


@app.get("/download/{sessao_id}/{nome}")
def download(sessao_id: str, nome: str):
    caminho = OUTPUTS_DIR / sessao_id / nome
    if not caminho.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(caminho, filename=nome)


@app.get("/api/senhas")
def api_listar_senhas():
    return {"senhas": db.listar_senhas()}


@app.post("/api/senhas")
def api_adicionar_senha(senha: str = Form(...)):
    if db.adicionar_senha(senha):
        return {"ok": True, "senhas": db.listar_senhas()}
    return JSONResponse(
        status_code=400,
        content={"ok": False, "msg": "Senha vazia ou ja cadastrada"},
    )


@app.post("/api/senhas/{senha_id}/excluir")
def api_remover_senha(senha_id: int):
    db.remover_senha(senha_id)
    return {"ok": True, "senhas": db.listar_senhas()}


@app.post("/api/limpar-agora")
def api_limpar_agora():
    removidos = executar_limpeza()
    return {"ok": True, "removidos": removidos}
