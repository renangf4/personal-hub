from pathlib import Path

import pikepdf

# Top senhas comuns (EN/BR) — lista leve embutida; rockyou/etc. ficam no upload.
SENHAS_COMUNS = [
    "123456", "123456789", "12345678", "password", "12345", "1234567",
    "qwerty", "abc123", "111111", "123123", "admin", "letmein", "welcome",
    "monkey", "login", "princess", "dragon", "passw0rd", "master", "hello",
    "freedom", "whatever", "qazwsx", "trustno1", "654321", "jordan23",
    "harley", "password1", "1234", "1234567890", "000000", "1q2w3e4r",
    "qwerty123", "1qaz2wsx", "qwertyuiop", "iloveyou", "sunshine",
    "football", "baseball", "superman", "batman", "access", "shadow",
    "michael", "jennifer", "hunter", "buster", "soccer", "tigger",
    "charlie", "andrew", "michelle", "love", "secret", "asdfgh",
    "zxcvbn", "asdf1234", "pass", "pass123", "senha", "senha123",
    "senha1234", "brasil", "brasil123", "flamengo", "palmeiras",
    "corinthians", "saopaulo", "santos", "vasco", "gremio", "cruzeiro",
    "atletico", "botafogo", "mudar123", "Mudar123", "Mudar@123",
    "admin123", "Admin123", "root", "toor", "guest", "test", "test123",
    "teste", "teste123", "demo", "demo123", "usuario", "user", "user123",
    "pdf", "pdf123", "documento", "doc123", "arquivo", "abrir", "abrir123",
    "empresa", "empresa123", "financeiro", "rh123", "contabilidade",
    "2020", "2021", "2022", "2023", "2024", "2025", "2026",
    "010203", "121212", "112233", "102030", "987654321", "147258369",
    "159357", "q1w2e3r4", "aa123456", "password123", "Password1",
    "P@ssw0rd", "P@ssword1", "Welcome1", "Changeme1", "Temp1234",
]


def _tentar(entrada: Path, saida: Path, senha: str | None) -> bool:
    kwargs = {} if senha is None else {"password": senha}
    with pikepdf.open(entrada, **kwargs) as pdf:
        pdf.save(saida)
    return True


def _carregar_wordlist(caminho: Path | None) -> list[str]:
    if not caminho or not caminho.is_file():
        return []
    linhas: list[str] = []
    texto = caminho.read_text(encoding="utf-8", errors="ignore")
    for linha in texto.splitlines():
        s = linha.strip()
        if s and not s.startswith("#"):
            linhas.append(s)
    return linhas


def _gerar_pins(digitos: int) -> list[str]:
    digitos = max(3, min(6, int(digitos)))
    fim = 10 ** digitos
    return [str(i).zfill(digitos) for i in range(fim)]


def processar(
    arquivos: list[Path],
    pasta_saida: Path,
    modo: str = "salvas",
    senhas: list[str] | None = None,
    senha_avulsa: str | None = None,
    wordlist: Path | None = None,
    wordlist_fonte: str = "comuns",
    pin_digits: int | None = None,
) -> list[dict]:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    resultados = []

    candidatas: list[str] = []
    if modo == "unica":
        if senha_avulsa and senha_avulsa.strip():
            candidatas.append(senha_avulsa.strip())
    elif modo == "wordlist":
        if wordlist_fonte == "upload":
            candidatas.extend(_carregar_wordlist(wordlist))
        else:
            candidatas.extend(SENHAS_COMUNS)
    elif modo == "numerico" and pin_digits:
        candidatas.extend(_gerar_pins(pin_digits))
    else:
        for s in senhas or []:
            if s:
                candidatas.append(s)

    for entrada in arquivos:
        if entrada.suffix.lower() != ".pdf":
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": "Nao e PDF",
                "senha_usada": None,
            })
            continue

        saida = pasta_saida / f"{entrada.stem}_desbloqueado.pdf"
        sucesso = False
        senha_usada = None
        ultimo_erro = None
        tentativas = 0

        try:
            _tentar(entrada, saida, None)
            sucesso = True
            senha_usada = None
        except pikepdf.PasswordError:
            for senha in candidatas:
                tentativas += 1
                try:
                    _tentar(entrada, saida, senha)
                    sucesso = True
                    senha_usada = senha
                    break
                except pikepdf.PasswordError:
                    continue
                except Exception as e:
                    ultimo_erro = str(e)
                    break
        except Exception as e:
            ultimo_erro = str(e)

        if sucesso:
            if senha_usada is None:
                msg = "Aberto sem senha"
            else:
                msg = (
                    f"Desbloqueado (senha: {senha_usada})"
                    if modo in ("salvas", "unica")
                    else f"Desbloqueado apos {tentativas} tentativa(s)"
                )
            resultados.append({
                "entrada": entrada.name,
                "saida": saida.name,
                "ok": True,
                "msg": msg,
                "senha_usada": senha_usada,
            })
        else:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": ultimo_erro or (
                    f"Nenhuma senha funcionou ({tentativas} tentativas)"
                    if candidatas
                    else "PDF protegido e nenhuma senha informada/cadastrada"
                ),
                "senha_usada": None,
            })

    return resultados
