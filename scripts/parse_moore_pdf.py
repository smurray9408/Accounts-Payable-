#!/usr/bin/env python3
"""
Parse Moore Supply invoice PDFs directly (via PyMuPDF) into the same structured
line-item JSONL that parse_moore_invoices.py emits from extracted text.

Reading the PDF directly avoids the 100k-character cap that truncates large
invoices when their text is pulled through the SharePoint/Graph reader. Use this
whenever the actual PDF files are available on disk.

Layout: each page prints the columns as separate label blocks — ITEM NUMBER,
PRODUCT DESCRIPTION, QTY ORDERED, QTY SHIPPED, UNIT PRICE, UNIT, NET AMOUNT —
each followed by its values one per line, in line order. A single invoice may
span pages; an order shipped in parts appears as generations .001, .002, ...

Usage:
    python3 scripts/parse_moore_pdf.py PDF_DIR_OR_FILE... OUT.jsonl
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
import fitz  # PyMuPDF

MONEY = re.compile(r"-?[\d,]+\.\d+")


def money(s):
    return float(s.replace(",", ""))


def block(text, label, nextlabels):
    """Return the lines between `label` and the next of nextlabels."""
    i = text.find(label)
    if i < 0:
        return []
    i += len(label)
    ends = [text.find(n, i) for n in nextlabels]
    ends = [e for e in ends if e >= 0]
    j = min(ends) if ends else len(text)
    return [x.strip() for x in text[i:j].split("\n") if x.strip()]


def parse_invoice_text(t):
    inv = re.search(r"INVOICE NUMBER\s*\n(\S+)", t)
    if not inv:
        return None
    rec = {"invoice_number": inv.group(1)}
    def g(pat):
        m = re.search(pat, t)
        return m.group(1) if m else None
    rec["invoice_date"] = g(r"INVOICE DATE\s*\n(\d\d/\d\d/\d\d)")
    rec["customer_po"] = g(r"CUSTOMER P\.O\.\s*\n(\S+)")
    rec["doc_type"] = "CREDIT MEMO" if "CREDIT MEMO" in t else "INVOICE"
    for k, pat in (("subtotal", r"SUBTOTAL\s*\n(" + MONEY.pattern + r")"),
                   ("sales_tax", r"SALES TAX\s*\n(" + MONEY.pattern + r")"),
                   ("amount_due", r"AMOUNT DUE\s*\n(" + MONEY.pattern + r")")):
        m = re.search(pat, t)
        rec[k] = money(m.group(1)) if m else None
    return rec


def parse_pdf(path):
    doc = fitz.open(path)
    # split concatenated invoices by INVOICE NUMBER occurrences across all pages
    full = "\n".join(p.get_text() for p in doc)
    # A file here is one invoice (may be multi-page); handle multiple just in case
    inv_positions = [m.start() for m in re.finditer(r"INVOICE NUMBER\s*\n\S+", full)]
    # group all pages of the same invoice number together
    items, qo, qs, up, units, na = [], [], [], [], [], []
    labels = ["PRODUCT DESCRIPTION", "QTY", "UNIT PRICE", "UNIT", "NET AMOUNT",
              "ITEM", "INVOICE TERMS", "Page"]
    for page in doc:
        t = page.get_text()
        items += block(t, "ITEM\nNUMBER\n", ["PRODUCT DESCRIPTION"])
        qo += [x for x in block(t, "QTY\nORDERED\n", ["QTY\nSHIPPED"])]
        qs += [x for x in block(t, "QTY\nSHIPPED\n", ["UNIT PRICE"])]
        up += [x for x in block(t, "UNIT PRICE\n", ["\nUNIT\n"]) if MONEY.fullmatch(x)]
        na += [x for x in block(t, "NET AMOUNT\n", ["INVOICE TERMS", "Page", "741 MOORE"]) if MONEY.fullmatch(x)]
    head = parse_invoice_text(full)
    if not head:
        return []
    lines = []
    n = len(items)
    if len(qs) == len(up) == len(na) == n and n:
        for k in range(n):
            qty = float(re.sub(r"[A-Za-z]+", "", qs[k]))
            unit = re.sub(r"[-\d.]+", "", qs[k]) or None
            lines.append({
                "item_number": items[k],
                "qty_ordered": float(re.sub(r"[A-Za-z]+", "", qo[k])) if k < len(qo) else None,
                "qty_shipped": qty, "unit": unit,
                "unit_price": money(up[k]), "net_amount": money(na[k]),
            })
        head["flags"] = []
    else:
        head["flags"] = [f"misaligned: item={n} qs={len(qs)} up={len(up)} na={len(na)}"]
    head["source_file"] = Path(path).name
    head["line_items"] = lines
    head["line_sum"] = round(sum(l["net_amount"] for l in lines), 2)
    if head["subtotal"] is not None and abs(head["line_sum"] - head["subtotal"]) > 0.02:
        head["flags"].append(f"subtotal_mismatch lines={head['line_sum']} sub={head['subtotal']}")
    return [head]


def main():
    *inputs, out = sys.argv[1:]
    paths = []
    for p in inputs:
        p = Path(p)
        paths += sorted(p.glob("*.pdf")) if p.is_dir() else [p]
    recs = []
    for p in paths:
        recs += parse_pdf(str(p))
    with open(out, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    flagged = [r for r in recs if r.get("flags")]
    print(f"parsed {len(recs)} invoices, {sum(len(r['line_items']) for r in recs)} lines, {len(flagged)} flagged")
    for r in flagged:
        print("  FLAG", r["invoice_number"], r["flags"])


if __name__ == "__main__":
    main()
