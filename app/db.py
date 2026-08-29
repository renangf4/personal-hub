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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extras_instalados (
                slug TEXT PRIMARY KEY,
                instalado_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS home_ordem (
                slug TEXT PRIMARY KEY,
                posicao INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hub_settings (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lan_mensagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                remetente TEXT NOT NULL,
                destinatario TEXT,
                conteudo TEXT NOT NULL DEFAULT '',
                arquivo_nome TEXT,
                arquivo_path TEXT,
                arquivo_bytes INTEGER NOT NULL DEFAULT 0,
                criado_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_lan_msg_dest ON lan_mensagens(destinatario, id)"
        )
        conn.commit()
        _migrar_extras_legado(conn)


def _import_ok(nome: str) -> bool:
    try:
        import importlib
        importlib.import_module(nome)
        return True
    except ImportError:
        return False


def _migrar_extras_legado(conn: sqlite3.Connection) -> None:
    """Migra extras pip legados uma unica vez (nao reativa apos desinstalar)."""
    if conn.execute(
        "SELECT 1 FROM hub_settings WHERE chave = 'extras_migracao_legado'"
    ).fetchone():
        return

    total = conn.execute("SELECT COUNT(*) FROM extras_instalados").fetchone()[0]
    if total == 0:
        from .extras import EXTRAS, eh_browser_only
        for slug, extra in EXTRAS.items():
            if eh_browser_only(extra):
                continue
            if all(_import_ok(nome) for nome in extra["imports"]):
                conn.execute(
                    "INSERT OR IGNORE INTO extras_instalados (slug) VALUES (?)",
                    (slug,),
                )

    conn.execute(
        "INSERT OR REPLACE INTO hub_settings (chave, valor) VALUES ('extras_migracao_legado', '1')"
    )
    conn.commit()


def listar_extras_instalados() -> set[str]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT slug FROM extras_instalados").fetchall()
        return {r["slug"] for r in rows}


def marcar_extra(slug: str) -> None:
    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO extras_instalados (slug, instalado_em) VALUES (?, datetime('now'))",
            (slug,),
        )


def desmarcar_extra(slug: str) -> None:
    init_db()
    with get_conn() as conn:
        conn.execute("DELETE FROM extras_instalados WHERE slug = ?", (slug,))


def listar_ordem_home() -> list[str]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT slug FROM home_ordem ORDER BY posicao ASC, slug ASC"
        ).fetchall()
        return [r["slug"] for r in rows]


def salvar_ordem_home(slugs: list[str]) -> None:
    init_db()
    limpos = [str(s).strip() for s in slugs if str(s).strip()]
    with get_conn() as conn:
        conn.execute("DELETE FROM home_ordem")
        for i, slug in enumerate(limpos):
            conn.execute(
                "INSERT INTO home_ordem (slug, posicao) VALUES (?, ?)",
                (slug, i),
            )


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


def obter_setting(chave: str, padrao: str = "") -> str:
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT valor FROM hub_settings WHERE chave = ?",
            (chave,),
        ).fetchone()
        return str(row["valor"]) if row else padrao


def salvar_setting(chave: str, valor: str) -> None:
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO hub_settings (chave, valor) VALUES (?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (chave, valor or ""),
        )


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


