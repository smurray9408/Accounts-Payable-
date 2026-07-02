# AP Automation Plan — Moore Supply Invoices → QuickBooks Enterprise

**Company:** Murray Plumbing Co., LLC
**Prepared:** 2026-07-02 · **Updated:** 2026-07-02 (after reviewing actual Billtrust exports)
**Scope:** Automate the accounts-payable workflow that ingests supplier invoices from the
Moore Supply Invoice Gateway (Billtrust) and posts them as bills in QuickBooks Enterprise
Solutions 24.0, matched to open purchase orders.

> **Key update:** Billtrust can export both a **structured CSV** (with a clean `PO_NUMBER`
> column) and a **QuickBooks IIF** file. This *solves data acquisition* — no EDI, API, or
> portal scraping is needed. But the IIF is a "flat" import that **destroys job costing**
> (single lump-sum line to one expense account, no Class, no Customer:Job, no PO link). The
> real automation is therefore: take the **CSV**, match each `PO_NUMBER` to the open QB PO, and
> post a **PO-linked bill** so line items, Customer:Job, and Class flow through automatically.
> See §4–§5 for the analysis of the real files.

---

## 1. Current State (As-Is)

Today the process is 100% manual and done one invoice at a time. Based on the documented
procedure, each invoice takes **11 discrete steps** across two systems:

| # | System | Action |
|---|--------|--------|
| 1 | QuickBooks | Open the **Open Purchase Orders** report |
| 2 | QuickBooks | Customize the report (Filters → Name = *Moore Supply Co*, TransactionType = *Purchase Order*, Received = *No*) |
| 3 | Billtrust Gateway | Open the **Open** tab; click the **PO Number** column |
| 4 | Billtrust Gateway | Filter the invoice list for a specific PO (e.g., `52412`) |
| 5 | QuickBooks | Open **Enter Bills** |
| 6 | Billtrust Gateway | **Download** the invoice PDF for that PO |
| 7 | QuickBooks | Set vendor to *Moore Supply Co*, **Select PO**, acknowledge the *"Pending item receipts exist"* and vendor/item-receipt warnings — line items auto-populate from the PO |
| 8 | QuickBooks | Verify each line's **Customer:Job** (e.g., *Chesmar Homes CT, Ltd:6464…*) and **Class** (e.g., *Construction*); confirm amounts against the invoice |
| 9 | Billtrust Gateway | Copy the **Invoice #** (e.g., `S180579939.001`) |
| 10 | QuickBooks | Paste it into the **Ref No.** field |
| 11 | QuickBooks | Click **Save & New** and repeat |

**Two systems involved**

- **Moore Supply Invoice Gateway** — a Billtrust portal (`secure.billtrust.com/mooresupplyco`)
  shared across the Hajoca family (Moore Supply Co, Hughes, Facets, Kohler Store). The **Open**
  tab currently lists **~1,867 open documents** with structured columns: *File, Note, Invoice #,
  PO Number, Inv Date, Due Date, Inv Amt, Disc Amt, Disc Date, Paid Online, Open Balance, Ship
  Addr, Customer*.
- **QuickBooks Enterprise Solutions 24.0** (multi-user) — bills are entered against existing POs
  so job-costing (Customer:Job) and Class flow through to WIP/job reports.

### Pain points

- **Volume:** ~1,867 open documents to reconcile one-by-one.
- **Swivel-chair matching:** the operator manually correlates each gateway invoice to its QB PO by copy/pasting a PO number back and forth.
- **Repetitive keying:** invoice number is hand-copied into Ref No. on every bill; warnings are dismissed on every bill.
- **PDF handling:** each invoice PDF is downloaded manually and (today) not systematically attached to the QB bill.
- **Error-prone:** amount, discount-terms (2% 10 Net), and due-date verification is eyeballed; discrepancies are easy to miss.
- **No audit trail / approval gate:** nothing enforces a match tolerance or captures who approved what.

---

## 2. Goals & Success Metrics

| Goal | Metric | Target |
|------|--------|--------|
| Eliminate manual keying | Bills auto-created vs. hand-keyed | ≥ 90% auto |
| Speed | Minutes per invoice | ~5 min → < 30 sec |
| Accuracy | Posting errors / month | → ~0 (tolerance-gated) |
| Control | % bills with 2-way/3-way match evidence + attached PDF | 100% |
| Backlog | Open-document reconciliation | Clear the ~1,867 backlog in staged batches |

