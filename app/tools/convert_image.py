from io import BytesIO
from pathlib import Path

from PIL import Image

EXTENSOES = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp", ".gif")

FORMATOS = {
    "webp": {"ext": ".webp", "label": "WebP"},
    "png": {"ext": ".png", "label": "PNG"},
    "jpeg": {"ext": ".jpg", "label": "JPEG"},
    "gif": {"ext": ".gif", "label": "GIF"},
    "bmp": {"ext": ".bmp", "label": "BMP"},
    "tiff": {"ext": ".tiff", "label": "TIFF"},
}


def _preparar(img: Image.Image, formato: str) -> Image.Image:
    if formato == "jpeg":
        if img.mode in ("RGBA", "LA", "P"):
            fundo = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
                fundo.paste(img, mask=img.split()[-1])
                return fundo
            return img.convert("RGB")
        if img.mode != "RGB":
            return img.convert("RGB")
    if formato == "gif" and img.mode not in ("P", "L"):
        return img.convert("P", palette=Image.ADAPTIVE)
    if formato in ("png", "webp", "tiff", "bmp") and img.mode == "P":
        return img.convert("RGBA")
    return img


def _opcoes_save(formato: str, quality: int) -> dict:
    q = max(1, min(100, int(quality)))
    if formato == "webp":
        if q >= 100:
            return {"format": "WEBP", "lossless": True, "quality": 100, "method": 6}
        return {"format": "WEBP", "quality": q, "method": 6}
    if formato == "jpeg":
        return {"format": "JPEG", "quality": max(1, min(95, q)), "optimize": True}
    if formato == "png":
        # 1 = mais compressao, 9 = menos; qualidade alta = menos compressao
        nivel = max(0, min(9, round((100 - q) / 100 * 9)))
        return {"format": "PNG", "optimize": True, "compress_level": nivel}
    if formato == "gif":
        return {"format": "GIF", "optimize": True}
    if formato == "bmp":
        return {"format": "BMP"}
    if formato == "tiff":
        return {"format": "TIFF", "compression": "tiff_lzw"}
    raise ValueError(f"Formato invalido: {formato}")


def _redimensionar(img: Image.Image, max_width: int | None) -> Image.Image:
    if max_width and max_width > 0 and img.width > max_width:
        ratio = max_width / img.width
        new_h = max(1, int(img.height * ratio))
        return img.resize((max_width, new_h), Image.LANCZOS)
    return img


def estimar(
    arquivo_bytes: bytes,
    max_width: int | None = None,
    quality: int = 100,
    formato: str = "webp",
) -> int:
    if formato not in FORMATOS:
        raise ValueError(f"Formato invalido: {formato}")
    with Image.open(BytesIO(arquivo_bytes)) as img:
        img.load()
        img = _redimensionar(img, max_width)
        img = _preparar(img, formato)
        buf = BytesIO()
        img.save(buf, **_opcoes_save(formato, quality))
        return buf.tell()


def processar(
    arquivos: list[Path],
    pasta_saida: Path,
    max_width: int | None = None,
    quality: int = 100,
    formato: str = "webp",
) -> list[dict]:
    if formato not in FORMATOS:
        return [{
            "entrada": "",
            "saida": None,
            "ok": False,
            "msg": f"Formato invalido: {formato}",
        }]

    pasta_saida.mkdir(parents=True, exist_ok=True)
    resultados = []
    meta = FORMATOS[formato]
    opcoes = _opcoes_save(formato, quality)

    for entrada in arquivos:
        if entrada.suffix.lower() not in EXTENSOES:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": "Extensao nao suportada",
            })
            continue

        saida = pasta_saida / f"{entrada.stem}{meta['ext']}"
        try:
            with Image.open(entrada) as img:
                img = _redimensionar(img, max_width)
                img = _preparar(img, formato)
                img.save(saida, **opcoes)
            resultados.append({
                "entrada": entrada.name,
                "saida": saida.name,
                "ok": True,
                "msg": f"Convertido para {meta['label']}",
            })
        except Exception as e:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": str(e),
            })

    return resultados
