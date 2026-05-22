from pathlib import Path

from PIL import Image

EXTENSOES = (".jpg", ".jpeg", ".png", ".bmp", ".tiff")
MAX_WIDTH = 500


def processar(arquivos: list[Path], pasta_saida: Path, max_width: int | None = None) -> list[dict]:
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

        saida = pasta_saida / f"{entrada.stem}.webp"
        try:
            with Image.open(entrada) as img:
                if max_width and max_width > 0 and img.width > max_width:
                    ratio = max_width / img.width
                    new_h = max(1, int(img.height * ratio))
                    img = img.resize((max_width, new_h), Image.LANCZOS)
                img.save(saida, format="WEBP", quality=100)
            resultados.append({
                "entrada": entrada.name,
                "saida": saida.name,
                "ok": True,
                "msg": "Convertido",
            })
        except Exception as e:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": str(e),
            })

    return resultados
