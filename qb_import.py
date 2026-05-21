"""Build SQL INSERTs for audit.qb_payment_schedule and audit.qb_payment_history
from the six QuickBase CSVs in C:\\Users\\lisul\\Downloads\\Payment History-Schedule\\.

SQL goes to stdout. Sanity checks + parse errors go to stderr.
Run:  py qb_import.py > qb_import.sql 2> qb_import.errors.log
"""

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

FOLDER = Path(r"C:\Users\lisul\Downloads\Payment History-Schedule")

# ── value parsers ───────────────────────────────────────────────────────────
def parse_money(s):
    if s is None: return None
    s = s.strip().strip('"')
    if s == "": return None
    return float(s.replace("$", "").replace(",", ""))

def parse_date(s):
    if s is None: return None
    s = s.strip().strip('"')
    if s == "": return None
    return datetime.strptime(s, "%m-%d-%Y").date().isoformat()

def parse_int(s):
    if s is None: return None
    s = s.strip().strip('"')
    if s == "": return None
    return int(s.replace(",", ""))

def parse_bigint(s):
    return parse_int(s)

def parse_float(s):
    if s is None: return None
    s = s.strip().strip('"')
    if s == "": return None
    return float(s)

def parse_text(s):
    # Empty/blank text → NULL (consistent with the rest of the spec).
    # Non-empty text is preserved verbatim; SQL-escaping of single quotes
    # is done at format time in sql_value().
    if s is None: return None
    if s.strip() == "": return None
    return s

# ── SQL value formatter ────────────────────────────────────────────────────
def sql_str(s):
    return "'" + s.replace("'", "''") + "'"

def sql_value(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, dict):
        # raw JSONB column
        return sql_str(json.dumps(v, ensure_ascii=False)) + "::jsonb"
    if isinstance(v, str):
        return sql_str(v)
    raise TypeError(f"Unknown type for SQL value: {type(v).__name__}")

# ── target table columns (order matters; matches the INSERT) ───────────────
SCHEDULE_COLS = [
    "deal_id", "related_application", "pmt_num", "payment_date", "mod_pmnt_date",
    "f_pmnt_date", "payment_amount", "mod_amount", "f_amount", "principal", "fee",
    "buyback_option", "cum_scheduled_payments", "original_xirr", "is_next_payment",
    "past_payment", "actual_principal_fee_received", "cum_sum_actual_prin_fee_pmnts",
    "paid_off", "note", "vintage_loan_payment", "pmnt_schedule_id",
    "total_speedchex_amount", "num_speedchex", "speedchex_current_status",
    "raw", "source_file",
]

HISTORY_COLS = [
    "deal_id", "payment_system_id", "payment_date", "amount", "principal_payment",
    "fee_payment", "nsf_fee", "compliance_fee", "new_other_fee", "total_split_pct",
    "reverse", "method", "reserve_replenishment", "note",
    "raw", "source_file",
]

# ── per-CSV row transforms (column-by-column type cast) ────────────────────
def transform_schedule_row(r, source_file):
    return [
        parse_int(r.get("LoanPro ID")),                              # deal_id
        parse_text(r.get("Related Application")),
        parse_int(r.get("Payment #")),
        parse_date(r.get("Payment Date")),
        parse_date(r.get("Mod Pmnt Date")),
        parse_date(r.get("F Pmnt Date")),
        parse_money(r.get("Payment Amount")),
        parse_money(r.get("Mod Amount")),
        parse_money(r.get("F Amount")),
        parse_money(r.get("Principal")),
        parse_money(r.get("Fee")),
        parse_money(r.get("BuyBack Option")),
        parse_money(r.get("Cum Scheduled Payments")),
        parse_float(r.get("Original XIRR")),
        parse_text(r.get("Is Next Payment")),
        parse_text(r.get("Past Payment")),
        parse_money(r.get("*Actual Principal+Fee Received")),
        parse_money(r.get("Cum Sum of Actual Prin+Fee Pmnts")),
        parse_text(r.get("Paid Off")),
        parse_text(r.get("Note")),
        parse_text(r.get("Vintage Loan / Payment")),
        parse_int(r.get("PmntScheduleID")),
        parse_money(r.get("Total Speedchex Amount")),
        parse_int(r.get("# of Speedchex")),
        parse_text(r.get("Speedchex Current Status")),
        dict(r),                                                     # raw JSONB
        source_file,
    ]

def transform_history_row(r, deal_id, source_file):
    return [
        deal_id,                                                     # from filename
        parse_bigint(r.get("Payment System Id")),
        parse_date(r.get("Payment Date")),
        parse_money(r.get("Amount")),
        parse_money(r.get("Principal Payment")),
        parse_money(r.get("Fee Payment")),
        parse_money(r.get("NSF-Fee")),
        parse_money(r.get("Compliance Fee")),
        parse_money(r.get("New Other Fee")),
        parse_text(r.get("Total Split %")),
        parse_text(r.get("Reverse")),
        parse_text(r.get("Method")),
        parse_text(r.get("Reserve Replenishment")),
        parse_text(r.get("Note")),
        dict(r),                                                     # raw JSONB
        source_file,
    ]

# ── SQL emitter ────────────────────────────────────────────────────────────
def emit_block(table, cols, source_file, rows, fh=None):
    if not rows:
        return
    out = fh if fh is not None else sys.stdout
    print(f"-- {table} from {source_file} ({len(rows)} rows)", file=out)
    print(f"INSERT INTO {table} (", file=out)
    print("  " + ", ".join(cols), file=out)
    print(") VALUES", file=out)
    lines = ["  (" + ", ".join(sql_value(v) for v in vals) + ")" for vals in rows]
    print(",\n".join(lines) + ";", file=out)
    print(file=out)


