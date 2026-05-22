from pathlib import Path

from PIL import Image

EXTENSOES = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp")
LARGURA_FINAL = 1200
ALTURA_FINAL = 900
TOLERANCIA_ALTURA = 0.1


def processar(arquivos: list[Path], pasta_saida: Path) -> list[dict]:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    resultados = []

    for entrada in arquivos:
        if entrada.suffix.lower() not in EXTENSOES:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": "Extensao nao suportada",
            })
            continue

        saida = pasta_saida / "screenshot.png"
        try:
            img = Image.open(entrada)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")

            largura_original, altura_original = img.size
            proporcao = LARGURA_FINAL / largura_original
            nova_altura = int(altura_original * proporcao)

            img_redim = img.resize((LARGURA_FINAL, nova_altura), Image.Resampling.LANCZOS)
            diferenca = abs(nova_altura - ALTURA_FINAL) / ALTURA_FINAL

            if diferenca <= TOLERANCIA_ALTURA:
                img_final = img_redim.resize((LARGURA_FINAL, ALTURA_FINAL), Image.Resampling.LANCZOS)
                modo = "achatado"
            elif nova_altura > ALTURA_FINAL:
                img_final = img_redim.crop((0, 0, LARGURA_FINAL, ALTURA_FINAL))
                modo = "recortado do topo"
            else:
                img_final = img_redim.resize((LARGURA_FINAL, ALTURA_FINAL), Image.Resampling.LANCZOS)
                modo = "achatado"

            img_final = img_final.quantize(
                colors=64,
                method=Image.Quantize.MEDIANCUT,
                dither=Image.Dither.FLOYDSTEINBERG,
            )
            img_final.save(saida, "PNG", optimize=True, compress_level=9)

            resultados.append({
                "entrada": entrada.name,
                "saida": saida.name,
                "ok": True,
                "msg": f"Convertido ({modo})",
            })
        except Exception as e:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": str(e),
            })

    return resultados