---

## 3. Target State (To-Be)

A scheduled middleware service pulls the open-invoice list from the gateway, matches each
invoice to its open PO in QuickBooks, validates amounts/terms against tolerance, and posts a
**Bill linked to the PO** — carrying Customer:Job and Class straight from the PO lines. Clean
matches post automatically; anything outside tolerance drops into an **exception queue** for a
human. The invoice PDF is attached to the bill for the audit trail.

```
┌─────────────────────┐        ┌──────────────────────────┐        ┌────────────────────────┐
│ Moore Supply Gateway│        │   AP Automation Service  │        │  QuickBooks Enterprise │
│      (Billtrust)     │        │      (middleware)        │        │        24.0            │
│                     │        │                          │        │                        │
│ • open invoice list │──(A)──▶│ 1. Ingest invoices       │◀─(B)──▶│ • Open POs (query)     │
│ • invoice PDFs      │        │ 2. Match invoice ⇆ PO    │        │ • BillAdd (linked PO)  │
│                     │        │ 3. Validate / tolerance  │──(C)──▶│ • Attach PDF           │
└─────────────────────┘        │ 4. Post bill or queue    │        └────────────────────────┘
                               │ 5. Exception review UI   │
                               └──────────────────────────┘
                                          │
                                     (D)  ▼
                                 Approval queue / dashboard
```

- **(A) Ingest** — pull structured open-invoice data + PDFs from the gateway.
- **(B) Match** — read open POs from QB, match on PO Number (+ vendor + amount).
- **(C) Post** — create a Bill in QB linked to the PO; set Ref No., terms, due/discount dates; attach PDF.
- **(D) Exceptions** — no PO, amount mismatch, receipt not posted, duplicate → human review.

---

## 4. Data Acquisition — SOLVED via Billtrust export

**Data acquisition is not a problem** — Billtrust exports two files directly. No EDI, API, or
portal scraping is required for the header-level data.

### 4a. The CSV export (use this)

8 clean columns, one row per invoice:

```
INVOICE_NUMBER, INVOICE_DATE, TOTAL_DUE, PO_NUMBER,
DISCOUNT_MESSAGE, DUE_DATE, TERMS, DISCOUNT_AMOUNT
```

Analysis of the actual export (1,837 invoices, 04/26–06/26 2026), via
[`scripts/classify_export.py`](scripts/classify_export.py):

| Bucket | Count | % | Amount | Handling |
|--------|------:|--:|-------:|----------|
| **Clean charge** (positive, numeric PO) | 1,516 | 82.5% | $738,443.60 | Auto-match to open PO → PO-linked bill |
| **Credit / return** (negative) | 215 | 11.7% | −$64,732.52 | Post as **vendor credit**, not a bill |
| **Exception** (non-numeric "PO") | 106 | 5.8% | $21,479.26 | Human review |

- **PO_NUMBER is 100% populated** and clean (e.g. `52412`). Every invoice number is unique.
- **55 POs carry >1 invoice** → partial shipments; link to the *remaining* PO balance, not the full PO.
- **2 terms strings** to map: `2% 10TH NET 25TH 1.5%SC55` and `2% 15 DAYS / 1.5 SC 30`.
- **Exception "PO" values** are either text (`MISC RETURNS`, `STOLEN MATERIAL`, `MISC SHOP`) or a
  different order-number scheme (`33920255-001`) that won't match a 5-digit QB PO.

### 4b. The IIF export (do **not** use as-is)

Billtrust also emits a QuickBooks `.iif`. It imports in one click, but every bill is a **single
lump-sum split to one `Plumbing Supplies` account** with:

- ❌ no **Class**   ❌ no **Customer:Job**   ❌ no **line-item detail**   ❌ no **PO link**
- PO number survives only as text after a semicolon in the memo
- Vendor is `Moore Supply` (your QB vendor is `Moore Supply Co` — a **name mismatch** to map)
- Its count (1,949) doesn't even match the CSV (1,837) — different snapshot/filter

**Importing the IIF would collapse all $700K+ into one GL account with zero job costing** — the
opposite of what your manual process achieves. It's only viable as a fallback coding path for the
non-PO exception items (§6).

> No OCR needed for header fields — the CSV is fully structured. OCR is only relevant later if you
> want to reconcile *line-level* detail against the invoice PDF.

