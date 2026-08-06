from io import BytesIO
from pathlib import Path

from PIL import Image

EXTENSOES = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp")
LARGURA_FINAL = 1200
ALTURA_FINAL = 900
TOLERANCIA_ALTURA = 0.1


def _cores(quality: int) -> int:
    """Mapa de qualidade → cores na paleta.

    1% ≈ 8 cores, 50% ≈ 64 (comportamento antigo), 100% ≈ 256.
    """
    q = max(1, min(100, int(quality)))
    if q <= 50:
        return max(8, round(8 + (q - 1) / 49 * (64 - 8)))
    return max(64, min(256, round(64 + (q - 50) / 50 * (256 - 64))))


def _compress_level(quality: int) -> int:
    """Qualidade alta = menos compressao zlib (0–9)."""
    q = max(1, min(100, int(quality)))
    return max(0, min(9, round((100 - q) / 100 * 9)))


def _preparar_final(entrada_img: Image.Image) -> tuple[Image.Image, str]:
    img = entrada_img
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
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

    return img_final, modo


def _salvar_png(img: Image.Image, destino, quality: int) -> None:
    cores = _cores(quality)
    nivel = _compress_level(quality)
    quantizada = img.quantize(
        colors=cores,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.FLOYDSTEINBERG,
    )
    quantizada.save(destino, "PNG", optimize=True, compress_level=nivel)


def estimar(arquivo_bytes: bytes, quality: int = 50) -> int:
    with Image.open(BytesIO(arquivo_bytes)) as img:
        img.load()
        final, _ = _preparar_final(img)
        buf = BytesIO()
        _salvar_png(final, buf, quality)
        return buf.tell()


def processar(
    arquivos: list[Path],
    pasta_saida: Path,
    quality: int = 50,
) -> list[dict]:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    resultados = []
    q = max(1, min(100, int(quality or 50)))

    for entrada in arquivos:
        if entrada.suffix.lower() not in EXTENSOES:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": "Extensao nao suportada",
            })
            continue

        saida = pasta_saida / f"{entrada.stem}.png"
        try:
            with Image.open(entrada) as img:
                img.load()
                final, modo = _preparar_final(img)
                _salvar_png(final, saida, q)

            resultados.append({
                "entrada": entrada.name,
                "saida": saida.name,
                "ok": True,
                "msg": f"Convertido ({modo}, q={q}%)",
            })
        except Exception as e:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": str(e),
            })

    return resultados
