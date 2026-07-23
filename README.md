# Personal Hub

Hub privado e local com utilitarios pessoais, acessivel apenas pelo navegador em `http://localhost:7777`. Nao expoe rede, nao usa Docker, nao usa WSL.

## Ferramentas

Instale sob demanda pela **Loja** (`/loja`):

- **Video** — MP4, WebM, GIF, MKV, MOV (FFmpeg embutido)
- **Imagem** — WebP, PNG, JPEG, GIF, BMP, TIFF
- **Screenshot WordPress** — padroniza em 1200x900 PNG
- **Desbloquear PDF** — senhas salvas, senha unica, wordlist ou PIN numerico
- **Assistente de IA Local** — chat com Ollama; anexos de arquivo/PDF; carteiras por foco
- **DNS e Whois** — DNS, Whois, IP/geo e Shodan (API key opcional)

## Requisitos

- Windows, Linux ou macOS
- Python 3.10+ no PATH
- [Ollama](https://ollama.com) (opcional; so para o Assistente de IA)
- Conta [Shodan](https://account.shodan.io/) (opcional; so se for usar a consulta Shodan)

## Como usar

### Windows

Duplo clique em `start.bat`, ou no terminal:

```powershell
cd caminho\para\personal-hub
.\start.bat
```

1. A primeira execucao cria o `venv` e instala o nucleo.
2. O navegador abre em `http://localhost:7777`.
3. Abra **Loja** e instale as ferramentas que quiser.
4. Pra fechar, feche o terminal.

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

## Caracteristicas

- **Porta 7777** (nao conflita com Apache/XAMPP, MySQL, Docker padrao).
- **Loja** instala e remove pacotes opcionais sem sujar a raiz do projeto.
- **Limpeza por ferramenta** e botao global de limpar em `storage/`.
- **SQLite local** em `storage/hub.db` (senhas PDF, chats IA, settings como key Shodan).
- **FFmpeg embutido** via `imageio-ffmpeg` (extra Video).
- **Ollama** em `localhost:11434` para o Assistente de IA.
- Home com ordem arrastavel das ferramentas.

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
  .cursor/rules/       Regras do Cursor no projeto
  requirements.txt     Nucleo (sempre)
  start.bat
  start.sh
```

## Observacoes

- Conversoes de video sao sincronas: a request espera o ffmpeg terminar.
- Toda a comunicacao e `127.0.0.1`; nada e exposto na rede.
- O Assistente de IA exige Ollama rodando localmente; a UI ajuda a instalar e baixar modelos.
- Consultas de rede (Whois/geo/Shodan) usam seu IP publico — a tela avisa qual IP esta saindo.
