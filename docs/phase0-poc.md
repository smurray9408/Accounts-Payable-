# Phase-0 Proof of Concept — PO-linked Bill in QuickBooks

**Goal:** prove that automation can post a Moore Supply invoice as a Bill **linked to its
Purchase Order**, so the line items arrive with their **Customer:Job** and **Class** intact —
the thing the flat Billtrust IIF cannot do. If this one transaction works, the whole approach
is validated.

> ⚠️ **Run against a QuickBooks *test* company file first**, never production. A Bill posts real
> AP. Use a backup/copy of the company file.

---

## What's in this proof

| File | Role |
|------|------|
| `scripts/qbxml_billadd.py` | Generates the two qbXML requests (PO query, then PO-linked BillAdd) |
| `config/mapping.json` | Vendor / AP account / terms names — **must match your QB lists exactly** |
| `tests/test_qbxml_billadd.py` | Verifies the generated qbXML is well-formed and complete |

The generated qbXML targets **qbXML spec 16.0** (QuickBooks Enterprise 24.0).

---

## The two-step mechanic

QuickBooks links a bill to a PO by transaction ID, so it's two round-trips:

```
1. PurchaseOrderQuery(RefNumber = PO_NUMBER)   ->  QB returns the PO's TxnID
2. BillAdd(LinkToTxnID = TxnID, RefNumber = INVOICE_NUMBER, Terms, DueDate, Memo)
       ->  QB copies the PO's open lines (Item, Qty, Cost, Customer:Job, Class) onto the bill
```

`LinkToTxnID` is the programmatic equivalent of the manual **Select PO** click. Because
Customer:Job and Class already live on the PO lines, they carry over automatically — no
per-line keying.

---

## How to run it (SDK "qbXML Test Tool" — fastest manual check)

1. Install the **QuickBooks Desktop SDK** (free from Intuit) on the machine with the QB test
   company file. It includes the **qbXML Test Tool**.
2. Open the **test company file** in QuickBooks, logged in as Admin (single-user is fine).
3. Edit `config/mapping.json` so `vendor_name`, `ap_account`, and the `terms_map` values are the
   **exact** names in your QB lists (Lists → Vendors / Terms / Chart of Accounts).
4. **Step 1 — find the PO's TxnID:**
   ```bash
   python3 scripts/qbxml_billadd.py po-query --po 52412 --out step1_query.xml
   ```
   Paste `step1_query.xml` into the qbXML Test Tool → send. In the response, copy the
   `<TxnID>` of the PurchaseOrder. Confirm the returned lines show the expected `CustomerRef`
   (e.g. *Chesmar Homes CT, Ltd:6464…*) and `ClassRef` (*Construction*).
5. **Step 2 — create the PO-linked bill:**
   ```bash
   python3 scripts/qbxml_billadd.py bill-add \
       --csv MOORESUPPLYCO_U1179769_BillTrust.csv \
       --invoice S180579939.001 \
       --po-txnid <TXNID-from-step-1> \
       --out step2_billadd.xml
   ```
   Paste `step2_billadd.xml` into the Test Tool → send.

### ✅ Success criteria
Open the new bill in QB (Enter Bills → Previous) and confirm:
- **Ref No.** = the invoice number (`S180579939.001`)
- Line items populated from the PO, each with the right **Customer:Job** and **Class**
- **Terms** and **Bill Due** correct; amount matches the invoice within tolerance
- The bill is **linked** to PO 52412 (the PO shows as received)

If all four hold, Phase-0 is proven and we proceed to Phase-1 (the review-and-approve UI).

---

## Known follow-ups (deliberately out of Phase-0 scope)

- **Partial receipts (55 POs have >1 invoice).** A whole-PO `LinkToTxnID` receives *all* open
  lines. When an invoice covers only part of a PO, drop `LinkToTxnID` and instead send
  `ItemLineAdd` entries that each carry a line-level `<LinkToTxn>` with the PO's `TxnID` +
  `TxnLineID` and the received `Quantity`. Build this in Phase-1.
- **Credits/returns (215 rows, negative).** Post as `VendorCreditAdd`, not `BillAdd`.
- **Non-PO exceptions (106 rows).** No PO to link → review queue; if coded flat, use
  `default_expense_account` from the mapping.
- **Vendor name mismatch.** Billtrust says `Moore Supply`; QB uses `Moore Supply Co`. Handled by
  `vendor_name` in the mapping — confirm the exact QB spelling.
- **Amount tolerance.** Compare CSV `TOTAL_DUE` to the PO-derived total; auto-post within
  tolerance, else queue.
- **Duplicate guard.** Before BillAdd, query for an existing bill with the same vendor +
  RefNumber.
- **PDF attachment.** Attach the downloaded invoice PDF to the bill (Doc Center) for the audit
  trail.

See [`../AP-Automation-Plan.md`](../AP-Automation-Plan.md) for the full roadmap.
