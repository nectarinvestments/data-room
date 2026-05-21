"""Build SQL VALUES lists for deal_payment_schedule and deal_dpd from the two
LoanPro CSVs that were exported for loan 1108.

Inputs:
    C:\\Users\\lisul\\Downloads\\Payment_Schedule (1).csv
    C:\\Users\\lisul\\Downloads\\Loan_Pro_Payments (4).csv

Output: prints two SQL VALUES blocks to stdout.

Merging logic for deal_dpd:
- Scheduled payments come from Payment_Schedule, one row per pmt_num.
- Actual collections come from Loan_Pro_Payments. Rows with Note containing
  "Temp Reversed" are dropped. Allocation uses Principal Payment + Fee Payment
  (so pure compliance/NSF fees do not reduce loan balance).
- Actuals are sorted oldest-first and applied FIFO against the cumulative
  scheduled balance. The actual that pushes cum_actual >= cum_sched[n]
  "resolves" scheduled payment n; its date is resolved_date.
- dpd_today = (today - due_date) if unresolved else resolved_dpd.
"""

import csv
import re
from datetime import date, datetime
from pathlib import Path

SCHED_PATH = Path(r"C:\Users\lisul\Downloads\Payment_Schedule (1).csv")
ACTUAL_PATH = Path(r"C:\Users\lisul\Downloads\Loan_Pro_Payments (4).csv")
TODAY = date(2026, 5, 19)
DEAL_ID = 1108


def parse_money(s):
    if s is None:
        return 0.0
    s = s.strip().strip('"').replace("$", "").replace(",", "")
    if s == "" or s.lower() == "nan":
        return 0.0
    return float(s)


def parse_mdy(s):
    s = s.strip().strip('"')
    if not s:
        return None
    return datetime.strptime(s, "%m-%d-%Y").date()


# --- read scheduled payments ---
sched_rows = []  # list of dicts
with SCHED_PATH.open(newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for r in reader:
        if not r.get("Payment #"):
            continue
        pmt_num = int(r["Payment #"])
        due_date = parse_mdy(r["Payment Date"])
        sched_amt = parse_money(r["Payment Amount"])
        actual_pf = parse_money(r["*Actual Principal+Fee Received"])
        month_str = due_date.strftime("%Y-%m")
        sched_rows.append({
            "pmt_num": pmt_num,
            "due_date": due_date,
            "month_str": month_str,
            "sched_amt": sched_amt,
            "actual_pf_from_sched": actual_pf,
        })

sched_rows.sort(key=lambda x: x["pmt_num"])

# --- read actual payments ---
actuals = []
with ACTUAL_PATH.open(newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for r in reader:
        note = (r.get("Note") or "").strip()
        if "reversed" in note.lower():
            continue
        d = parse_mdy(r["Payment Date"])
        if d is None:
            continue
        prin = parse_money(r.get("Principal Payment"))
        fee = parse_money(r.get("Fee Payment"))
        pf = prin + fee
        # Skip fee-only events (NSF/compliance) — they don't satisfy schedule.
        if pf <= 0:
            continue
        actuals.append({"date": d, "pf": pf})

actuals.sort(key=lambda x: x["date"])  # FIFO

# --- FIFO allocation of actuals to scheduled payments ---
cum_sched = 0.0
cum_actual = 0.0
actual_idx = 0
prev_cum_actual = 0.0
prev_date = None

results = []
for s in sched_rows:
    cum_sched += s["sched_amt"]
    # advance actuals until cum_actual >= cum_sched (or run out)
    while actual_idx < len(actuals) and cum_actual < cum_sched:
        prev_cum_actual = cum_actual
        cum_actual += actuals[actual_idx]["pf"]
        prev_date = actuals[actual_idx]["date"]
        actual_idx += 1
    if cum_actual >= cum_sched:
        resolved_date = prev_date
        resolved_dpd = (resolved_date - s["due_date"]).days
        is_resolved = True
        dpd_today = resolved_dpd
    else:
        resolved_date = None
        resolved_dpd = None
        is_resolved = False
        dpd_today = (TODAY - s["due_date"]).days

    # actual_amt allocated to this scheduled payment = sched_amt if resolved,
    # else whatever fraction of cum_actual remains above prior cum_sched.
    prior_cum_sched = cum_sched - s["sched_amt"]
    actual_amt = max(0.0, min(s["sched_amt"], cum_actual - prior_cum_sched))

    results.append({
        **s,
        "actual_amt": round(actual_amt, 2),
        "dpd_today": dpd_today,
        "resolved_date": resolved_date,
        "resolved_dpd": resolved_dpd,
        "is_resolved": is_resolved,
    })


def sql_str(s):
    return "'" + s.replace("'", "''") + "'"


def sql_date(d):
    return "NULL" if d is None else sql_str(d.isoformat())


def sql_num(n):
    return "NULL" if n is None else str(n)


def sql_bool(b):
    return "TRUE" if b else "FALSE"


# --- emit deal_payment_schedule ---
print("-- deal_payment_schedule: (deal_id, pmt_num, month_str, sched_amt)")
print("INSERT INTO deal_payment_schedule (deal_id, pmt_num, month_str, sched_amt) VALUES")
sched_lines = []
for r in results:
    sched_lines.append(
        f"  ({DEAL_ID}, {r['pmt_num']}, {sql_str(r['month_str'])}, {r['sched_amt']:.2f})"
    )
print(",\n".join(sched_lines) + ";")
print()

# --- emit deal_dpd ---
print("-- deal_dpd: one row per scheduled payment merged with FIFO-allocated actuals")
print("INSERT INTO deal_dpd (deal_id, pmt_num, month_str, due_date, sched_amt, actual_amt, dpd_today, resolved_date, resolved_dpd, is_resolved) VALUES")
dpd_lines = []
for r in results:
    dpd_lines.append(
        f"  ({DEAL_ID}, {r['pmt_num']}, {sql_str(r['month_str'])}, "
        f"{sql_date(r['due_date'])}, {r['sched_amt']:.2f}, {r['actual_amt']:.2f}, "
        f"{sql_num(r['dpd_today'])}, {sql_date(r['resolved_date'])}, "
        f"{sql_num(r['resolved_dpd'])}, {sql_bool(r['is_resolved'])})"
    )
print(",\n".join(dpd_lines) + ";")
