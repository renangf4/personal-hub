@echo off
setlocal EnableExtensions

cd /d "%~dp0"

REM Arg: start.bat [local|lan] [senha]
REM PowerShell: $env:HUB_PASSWORD="sua-senha"; .\start.bat lan
REM            ou: .\start.bat lan sua-senha
set "ARG_MODE=%~1"
set "ARG_PASS=%~2"
if /I "%ARG_MODE%"=="lan" set "HUB_MODE=lan"
if /I "%ARG_MODE%"=="rede" set "HUB_MODE=lan"
if /I "%ARG_MODE%"=="local" set "HUB_MODE=local"
if not defined HUB_MODE set "HUB_MODE=local"

if defined ARG_PASS if not defined HUB_PASSWORD set "HUB_PASSWORD=%ARG_PASS%"

if not defined HUB_PORT set "HUB_PORT=7777"

if /I "%HUB_MODE%"=="lan" (
    if not defined HUB_PASSWORD (
        echo.
        echo Modo LAN exige senha compartilhada.
        echo   PowerShell:  $env:HUB_PASSWORD="sua-senha"
        echo                .\start.bat lan
        echo   ou:          .\start.bat lan sua-senha
        echo   CMD:         set HUB_PASSWORD=sua-senha ^& start.bat lan
        echo.
        pause
        exit /b 1
    )
    set "HUB_BIND=0.0.0.0"
) else (
    set "HUB_MODE=local"
    set "HUB_BIND=127.0.0.1"
)

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
    echo Nucleo pronto. Instale ferramentas em http://localhost:%HUB_PORT%/loja
) else (
    call venv\Scripts\activate.bat
)

echo.
python -c "from app import config; config.print_banner()"
echo.

if /I "%HUB_MODE%"=="local" (
    start "" "http://localhost:%HUB_PORT%"
)

python -m uvicorn app.main:app --host %HUB_BIND% --port %HUB_PORT% --reload

endlocal
