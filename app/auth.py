"""Portao de senha compartilhada (modo LAN)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Request, WebSocket
from fastapi.responses import RedirectResponse, Response

from . import config

COOKIE_NAME = "hub_session"
_SESSION_SECRET = secrets.token_bytes(32)


def _session_token() -> str:
    material = (config.PASSWORD or "").encode("utf-8")
    return hmac.new(_SESSION_SECRET, b"hub-session-v1:" + material, hashlib.sha256).hexdigest()


def senha_ok(senha: str) -> bool:
    esperado = config.PASSWORD or ""
    if not esperado:
        return False
    return hmac.compare_digest(senha.encode("utf-8"), esperado.encode("utf-8"))


def autenticado(request: Request) -> bool:
    if not config.AUTH_REQUIRED:
        return True
    token = request.cookies.get(COOKIE_NAME) or ""
    if not token:
        return False
    return hmac.compare_digest(token, _session_token())


def autenticado_ws(websocket: WebSocket) -> bool:
    if not config.AUTH_REQUIRED:
        return True
    token = websocket.cookies.get(COOKIE_NAME) or ""
    if not token:
        return False
    return hmac.compare_digest(token, _session_token())


def gravar_sessao(response: Response) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=_session_token(),
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
        max_age=60 * 60 * 24 * 14,  # 14 dias
    )


def limpar_sessao(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def path_livre(path: str) -> bool:
    if path == "/login" or path.startswith("/login?"):
        return True
    if path.startswith("/static/"):
        return True
    if path in ("/favicon.ico", "/static/favicon.svg"):
        return True
    return False


def precisa_auth(request: Request) -> bool:
    return config.AUTH_REQUIRED and not autenticado(request)


def resposta_nao_autenticado(request: Request) -> Response:
    accept = request.headers.get("accept") or ""
    path = request.url.path
    if path.startswith("/api/") or "application/json" in accept:
        return Response(
            content='{"detail":"Nao autenticado"}',
            status_code=401,
            media_type="application/json",
        )
    nxt = path
    if request.url.query:
        nxt = f"{path}?{request.url.query}"
    return RedirectResponse(url=f"/login?next={nxt}", status_code=303)
