# Personal Hub

Hub privado e local com utilitarios pessoais, acessivel apenas pelo navegador em `http://localhost:7777`. Nao expoe rede, nao usa Docker, nao usa WSL.

## Ferramentas

Instale sob demanda pela **Loja** (`/loja`):

- Video — MP4 (H.264) e WebM (VP9)
- Imagem — WebP e Screenshot WordPress
- Desbloquear PDF — senhas em SQLite
- Assistente de IA Local — chat com Ollama

## Requisitos

- Windows, Linux ou macOS
- Python 3.10+ no PATH
- [Ollama](https://ollama.com) (opcional; necessario apenas para o Assistente de IA)

## Como usar

### Windows — duplo clique

1. Execute `start.bat` (primeira execucao cria o `venv` e instala o nucleo).
2. O navegador abre em `http://localhost:7777`.
3. Abra **Loja** e instale as ferramentas que quiser.
4. Pra fechar, feche o terminal.

### Windows — PowerShell

```powershell
cd caminho\para\personal-hub

python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

Start-Process http://localhost:7777
python -m uvicorn app.main:app --host 127.0.0.1 --port 7777 --reload
```

Se a ativacao do venv falhar por politica de execucao:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Ou use:

```powershell
.\start.bat
```

### Windows — CMD

```cmd
cd caminho\para\personal-hub
start.bat
```

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

## Caracteristicas

- **Porta 7777** (nao conflita com Apache/XAMPP, MySQL, Docker padrao).
- **Loja** instala e remove pacotes opcionais sem sujar a raiz do projeto.
- **Botao "Limpar Lixo"** remove arquivos em `storage/uploads/` e `storage/outputs/`.
- **SQLite local** em `storage/hub.db` (senhas PDF e chat de IA).
- **FFmpeg embutido** via `imageio-ffmpeg` (quando o extra Video estiver instalado).
- **Ollama** em `localhost:11434` para o Assistente de IA.

## Estrutura

```
personal-hub/
  app/
    main.py            FastAPI + rotas
    extras.py          Catalogo da Loja
    registry.py        Ferramentas ativas
    store.py           Instalar / desinstalar
    db.py              SQLite
    cleanup.py         Limpeza
    tools/             Logica de cada ferramenta
  templates/           Jinja2 + Bootstrap
  static/              CSS e JS
  storage/
  requirements.txt     Nucleo (sempre)
  start.bat
  start.sh
```

## Observacoes

- Conversoes de video sao sincronas: a request espera o ffmpeg terminar.
- Toda a comunicacao e `127.0.0.1`; nada e exposto na rede.
- O Assistente de IA exige Ollama rodando localmente; a UI ajuda a instalar e baixar modelos.
