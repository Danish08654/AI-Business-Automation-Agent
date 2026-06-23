import sqlite3
import os
from datetime import datetime
from pathlib import Path

DB_PATH = "database/business.db"
Path("database").mkdir(exist_ok=True)


# ─────────────────────────────
# CONNECTION
# ─────────────────────────────
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────
# INIT DB
# ─────────────────────────────
def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT UNIQUE NOT NULL,
        vendor_name TEXT NOT NULL,
        vendor_email TEXT,
        amount REAL NOT NULL,
        currency TEXT DEFAULT 'USD',
        description TEXT,
        due_date TEXT,
        status TEXT DEFAULT 'pending',
        priority TEXT DEFAULT 'normal',
        submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
        processed_at TEXT,
        approved_by TEXT,
        notes TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS approval_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER,
        invoice_number TEXT,
        action TEXT NOT NULL,
        reason TEXT,
        performed_by TEXT DEFAULT 'AI_AGENT',
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT,
        channel TEXT,
        message TEXT,
        status TEXT DEFAULT 'sent',
        sent_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


# ─────────────────────────────
# SEED DATA
# ─────────────────────────────
def seed_sample_invoices():
    conn = get_connection()
    c = conn.cursor()

    samples = [
        ("INV-2026-001", "TechSupplies Corp", 350),
        ("INV-2026-002", "CloudServices Ltd", 2450),
        ("INV-2026-003", "Design Studio Pro", 800),
        ("INV-2026-004", "Legal Associates LLP", 5500),
        ("INV-2026-005", "Marketing Agency X", 1200),
    ]

    for inv, vendor, amount in samples:
        c.execute("""
        INSERT OR IGNORE INTO invoices
        (invoice_number, vendor_name, amount)
        VALUES (?, ?, ?)
        """, (inv, vendor, amount))

    conn.commit()
    conn.close()


# ─────────────────────────────
# FAST READ (OPTIMIZED)
# ─────────────────────────────
def get_all_invoices():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM invoices ORDER BY submitted_at DESC"
    ).fetchall()
    conn.close()

    # SAFE + FAST conversion
    return [dict(row) for row in rows] if rows else []


def get_invoice(invoice_number: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM invoices WHERE invoice_number=?",
        (invoice_number,)
    ).fetchone()
    conn.close()

    return dict(row) if row else None


# ─────────────────────────────
# UPDATE STATUS
# ─────────────────────────────
def update_invoice_status(invoice_number: str, status: str,
                          approved_by="AI_AGENT", notes=""):

    conn = get_connection()
    conn.execute("""
    UPDATE invoices
    SET status=?, processed_at=?, approved_by=?, notes=?
    WHERE invoice_number=?
    """, (
        status,
        datetime.now().isoformat(),
        approved_by,
        notes,
        invoice_number
    ))
    conn.commit()
    conn.close()
    return True


# ─────────────────────────────
# LOGGING
# ─────────────────────────────
def log_approval_action(invoice_number, action, reason, performed_by="AI_AGENT"):
    conn = get_connection()

    inv = conn.execute(
        "SELECT id FROM invoices WHERE invoice_number=?",
        (invoice_number,)
    ).fetchone()

    inv_id = inv["id"] if inv else None

    conn.execute("""
    INSERT INTO approval_log
    (invoice_id, invoice_number, action, reason, performed_by)
    VALUES (?, ?, ?, ?, ?)
    """, (inv_id, invoice_number, action, reason, performed_by))

    conn.commit()
    conn.close()


def log_notification(invoice_number, channel, message, status="sent"):
    conn = get_connection()

    conn.execute("""
    INSERT INTO notifications
    (invoice_number, channel, message, status)
    VALUES (?, ?, ?, ?)
    """, (invoice_number, channel, message, status))

    conn.commit()
    conn.close()


def get_approval_log():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM approval_log ORDER BY timestamp DESC LIMIT 50"
    ).fetchall()
    conn.close()

    return [dict(r) for r in rows] if rows else []


# ─────────────────────────────
# AUTO INIT
# ─────────────────────────────
init_db()
seed_sample_invoices()