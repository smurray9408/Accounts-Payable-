"""Tests for the qbXML generator (Phase-0 proof).

No live QuickBooks needed: these assert the generated request documents are
well-formed and carry the fields QB requires to create a PO-linked bill.

Run:  python3 -m pytest tests/ -q      (or: python3 tests/test_qbxml_billadd.py)
"""
import sys
from pathlib import Path
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import qbxml_billadd as q  # noqa: E402

MAPPING = {
    "vendor_name": "Moore Supply Co",
    "ap_account": "Accounts Payable",
    "qbxml_version": "16.0",
    "terms_map": {"2% 10TH NET 25TH 1.5%SC55": "NET-MAPPED"},
}

ROW = {
    "INVOICE_NUMBER": "S180579939.001",
    "INVOICE_DATE": "06/26/26",
    "TOTAL_DUE": "1913.71",
    "PO_NUMBER": "52412",
    "DISCOUNT_MESSAGE": "If paid by cash or check 08/10/26 you may deduct $35.36",
    "DUE_DATE": "08/25/26",
    "TERMS": "2% 10TH NET 25TH 1.5%SC55",
    "DISCOUNT_AMOUNT": "35.36",
}


def _text(xml, tag):
    return minidom.parseString(xml).getElementsByTagName(tag)[0].firstChild.nodeValue


def test_date_conversion():
    assert q.mmddyy_to_iso("06/26/26") == "2026-06-26"
    assert q.mmddyy_to_iso("04/26/26") == "2026-04-26"


def test_po_query_wellformed_and_headers():
    xml = q.build_po_query("52412", MAPPING)
    assert xml.startswith('<?xml version="1.0" encoding="utf-8"?>')
    assert xml.count("<?qbxml") == 1                     # no duplicate PI
    minidom.parseString(xml)                             # well-formed
    assert _text(xml, "RefNumber") == "52412"


def test_bill_add_has_required_fields():
    xml = q.build_bill_add(ROW, "220A-1699884776", MAPPING)
    minidom.parseString(xml)                             # well-formed
    assert _text(xml, "FullName") == "Moore Supply Co"   # VendorRef first
    assert _text(xml, "RefNumber") == "S180579939.001"   # invoice # -> Ref No.
    assert _text(xml, "TxnDate") == "2026-06-26"
    assert _text(xml, "DueDate") == "2026-08-25"
    assert _text(xml, "LinkToTxnID") == "220A-1699884776"  # THE thing that pulls job/class
    assert "PO 52412" in _text(xml, "Memo")


def test_terms_are_mapped_to_qb_name():
    xml = q.build_bill_add(ROW, "T1", MAPPING)
    assert "NET-MAPPED" in xml                            # mapped, not raw string


def test_xml_escaping():
    row = dict(ROW, DISCOUNT_MESSAGE="deduct $1 & <stuff>")
    xml = q.build_bill_add(row, "T1", MAPPING)
    minidom.parseString(xml)                             # still well-formed
    assert "&amp;" in xml and "&lt;stuff&gt;" in xml


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
