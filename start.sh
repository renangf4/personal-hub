#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Criando ambiente virtual..."
    python3 -m venv venv
    # shellcheck disable=SC1091
    source venv/bin/activate
    echo "Instalando nucleo..."
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    echo
    echo "Nucleo pronto. Instale ferramentas em http://localhost:7777/loja"
else
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

echo
echo "===================================="
echo " Personal Hub iniciando em :7777"
echo " Abra: http://localhost:7777"
echo "===================================="
echo

URL="http://localhost:7777"
if command -v xdg-open >/dev/null 2>&1; then
    (sleep 1 && xdg-open "$URL") &
elif command -v open >/dev/null 2>&1; then
    (sleep 1 && open "$URL") &
fi

python -m uvicorn app.main:app --host 127.0.0.1 --port 7777 --reload
