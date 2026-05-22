from pathlib import Path

import pikepdf


def processar(arquivos: list[Path], pasta_saida: Path, senhas: list[str]) -> list[dict]:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    resultados = []

    for entrada in arquivos:
        if entrada.suffix.lower() != ".pdf":
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": "Nao e PDF",
            })
            continue

        saida = pasta_saida / f"{entrada.stem}_desbloqueado.pdf"
        sucesso = False
        senha_usada = None
        ultimo_erro = None

        try:
            with pikepdf.open(entrada) as pdf:
                pdf.save(saida)
            sucesso = True
            senha_usada = "(sem senha)"
        except pikepdf.PasswordError:
            for senha in senhas:
                try:
                    with pikepdf.open(entrada, password=senha) as pdf:
                        pdf.save(saida)
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
            resultados.append({
                "entrada": entrada.name,
                "saida": saida.name,
                "ok": True,
                "msg": f"Desbloqueado (senha: {senha_usada})",
            })
        else:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": ultimo_erro or "Nenhuma senha cadastrada funcionou",
            })

    return resultados
