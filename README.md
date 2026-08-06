# Personal Hub

Hub privado com utilitarios pessoais no navegador (`http://localhost:7777`). Sem Docker/WSL. Por padrao so escuta na propria maquina; opcionalmente sobe em modo LAN (Wi-Fi de casa) com senha.

## Ferramentas

Instale sob demanda pela **Loja** (`/loja`):

- **Video** — MP4, WebM, GIF, MKV, MOV (FFmpeg embutido); qualidade padrao 90%; estimativa automatica; resultados em card com preview
- **Imagem** — WebP, PNG, JPEG, GIF, BMP, TIFF; qualidade padrao 90%; estimativa automatica; resultados em card com preview
- **Screenshot WordPress** — padroniza em 1200x900 PNG comprimido; qualidade padrao 50%; estimativa de tamanho
- **Desbloquear PDF** — senhas salvas, senha unica, wordlist ou PIN numerico
- **Assistente de IA Local** — chat com Ollama em tela cheia; anexos; carteiras por foco; contexto sugerido pela RAM livre (com folga pra nao travar o PC)
- **DNS e Whois** — DNS (incl. SPF/DMARC/CAA), Whois, IP/geo, HTTP/TLS, portas, ping/traceroute, crt.sh, RBL, Shodan / AbuseIPDB / VirusTotal (keys opcionais)
- **Criptografar / Descriptografar** — AES-256-GCM no navegador (compativel com [gcm-encrypt-decrypt](https://github.com/renangf4/gcm-encrypt-decrypt))
- **Cofre de senhas** — arquivo `.hubvault` criptografado no navegador; importar / exportar / excluir; senha-mestra nunca gravada
- **Dados fake** — gera perfis editaveis (nome, e-mail, CPF...); colecao `.hubfake` criptografada; importar / exportar
- **Authenticator 2FA** — codigos TOTP locais; vault `.hubtotp` criptografado pra backup em pendrive

## Requisitos

- Windows, Linux ou macOS
- Python 3.10+ no PATH
- [Ollama](https://ollama.com) (opcional; so para o Assistente de IA)
- Conta [Shodan](https://account.shodan.io/) (opcional; so se for usar a consulta Shodan)

## Como usar

### Windows (modo local)

Duplo clique em `start.bat`, ou no terminal:

```powershell
cd caminho\para\personal-hub
.\start.bat
```

1. A primeira execucao cria o `venv` e instala o nucleo.
2. O navegador abre em `http://localhost:7777`.
3. Abra **Loja** e instale as ferramentas que quiser.
4. Pra fechar, feche o terminal.

### Windows (modo LAN — Wi-Fi de casa)

No PowerShell:

```powershell
.\start.bat lan sua-senha
```

Ou:

```powershell
$env:HUB_PASSWORD="sua-senha"
.\start.bat lan
```

O terminal lista os IPs (use o `192.168.x.x`, nao o `172.x` virtual). No celular/outro PC da **mesma rede**: `http://192.168.x.x:7777` e a senha. So quem esta no seu Wi-Fi acessa — nao fica aberto na internet. Nao faca port forward.

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

Modo LAN:

```bash
./start.sh lan sua-senha
```

## Caracteristicas

- **Porta 7777** (nao conflita com Apache/XAMPP, MySQL, Docker padrao).
- **Modo local** (padrao): so `127.0.0.1`, sem login.
- **Modo LAN**: bind `0.0.0.0` + senha compartilhada (`HUB_PASSWORD` / argumento).
- **Loja** instala e remove pacotes opcionais sem sujar a raiz do projeto; mostra deps, dados persistentes e o caminho em `storage/`.
- **Limpeza**: temporarios (video/imagem/PDF) separado de **Destruir tudo** (inclui vaults, chats, senhas e keys).
- **Storage** (Imagem / Video / Screenshot WP): browser com cards, preview, apagar um ou todos.
- Assets estaticos com `?v=mtime` pra nao ficar JS/CSS velho no navegador.
- Home mostra uso de armazenamento por ferramenta (KB/MB, conversas, keys).
- **SQLite local** em `storage/hub.db` (senhas PDF, chats IA, settings como key Shodan).
- **Vaults criptografados** (`.hubvault`, `.hubfake`, `.hubtotp`) — ciphertext em disco; senha-mestra so no navegador.
- **FFmpeg embutido** via `imageio-ffmpeg` (extra Video).
- **Ollama** em `localhost:11434` para o Assistente de IA.
- Home com ordem arrastavel das ferramentas.

## Estrutura

```
personal-hub/
  app/
    main.py            FastAPI + rotas
    config.py          Modo local/LAN, porta, senha
    auth.py            Portao de senha (LAN)
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
- Modo local: so `127.0.0.1`. Modo LAN: rede local com senha — nao exponha na internet.
- O Assistente de IA exige Ollama rodando localmente; a UI ajuda a instalar e baixar modelos.
- No Windows, o hub prefere o app de bandeja do Ollama (evita terminais pretos a cada pergunta).
- O tamanho de contexto e sugerido conforme a RAM livre; a geracao pode ser limitada/interrompida pra preservar folga de memoria.
- Consultas de rede (Whois/geo/Shodan) usam seu IP publico — a tela avisa qual IP esta saindo.
