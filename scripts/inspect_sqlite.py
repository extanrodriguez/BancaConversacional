"""Inspect the demo SQLite database schema and sample data."""
import sqlite3

conn = sqlite3.connect(r"data/demo/modelo_bancario_genesis_v2.sqlite")
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

for t in tables:
    cur.execute(f"PRAGMA table_info({t})")
    cols = [(r[1], r[2]) for r in cur.fetchall()]
    print(f"\n{t}: {cols}")
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    print(f"  rows: {cur.fetchone()[0]}")
    cur.execute(f"SELECT * FROM {t} LIMIT 3")
    for row in cur.fetchall():
        print(f"  {row}")

conn.close()
