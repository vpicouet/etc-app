"""bake_instruments.py — fetch the Google Sheet CSV and write data/instruments.js
as a fallback for when the browser cannot reach the sheet (file:// or CORS block).

Run:
    python3 scripts/bake_instruments.py
"""
import json, subprocess, sys
from pathlib import Path

SHEET_ID   = "1Ox0uxEm2TfgzYA6ivkTpU4xrmN5vO5kmnUPdCSt73uU"
SHEET_NAME = "instruments.csv"
OUT_JS     = Path(__file__).resolve().parent.parent / "data" / "instruments.js"

url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"
print(f"Fetching {url} ...")
result = subprocess.run(["curl", "-sL", "--max-time", "20", url], capture_output=True)
if result.returncode != 0:
    print("curl failed:", result.stderr.decode(), file=sys.stderr); sys.exit(1)
csv_text = result.stdout.decode("utf-8")

print(f"  {len(csv_text)} bytes received")

# Minimal CSV parse (same logic as the JS loadInstruments)
import csv, io
rows = list(csv.reader(io.StringIO(csv_text)))
if len(rows) < 2:
    raise ValueError("Sheet is empty")

header      = rows[0]
instr_names = [n.strip() for n in header[3:] if n.strip()]
char_units  = {}
instr_dict  = {n: {} for n in instr_names}

for row in rows[1:]:
    key = row[1].strip() if len(row) > 1 else ""
    if not key:
        continue
    unit = row[2].strip() if len(row) > 2 else ""
    char_units[key] = unit
    for c, name in enumerate(instr_names):
        raw = row[3 + c].strip() if (3 + c) < len(row) else ""
        if not raw:
            continue
        try:
            instr_dict[name][key] = float(raw)
        except ValueError:
            instr_dict[name][key] = raw

payload = {"colnames": instr_names, "char_units": char_units, "dict": instr_dict}
js = "window.INSTRUMENTS_BAKED=" + json.dumps(payload, separators=(",", ":")) + ";"
OUT_JS.write_text(js, encoding="utf-8")
print(f"Wrote {OUT_JS}  ({OUT_JS.stat().st_size/1024:.1f} KB, {len(instr_names)} instruments)")
