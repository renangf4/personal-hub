import subprocess
from pathlib import Path

import imageio_ffmpeg

EXTENSOES = (".mp4", ".mov", ".avi", ".mkv", ".webm")


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

        saida = pasta_saida / f"{entrada.stem}.mp4"
        comando = [
            ffmpeg,
            "-y",
            "-i", str(entrada),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-b:v", "5000k",
            "-crf", "23",
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
