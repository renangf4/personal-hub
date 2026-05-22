import threading
import time
from pathlib import Path

STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
OUTPUTS_DIR = STORAGE_DIR / "outputs"

MAX_AGE_SECONDS = 24 * 60 * 60
SCAN_INTERVAL_SECONDS = 60 * 60


def _limpar_pasta(pasta: Path) -> int:
    if not pasta.exists():
        return 0
    agora = time.time()
    removidos = 0
    for item in pasta.rglob("*"):
        if item.name == ".gitkeep":
            continue
        try:
            if item.is_file():
                idade = agora - item.stat().st_mtime
                if idade > MAX_AGE_SECONDS:
                    item.unlink(missing_ok=True)
                    removidos += 1
        except OSError:
            continue

    for sub in sorted(
        [p for p in pasta.rglob("*") if p.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            if not any(sub.iterdir()):
                sub.rmdir()
        except OSError:
            continue
    return removidos


def executar_limpeza() -> int:
    return _limpar_pasta(UPLOADS_DIR) + _limpar_pasta(OUTPUTS_DIR)


def _loop():
    while True:
        try:
            executar_limpeza()
        except Exception:
            pass
        time.sleep(SCAN_INTERVAL_SECONDS)


def iniciar_cleanup_em_background() -> None:
    t = threading.Thread(target=_loop, daemon=True, name="cleanup-d1")
    t.start()