def emit_split(schedule_blocks, history_blocks, out_dir):
    """One SQL file per deal_id, named qb_import_{deal_id}.sql."""
    from collections import defaultdict
    by_deal = defaultdict(lambda: {"schedule": [], "history": [], "sources": set()})
    for source_file, rows in schedule_blocks:
        for vals in rows:
            d_id = vals[0]
            by_deal[d_id]["schedule"].append(vals)
            by_deal[d_id]["sources"].add(source_file)
    for source_file, rows in history_blocks:
        for vals in rows:
            d_id = vals[0]
            by_deal[d_id]["history"].append(vals)
            by_deal[d_id]["sources"].add(source_file)

    written = []
    for d_id in sorted(by_deal):
        data = by_deal[d_id]
        path = out_dir / f"qb_import_{d_id}.sql"
        with path.open("w", encoding="utf-8") as fh:
            print(f"-- Deal {d_id}", file=fh)
            print(f"-- Sources: {', '.join(sorted(data['sources']))}", file=fh)
            print(f"-- Schedule rows: {len(data['schedule'])} | History rows: {len(data['history'])}", file=fh)
            print(file=fh)
            emit_block("audit.qb_payment_schedule", SCHEDULE_COLS, f"deal {d_id}", data["schedule"], fh=fh)
            emit_block("audit.qb_payment_history",  HISTORY_COLS,  f"deal {d_id}", data["history"],  fh=fh)
        written.append(path)
    return written

# ── main ───────────────────────────────────────────────────────────────────
HISTORY_RE  = re.compile(r"^(\d+)[- ]Payment History\.csv$")
SCHEDULE_RE = re.compile(r"^(\d+)[- ]Payment Schedule\.csv$")

def main():
    split_mode = "--split" in sys.argv[1:]

    if not FOLDER.is_dir():
        print(f"FATAL: folder not found: {FOLDER}", file=sys.stderr)
        sys.exit(1)

    schedule_blocks = []  # [(source_file, [row_vals, ...])]
    history_blocks  = []
    schedule_counts = {}
    history_counts  = {}
    parse_errors    = []

    for f in sorted(FOLDER.glob("*.csv")):
        hm = HISTORY_RE.match(f.name)
        sm = SCHEDULE_RE.match(f.name)
        if not (hm or sm):
            print(f"SKIP unknown filename pattern: {f.name}", file=sys.stderr)
            continue

        is_history = hm is not None
        filename_deal_id = int((hm or sm).group(1))
        rows = []
        with f.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                try:
                    if is_history:
                        vals = transform_history_row(raw, filename_deal_id, f.name)
                        d_id = filename_deal_id
                        history_counts[d_id] = history_counts.get(d_id, 0) + 1
                    else:
                        vals = transform_schedule_row(raw, f.name)
                        d_id = vals[0]  # deal_id from LoanPro ID column
                        if d_id != filename_deal_id:
                            print(
                                f"WARN {f.name} line {reader.line_num}: "
                                f"LoanPro ID={d_id} disagrees with filename deal {filename_deal_id}",
                                file=sys.stderr,
                            )
                        schedule_counts[d_id] = schedule_counts.get(d_id, 0) + 1
                    rows.append(vals)
                except Exception as e:
                    parse_errors.append((f.name, reader.line_num, repr(e), dict(raw)))

        (history_blocks if is_history else schedule_blocks).append((f.name, rows))

    # ---- SQL output ----
    if split_mode:
        out_dir = Path(__file__).resolve().parent
        written = emit_split(schedule_blocks, history_blocks, out_dir)
        print(f"Wrote {len(written)} per-deal SQL files to {out_dir}", file=sys.stderr)
        for p in written:
            print(f"  {p.name}", file=sys.stderr)
        print(file=sys.stderr)
    else:
        print("-- Generated by qb_import.py")
        print("-- Target tables: audit.qb_payment_schedule, audit.qb_payment_history")
        print()
        for source_file, rows in schedule_blocks:
            emit_block("audit.qb_payment_schedule", SCHEDULE_COLS, source_file, rows)
        for source_file, rows in history_blocks:
            emit_block("audit.qb_payment_history", HISTORY_COLS, source_file, rows)

    # ---- sanity checks (stderr) ----
    print("=== Row counts ===", file=sys.stderr)
    print(f"Schedule by deal_id: {dict(sorted(schedule_counts.items()))}", file=sys.stderr)
    print(f"History  by deal_id: {dict(sorted(history_counts.items()))}",  file=sys.stderr)
    print("Expected schedule: {1068: 16, 1069: 16, 1108: 24}", file=sys.stderr)
    print("Expected history:  {1068: 17, 1069: 17, 1108: 36}", file=sys.stderr)
    # The expected pin is for the original 3 deals; extras are allowed.
    EXP_SCHED = {1068: 16, 1069: 16, 1108: 24}
    EXP_HIST  = {1068: 17, 1069: 17, 1108: 36}
    sched_ok = all(schedule_counts.get(k) == v for k, v in EXP_SCHED.items())
    hist_ok  = all(history_counts.get(k)  == v for k, v in EXP_HIST.items())
    print(f"Original 3 schedule counts intact: {sched_ok}", file=sys.stderr)
    print(f"Original 3 history  counts intact: {hist_ok}",  file=sys.stderr)
    print(file=sys.stderr)

    if parse_errors:
        print(f"=== Parse errors ({len(parse_errors)}) ===", file=sys.stderr)
        for fname, lineno, err, row in parse_errors:
            print(f"  {fname} line {lineno}: {err}", file=sys.stderr)
            print(f"    row: {row}", file=sys.stderr)
    else:
        print("=== No parse errors ===", file=sys.stderr)


if __name__ == "__main__":
    main()
