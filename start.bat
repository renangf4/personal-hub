@echo off
setlocal EnableExtensions

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

REM Pasta no filesystem do WSL (qualquer distro), sem venv Windows:
REM usa start.sh. Se o WSL falhar, cai no Python do Windows abaixo.
call :try_wsl_fs
set "WSL_ERR=%ERRORLEVEL%"
if not defined WSL_RAN goto :win_start
endlocal & exit /b %WSL_ERR%

:win_start

REM Qualquer pasta Windows: disco local, UNC de rede, \\wsl.localhost\...
REM CMD nao usa UNC como cwd; pushd mapeia uma letra de drive.
pushd "%~dp0" 2>nul
if errorlevel 1 goto :dir_fail

set "PY=python"
python -c "import sys" 2>nul
if errorlevel 1 (
    py -3 -c "import sys" 2>nul
    if errorlevel 1 (
        echo Python 3 nao encontrado no PATH.
        pause
        exit /b 1
    )
    set "PY=py -3"
)

if not exist "venv\Scripts\activate.bat" (
    if exist "venv\" (
        echo venv incompativel ^(ex.: criado no Linux/WSL^). Recriando...
        rmdir /s /q venv
    ) else (
        echo Criando ambiente virtual...
    )
    %PY% -m venv venv
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

popd
endlocal
exit /b 0

:try_wsl_fs
echo %~dp0 | findstr /I /C:"wsl.localhost" /C:"wsl$" >nul
if errorlevel 1 goto :eof
where wsl.exe >nul 2>&1
if errorlevel 1 goto :eof
if exist "%~dp0venv\Scripts\activate.bat" goto :eof

set "RAW=%~dp0"
if "%RAW:~-1%"=="\" set "RAW=%RAW:~0,-1%"
set "RAW=%RAW:\\wsl.localhost\=%"
set "RAW=%RAW:\\WSL.LOCALHOST\=%"
set "RAW=%RAW:\\wsl$\=%"
set "RAW=%RAW:\\WSL$\=%"
for /f "tokens=1* delims=\" %%A in ("%RAW%") do (
    set "DISTRO=%%A"
    set "REST=%%B"
)
if not defined DISTRO goto :eof
if not defined REST goto :eof
set "LINUX=/%REST:\=/%"

wsl.exe -d %DISTRO% --cd "%LINUX%" -- bash -lc "exit 0" >nul 2>&1
if errorlevel 1 goto :eof

if /I "%HUB_MODE%"=="local" (
    start "" "http://localhost:%HUB_PORT%"
)

set "HUB_OPEN_BROWSER=0"
set "WSLENV=HUB_MODE:HUB_PORT:HUB_PASSWORD:HUB_OPEN_BROWSER"
echo.
echo Iniciando via WSL ^(%DISTRO%^)...
echo.
set "WSL_RAN=1"
wsl.exe -d %DISTRO% --cd "%LINUX%" -- bash ./start.sh
exit /b %ERRORLEVEL%

:dir_fail
echo.
echo Nao foi possivel entrar na pasta do projeto.
echo.
pause
exit /b 1
