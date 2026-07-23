import subprocess
import tempfile
from pathlib import Path

from . import _video_common as vc

EXTENSOES = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".gif", ".m4v")

FORMATOS = {
    "mp4": {
        "ext": ".mp4",
        "label": "MP4 (H.264)",
        "estimar_aviso": None,
    },
    "webm": {
        "ext": ".webm",
        "label": "WebM (VP9)",
        "estimar_aviso": "VP9 em modo rapido. O resultado real pode ser ate ~25% diferente.",
    },
    "gif": {
        "ext": ".gif",
        "label": "GIF animado",
        "estimar_aviso": "GIF costuma ficar bem maior que video comprimido.",
    },
    "mkv": {
        "ext": ".mkv",
        "label": "MKV (H.264)",
        "estimar_aviso": None,
    },
    "mov": {
        "ext": ".mov",
        "label": "MOV (H.264)",
        "estimar_aviso": None,
    },
}


def _montar_cmd(
    formato: str,
    entrada: Path,
    saida: Path,
    max_width: int | None,
    quality: int,
    *,
    rapido: bool = False,
    limite_segundos: float | None = None,
) -> list[str]:
    cmd = [vc.ffmpeg_exe(), "-y"]
    if limite_segundos is not None:
        cmd += ["-t", str(limite_segundos)]
    cmd += ["-i", str(entrada)]

    if formato == "gif":
        partes_vf = []
        if max_width and max_width > 0:
            partes_vf.append(f"scale='min({int(max_width)},iw)':-2:flags=lanczos")
        partes_vf.append("split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse")
        cmd += ["-vf", ",".join(partes_vf), "-loop", "0", "-an", str(saida)]
        return cmd

    cmd += vc.filtro_escala(max_width)

    if formato == "webm":
        cmd += [
            "-c:v", "libvpx-vp9",
            "-b:v", "0",
            "-crf", str(vc.crf_vp9(quality)),
            "-deadline", "realtime" if rapido else "good",
            "-cpu-used", "8" if rapido else "2",
            "-c:a", "libopus",
            "-threads", "0",
            str(saida),
        ]
        return cmd

    if formato in ("mp4", "mkv", "mov"):
        cmd += [
            "-c:v", "libx264",
            "-c:a", "aac",
            "-crf", str(vc.crf_h264(quality)),
            "-preset", "veryfast" if rapido else "medium",
            "-threads", "0",
            str(saida),
        ]
        return cmd

    raise ValueError(f"Formato invalido: {formato}")


def processar(
    arquivos: list[Path],
    pasta_saida: Path,
    max_width: int | None = None,
    quality: int = 100,
    formato: str = "mp4",
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
            subprocess.run(
                _montar_cmd(formato, entrada, saida, max_width, quality),
                check=True,
                capture_output=True,
            )
            resultados.append({
                "entrada": entrada.name,
                "saida": saida.name,
                "ok": True,
                "msg": f"Convertido para {meta['label']}",
            })
        except subprocess.CalledProcessError as e:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": f"Erro ffmpeg: {e.stderr.decode(errors='ignore')[-200:]}",
            })

    return resultados


def estimar(
    arquivo_bytes: bytes,
    nome_original: str,
    max_width: int | None = None,
    quality: int = 100,
    amostra_segundos: float = 4.0,
    formato: str = "mp4",
) -> dict:
    if formato not in FORMATOS:
        return {"ok": False, "msg": f"Formato invalido: {formato}"}

    meta = FORMATOS[formato]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        sufixo = Path(nome_original).suffix or ".mp4"
        entrada = tmp_path / f"in{sufixo}"
        entrada.write_bytes(arquivo_bytes)

        dur = vc.duracao_segundos(entrada)
        if not dur or dur <= 0:
            return {"ok": False, "msg": "Nao foi possivel ler a duracao do video"}

        amostra = min(amostra_segundos, dur)
        saida = tmp_path / f"sample{meta['ext']}"
        cmd = _montar_cmd(
            formato,
            entrada,
            saida,
            max_width,
            quality,
            rapido=True,
            limite_segundos=amostra,
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            return {
                "ok": False,
                "msg": f"Erro ffmpeg: {e.stderr.decode(errors='ignore')[-200:]}",
            }

        sample_size = saida.stat().st_size
        estimado = int(sample_size * dur / amostra)
        out = {
            "ok": True,
            "original": len(arquivo_bytes),
            "estimado": estimado,
            "duracao": dur,
            "amostra_segundos": amostra,
        }
        if meta.get("estimar_aviso"):
            out["aviso"] = meta["estimar_aviso"]
        return out