def excluir_mensagens_a_partir(chat_id: int, mensagem_id: int) -> int:
    """Apaga a mensagem e tudo depois dela no mesmo chat. Retorna quantas apagou."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM ai_mensagens WHERE id = ? AND chat_id = ?",
            (mensagem_id, chat_id),
        ).fetchone()
        if not row:
            return 0
        cur = conn.execute(
            "DELETE FROM ai_mensagens WHERE chat_id = ? AND id >= ?",
            (chat_id, mensagem_id),
        )
        conn.execute(
            "UPDATE ai_chats SET atualizado_em = datetime('now') WHERE id = ?",
            (chat_id,),
        )
        return int(cur.rowcount or 0)


def excluir_chat(chat_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM ai_mensagens WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM ai_chats WHERE id = ?", (chat_id,))


def limpar_chats() -> int:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM ai_chats").fetchone()[0]
        conn.execute("DELETE FROM ai_mensagens")
        conn.execute("DELETE FROM ai_chats")
        return int(total)


def limpar_senhas_pdf() -> int:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM pdf_passwords").fetchone()[0]
        conn.execute("DELETE FROM pdf_passwords")
        return int(total)


def limpar_settings_api() -> int:
    chaves = ("shodan_api_key", "abuseipdb_api_key", "virustotal_api_key")
    with get_conn() as conn:
        total = 0
        for chave in chaves:
            row = conn.execute(
                "SELECT valor FROM hub_settings WHERE chave = ?",
                (chave,),
            ).fetchone()
            if row and (row["valor"] or "").strip():
                total += 1
            conn.execute("DELETE FROM hub_settings WHERE chave = ?", (chave,))
        return total


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


def criar_lan_mensagem(
    remetente: str,
    destinatario: str | None,
    conteudo: str = "",
    arquivo_nome: str | None = None,
    arquivo_path: str | None = None,
    arquivo_bytes: int = 0,
) -> dict:
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO lan_mensagens
                (remetente, destinatario, conteudo, arquivo_nome, arquivo_path, arquivo_bytes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                remetente,
                destinatario,
                conteudo or "",
                arquivo_nome,
                arquivo_path,
                int(arquivo_bytes or 0),
            ),
        )
        row = conn.execute(
            """
            SELECT id, remetente, destinatario, conteudo, arquivo_nome, arquivo_path,
                   arquivo_bytes, criado_em
            FROM lan_mensagens WHERE id = ?
            """,
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)


def obter_lan_mensagem(msg_id: int) -> dict | None:
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, remetente, destinatario, conteudo, arquivo_nome, arquivo_path,
                   arquivo_bytes, criado_em
            FROM lan_mensagens WHERE id = ?
            """,
            (msg_id,),
        ).fetchone()
        return dict(row) if row else None


def listar_lan_mensagens(
    apelido: str,
    destinatario: str | None,
    desde_id: int = 0,
    limite: int = 200,
) -> list[dict]:
    init_db()
    limite = max(1, min(int(limite or 200), 500))
    desde_id = max(0, int(desde_id or 0))
    with get_conn() as conn:
        if destinatario:
            rows = conn.execute(
                """
                SELECT id, remetente, destinatario, conteudo, arquivo_nome, arquivo_path,
                       arquivo_bytes, criado_em
                FROM lan_mensagens
                WHERE id > ?
                  AND (
                    (remetente = ? AND destinatario = ?)
                    OR (remetente = ? AND destinatario = ?)
                  )
                ORDER BY id ASC
                LIMIT ?
                """,
                (desde_id, apelido, destinatario, destinatario, apelido, limite),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, remetente, destinatario, conteudo, arquivo_nome, arquivo_path,
                       arquivo_bytes, criado_em
                FROM lan_mensagens
                WHERE id > ? AND destinatario IS NULL
                ORDER BY id ASC
                LIMIT ?
                """,
                (desde_id, limite),
            ).fetchall()
        return [dict(r) for r in rows]


def info_lan_dm() -> dict:
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS mensagens,
                   COALESCE(SUM(arquivo_bytes), 0) AS bytes
            FROM lan_mensagens
            """
        ).fetchone()
        return {
            "mensagens": int(row["mensagens"] or 0),
            "bytes": int(row["bytes"] or 0),
        }


def limpar_lan_dm() -> dict:
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(arquivo_bytes), 0) AS b FROM lan_mensagens"
        ).fetchone()
        conn.execute("DELETE FROM lan_mensagens")
        return {
            "mensagens": int(row["n"] or 0),
            "bytes": int(row["b"] or 0),
        }
