import subprocess
from pathlib import Path

import imageio_ffmpeg

EXTENSOES = (".mp4", ".mov", ".avi", ".mkv")


def processar(arquivos: list[Path], pasta_saida: Path) -> list[dict]:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
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

        saida = pasta_saida / f"{entrada.stem}.webm"
        comando = [
            ffmpeg,
            "-y",
            "-i", str(entrada),
            "-c:v", "libvpx-vp9",
            "-b:v", "0",
            "-crf", "18",
            "-c:a", "libopus",
            "-threads", "0",
            str(saida),
        ]

        try:
            subprocess.run(comando, check=True, capture_output=True)
            resultados.append({
                "entrada": entrada.name,
                "saida": saida.name,
                "ok": True,
                "msg": "Convertido",
            })
        except subprocess.CalledProcessError as e:
            resultados.append({
                "entrada": entrada.name,
                "saida": None,
                "ok": False,
                "msg": f"Erro ffmpeg: {e.stderr.decode(errors='ignore')[-200:]}",
            })

    return resultados
