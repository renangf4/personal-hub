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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL DEFAULT 'Nova conversa',
                criado_em TEXT NOT NULL DEFAULT (datetime('now')),
                atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_mensagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                conteudo TEXT NOT NULL,
                criado_em TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (chat_id) REFERENCES ai_chats(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_mensagens_chat ON ai_mensagens(chat_id, id)"
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


def criar_chat(titulo: str = "Nova conversa") -> dict:
    titulo = (titulo or "Nova conversa").strip() or "Nova conversa"
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO ai_chats (titulo) VALUES (?)", (titulo,))
        chat_id = cur.lastrowid
        row = conn.execute(
            "SELECT id, titulo, criado_em, atualizado_em FROM ai_chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
        return dict(row)


def listar_chats() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.titulo, c.criado_em, c.atualizado_em,
                   (SELECT COUNT(*) FROM ai_mensagens m WHERE m.chat_id = c.id) AS total_mensagens
            FROM ai_chats c
            ORDER BY datetime(c.atualizado_em) DESC, c.id DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def obter_chat(chat_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, titulo, criado_em, atualizado_em FROM ai_chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
        return dict(row) if row else None


def renomear_chat(chat_id: int, titulo: str) -> bool:
    titulo = (titulo or "").strip()
    if not titulo:
        return False
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE ai_chats SET titulo = ?, atualizado_em = datetime('now') WHERE id = ?",
            (titulo, chat_id),
        )
        return cur.rowcount > 0


def excluir_chat(chat_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM ai_mensagens WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM ai_chats WHERE id = ?", (chat_id,))


def adicionar_mensagem(chat_id: int, role: str, conteudo: str) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO ai_mensagens (chat_id, role, conteudo) VALUES (?, ?, ?)",
            (chat_id, role, conteudo),
        )
        conn.execute(
            "UPDATE ai_chats SET atualizado_em = datetime('now') WHERE id = ?",
            (chat_id,),
        )
        row = conn.execute(
            "SELECT id, chat_id, role, conteudo, criado_em FROM ai_mensagens WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)


def listar_mensagens(chat_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, chat_id, role, conteudo, criado_em
            FROM ai_mensagens
            WHERE chat_id = ?
            ORDER BY id ASC
            """,
            (chat_id,),
        ).fetchall()
        return [dict(r) for r in rows]
