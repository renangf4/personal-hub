import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent.parent / "storage" / "hub.db"


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pdf_passwords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                senha TEXT NOT NULL UNIQUE,
                criada_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def listar_senhas() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, senha, criada_em FROM pdf_passwords ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def adicionar_senha(senha: str) -> bool:
    senha = (senha or "").strip()
    if not senha:
        return False
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO pdf_passwords (senha) VALUES (?)", (senha,))
        return True
    except sqlite3.IntegrityError:
        return False


def remover_senha(senha_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM pdf_passwords WHERE id = ?", (senha_id,))


def senhas_como_lista() -> list[str]:
    return [s["senha"] for s in listar_senhas()]
