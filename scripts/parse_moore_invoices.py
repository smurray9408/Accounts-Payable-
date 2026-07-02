#!/usr/bin/env python3
"""
Parse Moore Supply (Hajoca/Billtrust) invoice PDFs into structured line items.

Input is the *text extraction* of each invoice PDF (one physical page per line
of the text file). A single PDF file bundles many invoices, and one invoice may
span multiple pages. Each invoice carries a CUSTOMER P.O. that ties it back to
the QuickBooks purchase-order number.

For every invoice this extracts the header (invoice #, date, doc type, customer
PO, subtotal / tax / amount due) and the per-line arrays that appear as parallel
columns on the page: ITEM NUMBER, QTY ORDERED, QTY SHIPPED, UNIT PRICE, UNIT,
NET AMOUNT. The columns are position-aligned, so line k is
(item_number[k], qty_shipped[k], unit_price[k], net_amount[k]).

Each invoice is validated: the sum of its line NET AMOUNTs must equal the
printed SUBTOTAL (within a cent). Parse failures are reported, never hidden.

Usage:
    python3 scripts/parse_moore_invoices.py RAWDIR OUT.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MONEY = r"-?[\d,]+\.\d+"


def money(s: str) -> float:
    return float(s.replace(",", ""))


def _search(pat: str, text: str):
    m = re.search(pat, text)
    return m


def _between(text: str, start_end: int, stop: int) -> str:
    if start_end < 0 or stop < 0 or stop < start_end:
        return ""
    return text[start_end:stop]


def parse_page(page: str):
    """Return (header_dict, list_of_line_tuples) for one physical page."""
    inv = _search(r"INVOICE\s+NUMBER\s+(\S+)", page)
    if not inv:
        return None, []
    header = {
        "invoice_number": inv.group(1),
    }
    m = _search(r"INVOICE\s+DATE\s+(\d\d/\d\d/\d\d)", page)
    header["invoice_date"] = m.group(1) if m else None
    m = _search(r"CUSTOMER\s+P\.?\s*O\.?\s+(\S+)", page)
    header["customer_po"] = m.group(1) if m else None
    m = _search(r"JOB\s+NAME\s+(.*?)\s+JOB\s+NUMBER", page)
    header["job_name"] = m.group(1).strip() if m else None
    # Doc type: the word CREDIT MEMO / INVOICE printed near the remit block.
    header["doc_type"] = "CREDIT MEMO" if re.search(r"CREDIT\s+MEMO", page) else "INVOICE"
    for key, pat in (
        ("subtotal", r"SUBTOTAL\s+(" + MONEY + r")"),
        ("sales_tax", r"SALES\s+TAX\s+(" + MONEY + r")"),
        ("amount_due", r"AMOUNT\s+DUE\s+(" + MONEY + r")"),
    ):
        m = _search(pat, page)
        header[key] = money(m.group(1)) if m else None
    m = _search(r"Page\s+(\d+)\s+of\s+(\d+)", page)
    header["page"] = (int(m.group(1)), int(m.group(2))) if m else (1, 1)

    # --- locate the column-header labels (positions) ---
    def pos(pat, frm=0):
        m = re.compile(pat).search(page, frm)
        return m.start() if m else -1, (m.end() if m else -1)

    i_item_s, i_item_e = pos(r"ITEM\s+NUMBER")
    i_desc_s, i_desc_e = pos(r"PRODUCT\s+DESCRIPTION")
    i_qo_s, i_qo_e = pos(r"QTY\s+ORDERED")
    i_qs_s, i_qs_e = pos(r"QTY\s+SHIPPED")
    i_up_s, i_up_e = pos(r"UNIT\s+PRICE")
    i_na_s, i_na_e = pos(r"NET\s+AMOUNT")
    if min(i_item_e, i_desc_s, i_qo_s, i_qs_s, i_up_s, i_na_s) < 0:
        return header, []  # header-only / no line grid on this page

    # standalone UNIT column label sits between UNIT PRICE values and NET AMOUNT
    i_unit_s = -1
    for m in re.finditer(r"UNIT", page):
        if i_up_e < m.start() < i_na_s and page[m.start():m.start() + 9] != "UNIT   PR" \
           and not page[m.start():].startswith("UNIT   PRICE"):
            i_unit_s = m.start()
    i_unit_e = i_unit_s + 4 if i_unit_s >= 0 else -1

    items = re.findall(r"\S+", _between(page, i_item_e, i_desc_s))
    qo = re.findall(r"(-?\d+(?:\.\d+)?)([A-Za-z]+)", _between(page, i_qo_e, i_qs_s))
    qs = re.findall(r"(-?\d+(?:\.\d+)?)([A-Za-z]+)", _between(page, i_qs_e, i_up_s))
    up = re.findall(MONEY, _between(page, i_up_e, i_unit_s if i_unit_s > 0 else i_na_s))
    na_region = page[i_na_e:]
    na_region = re.split(r"Page\s+\d+\s+of|\s+INVOICE\s+TERMS", na_region)[0]
    na = re.findall(MONEY, na_region)

    n = len(items)
    lines = []
    # Only keep lines where all parallel arrays agree in length with item count.
    if not (len(qs) == len(up) == len(na) == n) or n == 0:
        # Return a marker so the caller can flag this page for review.
        return header, [{"_MISALIGNED_": True,
                         "counts": {"item": n, "qty_ord": len(qo), "qty_shp": len(qs),
                                    "unit_price": len(up), "net": len(na)}}]
    for k in range(n):
        lines.append({
            "item_number": items[k],
            "qty_ordered": float(qo[k][0]) if k < len(qo) else None,
            "qty_shipped": float(qs[k][0]),
            "unit": qs[k][1] if k < len(qs) else None,
            "unit_price": money(up[k]),
            "net_amount": money(na[k]),
        })
    return header, lines


def parse_file(path: Path):
    pages = path.read_text().split("\n")
    invoices = {}  # invoice_number -> record
    order = []
    for raw in pages:
        page = raw
        # strip leading "<n>\t" that Read/cat-n style may add
        page = re.sub(r"^\s*\d+\t", "", page)
        if "INVOICE   NUMBER" not in page and "INVOICE NUMBER" not in page:
            continue
        header, lines = parse_page(page)
        if not header:
            continue
        inv = header["invoice_number"]
        if inv not in invoices:
            invoices[inv] = {
                "source_file": path.name,
                "invoice_number": inv,
                "invoice_date": header["invoice_date"],
                "doc_type": header["doc_type"],
                "customer_po": header["customer_po"],
                "job_name": header["job_name"],
                "subtotal": None, "sales_tax": None, "amount_due": None,
                "line_items": [], "flags": [],
            }
            order.append(inv)
        rec = invoices[inv]
        if header["customer_po"] and not rec["customer_po"]:
            rec["customer_po"] = header["customer_po"]
        for key in ("subtotal", "sales_tax", "amount_due"):
            if header[key] is not None:
                rec[key] = header[key]
        for ln in lines:
            if ln.get("_MISALIGNED_"):
                rec["flags"].append("misaligned_page:" + json.dumps(ln["counts"]))
            else:
                rec["line_items"].append(ln)
    # validate
    for inv in order:
        rec = invoices[inv]
        line_sum = round(sum(l["net_amount"] for l in rec["line_items"]), 2)
        rec["line_sum"] = line_sum
        if rec["subtotal"] is not None and abs(line_sum - rec["subtotal"]) > 0.02:
            rec["flags"].append(f"subtotal_mismatch: lines={line_sum} subtotal={rec['subtotal']}")
    return [invoices[i] for i in order]


def main():
    rawdir = Path(sys.argv[1])
    out = Path(sys.argv[2])
    all_inv = []
    for f in sorted(rawdir.glob("*.txt")):
        all_inv.extend(parse_file(f))
    with out.open("w") as fh:
        for rec in all_inv:
            fh.write(json.dumps(rec) + "\n")
    # summary
    n_lines = sum(len(r["line_items"]) for r in all_inv)
    flagged = [r for r in all_inv if r["flags"]]
    print(f"invoices={len(all_inv)} line_items={n_lines} flagged={len(flagged)}")
    for r in flagged:
        print("  FLAG", r["invoice_number"], r["source_file"], r["flags"])


if __name__ == "__main__":
    main()
