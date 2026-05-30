import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .cleanup import (
    OUTPUTS_DIR,
    UPLOADS_DIR,
    executar_limpeza,
    info_armazenamento,
)
from .tools import ai_chat, convert_mp4, convert_webm, convert_webp, unlock_pdf, wp_screenshot

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
        "controles": "video",
        "modulo": convert_mp4,
    },
    "convert-webm": {
        "slug": "convert-webm",
        "nome": "Converter para WebM",
        "descricao": "Converte videos (mp4, mov, avi, mkv) para WebM VP9.",
        "icone": "bi-camera-video",
        "aceita": "video/*,.mkv,.mov,.avi",
        "controles": "video",
        "modulo": convert_webm,
    },
    "convert-webp": {
        "slug": "convert-webp",
        "nome": "Converter para WebP",
        "descricao": "Converte imagens para WebP.",
        "icone": "bi-image",
        "aceita": "image/*",
        "controles": "webp",
        "modulo": convert_webp,
    },
    "unlock-pdf": {
        "slug": "unlock-pdf",
        "nome": "Desbloquear PDF",
        "descricao": "Remove senha de PDFs usando lista persistente cadastrada.",
        "icone": "bi-file-earmark-lock",
        "aceita": ".pdf,application/pdf",
        "controles": "unlock",
        "modulo": unlock_pdf,
    },
    "wp-screenshot": {
        "slug": "wp-screenshot",
        "nome": "Screenshot WordPress",
        "descricao": "Padroniza imagens em 1200x900 PNG otimizado.",
        "icone": "bi-window",
        "aceita": "image/*",
        "controles": "none",
        "modulo": wp_screenshot,
    },
    "ai-chat": {
        "slug": "ai-chat",
        "nome": "Assistente de IA Local",
        "descricao": "Chat local com Ollama (qwen2.5-coder) para duvidas de codigo e arquitetura.",
        "icone": "bi-robot",
        "aceita": "",
        "controles": "ai",
        "modulo": ai_chat,
    },
}


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


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

    if slug == "ai-chat":
        return templates.TemplateResponse(
            "ai_chat.html",
            {
                "request": request,
                "tool": tool,
                "modelo": ai_chat.MODELO_PADRAO,
                "chats": db.listar_chats(),
            },
        )

    return templates.TemplateResponse(
        "tool.html",
        {"request": request, "tool": tool, "controles": tool.get("controles", "none")},
    )


@app.post("/tool/{slug}/processar")
async def processar(
    slug: str,
    arquivos: list[UploadFile] = File(...),
    max_width: int | None = Form(None),
    quality: int | None = Form(None),
):
    tool = TOOLS.get(slug)
    if not tool:
        raise HTTPException(status_code=404)

    if slug == "ai-chat":
        raise HTTPException(status_code=400, detail="Use /api/ai/* para o assistente")

    upload_dir, output_dir, sessao_id = _criar_sessao()
    entradas = _salvar_uploads(arquivos, upload_dir)

    if not entradas:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado")

    largura = max_width if max_width and max_width > 0 else None
    q = quality if quality and quality > 0 else 100

    if slug == "convert-webp":
        resultados = tool["modulo"].processar(entradas, output_dir, max_width=largura, quality=q)
    elif slug in ("convert-mp4", "convert-webm"):
        resultados = tool["modulo"].processar(entradas, output_dir, max_width=largura, quality=q)
    elif slug == "unlock-pdf":
        resultados = tool["modulo"].processar(entradas, output_dir, senhas=db.senhas_como_lista())
    else:
        resultados = tool["modulo"].processar(entradas, output_dir)

    for r in resultados:
        if r["ok"] and r["saida"]:
            r["download_url"] = f"/download/{sessao_id}/{r['saida']}"

    return JSONResponse({"sessao_id": sessao_id, "resultados": resultados})


@app.post("/api/webp/estimar")
async def api_webp_estimar(
    arquivo: UploadFile = File(...),
    quality: int = Form(100),
    max_width: int | None = Form(None),
):
    conteudo = await arquivo.read()
    try:
        largura = max_width if max_width and max_width > 0 else None
        tamanho = convert_webp.estimar(conteudo, max_width=largura, quality=quality)
        return {
            "ok": True,
            "original": len(conteudo),
            "estimado": tamanho,
            "nome": arquivo.filename,
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(e)})


@app.post("/api/video/estimar")
async def api_video_estimar(
    slug: str = Form(...),
    arquivo: UploadFile = File(...),
    quality: int = Form(100),
    max_width: int | None = Form(None),
):
    if slug not in ("convert-mp4", "convert-webm"):
        raise HTTPException(status_code=400, detail="Slug invalido")
    conteudo = await arquivo.read()
    largura = max_width if max_width and max_width > 0 else None
    modulo = TOOLS[slug]["modulo"]
    resultado = modulo.estimar(
        conteudo,
        nome_original=arquivo.filename or "video.mp4",
        max_width=largura,
        quality=quality,
    )
    if not resultado.get("ok"):
        return JSONResponse(status_code=400, content=resultado)
    return resultado


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


@app.get("/api/limpar-info")
def api_limpar_info():
    return {"ok": True, **info_armazenamento()}


