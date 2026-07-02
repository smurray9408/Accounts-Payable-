#!/usr/bin/env python3
"""
Generate qbXML to post a Moore Supply invoice as a PO-linked Bill in QuickBooks
Enterprise -- the Phase-0 proof that job costing survives automation.

Why PO-linked: when a Bill links to a Purchase Order, QuickBooks pulls the PO's
line items into the bill AS-IS, including each line's Customer:Job and Class.
That is exactly what the manual "Select PO" step does, and it is what the flat
Billtrust IIF cannot do.

The QuickBooks Web Connector (or the SDK's "qbXML Test Tool") talks to the
company file for us. In production the flow is two round-trips:

    1. PurchaseOrderQuery(RefNumber = PO_NUMBER)  -> returns the PO's TxnID
    2. BillAdd(LinkToTxnID = that TxnID, RefNumber = INVOICE_NUMBER, ...)

This module builds both request documents. Because we have no live QB in this
environment, `bill-add` takes the PO TxnID as an argument (in production the
connector fills it in from step 1's response).

Usage:
    # Step 1: request to find the PO's TxnID
    python3 scripts/qbxml_billadd.py po-query --po 52412

    # Step 2: build the PO-linked bill for one invoice from the CSV
    python3 scripts/qbxml_billadd.py bill-add \\
        --csv MOORESUPPLYCO_*.csv --invoice S180579939.001 --po-txnid <TXNID>

Output is well-formed qbXML printed to stdout (or --out FILE).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from xml.dom import minidom
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MAPPING = REPO / "config" / "mapping.json"


def load_mapping(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_invoice(csv_path: Path, invoice_number: str) -> dict:
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row["INVOICE_NUMBER"].strip() == invoice_number:
                return row
    sys.exit(f"ERROR: invoice {invoice_number!r} not found in {csv_path}")


def mmddyy_to_iso(value: str) -> str:
    """Billtrust dates are MM/DD/YY; qbXML wants YYYY-MM-DD."""
    value = value.strip()
    mm, dd, yy = value.split("/")
    year = int(yy)
    year += 2000 if year < 100 else 0
    return f"{year:04d}-{int(mm):02d}-{int(dd):02d}"


def _wrap(qbxml_body: str, version: str) -> str:
    doc = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<?qbxml version="{version}"?>\n'
        f"<QBXML>{qbxml_body}</QBXML>"
    )
    # Reparse to guarantee well-formedness and pretty-print, then normalize the
    # header to exactly one xml decl + one qbxml PI (minidom's handling varies).
    pretty = minidom.parseString(doc).toprettyxml(indent="  ")
    body = [ln for ln in pretty.splitlines()
            if ln.strip() and not ln.lstrip().startswith("<?")]
    header = ['<?xml version="1.0" encoding="utf-8"?>',
              f'<?qbxml version="{version}"?>']
    return "\n".join(header + body) + "\n"


def build_po_query(po_number: str, mapping: dict) -> str:
    """Step 1: find the open PO by its number, including line items."""
    body = (
        '<QBXMLMsgsRq onError="stopOnError">'
        '<PurchaseOrderQueryRq requestID="1">'
        f"<RefNumber>{escape(po_number)}</RefNumber>"
        "<IncludeLineItems>true</IncludeLineItems>"
        "</PurchaseOrderQueryRq>"
        "</QBXMLMsgsRq>"
    )
    return _wrap(body, mapping["qbxml_version"])


def build_bill_add(row: dict, po_txnid: str, mapping: dict) -> str:
    """Step 2: create the Bill linked to the PO (lines + Job + Class carry over)."""
    vendor = escape(mapping["vendor_name"])
    invoice = escape(row["INVOICE_NUMBER"].strip())
    txn_date = mmddyy_to_iso(row["INVOICE_DATE"])
    due_date = mmddyy_to_iso(row["DUE_DATE"])

    raw_terms = row["TERMS"].strip()
    terms = mapping["terms_map"].get(raw_terms, raw_terms)

    po_number = row["PO_NUMBER"].strip()
    disc_msg = row.get("DISCOUNT_MESSAGE", "").strip()
    memo = f"PO {po_number} | {disc_msg}".strip(" |")

    # LinkToTxnID pulls ALL open lines from the PO, exactly like "Select PO".
    # Do NOT also send ItemLineAdd here -- for a full receipt the two conflict.
    # (For partial receipts, see docs/phase0-poc.md: use line-level LinkToTxn.)
    body = (
        '<QBXMLMsgsRq onError="stopOnError">'
        '<BillAddRq requestID="1">'
        "<BillAdd>"
        f"<VendorRef><FullName>{vendor}</FullName></VendorRef>"
        f"<APAccountRef><FullName>{escape(mapping['ap_account'])}</FullName></APAccountRef>"
        f"<TxnDate>{txn_date}</TxnDate>"
        f"<DueDate>{due_date}</DueDate>"
        f"<RefNumber>{invoice}</RefNumber>"
        f"<TermsRef><FullName>{escape(terms)}</FullName></TermsRef>"
        f"<Memo>{escape(memo)}</Memo>"
        f"<LinkToTxnID>{escape(po_txnid)}</LinkToTxnID>"
        "</BillAdd>"
        "</BillAddRq>"
        "</QBXMLMsgsRq>"
    )
    return _wrap(body, mapping["qbxml_version"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    ap.add_argument("--out", type=Path, help="write qbXML here instead of stdout")
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("po-query", help="build a PurchaseOrderQuery to find a PO's TxnID")
    q.add_argument("--po", required=True, help="PO number, e.g. 52412")

    b = sub.add_parser("bill-add", help="build a PO-linked BillAdd for one invoice")
    b.add_argument("--csv", type=Path, required=True)
    b.add_argument("--invoice", required=True, help="INVOICE_NUMBER from the CSV")
    b.add_argument("--po-txnid", required=True,
                   help="TxnID returned by po-query (from live QB)")

    args = ap.parse_args()
    mapping = load_mapping(args.mapping)

    if args.cmd == "po-query":
        xml = build_po_query(args.po, mapping)
    else:
        row = load_invoice(args.csv, args.invoice)
        xml = build_bill_add(row, args.po_txnid, mapping)

    if args.out:
        args.out.write_text(xml, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(xml)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
