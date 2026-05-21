"""Emit a single UPSERT into audit.qb_principal_data from the QuickBase
schedule CSVs. One row per (deal_id, pmt_num) with payment_amount,
principal, actual_received. Skips rows where Principal is blank or zero."""

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


def sql_num(n):
    return "NULL" if n is None else f"{n:.2f}"


rows = []  # (deal_id, pmt_num, payment_amount, principal, actual_received)
for f in sorted(FOLDER.glob("*.csv")):
    if not SCHEDULE_RE.match(f.name):
        continue
    with f.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            deal_id_s = (r.get("LoanPro ID") or "").strip()
            pmt_num_s = (r.get("Payment #") or "").strip()
            principal = parse_money(r.get("Principal"))
            if not deal_id_s or not pmt_num_s:
                continue
            if principal is None or principal == 0:
                continue
            payment_amount = parse_money(r.get("Payment Amount"))
            actual_received = parse_money(r.get("*Actual Principal+Fee Received"))
            rows.append((
                int(deal_id_s),
                int(pmt_num_s),
                payment_amount,
                principal,
                actual_received,
            ))

rows.sort(key=lambda t: (t[0], t[1]))

print("INSERT INTO audit.qb_principal_data (deal_id, pmt_num, payment_amount, principal, actual_received)")
print("VALUES")
tuples = [
    f"  ({d}, {p}, {sql_num(pa)}, {sql_num(pr)}, {sql_num(ar)})"
    for d, p, pa, pr, ar in rows
]
print(",\n".join(tuples))
print("ON CONFLICT (deal_id, pmt_num) DO UPDATE SET")
print("  payment_amount = EXCLUDED.payment_amount,")
print("  principal = EXCLUDED.principal,")
print("  actual_received = EXCLUDED.actual_received;")
