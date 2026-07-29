"""Persistencia de arquivos criptografados: apenas ciphertext opaco. A senha nunca chega aqui."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile

STORAGE = Path(__file__).resolve().parent.parent / "storage"

# Cada kind = pasta + extensao + rotulo (mensagens de erro)
KINDS: dict[str, dict] = {
    "cofre": {
        "dir": STORAGE / "vaults",
        "ext": "hubvault",
        "label": "Cofre",
    },
    "fake": {
        "dir": STORAGE / "fake-profiles",
        "ext": "hubfake",
        "label": "Colecao de perfis",
    },
    "totp": {
        "dir": STORAGE / "totp-vaults",
        "ext": "hubtotp",
        "label": "Authenticator",
    },
}

_ID_RE = re.compile(r"^[a-f0-9]{8,32}$", re.I)
_NOME_MAX = 80
_BLOB_MAX = 8 * 1024 * 1024  # 8 MB


def _kind(kind: str) -> dict:
    cfg = KINDS.get(kind)
    if not cfg:
        raise HTTPException(status_code=400, detail="Tipo de vault invalido")
    return cfg


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def garantir_pasta(kind: str = "cofre") -> Path:
    pasta = _kind(kind)["dir"]
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _path(vault_id: str, kind: str = "cofre") -> Path:
    if not _ID_RE.match(vault_id or ""):
        raise HTTPException(status_code=400, detail="ID invalido")
    cfg = _kind(kind)
    return garantir_pasta(kind) / f"{vault_id}.{cfg['ext']}"


def _ler_meta(path: Path, kind: str = "cofre") -> dict:
    label = _kind(kind)["label"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Arquivo de {label.lower()} invalido") from exc
    if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("blob"), str):
        raise HTTPException(status_code=400, detail=f"Formato de {label.lower()} invalido")
    return data


def _validar_nome(nome: str) -> str:
    nome = (nome or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Informe um nome")
    if len(nome) > _NOME_MAX:
        raise HTTPException(status_code=400, detail="Nome muito longo")
    return nome


def _validar_blob(blob: str) -> str:
    blob = (blob or "").strip()
    if not blob:
        raise HTTPException(status_code=400, detail="Blob vazio")
    if len(blob.encode("utf-8")) > _BLOB_MAX:
        raise HTTPException(status_code=400, detail="Arquivo muito grande")
    # So base64 / ASCII — nunca plaintext JSON de entradas
    if any(c.isspace() for c in blob):
        blob = "".join(blob.split())
    try:
        import base64
        base64.b64decode(blob, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Blob nao e base64 valido") from exc
    return blob


def listar(kind: str = "cofre") -> list[dict]:
    cfg = _kind(kind)
    pasta = garantir_pasta(kind)
    itens: list[dict] = []
    for path in sorted(pasta.glob(f"*.{cfg['ext']}"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = _ler_meta(path, kind)
            st = path.stat()
            itens.append({
                "id": path.stem,
                "nome": meta.get("nome") or path.stem,
                "bytes": st.st_size,
                "atualizado": meta.get("atualizado") or datetime.fromtimestamp(
                    st.st_mtime, timezone.utc
                ).replace(microsecond=0).isoformat(),
            })
        except HTTPException:
            continue
    return itens


def obter(vault_id: str, kind: str = "cofre") -> dict:
    path = _path(vault_id, kind)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{_kind(kind)['label']} nao encontrado")
    meta = _ler_meta(path, kind)
    return {
        "id": vault_id,
        "nome": meta.get("nome") or vault_id,
        "blob": meta["blob"],
        "atualizado": meta.get("atualizado"),
    }


def criar(nome: str, blob: str, kind: str = "cofre") -> dict:
    nome = _validar_nome(nome)
    blob = _validar_blob(blob)
    vault_id = uuid.uuid4().hex[:16]
    path = _path(vault_id, kind)
    payload = {"v": 1, "nome": nome, "atualizado": _agora(), "blob": blob}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"id": vault_id, "nome": nome, "atualizado": payload["atualizado"]}


def atualizar(vault_id: str, blob: str, nome: str | None = None, kind: str = "cofre") -> dict:
    path = _path(vault_id, kind)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{_kind(kind)['label']} nao encontrado")
    meta = _ler_meta(path, kind)
    meta["blob"] = _validar_blob(blob)
    if nome is not None:
        meta["nome"] = _validar_nome(nome)
    meta["atualizado"] = _agora()
    path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {"id": vault_id, "nome": meta["nome"], "atualizado": meta["atualizado"]}


def excluir(vault_id: str, kind: str = "cofre") -> None:
    path = _path(vault_id, kind)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{_kind(kind)['label']} nao encontrado")
    path.unlink(missing_ok=True)


def caminho_export(vault_id: str, kind: str = "cofre") -> tuple[Path, str]:
    cfg = _kind(kind)
    path = _path(vault_id, kind)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{cfg['label']} nao encontrado")
    meta = _ler_meta(path, kind)
    safe = re.sub(r"[^\w\-]+", "_", (meta.get("nome") or vault_id).strip())[:60] or vault_id
    return path, f"{safe}.{cfg['ext']}"


async def importar(arquivo: UploadFile, nome: str | None = None, kind: str = "cofre") -> dict:
    label = _kind(kind)["label"]
    raw = await arquivo.read()
    if len(raw) > _BLOB_MAX:
        raise HTTPException(status_code=400, detail="Arquivo muito grande")
    try:
        text = raw.decode("utf-8")
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Arquivo invalido") from exc
    if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("blob"), str):
        raise HTTPException(status_code=400, detail=f"Formato de {label.lower()} invalido")
    display = nome or data.get("nome") or (arquivo.filename or "Importado").rsplit(".", 1)[0]
    return criar(str(display), data["blob"], kind=kind)


def info_bytes(kind: str = "cofre") -> dict:
    cfg = _kind(kind)
    pasta = garantir_pasta(kind)
    arquivos = 0
    total = 0
    for path in pasta.glob(f"*.{cfg['ext']}"):
        if not path.is_file():
            continue
        try:
            total += path.stat().st_size
            arquivos += 1
        except OSError:
            continue
    return {"arquivos": arquivos, "bytes": total}


def limpar_todos(kind: str = "cofre") -> dict:
    cfg = _kind(kind)
    pasta = garantir_pasta(kind)
    removidos = 0
    liberados = 0
    for path in list(pasta.glob(f"*.{cfg['ext']}")):
        try:
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            removidos += 1
            liberados += size
        except OSError:
            continue
    return {"arquivos": removidos, "bytes": liberados}
