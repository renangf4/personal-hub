"""Configuracao de bind e modo (local | lan) via env."""

from __future__ import annotations

import os
import socket
import sys


def _mode() -> str:
    raw = (os.environ.get("HUB_MODE") or "local").strip().lower()
    if raw in ("lan", "rede", "network"):
        return "lan"
    return "local"


def _port() -> int:
    raw = (os.environ.get("HUB_PORT") or "7777").strip()
    try:
        valor = int(raw)
    except ValueError:
        return 7777
    if 1 <= valor <= 65535:
        return valor
    return 7777


def _password() -> str:
    return os.environ.get("HUB_PASSWORD") or ""


MODE = _mode()
PORT = _port()
PASSWORD = _password()
IS_LAN = MODE == "lan"
AUTH_REQUIRED = IS_LAN

# Override fino; senao local=127.0.0.1, lan=0.0.0.0
_host_env = (os.environ.get("HUB_HOST") or "").strip()
if _host_env:
    BIND_HOST = _host_env
elif IS_LAN:
    BIND_HOST = "0.0.0.0"
else:
    BIND_HOST = "127.0.0.1"

BIND_LABEL = f"LAN :{PORT}" if IS_LAN else f"127.0.0.1:{PORT}"


def validate_or_raise() -> None:
    """LAN exige senha — aborta startup se faltar."""
    if IS_LAN and not PASSWORD:
        raise RuntimeError(
            "Modo LAN exige HUB_PASSWORD. Ex.: set HUB_PASSWORD=sua-senha && start.bat lan"
        )


def listar_ips_lan() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127."):
                continue
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass

    # Fallback: UDP "connect" pra descobrir interface de saida
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.insert(0, ip)
    except OSError:
        pass
    return ips


def urls_acesso() -> list[str]:
    if not IS_LAN:
        return [f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"]
    urls = [f"http://127.0.0.1:{PORT}"]
    for ip in listar_ips_lan():
        urls.append(f"http://{ip}:{PORT}")
    return urls


def print_banner() -> None:
    print("====================================")
    if IS_LAN:
        print(f" Personal Hub — modo LAN :{PORT}")
        print(" Acesso (mesma rede):")
        for url in urls_acesso():
            print(f"   {url}")
        print(" Senha: HUB_PASSWORD (obrigatoria)")
        print(" Nao exponha na internet.")
        if sys.platform == "linux":
            print(f" Firewall: se nao conectar da rede, rode:")
            print(f"   sudo ufw allow {PORT}/tcp")
    else:
        print(f" Personal Hub — modo local :{PORT}")
        print(f" Abra: http://localhost:{PORT}")
    print("====================================")
