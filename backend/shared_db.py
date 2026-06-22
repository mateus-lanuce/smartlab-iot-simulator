import sqlite3
import os
import json
from datetime import datetime, timedelta

DB_DIR = "data"
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "database.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    # Ativa o modo WAL (Write-Ahead Logging) para permitir leitura concorrente com escrita
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS digital_twins (
            device_id TEXT PRIMARY KEY,
            lab_id TEXT NOT NULL,
            device_type TEXT NOT NULL,
            status TEXT NOT NULL,
            online BOOLEAN NOT NULL,
            last_update DATETIME NOT NULL,
            metrics_json TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT,
            lab_id TEXT NOT NULL,
            timestamp DATETIME NOT NULL,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lab_statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lab_id TEXT NOT NULL,
            timestamp DATETIME NOT NULL,
            cpu_avg REAL,
            ram_avg REAL,
            temp_avg REAL,
            active_pcs INTEGER,
            total_energy REAL
        )
    """)
    conn.commit()
    conn.close()
    print("Banco de dados SQLite central inicializado em modo WAL.")

def parse_interval(interval_str: str):
    if not interval_str:
        return None
    try:
        unit = interval_str[-1].lower()
        value = int(interval_str[:-1])
        if unit == 'h':
            return datetime.utcnow() - timedelta(hours=value)
        elif unit == 'm':
            return datetime.utcnow() - timedelta(minutes=value)
        elif unit == 'd':
            return datetime.utcnow() - timedelta(days=value)
    except Exception:
        pass
    return None

def save_event_to_db(device_id, lab_id, event_type, description, severity, timestamp):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO events_history (device_id, lab_id, timestamp, event_type, description, severity)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (device_id, lab_id, timestamp, event_type, description, severity))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao salvar evento: {e}")

def update_digital_twin_in_db(device_id, lab_id, device_type, status, online, metrics, timestamp):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO digital_twins (device_id, lab_id, device_type, status, online, last_update, metrics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                status=excluded.status,
                online=excluded.online,
                last_update=excluded.last_update,
                metrics_json=excluded.metrics_json
        """, (device_id, lab_id, device_type, status, online, timestamp, json.dumps(metrics)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao atualizar digital twin: {e}")

def save_lab_statistics_to_db(lab_id, timestamp, cpu_avg, ram_avg, temp_avg, active_pcs, total_energy):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO lab_statistics (lab_id, timestamp, cpu_avg, ram_avg, temp_avg, active_pcs, total_energy)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (lab_id, timestamp, cpu_avg, ram_avg, temp_avg, active_pcs, total_energy))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erro ao salvar estatisticas do lab: {e}")