---

## 5. Posting into QuickBooks — build vs. buy

The IIF settles data acquisition but not job costing — the challenge is posting **PO-linked**
bills so lines, Customer:Job, and Class carry over. QuickBooks Enterprise (Desktop) is the
constraint. Options:

| Option | How it works | Fit for PO-linked bills | Notes |
|--------|--------------|-------------------------|-------|
| **QuickBooks Web Connector + qbXML (recommended)** | Small service exposes a SOAP endpoint QBWC polls; sends `PurchaseOrderQuery` and `BillAdd` with `LinkToTxnID` to the PO | ★★★ Full control incl. PO linking, Ref No., terms, Class, Customer:Job | Native, free SDK; runs on the machine hosting the QB company file |
| **Transaction Pro Importer / similar** | Import Bills from CSV/Excel | ★★ Can import bills; PO **receipt linking** is limited/manual | Fast to stand up; may not fully replicate "Select PO → receive" behavior |
| **AP SaaS (Bill.com, Melio, etc.)** | Cloud AP + QB sync | ★ Weak on Enterprise PO receiving & job costing | Good for approvals, weak on our exact PO/job-cost flow |

**Recommendation:** Build middleware on the **QuickBooks Web Connector + qbXML** path. It is the
only option that faithfully reproduces steps 6–11 (Select PO, auto-populate lines, carry
Customer:Job + Class, set Ref No./terms, save) programmatically, and it keeps job-costing intact.

