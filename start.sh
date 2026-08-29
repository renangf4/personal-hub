#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Arg: ./start.sh [local|lan] [senha]
#   export HUB_PASSWORD=sua-senha && ./start.sh lan
#   ou: ./start.sh lan sua-senha
ARG_MODE="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
ARG_PASS="${2:-}"
case "$ARG_MODE" in
    lan|rede) export HUB_MODE=lan ;;
    local) export HUB_MODE=local ;;
esac
export HUB_MODE="${HUB_MODE:-local}"
export HUB_PORT="${HUB_PORT:-7777}"

if [ -n "$ARG_PASS" ] && [ -z "${HUB_PASSWORD:-}" ]; then
    export HUB_PASSWORD="$ARG_PASS"
fi

if [ "$HUB_MODE" = "lan" ]; then
    if [ -z "${HUB_PASSWORD:-}" ]; then
        echo
        echo "Modo LAN exige senha compartilhada."
        echo "  export HUB_PASSWORD=sua-senha"
        echo "  ./start.sh lan"
        echo "  ou: ./start.sh lan sua-senha"
        echo
        exit 1
    fi
    HUB_BIND="0.0.0.0"
    if [ "$(uname -s)" = "Linux" ]; then
        echo
        echo "Linux + LAN: outros dispositivos precisam alcançar a porta ${HUB_PORT}."
        echo "  Se o firewall bloquear: sudo ufw allow ${HUB_PORT}/tcp"
        echo
    fi
else
    HUB_MODE=local
    export HUB_MODE
    HUB_BIND="127.0.0.1"
fi

if [ ! -f "venv/bin/activate" ]; then
    if [ -d "venv" ]; then
        echo "venv incompatível (ex.: criado no Windows). Recriando..."
        rm -rf venv
    else
        echo "Criando ambiente virtual..."
    fi
    if command -v python3 >/dev/null 2>&1; then
        if ! python3 -m venv venv; then
            echo
            echo "Nao foi possivel criar o venv."
            if [ "$(uname -s)" = "Linux" ] && command -v apt >/dev/null 2>&1; then
                pyver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
                echo "No Ubuntu/Debian instale o modulo venv, por exemplo:"
                if [ -n "$pyver" ]; then
                    echo "  sudo apt install python${pyver}-venv"
                else
                    echo "  sudo apt install python3-venv"
                fi
            else
                echo "Instale o Python 3 com suporte a venv (modulo ensurepip)."
            fi
            echo
            exit 1
        fi
    elif command -v python >/dev/null 2>&1; then
        if ! python -m venv venv; then
            echo "Nao foi possivel criar o venv. Verifique se o Python 3 inclui o modulo venv."
            exit 1
        fi
    else
        echo "Python 3 nao encontrado no PATH."
        exit 1
    fi
    # shellcheck disable=SC1091
    source venv/bin/activate
    echo "Instalando nucleo..."
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    echo
    echo "Nucleo pronto. Instale ferramentas em http://localhost:${HUB_PORT}/loja"
else
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

echo
python -c "from app import config; config.print_banner()"
echo

if [ "$HUB_MODE" = "local" ] && [ "${HUB_OPEN_BROWSER:-1}" != "0" ]; then
    URL="http://localhost:${HUB_PORT}"
    if command -v xdg-open >/dev/null 2>&1; then
        (sleep 1 && xdg-open "$URL") &
    elif command -v open >/dev/null 2>&1; then
        (sleep 1 && open "$URL") &
    elif command -v explorer.exe >/dev/null 2>&1; then
        (sleep 1 && explorer.exe "$URL") &
    elif [ -x /mnt/c/Windows/System32/cmd.exe ]; then
        (sleep 1 && /mnt/c/Windows/System32/cmd.exe /c start "" "$URL") &
    fi
fi

python -m uvicorn app.main:app --host "$HUB_BIND" --port "$HUB_PORT" --reload
