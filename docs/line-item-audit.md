# Moore Supply — Automated Line-Item Audit

Compares a QuickBooks **Purchase Order Detail** export against the line items on
Moore Supply's actual invoices, and reports every price discrepancy on a
spreadsheet. Fully automated and re-runnable as new reports/invoices arrive.

## Pipeline

```
Moore invoice PDFs (SharePoint / Billtrust email)
        │  read as text
        ▼
scripts/parse_moore_invoices.py   →  invoices.jsonl   (invoice header + line items)
        │
QB PODetail CSV (Item column = "<code> (<desc>)")
        │
        ├─ scripts/build_item_descriptions.py → item_desc.json  (item code → name)
        ▼
scripts/line_item_audit.py        →  Moore_LineItem_Audit_<date>.xlsx
                                     Moore_Discrepancies_<date>.csv
```

Run:

```bash
python3 scripts/parse_moore_invoices.py raw/ invoices.jsonl
python3 scripts/build_item_descriptions.py QB_PODetail.csv raw/ item_desc.json
python3 scripts/line_item_audit.py QB_PODetail.csv invoices.jsonl \
        out/Moore_LineItem_Audit.xlsx out/Moore_Discrepancies.csv item_desc.json
```

## Join key

The QB report's `Item` column and each invoice line share the **Moore item
code** (e.g. `2531756`). That is the reliable join — the QB purchase-order
`Num` is *not* the same numbering as an invoice's `CUSTOMER P.O.`, so items are
matched by code, not by PO.

## What each parser guarantees

- **Invoice parser** reads the six position-aligned columns (Item #, Qty
  Ordered, Qty Shipped, Unit Price, Unit, Net Amount). Every invoice is
  validated: the line-item net amounts must sum to the printed **SUBTOTAL**
  (±$0.02) or it is flagged. Credit memos (negative) are handled.
- **Audit** materiality: a price gap is flagged only when it is **≥ $0.02 per
  unit AND ≥ 1%**. Sub-cent rounding (both sides carry 3 decimals) is ignored.

## Workbook sheets

| Sheet | Contents |
|-------|----------|
| Data Coverage | scope, counts, findings summary, materiality, limitations |
| PO Price Check | every open-PO line: PO unit price vs Moore's most-recent billed price, difference, status |
| Price Anomalies | items Moore billed at **inconsistent** unit prices across invoices (likely over/undercharges) |
| Over-Billing Check | invoices grouped by PO across backorder generations (.001/.002/…); invoiced qty vs ordered qty, flags **invoiced > ordered** (double-bill) and shows still-open backorders |
| No Price Ref | open-PO items never seen on a captured invoice (cannot verify) |
| Truncated | invoices whose PDF text was cut off (see limitations) |

## Backorder generations

Moore fills one order in parts, invoicing each shipment as a new generation of
the same number: `S180636610.001`, `.002`, … A PO is only fully invoiced when
its generations *sum* to the ordered quantity. The Over-Billing Check groups by
Customer P.O., sums qty across all generations, and compares to the PO — so a
line re-billed across generations (over-ship / double-bill) is caught, and a PO
still short of its ordered qty shows as an open backorder.

## Reading invoices straight from PDF

`scripts/parse_moore_pdf.py` parses the actual PDF files (PyMuPDF) into the same
JSONL, bypassing the 100k-character text cap entirely. Use it whenever the PDFs
are on disk (e.g. dropped into SharePoint or saved from the Billtrust email):

```bash
python3 scripts/parse_moore_pdf.py path/to/invoices/ invoices.jsonl
```

## Known data limitations

1. **Report is open POs.** The supplied QB report is Open Purchase Orders
   (every line still backordered), mostly dated 06/26–07/02. Open POs are not
   yet invoiced, so the audit is a *price* comparison (PO price vs the price
   Moore has actually been billing for that item), not a PO-by-PO settlement.
2. **Invoice text truncation.** The SharePoint file reader caps extracted text
   at 100,000 characters per PDF, which cuts off the last invoice of each large
   daily batch (16 invoices affected). Their captured lines are still used;
   their tail is listed on the *Truncated* sheet.
3. **Invoices after 06/25/26.** Only invoices dated 05/28–06/25 were available
   (SharePoint). The 06/26–07/02 batches exist only as email attachments whose
   download host is blocked by the environment's egress policy. Supplying those
   PDFs (or allow-listing the host) would extend the price reference to the most
   recent POs.
