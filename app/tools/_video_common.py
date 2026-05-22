import re
import subprocess
from pathlib import Path

import imageio_ffmpeg


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def duracao_segundos(path: Path) -> float | None:
    try:
        res = subprocess.run(
            [ffmpeg_exe(), "-i", str(path)],
            capture_output=True,
            text=True,
            errors="ignore",
        )
        match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", res.stderr)
        if not match:
            return None
        h, m, s = match.groups()
        return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        return None


def filtro_escala(max_width: int | None) -> list[str]:
    if not max_width or max_width <= 0:
        return []
    return ["-vf", f"scale='min({int(max_width)},iw)':-2"]


def crf_h264(quality: int) -> int:
    q = max(1, min(100, int(quality)))
    return round(40 - (q / 100) * 22)


def crf_vp9(quality: int) -> int:
    q = max(1, min(100, int(quality)))
    return round(45 - (q / 100) * 27)
