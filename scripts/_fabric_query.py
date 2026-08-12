"""Run a query against the Fabric Warehouse using the az login token. Diagnostic helper."""
import json
import os
import struct
import subprocess
import sys

import pyodbc

server = os.environ.get("FABRIC_SQL_ENDPOINT")
database = os.environ.get("FABRIC_WAREHOUSE", "WH_MerchantVoucher")
if not server:
    sys.exit("FABRIC_SQL_ENDPOINT not set — run:  . .\\dbt\\.env.fabric.ps1")

tok = json.loads(subprocess.run(
    ["az", "account", "get-access-token", "--resource", "https://database.windows.net/",
     "-o", "json"], capture_output=True, text=True, shell=True).stdout)["accessToken"]
raw = tok.encode("utf-16-le")
conn = pyodbc.connect(
    f"Driver={{ODBC Driver 17 for SQL Server}};Server={server};Database={database};"
    f"Encrypt=yes;TrustServerCertificate=no",
    attrs_before={1256: struct.pack(f"<I{len(raw)}s", len(raw), raw)}, autocommit=True)
cur = conn.cursor()

sql = " ".join(sys.argv[1:]) or """
    SELECT s.name AS [schema], t.name AS [table]
    FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id
    ORDER BY s.name, t.name"""
cur.execute(sql)
cols = [d[0] for d in cur.description]
rows = cur.fetchall()
w = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c))
     for i, c in enumerate(cols)]
print("  " + "  ".join(str(c).ljust(w[i]) for i, c in enumerate(cols)))
print("  " + "  ".join("-" * w[i] for i in range(len(cols))))
for r in rows:
    print("  " + "  ".join(str(v).ljust(w[i]) for i, v in enumerate(r)))
print(f"\n  {len(rows)} row(s)")
cur.close(); conn.close()
