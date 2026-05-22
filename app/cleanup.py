from pathlib import Path

STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
OUTPUTS_DIR = STORAGE_DIR / "outputs"


def _iter_arquivos(pasta: Path):
    if not pasta.exists():
        return
    for item in pasta.rglob("*"):
        if item.name == ".gitkeep" or not item.is_file():
            continue
        yield item


def info_armazenamento() -> dict:
    arquivos = 0
    bytes_total = 0
    for pasta in (UPLOADS_DIR, OUTPUTS_DIR):
        for item in _iter_arquivos(pasta):
            try:
                bytes_total += item.stat().st_size
                arquivos += 1
            except OSError:
                continue
    return {"arquivos": arquivos, "bytes": bytes_total}


def _limpar_pasta(pasta: Path) -> tuple[int, int]:
    if not pasta.exists():
        return 0, 0
    removidos = 0
    bytes_liberados = 0
    for item in list(_iter_arquivos(pasta)):
        try:
            size = item.stat().st_size
            item.unlink(missing_ok=True)
            removidos += 1
            bytes_liberados += size
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
    return removidos, bytes_liberados


def executar_limpeza() -> dict:
    arquivos = 0
    bytes_total = 0
    for pasta in (UPLOADS_DIR, OUTPUTS_DIR):
        a, b = _limpar_pasta(pasta)
        arquivos += a
        bytes_total += b
    return {"arquivos": arquivos, "bytes": bytes_total}