@app.post("/api/limpar-agora")
def api_limpar_agora():
    resultado = executar_limpeza()
    return {"ok": True, **resultado}


def _modelo_permitido(modelo: str | None) -> str:
    if not modelo:
        return ai_chat.MODELO_PADRAO
    permitidos = {p["slug"] for p in ai_chat.MODELOS_PRESET}
    if modelo not in permitidos:
        raise HTTPException(status_code=400, detail="Modelo nao permitido")
    return modelo


@app.get("/api/ai/status")
async def api_ai_status():
    info = await ai_chat.verificar_status(ai_chat.MODELO_PADRAO)
    return {"ok": True, **info}


@app.post("/api/ai/pull")
async def api_ai_pull(payload: dict = Body(default_factory=dict)):
    modelo = _modelo_permitido(payload.get("modelo"))
    return StreamingResponse(
        ai_chat.stream_pull(modelo),
        media_type="application/x-ndjson",
    )


@app.post("/api/ai/instalar-ollama")
async def api_ai_instalar_ollama():
    return StreamingResponse(
        ai_chat.stream_install_ollama(),
        media_type="application/x-ndjson",
    )


@app.post("/api/ai/iniciar-ollama")
def api_ai_iniciar_ollama():
    resultado = ai_chat.iniciar_servico_ollama()
    status_code = 200 if resultado.get("ok") else 400
    return JSONResponse(status_code=status_code, content=resultado)


@app.get("/api/ai/chats")
def api_ai_chats_listar():
    return {"ok": True, "chats": db.listar_chats()}


@app.post("/api/ai/chats")
def api_ai_chats_criar(payload: dict = Body(default_factory=dict)):
    titulo = (payload.get("titulo") or "Nova conversa").strip() or "Nova conversa"
    chat = db.criar_chat(titulo)
    return {"ok": True, "chat": chat}


@app.get("/api/ai/chats/{chat_id}")
def api_ai_chat_detalhe(chat_id: int):
    chat = db.obter_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404)
    return {
        "ok": True,
        "chat": chat,
        "mensagens": db.listar_mensagens(chat_id),
    }


@app.patch("/api/ai/chats/{chat_id}")
def api_ai_chat_renomear(chat_id: int, payload: dict = Body(...)):
    titulo = (payload.get("titulo") or "").strip()
    if not titulo:
        raise HTTPException(status_code=400, detail="Titulo vazio")
    if not db.renomear_chat(chat_id, titulo):
        raise HTTPException(status_code=404)
    return {"ok": True, "chat": db.obter_chat(chat_id)}


@app.delete("/api/ai/chats/{chat_id}")
def api_ai_chat_excluir(chat_id: int):
    db.excluir_chat(chat_id)
    return {"ok": True}


@app.post("/api/ai/chats/{chat_id}/mensagens")
async def api_ai_mensagem(chat_id: int, payload: dict = Body(...)):
    conteudo = (payload.get("conteudo") or "").strip()
    if not conteudo:
        raise HTTPException(status_code=400, detail="Mensagem vazia")

    modelo = _modelo_permitido(payload.get("modelo"))

    chat = db.obter_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404)

    msg_user = db.adicionar_mensagem(chat_id, "user", conteudo)

    if chat["titulo"] == "Nova conversa":
        novo_titulo = conteudo.strip().splitlines()[0][:60]
        if novo_titulo:
            db.renomear_chat(chat_id, novo_titulo)

    historico = [
        {"role": m["role"], "content": m["conteudo"]}
        for m in db.listar_mensagens(chat_id)
        if m["role"] in ("user", "assistant")
    ]

    async def gerar():
        yield (json.dumps({"tipo": "user_msg", "mensagem": msg_user}) + "\n").encode("utf-8")

        partes: list[str] = []
        async for chunk in ai_chat.stream_chat(modelo, historico):
            if chunk.get("erro"):
                yield (
                    json.dumps({"tipo": "erro", "msg": chunk.get("msg", "Erro desconhecido")}) + "\n"
                ).encode("utf-8")
                return
            pedaco = chunk.get("message", {}).get("content", "")
            if pedaco:
                partes.append(pedaco)
                yield (json.dumps({"tipo": "delta", "conteudo": pedaco}) + "\n").encode("utf-8")
            if chunk.get("done"):
                resposta = "".join(partes).strip()
                total_ns = chunk.get("total_duration") or 0
                eval_count = chunk.get("eval_count") or 0
                eval_ns = chunk.get("eval_duration") or 0
                load_ns = chunk.get("load_duration") or 0
                metricas = {
                    "total_s": round(total_ns / 1e9, 2) if total_ns else None,
                    "load_s": round(load_ns / 1e9, 2) if load_ns else None,
                    "tokens": eval_count,
                    "tokens_por_s": round(eval_count / (eval_ns / 1e9), 1) if eval_ns else None,
                }
                msg_ai = None
                if resposta:
                    msg_ai = db.adicionar_mensagem(chat_id, "assistant", resposta)
                yield (
                    json.dumps({"tipo": "fim", "mensagem": msg_ai, "metricas": metricas}) + "\n"
                ).encode("utf-8")
                return

    return StreamingResponse(gerar(), media_type="application/x-ndjson")
