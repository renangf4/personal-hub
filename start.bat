@echo off
setlocal

cd /d "%~dp0"

if not exist "venv\" (
    echo Criando ambiente virtual...
    python -m venv venv
    if errorlevel 1 (
        echo Erro ao criar venv. Verifique se o Python esta instalado.
        pause
        exit /b 1
    )

    echo Instalando nucleo...
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    echo.
    echo Nucleo pronto. Instale ferramentas em http://localhost:7777/loja
) else (
    call venv\Scripts\activate.bat
)

echo.
echo ====================================
echo  Personal Hub iniciando em :7777
echo  Abra: http://localhost:7777
echo ====================================
echo.

start "" http://localhost:7777
python -m uvicorn app.main:app --host 127.0.0.1 --port 7777 --reload

endlocal
