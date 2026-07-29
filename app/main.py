import json
import shutil
import time
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, registry, store
from .cleanup import (
    OUTPUTS_DIR,
    UPLOADS_DIR,
    escopo_de_slug,
    executar_limpeza,
    info_armazenamento,
    migrar_sessoes_legado,
)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Personal Hub", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    migrar_sessoes_legado()
    registry.rebuild()


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
def download(escopo: str, sessao_id: str, nome: str):
    if ".." in escopo or ".." in sessao_id or ".." in nome:
        raise HTTPException(status_code=400)
    caminho = OUTPUTS_DIR / escopo / sessao_id / nome
    if not caminho.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(caminho, filename=nome)


@app.get("/api/limpar-info")
def api_limpar_info():
    return {"ok": True, **info_armazenamento()}


@app.get("/api/limpar-info/{escopo}")
def api_limpar_info_escopo(escopo: str):
    return {"ok": True, "escopo": escopo, **info_armazenamento(escopo)}


@app.post("/api/limpar-agora")
def api_limpar_agora():
    resultado = executar_limpeza()
    return {"ok": True, **resultado}


@app.post("/api/limpar-agora/{escopo}")
def api_limpar_agora_escopo(escopo: str):
    resultado = executar_limpeza(escopo)
    return {"ok": True, "escopo": escopo, **resultado}


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


def _cofre_ok():
    if not registry.extra_instalado("cofre"):
        raise HTTPException(status_code=404, detail="Cofre nao instalado. Abra a Loja.")


@app.get("/api/cofre")
def api_cofre_listar():
    _cofre_ok()
    from . import vault_store
    return vault_store.listar()


@app.post("/api/cofre")
def api_cofre_criar(payload: dict = Body(...)):
    _cofre_ok()
    from . import vault_store
    return vault_store.criar(payload.get("nome", ""), payload.get("blob", ""))


@app.post("/api/cofre/importar")
async def api_cofre_importar(arquivo: UploadFile = File(...), nome: str = Form(None)):
    _cofre_ok()
    from . import vault_store
    return await vault_store.importar(arquivo, nome)


@app.get("/api/cofre/{vault_id}")
def api_cofre_obter(vault_id: str):
    _cofre_ok()
    from . import vault_store
    return vault_store.obter(vault_id)


@app.put("/api/cofre/{vault_id}")
def api_cofre_atualizar(vault_id: str, payload: dict = Body(...)):
    _cofre_ok()
    from . import vault_store
    return vault_store.atualizar(vault_id, payload.get("blob", ""), payload.get("nome"))


@app.delete("/api/cofre/{vault_id}")
def api_cofre_excluir(vault_id: str):
    _cofre_ok()
    from . import vault_store
    vault_store.excluir(vault_id)
    return {"ok": True}


@app.get("/api/cofre/{vault_id}/exportar")
def api_cofre_exportar(vault_id: str):
    _cofre_ok()
    from . import vault_store
    path, nome = vault_store.caminho_export(vault_id)
    return FileResponse(path, filename=nome, media_type="application/json")


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
async def api_ai_status():
    ai = _ai()
    info = await ai.verificar_status(ai.MODELO_PADRAO)
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
        async for chunk in ai.stream_chat(modelo_ok, historico, num_ctx=num_ctx_ok):
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

    return StreamingResponse(gerar(), media_type="application/x-ndjson")


def _rede():
    mod = registry.modulo("rede_lookup")
    if mod is None:
        raise HTTPException(status_code=404, detail="DNS e Whois nao instalado. Abra a Loja.")
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
async def api_rede_dns(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_dns, payload.get("alvo") or "", payload.get("tipos"))


@app.post("/api/rede/whois")
async def api_rede_whois(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_whois, payload.get("alvo") or "")


@app.post("/api/rede/ip")
async def api_rede_ip(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_ip, payload.get("alvo") or "")


@app.post("/api/rede/http")
async def api_rede_http(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_http_tls, payload.get("alvo") or "")


@app.post("/api/rede/portas")
async def api_rede_portas(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_portas, payload.get("alvo") or "")


@app.post("/api/rede/ping")
async def api_rede_ping(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_ping, payload.get("alvo") or "")


@app.post("/api/rede/traceroute")
async def api_rede_traceroute(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_traceroute, payload.get("alvo") or "")


@app.post("/api/rede/certificados")
async def api_rede_certificados(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_certificados, payload.get("alvo") or "")


@app.post("/api/rede/rbl")
async def api_rede_rbl(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(rede.consultar_rbl, payload.get("alvo") or "")


@app.post("/api/rede/shodan")
async def api_rede_shodan(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(
        rede.consultar_shodan,
        payload.get("alvo") or "",
        db.obter_setting("shodan_api_key"),
    )


@app.post("/api/rede/abuseipdb")
async def api_rede_abuseipdb(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(
        rede.consultar_abuseipdb,
        payload.get("alvo") or "",
        db.obter_setting("abuseipdb_api_key"),
    )


@app.post("/api/rede/virustotal")
async def api_rede_virustotal(payload: dict = Body(...)):
    rede = _rede()
    return _rede_call(
        rede.consultar_virustotal,
        payload.get("alvo") or "",
        db.obter_setting("virustotal_api_key"),
    )
