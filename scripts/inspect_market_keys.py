"""Inspect canonical symbol keys in the market_prices DuckDB table.

Verifies the canonical-key invariant: rows are keyed by the internal
FinCortext symbol (e.g. 'TCS'), never the provider ticker ('TCS.NS').
Provider-ticker keys make every read path (prices, status, agents) return
zero rows even though refresh reports rows stored.

Run from anywhere:  python scripts/inspect_market_keys.py
"""

import duckdb

DB = r"d:\KODERRRR\FinCortext\data\processed\fincortext.duckdb"

con = duckdb.connect(DB, read_only=True)

print("=== distinct symbol keys in market_prices ===")
rows = con.execute(
    "SELECT symbol, COUNT(*) AS n, MIN(trade_date) AS first, MAX(trade_date) AS last "
    "FROM market_prices GROUP BY symbol ORDER BY symbol"
).fetchall()
for row in rows:
    print(row)

print()
print("=== count WHERE symbol = 'TCS'  (what the API/agents query) ===")
print(con.execute("SELECT COUNT(*) FROM market_prices WHERE symbol = 'TCS'").fetchone()[0])

print()
print("=== count WHERE symbol = 'TCS.NS' (must be 0 — provider ticker) ===")
print(con.execute("SELECT COUNT(*) FROM market_prices WHERE symbol = 'TCS.NS'").fetchone()[0])

con.close()
