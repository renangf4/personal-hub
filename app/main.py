import asyncio
import json
import shutil
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.types import ASGIApp, Receive, Scope, Send

from . import auth, config, db, registry, store
from .cleanup import (
    OUTPUTS_DIR,
    UPLOADS_DIR,
    caminho_storage,
    escopo_de_slug,
    executar_limpeza,
    executar_limpeza_temporarios,
    info_armazenamento,
    info_temporarios,
    listar_arquivos,
    migrar_sessoes_legado,
    remover_arquivo,
)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Personal Hub", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def static_url(path: str) -> str:
    """URL de asset com ?v=mtime para invalidar cache quando o arquivo mudar."""
    rel = path.lstrip("/").removeprefix("static/")
    arquivo = STATIC_DIR / rel
    try:
        ver = int(arquivo.stat().st_mtime)
    except OSError:
        ver = int(time.time())
    return f"/static/{rel}?v={ver}"


templates.env.globals.update({
    "hub_mode": config.MODE,
    "hub_port": config.PORT,
    "hub_bind_label": config.BIND_LABEL,
    "hub_auth_required": config.AUTH_REQUIRED,
    "hub_is_lan": config.IS_LAN,
    "hub_is_linux": sys.platform == "linux",
    "static_url": static_url,
})


class HubAuthMiddleware:
    """ASGI puro — evita BaseHTTPMiddleware (quebra StreamingResponse)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        scope.setdefault("state", {})
        scope["state"]["hub_authenticated"] = auth.autenticado(request)

        path = scope.get("path") or ""
        if auth.path_livre(path):
            await self.app(scope, receive, send)
            return
        if auth.precisa_auth(request):
            response = auth.resposta_nao_autenticado(request)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


app.add_middleware(HubAuthMiddleware)


def _ai():
    mod = registry.modulo("ai_chat")
    if mod is None:
        raise HTTPException(status_code=404, detail="Assistente de IA nao instalado. Abra a Loja.")
    return mod


def _imagem():
    mod = registry.modulo("convert_image")
    if mod is None:
        raise HTTPException(status_code=404, detail="Ferramenta de imagem nao instalada. Abra a Loja.")
    return mod


def _wp_screenshot():
    mod = registry.modulo("wp_screenshot")
    if mod is None:
        raise HTTPException(status_code=404, detail="Screenshot WordPress nao instalado. Abra a Loja.")
    return mod


@app.on_event("startup")
def _startup() -> None:
    config.validate_or_raise()
    db.init_db()
    db.migrar_extras_legado()
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    migrar_sessoes_legado()
    registry.rebuild()


def _next_seguro(raw: str | None) -> str:
    if not raw:
        return "/"
    raw = raw.strip()
    if not raw.startswith("/") or raw.startswith("//"):
        return "/"
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return "/"
    return raw or "/"


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if not config.AUTH_REQUIRED:
        return RedirectResponse("/", status_code=303)
    if auth.autenticado(request):
        return RedirectResponse(_next_seguro(next), status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next": _next_seguro(next),
            "erro": None,
        },
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    senha: str = Form(""),
    next: str = Form("/"),
):
    if not config.AUTH_REQUIRED:
        return RedirectResponse("/", status_code=303)
    destino = _next_seguro(next)
    if auth.senha_ok(senha):
        resp = RedirectResponse(destino, status_code=303)
        auth.gravar_sessao(resp)
        return resp
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next": destino,
            "erro": "Senha incorreta",
        },
        status_code=401,
    )


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login" if config.AUTH_REQUIRED else "/", status_code=303)
    auth.limpar_sessao(resp)
    return resp


def _criar_sessao(escopo: str) -> tuple[Path, Path, str]:
    sessao_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    upload_dir = UPLOADS_DIR / escopo / sessao_id
    output_dir = OUTPUTS_DIR / escopo / sessao_id
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
        {
            "request": request,
            "tools": registry.home_itens(),
            "extras_disponiveis": sum(1 for e in registry.listar_loja() if not e["instalado"]),
        },
    )


@app.post("/api/home/ordem")
def api_home_ordem(payload: dict = Body(...)):
    ordem = payload.get("ordem")
    if not isinstance(ordem, list) or not all(isinstance(x, str) for x in ordem):
        raise HTTPException(status_code=400, detail="Ordem invalida")
    db.salvar_ordem_home(ordem)
    return {"ok": True, "ordem": db.listar_ordem_home()}


@app.get("/loja", response_class=HTMLResponse)
def loja_page(request: Request):
    return templates.TemplateResponse(
        "loja.html",
        {"request": request, "extras": registry.listar_loja()},
    )


@app.get("/api/loja")
def api_loja_listar():
    return {"ok": True, "extras": registry.listar_loja()}


@app.post("/api/loja/{slug}/instalar")
async def api_loja_instalar(slug: str):
    from .extras import EXTRAS
    if slug not in EXTRAS:
        raise HTTPException(status_code=404, detail="Extra desconhecido")
    return StreamingResponse(store.instalar(slug), media_type="application/x-ndjson")


@app.post("/api/loja/{slug}/desinstalar")
async def api_loja_desinstalar(slug: str):
    from .extras import EXTRAS
    if slug not in EXTRAS:
        raise HTTPException(status_code=404, detail="Extra desconhecido")
    return StreamingResponse(store.desinstalar(slug), media_type="application/x-ndjson")


@app.get("/categoria/{slug}", response_class=HTMLResponse)
def categoria_page(request: Request, slug: str):
    cat = registry.CATEGORIAS.get(slug)
    if not cat:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "tool.html",
        {
            "request": request,
            "tool": cat,
            "controles": cat["controles"],
            "categoria": cat,
        },
    )


@app.get("/tool/{slug}", response_class=HTMLResponse)
def tool_page(request: Request, slug: str):
    tool = registry.TOOLS.get(slug)
    if not tool:
        raise HTTPException(status_code=404)

    if slug == "unlock-pdf":
        return templates.TemplateResponse(
            "unlock_pdf.html",
            {"request": request, "tool": tool, "senhas": db.listar_senhas()},
        )

    if slug == "ai-chat":
        ai = _ai()
        return templates.TemplateResponse(
            "ai_chat.html",
            {
                "request": request,
                "tool": tool,
                "modelo": ai.MODELO_PADRAO,
                "chats": db.listar_chats(),
            },
        )

    if slug == "rede-lookup":
        return templates.TemplateResponse(
            "rede_lookup.html",
            {
                "request": request,
                "tool": tool,
                "keys": {
                    "shodan": db.obter_setting("shodan_api_key"),
                    "abuseipdb": db.obter_setting("abuseipdb_api_key"),
                    "virustotal": db.obter_setting("virustotal_api_key"),
                },
            },
        )

    if slug == "gcm-crypto":
        return templates.TemplateResponse(
            "gcm_crypto.html",
            {"request": request, "tool": tool},
        )

    if slug == "cofre-senhas":
        return templates.TemplateResponse(
            "cofre_senhas.html",
            {"request": request, "tool": tool},
        )

    if slug == "fake-data":
        return templates.TemplateResponse(
            "fake_data.html",
            {"request": request, "tool": tool},
        )

    if slug == "totp-auth":
        return templates.TemplateResponse(
            "totp_auth.html",
            {"request": request, "tool": tool},
        )

    if slug == "lan-dm":
        _lan_dm()
        return templates.TemplateResponse(
            "lan_dm.html",
            {"request": request, "tool": tool},
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
    modo: str | None = Form(None),
    senha_avulsa: str | None = Form(None),
    salvar_senha: str | None = Form(None),
    pin_digits: str | None = Form(None),
    wordlist_fonte: str | None = Form(None),
    wordlist: UploadFile | None = File(None),
):
    tool = registry.TOOLS.get(slug)
    if not tool:
        raise HTTPException(status_code=404)

    if slug == "ai-chat":
        raise HTTPException(status_code=400, detail="Use /api/ai/* para o assistente")

    upload_dir, output_dir, sessao_id = _criar_sessao(escopo_de_slug(slug))
    entradas = _salvar_uploads(arquivos, upload_dir)

    if not entradas:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado")

    largura = max_width if max_width and max_width > 0 else None
    q = quality if quality and quality > 0 else 100

    familia = tool.get("familia")
    if familia == "imagem":
        resultados = tool["modulo"].processar(
            entradas, output_dir, max_width=largura, quality=q, formato=tool["formato"]
        )
    elif familia == "video":
        resultados = tool["modulo"].processar(
            entradas, output_dir, max_width=largura, quality=q, formato=tool["formato"]
        )
    elif slug == "wp-screenshot":
        q_wp = quality if quality and quality > 0 else 50
        resultados = tool["modulo"].processar(entradas, output_dir, quality=q_wp)
    elif slug == "unlock-pdf":
        modo_unlock = (modo or "salvas").strip().lower()
        if modo_unlock not in ("salvas", "unica", "wordlist", "numerico"):
            modo_unlock = "salvas"
        wordlist_path = None
        pin = None
        fonte_wl = (wordlist_fonte or "comuns").strip().lower()
        if fonte_wl not in ("comuns", "upload"):
            fonte_wl = "comuns"
        if modo_unlock == "wordlist" and fonte_wl == "upload" and wordlist and wordlist.filename:
            wl = upload_dir / "wordlist.txt"
            wl.write_bytes(await wordlist.read())
            wordlist_path = wl
        if modo_unlock == "numerico" and pin_digits and str(pin_digits).isdigit():
            n = int(pin_digits)
            if 3 <= n <= 6:
                pin = n
        resultados = tool["modulo"].processar(
            entradas,
            output_dir,
            modo=modo_unlock,
            senhas=db.senhas_como_lista() if modo_unlock == "salvas" else None,
            senha_avulsa=senha_avulsa if modo_unlock == "unica" else None,
            wordlist=wordlist_path,
            wordlist_fonte=fonte_wl if modo_unlock == "wordlist" else "comuns",
            pin_digits=pin,
        )
        if modo_unlock != "salvas" and salvar_senha in ("1", "on", "true", "True"):
            for r in resultados:
                s = r.get("senha_usada")
                if r.get("ok") and s:
                    db.adicionar_senha(s)
    else:
        resultados = tool["modulo"].processar(entradas, output_dir)

    escopo = escopo_de_slug(slug)
    for r in resultados:
        if r["ok"] and r["saida"]:
            r["download_url"] = f"/download/{escopo}/{sessao_id}/{r['saida']}"
            caminho = OUTPUTS_DIR / escopo / sessao_id / r["saida"]
            if caminho.is_file():
                r["bytes"] = caminho.stat().st_size

    return JSONResponse({"sessao_id": sessao_id, "escopo": escopo, "resultados": resultados})


@app.post("/api/imagem/estimar")
async def api_imagem_estimar(
    arquivo: UploadFile = File(...),
    quality: int = Form(100),
    max_width: int | None = Form(None),
    slug: str = Form("convert-webp"),
):
    tool = registry.TOOLS.get(slug)
    if not tool or tool.get("familia") != "imagem":
        raise HTTPException(status_code=400, detail="Formato de imagem invalido")
    convert_image = _imagem()
    conteudo = await arquivo.read()
    try:
        largura = max_width if max_width and max_width > 0 else None
        tamanho = convert_image.estimar(
            conteudo,
            max_width=largura,
            quality=quality,
            formato=tool["formato"],
        )
        return {
            "ok": True,
            "original": len(conteudo),
            "estimado": tamanho,
            "nome": arquivo.filename,
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "msg": str(e)})


@app.post("/api/webp/estimar")
async def api_webp_estimar(
    arquivo: UploadFile = File(...),
    quality: int = Form(100),
    max_width: int | None = Form(None),
    slug: str = Form("convert-webp"),
):
    return await api_imagem_estimar(arquivo, quality, max_width, slug)


@app.post("/api/wp-screenshot/estimar")
async def api_wp_screenshot_estimar(
    arquivo: UploadFile = File(...),
    quality: int = Form(50),
):
    wp = _wp_screenshot()
    conteudo = await arquivo.read()
    try:
        tamanho = wp.estimar(conteudo, quality=quality if quality and quality > 0 else 50)
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
    tool = registry.TOOLS.get(slug)
    if not tool or tool.get("familia") != "video":
        raise HTTPException(status_code=400, detail="Slug invalido")
    conteudo = await arquivo.read()
    largura = max_width if max_width and max_width > 0 else None
    resultado = tool["modulo"].estimar(
        conteudo,
        nome_original=arquivo.filename or "video.mp4",
        max_width=largura,
        quality=quality,
        formato=tool["formato"],
    )
    if not resultado.get("ok"):
        return JSONResponse(status_code=400, content=resultado)
    return resultado


@app.get("/download/{escopo}/{sessao_id}/{nome}")
def download(escopo: str, sessao_id: str, nome: str, inline: int = 0):
    if ".." in escopo or ".." in sessao_id or ".." in nome:
        raise HTTPException(status_code=400)
    caminho = OUTPUTS_DIR / escopo / sessao_id / nome
    if not caminho.is_file():
        raise HTTPException(status_code=404)
    if inline:
        return FileResponse(
            caminho,
            filename=nome,
            content_disposition_type="inline",
        )
    return FileResponse(caminho, filename=nome)


@app.get("/api/limpar-info")
def api_limpar_info():
    return {"ok": True, **info_armazenamento()}


@app.get("/api/limpar-info/{escopo}")
def api_limpar_info_escopo(escopo: str):
    if escopo == "temporarios":
        return {"ok": True, "escopo": escopo, **info_temporarios()}
    return {"ok": True, "escopo": escopo, **info_armazenamento(escopo)}


@app.post("/api/limpar-agora")
def api_limpar_agora():
    resultado = executar_limpeza()
    return {"ok": True, **resultado}


@app.post("/api/limpar-agora/{escopo}")
def api_limpar_agora_escopo(escopo: str):
    if escopo == "temporarios":
        resultado = executar_limpeza_temporarios()
        return {"ok": True, "escopo": escopo, **resultado}
    resultado = executar_limpeza(escopo)
    return {"ok": True, "escopo": escopo, **resultado}


@app.get("/api/storage/{escopo}")
def api_storage_listar(escopo: str):
    if escopo not in ("video", "imagem", "wp-screenshot"):
        raise HTTPException(status_code=400, detail="Escopo sem browser de storage")
    return {"ok": True, **listar_arquivos(escopo)}


@app.get("/api/storage/{escopo}/{kind}/{sessao_id}/{nome}")
def api_storage_arquivo(escopo: str, kind: str, sessao_id: str, nome: str, inline: int = 1):
    if escopo not in ("video", "imagem", "wp-screenshot"):
        raise HTTPException(status_code=400, detail="Escopo invalido")
    try:
        caminho = caminho_storage(escopo, kind, sessao_id, nome)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not caminho.is_file():
        raise HTTPException(status_code=404)
    if inline:
        return FileResponse(caminho, filename=nome, content_disposition_type="inline")
    return FileResponse(caminho, filename=nome)


@app.delete("/api/storage/{escopo}/{kind}/{sessao_id}/{nome}")
def api_storage_remover(escopo: str, kind: str, sessao_id: str, nome: str):
    if escopo not in ("video", "imagem", "wp-screenshot"):
        raise HTTPException(status_code=400, detail="Escopo invalido")
    try:
        return remover_arquivo(escopo, kind, sessao_id, nome)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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


_VAULT_EXTRAS = {
    "cofre": {"extra": "cofre", "label": "Cofre"},
    "fake": {"extra": "fake", "label": "Dados fake"},
    "totp": {"extra": "totp", "label": "Authenticator"},
}


def _vault_ok(kind: str) -> None:
    meta = _VAULT_EXTRAS.get(kind)
    if not meta or not registry.extra_instalado(meta["extra"]):
        raise HTTPException(
            status_code=404,
            detail=f"{(meta or {}).get('label', 'Extra')} nao instalado. Abra a Loja.",
        )


def _register_vault_api(kind: str, prefix: str) -> None:
    def api_listar():
        _vault_ok(kind)
        from . import vault_store
        return vault_store.listar(kind)

    def api_criar(payload: dict = Body(...)):
        _vault_ok(kind)
        from . import vault_store
        return vault_store.criar(payload.get("nome", ""), payload.get("blob", ""), kind=kind)

    async def api_importar(arquivo: UploadFile = File(...), nome: str = Form(None)):
        _vault_ok(kind)
        from . import vault_store
        return await vault_store.importar(arquivo, nome, kind=kind)

    def api_obter(vault_id: str):
        _vault_ok(kind)
        from . import vault_store
        return vault_store.obter(vault_id, kind=kind)

    def api_atualizar(vault_id: str, payload: dict = Body(...)):
        _vault_ok(kind)
        from . import vault_store
        return vault_store.atualizar(
            vault_id, payload.get("blob", ""), payload.get("nome"), kind=kind
        )

    def api_excluir(vault_id: str):
        _vault_ok(kind)
        from . import vault_store
        vault_store.excluir(vault_id, kind=kind)
        return {"ok": True}

    def api_exportar(vault_id: str):
        _vault_ok(kind)
        from . import vault_store
        path, nome = vault_store.caminho_export(vault_id, kind=kind)
        return FileResponse(path, filename=nome, media_type="application/json")

    api_listar.__name__ = f"api_{prefix}_listar"
    api_criar.__name__ = f"api_{prefix}_criar"
    api_importar.__name__ = f"api_{prefix}_importar"
    api_obter.__name__ = f"api_{prefix}_obter"
    api_atualizar.__name__ = f"api_{prefix}_atualizar"
    api_excluir.__name__ = f"api_{prefix}_excluir"
    api_exportar.__name__ = f"api_{prefix}_exportar"

    app.get(f"/api/{prefix}")(api_listar)
    app.post(f"/api/{prefix}")(api_criar)
    app.post(f"/api/{prefix}/importar")(api_importar)
    app.get(f"/api/{prefix}/{{vault_id}}")(api_obter)
    app.put(f"/api/{prefix}/{{vault_id}}")(api_atualizar)
    app.delete(f"/api/{prefix}/{{vault_id}}")(api_excluir)
    app.get(f"/api/{prefix}/{{vault_id}}/exportar")(api_exportar)


_register_vault_api("cofre", "cofre")
_register_vault_api("fake", "fake")
_register_vault_api("totp", "totp")


def _modelo_permitido(modelo: str | None) -> str:
    ai = _ai()
    if not modelo:
        return ai.MODELO_PADRAO
    permitidos = {p["slug"] for p in ai.MODELOS_PRESET}
    if modelo not in permitidos:
        raise HTTPException(status_code=400, detail="Modelo nao permitido")
    return modelo


def _contexto_permitido(num_ctx) -> int:
    ai = _ai()
    try:
        valor = int(num_ctx) if num_ctx is not None else ai.CONTEXT_PADRAO
    except (TypeError, ValueError):
        return ai.CONTEXT_PADRAO
    if valor not in ai.CONTEXTOS_PERMITIDOS:
        raise HTTPException(status_code=400, detail="Context length invalido")
    return valor


@app.get("/api/ai/status")
async def api_ai_status(modelo: str | None = None):
    ai = _ai()
    alvo = ai.MODELO_PADRAO
    if modelo:
        try:
            alvo = _modelo_permitido(modelo)
        except HTTPException:
            alvo = ai.MODELO_PADRAO
    info = await ai.verificar_status(alvo)
    return {"ok": True, **info}


@app.post("/api/ai/pull")
async def api_ai_pull(payload: dict = Body(default_factory=dict)):
    ai = _ai()
    modelo = _modelo_permitido(payload.get("modelo"))
    return StreamingResponse(
        ai.stream_pull(modelo),
        media_type="application/x-ndjson",
    )


@app.post("/api/ai/delete")
async def api_ai_delete(payload: dict = Body(default_factory=dict)):
    ai = _ai()
    modelo = _modelo_permitido(payload.get("modelo"))
    resultado = await ai.deletar_modelo(modelo)
    status_code = 200 if resultado.get("ok") else 400
    return JSONResponse(status_code=status_code, content=resultado)


@app.post("/api/ai/instalar-ollama")
async def api_ai_instalar_ollama():
    ai = _ai()
    return StreamingResponse(
        ai.stream_install_ollama(),
        media_type="application/x-ndjson",
    )


@app.post("/api/ai/iniciar-ollama")
def api_ai_iniciar_ollama():
    ai = _ai()
    resultado = ai.iniciar_servico_ollama()
    status_code = 200 if resultado.get("ok") else 400
    return JSONResponse(status_code=status_code, content=resultado)


@app.post("/api/ai/descarregar")
async def api_ai_descarregar(payload: dict = Body(default_factory=dict)):
    """Descarrega modelo(s) da RAM do Ollama (sair do chat, Parar, Liberar mem.)."""
    ai = _ai()
    modelo = (payload.get("modelo") or "").strip()
    if modelo:
        return await ai.descarregar_modelo(modelo)
    return await ai.descarregar_todos()


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


@app.delete("/api/ai/chats/{chat_id}/mensagens/{mensagem_id}")
def api_ai_mensagens_truncar(chat_id: int, mensagem_id: int):
    """Remove a mensagem e todas as seguintes (pra editar/regerar)."""
    chat = db.obter_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat nao encontrado")
    apagadas = db.excluir_mensagens_a_partir(chat_id, mensagem_id)
    if not apagadas:
        raise HTTPException(status_code=404, detail="Mensagem nao encontrada")
    return {"ok": True, "apagadas": apagadas, "mensagens": db.listar_mensagens(chat_id)}


@app.post("/api/ai/chats/{chat_id}/mensagens")
async def api_ai_mensagem(chat_id: int, request: Request):
    ai = _ai()
    content_type = (request.headers.get("content-type") or "").lower()

    texto = ""
    modelo_raw = None
    ctx_raw = None
    arquivos_raw: list[tuple[str, bytes]] = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        texto = str(form.get("conteudo") or "").strip()
        modelo_raw = form.get("modelo")
        ctx_raw = form.get("num_ctx")
        uploads = form.getlist("arquivos")
        for up in uploads:
            if hasattr(up, "read") and getattr(up, "filename", None):
                arquivos_raw.append((up.filename, await up.read()))
    else:
        payload = await request.json()
        texto = (payload.get("conteudo") or "").strip()
        modelo_raw = payload.get("modelo")
        ctx_raw = payload.get("num_ctx")

    anexos_info: list[dict] = []
    if arquivos_raw:
        if len(arquivos_raw) > ai.MAX_ANEXOS:
            raise HTTPException(status_code=400, detail=f"Maximo de {ai.MAX_ANEXOS} anexos")
        for nome, dados in arquivos_raw:
            anexos_info.append(ai.extrair_texto_bytes(nome, dados))

    falhas = [a for a in anexos_info if not a.get("ok")]
    ok_anexos = [a for a in anexos_info if a.get("ok")]
    mensagem = ai.montar_mensagem_com_anexos(texto, ok_anexos)

    if not mensagem:
        if falhas:
            raise HTTPException(
                status_code=400,
                detail="; ".join(f"{f['nome']}: {f.get('msg', 'erro')}" for f in falhas),
            )
        raise HTTPException(status_code=400, detail="Mensagem vazia")

    modelo_ok = _modelo_permitido(modelo_raw)
    num_ctx_ok = _contexto_permitido(ctx_raw)

    chat = db.obter_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404)

    if ok_anexos and not texto:
        nomes = ", ".join(a["nome"] for a in ok_anexos)
        mensagem = f"(anexos: {nomes})\n\n{mensagem}"
    elif falhas:
        avisos = "\n".join(f"[anexo ignorado: {f['nome']} — {f.get('msg')}]" for f in falhas)
        mensagem = f"{mensagem}\n\n{avisos}"

    msg_user = db.adicionar_mensagem(chat_id, "user", mensagem)

    if chat["titulo"] == "Nova conversa":
        base = texto.strip().splitlines()[0] if texto.strip() else (
            ok_anexos[0]["nome"] if ok_anexos else mensagem.splitlines()[0]
        )
        novo_titulo = (base or "")[:60]
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
        cancelado = False
        try:
            async for chunk in ai.stream_chat(modelo_ok, historico, num_ctx=num_ctx_ok):
                if await request.is_disconnected():
                    cancelado = True
                    break
                if chunk.get("hub") and chunk.get("tipo") == "aviso":
                    yield (json.dumps({
                        "tipo": "aviso",
                        "msg": chunk.get("msg"),
                        "pedido": chunk.get("pedido"),
                        "usado": chunk.get("usado"),
                    }) + "\n").encode("utf-8")
                    continue
                if chunk.get("erro"):
                    # Se ja veio texto parcial, salva o que deu pra gerar
                    if chunk.get("parcial") and partes:
                        parcial = "".join(partes).strip()
                        if parcial:
                            db.adicionar_mensagem(chat_id, "assistant", parcial)
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
        except (asyncio.CancelledError, GeneratorExit):
            cancelado = True
            parcial = "".join(partes).strip()
            if parcial:
                try:
                    db.adicionar_mensagem(chat_id, "assistant", parcial)
                except Exception:
                    pass
            try:
                await ai.descarregar_modelo(modelo_ok)
            except Exception:
                pass
            raise

        if cancelado:
            parcial = "".join(partes).strip()
            if parcial:
                try:
                    db.adicionar_mensagem(chat_id, "assistant", parcial)
                except Exception:
                    pass
            try:
                await ai.descarregar_modelo(modelo_ok)
            except Exception:
                pass
            # Cliente ja pode ter ido embora — yield e best-effort
            try:
                yield (
                    json.dumps({"tipo": "parado", "msg": "Geracao interrompida pelo usuario."}) + "\n"
                ).encode("utf-8")
            except Exception:
                pass

    return StreamingResponse(gerar(), media_type="application/x-ndjson")


def _rede():
    mod = registry.modulo("rede_lookup")
    if mod is None:
        raise HTTPException(status_code=404, detail="DNS e Whois nao instalado. Abra a Loja.")
    return mod


def _lan_dm():
    if not config.IS_LAN:
        raise HTTPException(status_code=404, detail="Mensagem direta LAN so funciona em modo LAN")
    mod = registry.modulo("lan_dm")
    if mod is None:
        raise HTTPException(status_code=404, detail="Mensagem direta LAN nao instalada. Abra a Loja.")
    return mod


@app.get("/api/rede/meu-ip")
async def api_rede_meu_ip():
    rede = _rede()
    return rede.meu_ip_publico()


_REDE_KEYS = {
    "shodan": "shodan_api_key",
    "abuseipdb": "abuseipdb_api_key",
    "virustotal": "virustotal_api_key",
}


@app.get("/api/rede/keys")
def api_rede_keys_get():
    _rede()
    out = {}
    for slug, chave in _REDE_KEYS.items():
        val = db.obter_setting(chave)
        out[slug] = {"configurada": bool(val), "key": val}
    return {"ok": True, "keys": out}


@app.post("/api/rede/keys")
async def api_rede_keys_set(payload: dict = Body(...)):
    _rede()
    salvos = []
    for slug, chave in _REDE_KEYS.items():
        if slug in payload:
            db.salvar_setting(chave, str(payload.get(slug) or "").strip())
            salvos.append(slug)
    return {"ok": True, "salvos": salvos}


def _rede_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/rede/dns")
def api_rede_dns(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_dns, payload.get("alvo") or "", payload.get("tipos"))


@app.post("/api/rede/whois")
def api_rede_whois(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_whois, payload.get("alvo") or "")


@app.post("/api/rede/ip")
def api_rede_ip(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_ip, payload.get("alvo") or "")


@app.post("/api/rede/http")
def api_rede_http(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_http_tls, payload.get("alvo") or "")


@app.post("/api/rede/portas")
def api_rede_portas(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_portas, payload.get("alvo") or "")


@app.post("/api/rede/ping")
def api_rede_ping(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_ping, payload.get("alvo") or "")


@app.post("/api/rede/traceroute")
def api_rede_traceroute(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_traceroute, payload.get("alvo") or "")


@app.post("/api/rede/certificados")
def api_rede_certificados(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_certificados, payload.get("alvo") or "")


@app.post("/api/rede/rbl")
def api_rede_rbl(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_rbl, payload.get("alvo") or "")


@app.post("/api/rede/shodan")
def api_rede_shodan(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(
        rede.consultar_shodan,
        payload.get("alvo") or "",
        db.obter_setting("shodan_api_key"),
    )


@app.post("/api/rede/abuseipdb")
def api_rede_abuseipdb(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(
        rede.consultar_abuseipdb,
        payload.get("alvo") or "",
        db.obter_setting("abuseipdb_api_key"),
    )


@app.post("/api/rede/virustotal")
def api_rede_virustotal(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(
        rede.consultar_virustotal,
        payload.get("alvo") or "",
        db.obter_setting("virustotal_api_key"),
    )


@app.post("/api/rede/origem")
def api_rede_origem(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_origem, payload.get("alvo") or "")


@app.post("/api/rede/osint")
def api_rede_osint(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_osint, payload.get("alvo") or "")


def _exigir_lan_dm():
    lan = _lan_dm()
    if not config.IS_LAN:
        raise HTTPException(status_code=404, detail="Disponivel apenas em modo LAN")
    return lan


@app.get("/api/lan-dm/mensagens")
def api_lan_dm_mensagens(
    apelido: str,
    destinatario: str = "",
    desde_id: int = 0,
):
    lan = _exigir_lan_dm()
    apelido = lan.normalizar_apelido(apelido)
    if not lan.apelido_valido(apelido):
        raise HTTPException(status_code=400, detail="Apelido invalido")
    dest_db = lan.destino_db(destinatario)
    rows = db.listar_lan_mensagens(apelido, dest_db, desde_id=desde_id)
    return {
        "ok": True,
        "mensagens": [lan.mensagem_para_dict(r) for r in rows],
    }


@app.post("/api/lan-dm/mensagens")
async def api_lan_dm_enviar(
    apelido: str = Form(...),
    destinatario: str = Form(""),
    conteudo: str = Form(""),
    arquivo: UploadFile | None = File(None),
):
    lan = _exigir_lan_dm()
    apelido = lan.normalizar_apelido(apelido)
    if not lan.apelido_valido(apelido):
        raise HTTPException(status_code=400, detail="Apelido invalido")

    texto = (conteudo or "").strip()
    if len(texto) > lan.MAX_TEXTO:
        raise HTTPException(status_code=400, detail="Texto longo demais")

    dest_db = lan.destino_db(destinatario)
    if dest_db and not lan.apelido_valido(dest_db):
        raise HTTPException(status_code=400, detail="Destinatario invalido")
    if dest_db == apelido:
        raise HTTPException(status_code=400, detail="Nao envie mensagem para voce mesmo")

    arquivo_nome = None
    arquivo_path = None
    arquivo_bytes = 0
    if arquivo and arquivo.filename:
        dados = await arquivo.read()
        if dados:
            try:
                arquivo_path, arquivo_bytes = lan.salvar_arquivo(arquivo.filename, dados)
                arquivo_nome = Path(arquivo.filename).name
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

    if not texto and not arquivo_path:
        raise HTTPException(status_code=400, detail="Envie texto ou arquivo")

    row = db.criar_lan_mensagem(
        apelido,
        dest_db,
        texto,
        arquivo_nome,
        arquivo_path,
        arquivo_bytes,
    )
    msg = lan.mensagem_para_dict(row)
    await lan.hub.enviar_mensagem(msg)
    return {"ok": True, "mensagem": msg}


@app.get("/api/lan-dm/arquivos/{msg_id}")
def api_lan_dm_arquivo(msg_id: int):
    lan = _exigir_lan_dm()
    caminho = lan.caminho_arquivo(msg_id)
    if not caminho:
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado")
    row = db.obter_lan_mensagem(msg_id)
    nome = (row or {}).get("arquivo_nome") or caminho.name
    return FileResponse(caminho, filename=nome)


@app.websocket("/ws/lan-dm")
async def ws_lan_dm(websocket: WebSocket):
    if not config.IS_LAN or registry.modulo("lan_dm") is None:
        await websocket.close(code=4404)
        return
    if not auth.autenticado_ws(websocket):
        await websocket.close(code=4401)
        return

    from .tools import lan_dm as lan

    await websocket.accept()
    apelido = ""
    try:
        raw = await websocket.receive_text()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.close(code=4400)
            return
        if payload.get("tipo") != "join":
            await websocket.close(code=4400)
            return
        apelido = await lan.hub.connect(websocket, payload.get("apelido") or "")
        if not apelido:
            return

        await websocket.send_text(
            json.dumps({"tipo": "joined", "apelido": apelido, "online": lan.hub.online()})
        )

        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text(json.dumps({"tipo": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        await lan.hub.disconnect(websocket)
