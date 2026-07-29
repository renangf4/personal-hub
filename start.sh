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
else
    HUB_MODE=local
    export HUB_MODE
    HUB_BIND="127.0.0.1"
fi

if [ ! -d "venv" ]; then
    echo "Criando ambiente virtual..."
    python3 -m venv venv
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

if [ "$HUB_MODE" = "local" ]; then
    URL="http://localhost:${HUB_PORT}"
    if command -v xdg-open >/dev/null 2>&1; then
        (sleep 1 && xdg-open "$URL") &
    elif command -v open >/dev/null 2>&1; then
        (sleep 1 && open "$URL") &
    fi
fi

python -m uvicorn app.main:app --host "$HUB_BIND" --port "$HUB_PORT" --reload
