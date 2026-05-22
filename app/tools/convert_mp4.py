import subprocess
import tempfile
from pathlib import Path

from . import _video_common as vc

EXTENSOES = (".mp4", ".mov", ".avi", ".mkv", ".webm")


def _comando(entrada: Path, saida: Path, max_width: int | None, quality: int, preset: str) -> list[str]:
    return [
        vc.ffmpeg_exe(),
        "-y",
        "-i", str(entrada),
        *vc.filtro_escala(max_width),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-crf", str(vc.crf_h264(quality)),
        "-preset", preset,
        "-threads", "0",
        str(saida),
    ]


def processar(
    arquivos: list[Path],
    pasta_saida: Path,
    max_width: int | None = None,
    quality: int = 100,
) -> list[dict]:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    resultados = []
    crf = vc.crf_h264(quality)

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
        try:
            subprocess.run(
                _comando(entrada, saida, max_width, quality, "medium"),
                check=True,
                capture_output=True,
            )
            resultados.append({
                "entrada": entrada.name,
                "saida": saida.name,
                "ok": True,
                "msg": f"Convertido (CRF {crf})",
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
) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        sufixo = Path(nome_original).suffix or ".mp4"
        entrada = tmp_path / f"in{sufixo}"
        entrada.write_bytes(arquivo_bytes)

        dur = vc.duracao_segundos(entrada)
        if not dur or dur <= 0:
            return {"ok": False, "msg": "Nao foi possivel ler a duracao do video"}

        amostra = min(amostra_segundos, dur)
        saida = tmp_path / "sample.mp4"

        cmd = [
            vc.ffmpeg_exe(),
            "-y",
            "-t", str(amostra),
            "-i", str(entrada),
            *vc.filtro_escala(max_width),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-crf", str(vc.crf_h264(quality)),
            "-preset", "veryfast",
            "-threads", "0",
            str(saida),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            return {
                "ok": False,
                "msg": f"Erro ffmpeg: {e.stderr.decode(errors='ignore')[-200:]}",
            }

        sample_size = saida.stat().st_size
        estimado = int(sample_size * dur / amostra)
        return {
            "ok": True,
            "original": len(arquivo_bytes),
            "estimado": estimado,
            "duracao": dur,
            "amostra_segundos": amostra,
        }