**Key qbXML mechanics to prototype first (highest technical risk):**
- `PurchaseOrderQueryRq` filtered to vendor *Moore Supply Co*, open only → get PO `TxnID`s + line detail.
- `BillAddRq` with `VendorRef`, `RefNumber` (invoice #), `TermsRef` (2% 10 Net), `DueDate`, and
  **line items that `LinkToTxnID` the PO's line items** so QB "receives" them exactly like the
  manual *Select PO* flow — inheriting Customer:Job and Class.
- Attaching the PDF via the **Attached Documents / Doc Center** API (or file drop + link).

---

## 6. Matching & validation rules

- **Primary key:** invoice `PO Number` → QB open PO. (One invoice may cover part of a PO; support partial receipts.)
- **Vendor guard:** only match POs where vendor = *Moore Supply Co*.
- **Amount tolerance:** auto-post if `|Invoice Amt − PO open balance for received lines|` ≤ configurable tolerance (e.g., $0.01 or 1%). Otherwise → exception.
- **Discount/terms:** carry Disc Amt / Disc Date / terms (2% 10 Net) onto the bill.
- **Duplicate check:** skip if a QB bill already exists with the same vendor + Ref No.
- **Receipt-warning handling:** the "pending item receipts" case is expected — the automation *is* the receipt; log it rather than treating it as an error.

### Exception queue triggers
No matching open PO · amount out of tolerance · PO already fully billed · missing Customer:Job or
Class on a PO line · duplicate invoice # · closed/on-hold PO.

---

## 7. Field mapping (Gateway → QuickBooks Bill)

| CSV column | QuickBooks Bill field | Source of truth |
|------------|-----------------------|-----------------|
| `INVOICE_NUMBER` (`S180579939.001`) | **Ref No.** (also dedup key) | CSV |
| `PO_NUMBER` (`52412`) | Links to PO `TxnID` (Select PO) | Match key |
| — | **Vendor** = Moore Supply Co (map from `Moore Supply`) | Fixed / mapping |
| `TOTAL_DUE` (`1913.71`) | **Amount Due** (validated vs. PO) | CSV, tolerance-checked |
| `DUE_DATE` | **Bill Due** | CSV |
| `TERMS`, `DISCOUNT_AMOUNT`, `DISCOUNT_MESSAGE` | **Terms** + Discount Date/Amt | CSV (map 2 terms strings) |
| — | Bill line **Item/Qty/Cost/Amount** | **PO** (auto-populated) |
| — | **Customer:Job** (e.g., Chesmar Homes CT, Ltd:6464…) | **PO line** (carried over) |
| — | **Class** (e.g., Construction) | **PO line** (carried over) |
| (PDF, downloaded separately) | Attached document on the bill | Gateway download |

> Because Customer:Job and Class already live on the PO lines, the automation inherits them — no
> per-line re-keying. Exceptions only arise when a PO line is missing that data.

---

## 8. Phased Roadmap (crawl → walk → run)

**Phase 0 — De-risking (1–2 wks).** Data acquisition is already proven (CSV export +
[`scripts/classify_export.py`](scripts/classify_export.py) triages 82.5% as clean auto-match
candidates). Remaining risk is the QB side: stand up QBWC against a **test QB company file** and
prove a single `BillAdd` linked to a PO that carries the correct Ref No., Class, and Customer:Job.
That validates the one unproven piece before further investment.

**Phase 1 — Assisted / "human-in-the-loop" (2–4 wks).** Ingest the open-invoice list → auto-match
to POs → present a **review screen** showing proposed bills side-by-side with the PDF. Operator
clicks *Approve* to post via QBWC. Cuts time per invoice sharply while a human still confirms every
post. Begin clearing the ~1,867 backlog in batches.

**Phase 2 — Straight-through for clean matches (2–3 wks).** Auto-post invoices that pass tolerance
+ duplicate + PO checks; route only exceptions to the review screen. Attach PDFs automatically.
Add a daily reconciliation report.

**Phase 3 — Scale & hardening (ongoing).** Scheduled runs (e.g., nightly), monitoring/alerting,
credential rotation, exception SLAs, and metrics dashboard. Pursue EDI 810 if not already adopted
to retire portal scraping.

---

## 9. Recommended tech stack

- **Middleware:** Python or .NET service.
- **QB integration:** QuickBooks Web Connector + qbXML (on the QB host / server hosting the company file).
- **Gateway ingestion:** Billtrust **CSV export** (proven). Optionally automate the download later.
- **Store:** lightweight DB (SQLite/Postgres) for invoice staging, match state, dedup, and audit log.
- **Review UI:** simple web app (approval queue + PDF preview + exception handling).
- **Secrets:** OS keychain / vault for gateway + QB credentials.
- **This repo (`Accounts-Payable-`)** houses the code, qbXML templates, mapping config, and tests.

---

## 10. Risks & controls

| Risk | Mitigation |
|------|------------|
| Posting a wrong/duplicate bill | Tolerance gate, duplicate detection on vendor+Ref No., Phase-1 human approval, run against **test company file** first |
| Portal UI changes break scraping | Prefer API/EDI; version-pin selectors; alert on scrape failures; nightly canary |
| QB company file locked (multi-user) / SDK limits | Run QBWC on the host; schedule off-peak; handle QB busy/lock errors with retry |
| PO line missing Customer:Job or Class | Route to exception queue rather than posting incomplete job costing |
| Credential security | Vault storage, least-privilege gateway user, rotation |
| Partial shipments / multi-PO invoices | Support partial receipts and 1-invoice-to-many-PO / many-invoice-to-1-PO mapping |

---

## 11. Effort & ROI (rough order of magnitude)

- **Build:** ~6–10 weeks phased (Phase 0–2), largely the QBWC integration + review UI.
- **Time saved:** ~5 min/invoice → <30 sec. At even a few hundred invoices/month that is tens of
  hours/month returned, plus fewer errors and a clean audit trail.
- **Buy-vs-build:** a SaaS importer could shortcut Phase 1 but is unlikely to fully honor the
  PO-receipt + job-cost flow — validate against a test file before committing.

---

## 12. Open questions (confirm before Phase 1)

1. ✅ *Resolved:* data comes from the **Billtrust CSV export** (no EDI/API/scraping needed).
2. **Is per-line job costing (Customer:Job + Class via PO link) required, or is a flat GL-coded
   bill acceptable?** This is the pivotal fork — it decides whether we build PO-matching (CSV path)
   or just import the IIF. *(The manual process strongly implies job costing is required.)*
3. Can we get a **QuickBooks test company file** to develop against safely?
4. How should **credits/returns** (215 rows, −$64.7K) post — vendor credits auto-applied, or queued?
5. What **match tolerance** and **auto-post vs. always-review** policy does accounting want?
6. How should the **106 non-PO exceptions** be coded (default expense account, à la the IIF)?
7. Should PDFs attach to the bill in QB's Doc Center, or to a shared drive with a link?
8. Are there **other suppliers** (Ferguson, etc. seen in the PO report) for the same pipeline later?
9. Who owns the **exception queue**, and what's the approval threshold?
