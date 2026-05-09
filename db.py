"""BURNING ZERO — SQLite database layer."""

import sqlite3
import os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "burning_zero.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            mt5_login INTEGER,
            mt5_server TEXT,
            mt5_password TEXT,
            status TEXT DEFAULT 'pending',
            conf_threshold REAL DEFAULT 0.68,
            lot_mode TEXT DEFAULT 'fixed',
            lot_size REAL DEFAULT 0.01,
            risk_pct REAL DEFAULT 1.0,
            strategies_a INTEGER DEFAULT 1,
            strategies_b INTEGER DEFAULT 1,
            strategies_d INTEGER DEFAULT 1,
            active INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            strategy TEXT,
            direction TEXT,
            symbol TEXT DEFAULT 'XAUUSD',
            entry_price REAL,
            exit_price REAL,
            lot REAL,
            profit REAL,
            conf REAL,
            ticket INTEGER,
            opened_at TIMESTAMP,
            closed_at TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            strategy TEXT,
            direction TEXT,
            symbol TEXT DEFAULT 'XAUUSD',
            entry_price REAL,
            lot REAL,
            ticket INTEGER,
            conf REAL,
            opened_at TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id);
        CREATE INDEX IF NOT EXISTS idx_positions_user ON positions(user_id);
    """)
    conn.commit()
    conn.close()


# ── User CRUD ──

def create_user(name: str, email: str, password_hash: str,
                mt5_login: int, mt5_server: str, mt5_password: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, mt5_login, mt5_server, mt5_password) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, password_hash, mt5_login, mt5_server, mt5_password),
    )
    uid = cur.lastrowid
    conn.commit()
    conn.close()
    return uid


def get_user_by_email(email: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(uid: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_approved_active_users() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM users WHERE status = 'approved' AND active = 1 ORDER BY created_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_approved_users() -> int:
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE status = 'approved'").fetchone()
    conn.close()
    return row["cnt"]


def approve_user(uid: int):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET status = 'approved', approved_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), uid),
    )
    conn.commit()
    conn.close()


def reject_user(uid: int):
    conn = get_conn()
    conn.execute("UPDATE users SET status = 'rejected' WHERE id = ?", (uid,))
    conn.commit()
    conn.close()


def update_user_settings(uid: int, **kwargs):
    allowed = {
        "conf_threshold", "lot_mode", "lot_size", "risk_pct",
        "strategies_a", "strategies_b", "strategies_d", "active",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [uid]
    conn = get_conn()
    conn.execute(f"UPDATE users SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()


# ── Positions ──

def add_position(user_id: int, strategy: str, direction: str, symbol: str,
                 entry_price: float, lot: float, ticket: int, conf: float):
    conn = get_conn()
    conn.execute(
        "INSERT INTO positions (user_id, strategy, direction, symbol, entry_price, lot, ticket, conf, opened_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, strategy, direction, symbol, entry_price, lot, ticket, conf,
         datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_positions(user_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM positions WHERE user_id = ? ORDER BY opened_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_positions() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM positions ORDER BY opened_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def remove_position(position_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
    if row:
        conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        conn.commit()
    conn.close()
    return dict(row) if row else None


def remove_position_by_ticket(user_id: int, ticket: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM positions WHERE user_id = ? AND ticket = ?", (user_id, ticket)
    ).fetchone()
    if row:
        conn.execute("DELETE FROM positions WHERE user_id = ? AND ticket = ?", (user_id, ticket))
        conn.commit()
    conn.close()
    return dict(row) if row else None


# ── Trades ──

def add_trade(user_id: int, strategy: str, direction: str, symbol: str,
              entry_price: float, exit_price: float, lot: float,
              profit: float, conf: float, ticket: int,
              opened_at: str, closed_at: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO trades (user_id, strategy, direction, symbol, entry_price, exit_price, "
        "lot, profit, conf, ticket, opened_at, closed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, strategy, direction, symbol, entry_price, exit_price,
         lot, profit, conf, ticket, opened_at, closed_at),
    )
    conn.commit()
    conn.close()


def get_trades(user_id: int, limit: int = 100) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades WHERE user_id = ? ORDER BY closed_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_trades(limit: int = 500) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
