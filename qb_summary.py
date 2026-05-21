"""Per-deal reconciliation summary from the QuickBase CSVs.

For each deal_id, prints a markdown table with:
  - qb_history_total     : sum of Amount, excluding rows where Reverse='yes'
                           or Note contains 'revers' (case-insensitive)
  - qb_history_pmts      : count of those non-reversed history rows
  - qb_schedule_collected: sum of *Actual Principal+Fee Received from schedule
  - qb_schedule_pmts     : count of schedule rows where that field > 0
"""

import csv
import re
from collections import defaultdict
from pathlib import Path

FOLDER = Path(r"C:\Users\lisul\Downloads\Payment History-Schedule")
HISTORY_RE  = re.compile(r"^(\d+)[- ]Payment History\.csv$")
SCHEDULE_RE = re.compile(r"^(\d+)[- ]Payment Schedule\.csv$")


def parse_money(s):
    if s is None: return 0.0
    s = s.strip().strip('"')
    if s == "": return 0.0
    return float(s.replace("$", "").replace(",", ""))


def is_reversed(row):
    rev = (row.get("Reverse") or "").strip().lower()
    note = (row.get("Note") or "").lower()
    return rev == "yes" or "revers" in note


deals = defaultdict(lambda: {
    "history_total": 0.0,
    "history_pmts": 0,
    "schedule_collected": 0.0,
    "schedule_pmts": 0,
})

for f in sorted(FOLDER.glob("*.csv")):
    hm = HISTORY_RE.match(f.name)
    sm = SCHEDULE_RE.match(f.name)
    if not (hm or sm):
        continue

    if hm:
        deal_id = int(hm.group(1))
        with f.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if is_reversed(row):
                    continue
                deals[deal_id]["history_total"] += parse_money(row.get("Amount"))
                deals[deal_id]["history_pmts"]  += 1
    else:
        with f.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                deal_id_str = (row.get("LoanPro ID") or "").strip()
                if not deal_id_str:
                    continue
                d_id = int(deal_id_str)
                amt = parse_money(row.get("*Actual Principal+Fee Received"))
                deals[d_id]["schedule_collected"] += amt
                if amt > 0:
                    deals[d_id]["schedule_pmts"] += 1

# ── render markdown table ─────────────────────────────────────────────────
print("| deal_id | qb_history_total | qb_history_pmts | qb_schedule_collected | qb_schedule_pmts |")
print("|---:|---:|---:|---:|---:|")
for d_id in sorted(deals):
    d = deals[d_id]
    print(f"| {d_id} | {d['history_total']:.2f} | {d['history_pmts']} | "
          f"{d['schedule_collected']:.2f} | {d['schedule_pmts']} |")
