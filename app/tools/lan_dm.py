"""Mensagens diretas na LAN — texto e arquivos entre PCs."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from .. import db

NOME = "Chat (LAN)"
MAX_ARQUIVO_BYTES = 25 * 1024 * 1024
MAX_TEXTO = 8000
MAX_APELIDO = 40
_APELIDO_RE = re.compile(r"^[\w .\-áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]{1,40}$", re.UNICODE)

STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage" / "lan-dm"
ARQUIVOS_DIR = STORAGE_DIR / "arquivos"


def normalizar_apelido(raw: str) -> str:
    return " ".join((raw or "").strip().split())[:MAX_APELIDO]


def apelido_valido(apelido: str) -> bool:
    return bool(apelido and _APELIDO_RE.match(apelido))


def canal_geral() -> str:
    return "__geral__"


def destino_db(destinatario: str | None) -> str | None:
    d = normalizar_apelido(destinatario or "")
    if not d or d == canal_geral():
        return None
    return d


def mensagem_para_dict(row: dict) -> dict[str, Any]:
    dest = row.get("destinatario")
    return {
        "id": row["id"],
        "remetente": row["remetente"],
        "destinatario": dest or canal_geral(),
        "conteudo": row.get("conteudo") or "",
        "arquivo_nome": row.get("arquivo_nome") or "",
        "arquivo_bytes": int(row.get("arquivo_bytes") or 0),
        "tem_arquivo": bool(row.get("arquivo_path")),
        "criado_em": row.get("criado_em") or "",
    }


def caminho_arquivo(msg_id: int) -> Path | None:
    row = db.obter_lan_mensagem(msg_id)
    if not row or not row.get("arquivo_path"):
        return None
    caminho = (ARQUIVOS_DIR / row["arquivo_path"]).resolve()
    root = ARQUIVOS_DIR.resolve()
    if caminho != root and root not in caminho.parents:
        return None
    return caminho if caminho.is_file() else None


def salvar_arquivo(nome: str, dados: bytes) -> tuple[str, int]:
    if len(dados) > MAX_ARQUIVO_BYTES:
        raise ValueError("Arquivo grande demais")
    ARQUIVOS_DIR.mkdir(parents=True, exist_ok=True)
    seguro = Path(nome or "arquivo").name
    if not seguro or seguro in (".", ".."):
        seguro = "arquivo"
    rel = f"{uuid.uuid4().hex[:12]}_{seguro}"
    destino = ARQUIVOS_DIR / rel
    destino.write_bytes(dados)
    return rel, len(dados)


class LanDmHub:
    """Presenca e push em tempo real via WebSocket."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._peers: dict[str, WebSocket] = {}
        self._ws_meta: dict[WebSocket, str] = {}

    def online(self) -> list[str]:
        return sorted(self._peers.keys())

    async def connect(self, ws: WebSocket, apelido: str) -> str | None:
        apelido = normalizar_apelido(apelido)
        if not apelido_valido(apelido):
            await ws.close(code=4400)
            return None
        async with self._lock:
            if apelido in self._peers:
                await ws.close(code=4409)
                return None
            self._peers[apelido] = ws
            self._ws_meta[ws] = apelido
        await self._broadcast_presence()
        return apelido

    async def disconnect(self, ws: WebSocket) -> None:
        apelido = None
        async with self._lock:
            apelido = self._ws_meta.pop(ws, None)
            if apelido:
                self._peers.pop(apelido, None)
        if apelido:
            await self._broadcast_presence()

    async def _broadcast_presence(self) -> None:
        payload = json.dumps({"tipo": "presence", "online": self.online()})
        mortos: list[WebSocket] = []
        for ws in list(self._ws_meta.keys()):
            try:
                await ws.send_text(payload)
            except Exception:
                mortos.append(ws)
        for ws in mortos:
            await self.disconnect(ws)

    async def enviar_mensagem(self, msg: dict[str, Any]) -> None:
        remetente = msg.get("remetente") or ""
        destinatario = msg.get("destinatario") or canal_geral()
        payload = json.dumps({"tipo": "mensagem", "msg": msg})
        alvos: set[WebSocket] = set()

        if destinatario == canal_geral():
            alvos.update(self._peers.values())
        else:
            ws = self._peers.get(remetente)
            if ws:
                alvos.add(ws)
            ws_dest = self._peers.get(destinatario)
            if ws_dest:
                alvos.add(ws_dest)

        mortos: list[WebSocket] = []
        for ws in alvos:
            try:
                await ws.send_text(payload)
            except Exception:
                mortos.append(ws)
        for ws in mortos:
            await self.disconnect(ws)


hub = LanDmHub()
