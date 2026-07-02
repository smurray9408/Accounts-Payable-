#!/usr/bin/env python3
"""
Classify a Billtrust "Moore Supply" invoice CSV export into processing buckets.

This is the Phase-0 triage step of the AP automation: before anything posts to
QuickBooks, sort each exported invoice into how it should be handled.

  clean_charge : positive amount with a real (numeric) PO number
                 -> auto-match to the open QB PO and post a PO-linked bill
  credit       : negative amount (return / vendor credit)
                 -> apply as a vendor credit, not a bill
  exception    : non-numeric "PO" (e.g. MISC RETURNS, STOLEN MATERIAL) or an
                 order number in a different scheme -> human review

Usage:
    python3 scripts/classify_export.py MOORESUPPLYCO_*.csv
    python3 scripts/classify_export.py export.csv --write-buckets out/

The export contains vendor financial data; keep real exports OUT of version
control (see .gitignore).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

# QuickBooks POs in the documented workflow are 4-6 digit numbers (e.g. 52412).
REAL_PO = re.compile(r"\d{4,6}")

EXPECTED_COLUMNS = [
    "INVOICE_NUMBER", "INVOICE_DATE", "TOTAL_DUE", "PO_NUMBER",
    "DISCOUNT_MESSAGE", "DUE_DATE", "TERMS", "DISCOUNT_AMOUNT",
]


def is_real_po(value: str) -> bool:
    return bool(REAL_PO.fullmatch(value.strip()))


def to_amount(value: str) -> float:
    try:
        return float(value.replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def classify(row: dict) -> str:
    amount = to_amount(row.get("TOTAL_DUE", ""))
    if amount < 0:
        return "credit"
    if is_real_po(row.get("PO_NUMBER", "")):
        return "clean_charge"
    return "exception"


def load_rows(path: Path) -> list[dict]:
    # utf-8-sig handles the BOM Billtrust sometimes prepends.
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in EXPECTED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"ERROR: export is missing expected columns: {missing}\n"
                     f"Found: {reader.fieldnames}")
        return list(reader)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path", type=Path, help="Billtrust CSV export")
    ap.add_argument("--write-buckets", type=Path, metavar="DIR",
                    help="write clean_charge / credit / exception CSVs to DIR")
    args = ap.parse_args()

    rows = load_rows(args.csv_path)
    buckets: dict[str, list[dict]] = {"clean_charge": [], "credit": [], "exception": []}
    for row in rows:
        buckets[classify(row)].append(row)

    total = len(rows) or 1
    print(f"Billtrust export: {args.csv_path.name}")
    print(f"Total invoices: {len(rows)}\n")
    print(f"{'bucket':<14}{'count':>7}{'pct':>8}{'amount':>15}")
    print("-" * 44)
    for name in ("clean_charge", "credit", "exception"):
        b = buckets[name]
        amt = sum(to_amount(r["TOTAL_DUE"]) for r in b)
        print(f"{name:<14}{len(b):>7}{100*len(b)/total:>7.1f}%{amt:>15,.2f}")

    # multi-invoice POs signal partial receipts -> link to remaining PO balance.
    po_counts = Counter(r["PO_NUMBER"].strip()
                        for r in buckets["clean_charge"] if r["PO_NUMBER"].strip())
    multi = {p: c for p, c in po_counts.items() if c > 1}
    print(f"\nDistinct terms strings: {sorted(set(r['TERMS'] for r in rows))}")
    print(f"POs with >1 invoice (partial receipts): {len(multi)}")
    if buckets["exception"]:
        sample = sorted({r['PO_NUMBER'].strip() for r in buckets['exception']})[:10]
        print(f"Sample exception 'PO' values: {sample}")

    if args.write_buckets:
        args.write_buckets.mkdir(parents=True, exist_ok=True)
        for name, b in buckets.items():
            out = args.write_buckets / f"{name}.csv"
            with out.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(b)
            print(f"wrote {out} ({len(b)} rows)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
