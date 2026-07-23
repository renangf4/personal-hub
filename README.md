# Personal Hub

Hub privado e local com utilitarios pessoais, acessivel apenas pelo navegador em `http://localhost:7777`. Nao expoe rede, nao usa Docker, nao usa WSL.

## Ferramentas

- Converter video para MP4 (H.264)
- Converter video para WebM (VP9)
- Converter imagem para WebP (com largura ajustavel)
- Desbloquear PDF (com gerenciador de senhas em SQLite)
- Screenshot WordPress (padroniza em 1200x900 PNG otimizado)
- Assistente de IA Local (chat com Ollama — carteiras por foco)

## Requisitos

- Windows, Linux ou macOS
- Python 3.10+ no PATH
- [Ollama](https://ollama.com) (opcional; necessario apenas para o Assistente de IA)

## Como usar

### Windows — duplo clique

1. Execute `start.bat` (primeira execucao cria o `venv` e instala dependencias).
2. O navegador abre automaticamente em `http://localhost:7777`.
3. Pra fechar, feche o terminal.

### Windows — PowerShell

```powershell
cd caminho\para\personal-hub

# Primeira vez: criar venv e instalar dependencias
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# Iniciar
Start-Process http://localhost:7777
python -m uvicorn app.main:app --host 127.0.0.1 --port 7777 --reload
```

Se a ativacao do venv falhar por politica de execucao:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Ou use o script direto (equivalente ao duplo clique):

```powershell
.\start.bat
```

### Windows — CMD

```cmd
cd caminho\para\personal-hub

REM Primeira vez: criar venv e instalar dependencias
python -m venv venv
venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

REM Iniciar
start http://localhost:7777
python -m uvicorn app.main:app --host 127.0.0.1 --port 7777 --reload
```

Ou simplesmente:

```cmd
start.bat
```

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

Primeira execucao cria o `venv` e instala dependencias. Acesse `http://localhost:7777`.

## Caracteristicas

- **Porta 7777** (nao conflita com Apache/XAMPP, MySQL, Docker padrao).
- **Botao "Limpar cache"** no topo remove manualmente todos os arquivos em `storage/uploads/` e `storage/outputs/`, exibindo antes quantos arquivos e quanto espaco sera liberado.
- **SQLite local** em `storage/hub.db` guarda senhas do desbloqueio de PDF e dados do chat de IA.
- **FFmpeg embutido** via `imageio-ffmpeg` (nao precisa instalar separadamente).
- **Ollama** em `localhost:11434` para o Assistente de IA (instalacao/modelos pela propria UI).

## Estrutura

```
personal-hub/
  app/
    main.py            FastAPI + rotas
    db.py              SQLite
    cleanup.py         Limpeza D+1
    tools/             Logica de cada ferramenta
  templates/           Jinja2 + Bootstrap
  static/              CSS e JS
  storage/
    uploads/           Arquivos enviados (limpos via botao)
    outputs/           Arquivos gerados (limpos via botao)
    hub.db             SQLite
  requirements.txt
  start.bat
  start.sh
```

## Observacoes

- Conversoes de video sao sincronas: a request espera o ffmpeg terminar. Arquivos muito grandes podem demorar.
- Toda a comunicacao e `127.0.0.1`; nada e exposto na rede.
- O Assistente de IA exige Ollama rodando localmente; a UI ajuda a instalar e baixar modelos.
