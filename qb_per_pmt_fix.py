"""Emit a single SQL UPDATE that backfills deal_dpd.actual_amt from the
QuickBase schedule CSVs. Skips rows where *Actual Principal+Fee Received
is blank or zero so unpaid scheduled payments keep whatever value
production already has."""

import csv
import re
from pathlib import Path

FOLDER = Path(r"C:\Users\lisul\Downloads\Payment History-Schedule")
SCHEDULE_RE = re.compile(r"^(\d+)[- ]Payment Schedule\.csv$")


def parse_money(s):
    if s is None: return None
    s = s.strip().strip('"')
    if s == "": return None
    return float(s.replace("$", "").replace(",", ""))


rows = []  # (deal_id, pmt_num, actual_amt)
for f in sorted(FOLDER.glob("*.csv")):
    if not SCHEDULE_RE.match(f.name):
        continue
    with f.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            deal_id_s = (r.get("LoanPro ID") or "").strip()
            pmt_num_s = (r.get("Payment #") or "").strip()
            actual = parse_money(r.get("*Actual Principal+Fee Received"))
            if not deal_id_s or not pmt_num_s:
                continue
            if actual is None or actual == 0:
                continue
            rows.append((int(deal_id_s), int(pmt_num_s), actual))

rows.sort(key=lambda t: (t[0], t[1]))

print("WITH updates AS (")
print("  SELECT * FROM (VALUES")
tuples = [f"    ({d}, {p}, {a:.2f})" for d, p, a in rows]
print(",\n".join(tuples))
print("  ) AS t(deal_id, pmt_num, actual_amt)")
print(")")
print("UPDATE deal_dpd dd")
print("SET actual_amt = u.actual_amt")
print("FROM updates u")
print("WHERE dd.deal_id = u.deal_id AND dd.pmt_num = u.pmt_num;")
