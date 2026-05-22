# Personal Hub

Hub privado e local com utilitarios pessoais, acessivel apenas pelo navegador em `http://localhost:7777`. Nao expoe rede, nao usa Docker, nao usa WSL.

## Ferramentas

- Converter video para MP4 (H.264)
- Converter video para WebM (VP9)
- Converter imagem para WebP (com largura ajustavel)
- Desbloquear PDF (com gerenciador de senhas em SQLite)
- Screenshot WordPress (padroniza em 1200x900 PNG otimizado)

## Requisitos

- Windows, Linux ou macOS
- Python 3.10+ no PATH

## Como usar

### Windows

1. Execute `start.bat` (primeira execucao cria o `venv` e instala dependencias).
2. O navegador abre automaticamente em `http://localhost:7777`.
3. Pra fechar, feche o terminal.

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

Primeira execucao cria o `venv` e instala dependencias. Acesse `http://localhost:7777`.

## Caracteristicas

- **Porta 7777** (nao conflita com Apache/XAMPP, MySQL, Docker padrao).
- **Botao "Limpar cache"** no topo remove manualmente todos os arquivos em `storage/uploads/` e `storage/outputs/`, exibindo antes quantos arquivos e quanto espaco sera liberado.
- **SQLite local** em `storage/hub.db` guarda apenas as senhas do desbloqueio de PDF.
- **FFmpeg embutido** via `imageio-ffmpeg` (nao precisa instalar separadamente).

## Estrutura

```
personal-hub/
  app/
    main.py            FastAPI + rotas
    db.py              SQLite das senhas
    cleanup.py         Limpeza D+1
    tools/             Logica de cada ferramenta
  templates/           Jinja2 + Bootstrap
  static/              CSS e JS
  storage/
    uploads/           Arquivos enviados (limpos via botao)
    outputs/           Arquivos gerados (limpos via botao)
    hub.db             SQLite das senhas
  requirements.txt
  start.bat
```

## Observacoes

- Conversoes de video sao sincronas: a request espera o ffmpeg terminar. Arquivos muito grandes podem demorar.
- Toda a comunicacao e `127.0.0.1`; nada e exposto na rede.
