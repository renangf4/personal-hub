from io import BytesIO
from pathlib import Path

from PIL import Image

EXTENSOES = (".jpg", ".jpeg", ".png", ".bmp", ".tiff")
MAX_WIDTH = 500


def _opcoes_webp(quality: int) -> dict:
    quality = max(1, min(100, int(quality)))
    if quality >= 100:
        return {"format": "WEBP", "lossless": True, "quality": 100, "method": 6}
    return {"format": "WEBP", "quality": quality, "method": 6}


def estimar(arquivo_bytes: bytes, max_width: int | None = None, quality: int = 100) -> int:
    with Image.open(BytesIO(arquivo_bytes)) as img:
        img.load()
        if max_width and max_width > 0 and img.width > max_width:
            ratio = max_width / img.width
            new_h = max(1, int(img.height * ratio))
            img = img.resize((max_width, new_h), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, **_opcoes_webp(quality))
        return buf.tell()


def processar(
    arquivos: list[Path],
    pasta_saida: Path,
    max_width: int | None = None,
    quality: int = 100,
) -> list[dict]:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    resultados = []

    opcoes = _opcoes_webp(quality)
    rotulo_modo = "sem perda" if opcoes.get("lossless") else f"qualidade {opcoes['quality']}"

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
                img.save(saida, **opcoes)
            resultados.append({
                "entrada": entrada.name,
                "saida": saida.name,
                "ok": True,
                "msg": f"Convertido ({rotulo_modo})",
            })
        except Exception as e:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": str(e),
            })

    return resultados
