"""
10_build_runbook_pdf.py
=======================
Builds docs/Fabric_dbt_ADF_Runbook.pdf — the step-by-step implementation runbook covering
Microsoft Fabric workspace setup, the dbt project, and Azure Data Factory orchestration.

Written as a runbook, not a description: every step is something a named role does in a named
tool, with the command or the click-path, and a stated "done when" so it can be verified.
"""
from pathlib import Path
import json
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "Fabric_dbt_ADF_Runbook.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

NAVY = colors.HexColor("#12305B")
TEAL = colors.HexColor("#0E8B8B")
AMBER = colors.HexColor("#E8A317")
RED = colors.HexColor("#C0392B")
GREY = colors.HexColor("#5A6672")
LIGHT = colors.HexColor("#EEF3F9")
BAND = colors.HexColor("#F7FAFC")

ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=ss["Title"], fontSize=26, textColor=NAVY,
                            spaceAfter=4, fontName="Helvetica-Bold"),
    "sub": ParagraphStyle("s", parent=ss["Normal"], fontSize=11, textColor=GREY,
                          alignment=TA_LEFT, spaceAfter=16),
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, textColor=NAVY,
                         spaceBefore=16, spaceAfter=8, fontName="Helvetica-Bold"),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=TEAL,
                         spaceBefore=11, spaceAfter=5, fontName="Helvetica-Bold"),
    "b": ParagraphStyle("b", parent=ss["Normal"], fontSize=9.5, leading=14, spaceAfter=6),
    "cell": ParagraphStyle("c", parent=ss["Normal"], fontSize=8.5, leading=11.5),
    "cellb": ParagraphStyle("cb", parent=ss["Normal"], fontSize=8.5, leading=11.5,
                            fontName="Helvetica-Bold", textColor=NAVY),
    "code": ParagraphStyle("code", parent=ss["Normal"], fontSize=8.5, leading=12,
                           fontName="Courier", textColor=NAVY, backColor=LIGHT,
                           borderPadding=5, spaceAfter=6, spaceBefore=2),
    "note": ParagraphStyle("n", parent=ss["Normal"], fontSize=8.5, leading=12,
                           textColor=GREY, spaceAfter=6),
}
P = lambda t, s="b": Paragraph(t, S[s])


def steps_table(rows, widths=(12, 52, 30, 60, 46)):
    """rows: (step, action, tool/role, command or click-path, done when)"""
    data = [[P("#", "cellb"), P("Action", "cellb"), P("Tool / role", "cellb"),
             P("Command or click-path", "cellb"), P("Done when", "cellb")]]
    for r in rows:
        data.append([P(str(r[0]), "cell"), P(r[1], "cell"), P(r[2], "cell"),
                     P(r[3], "cell"), P(r[4], "cell")])
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D6DEE8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def callout(title, body, colour=TEAL, fill=colors.HexColor("#F0F9F9")):
    t = Table([[P(f'<b><font color="#{colour.hexval()[2:]}">{title}</font></b><br/>{body}',
                  "cell")]], colWidths=[200 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("LINEBEFORE", (0, 0), (0, -1), 3, colour),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, A4[1] - 14 * mm, A4[0], 14 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(15 * mm, A4[1] - 9.5 * mm,
                      "Merchant Sales & Voucher Intelligence  |  Fabric · dbt · ADF Runbook")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(A4[0] - 15 * mm, A4[1] - 9.5 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(colors.HexColor("#D6DEE8"))
    canvas.line(15 * mm, 12 * mm, A4[0] - 15 * mm, 12 * mm)
    canvas.setFillColor(GREY)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(15 * mm, 8 * mm, "Anthony Apollis  ·  August 2026")
    canvas.restoreState()


doc = SimpleDocTemplate(str(OUT), pagesize=(A4[1], A4[0]),   # landscape
                        leftMargin=15 * mm, rightMargin=15 * mm,
                        topMargin=20 * mm, bottomMargin=16 * mm,
                        title="Fabric / dbt / ADF Implementation Runbook")
F = []

# ---------------------------------------------------------------- title
F += [Spacer(1, 30 * mm),
      P("Implementation Runbook", "title"),
      P("Microsoft Fabric &nbsp;·&nbsp; dbt &nbsp;·&nbsp; Azure Data Factory<br/>"
        "Merchant Sales &amp; Voucher Intelligence — BI Developer Second-Round Practical Task",
        "sub"),
      Spacer(1, 6 * mm)]
F.append(Table([
    [P("Scope", "cellb"), P("Workspace provisioning through to a scheduled, "
                            "quality-gated daily refresh feeding a Direct Lake semantic model",
                            "cell")],
    [P("Layers", "cellb"), P("Landing → Bronze → Silver → Gold (Kimball star) → Power BI",
                             "cell")],
    [P("Artefacts", "cellb"), P("1 Lakehouse · 1 Warehouse · 4 notebooks · 1 ADF pipeline · "
                                "1 schedule trigger · 18 dbt models · 1 SCD2 snapshot · "
                                "132 dbt tests", "cell")],
    [P("Cadence", "cellb"), P("Daily 02:00 South Africa Standard Time", "cell")],
    [P("Quality gate", "cellb"), P("dbt test runs BETWEEN silver and gold. Gold is not "
                                   "rebuilt unless every test passes.", "cell")],
], colWidths=[35 * mm, 200 * mm], style=TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D6DEE8")),
    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, BAND]),
    ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
])))
F.append(PageBreak())

# ---------------------------------------------------------------- Part 0: the data journey
F += [P("Part 0 — The journey of one row through Microsoft Fabric", "h1"),
      P("Before the setup steps, this is the story the architecture tells: what actually "
        "happens to a single sales record between the source file landing and an executive "
        "seeing it on a page. Every later section exists to serve one of these seven stages.",
        "b")]

F.append(steps_table([
    ("1", "It lands", "OneLake Files / ADF Copy",
     "At 02:00 SAST the pipeline copies MerchantSales.csv into "
     "LH_MerchantVoucher/Files/landing. Our row is one line of text: "
     "<font face='Courier' size='7'>2026-07-31,M002,Umhlanga Value Mart,Free State,Retail,"
     "Airtime,2191.80,46</font>",
     "Nothing is validated yet. The only question asked is 'did the file arrive and is it "
     "big enough' — the minRows floor of 20,000 catches a truncated feed here, before it "
     "can look like a bad trading day."),

    ("2", "It is landed raw (BRONZE)",
     "Lakehouse Delta table",
     "Written to bronze_merchant_sales exactly as received — every column still a string. "
     "Three columns are added and nothing else changes: _source_file, _ingested_at, "
     "_batch_id.",
     "Bronze deliberately applies no business logic. If a number is later disputed, this is "
     "the layer that proves what the source actually sent, unmodified. The batch id is what "
     "makes 'which load produced this figure?' answerable during an incident."),

    ("3", "It is cleaned and conformed (SILVER)",
     "Fabric notebook 01_bronze_to_silver",
     "The row is typed (date, decimal, int), trimmed, and de-duplicated at its declared "
     "grain of Date × Merchant × VoucherType. Merchant, Region and Channel are DROPPED.",
     "Dropping them is the important move. They also live on MerchantReference, and "
     "profiling proved 100% agreement — so keeping both would let two competing versions of "
     "'Region' exist in one model, which is how a report ends up with two different regional "
     "totals on two different pages."),

    ("4", "It is judged against the rules", "dbt test — the quality gate",
     "132 tests run against silver. Is the grain still unique? Does every merchant id "
     "resolve? Is the date table contiguous? Does total revenue still tie to bronze to the "
     "cent?",
     "This gate sits BEFORE gold, not after. If it fails the pipeline stops and gold is left "
     "untouched, so the report keeps yesterday's correct numbers instead of publishing "
     "today's wrong ones. Our row only continues because every test passed."),

    ("5", "It joins the star schema (GOLD)", "dbt build → Warehouse",
     "The row becomes a fact: date 2026-07-31 becomes date_key 20260731; M002 becomes a "
     "merchant surrogate key; Airtime becomes a voucher_type key. Only keys and measures "
     "remain — 2191.80 and 46.",
     "Alongside it, snap_merchant checks whether M002's status, region, manager or target "
     "changed since yesterday. If they did, a new version row is written and "
     "mart_merchant_change_alerts raises it — so a merchant quietly moving to 'At Risk' "
     "cannot pass unnoticed."),

    ("6", "It becomes a number someone reads", "Power BI Direct Lake",
     "No import, no copy. The semantic model reads the Delta files directly; the pipeline's "
     "last step reframes it. [Total Sales] = SUM(sales_value) now includes our R2,191.80.",
     "The row also lands in mart_merchant_scorecard, where M002's July collapse of −42.5% "
     "against its own prior three months drops its health score to 17.3 and puts R571,518 of "
     "annualised revenue at risk on the focus list."),

    ("7", "It is explained", "ML notebook + narrative measures",
     "The Isolation Forest scores M002's July as the single most anomalous merchant-month in "
     "the dataset, with the reason attached in plain English: sales −38% vs own history, "
     "tickets +594%.",
     "An account manager opens the report at 07:00 and sees not a number but a sentence: "
     "Umhlanga Value Mart has declined sharply, support volume has risen 693%, and the "
     "annualised shortfall is R571,518. That is the point of all six preceding stages."),
], widths=(10, 40, 34, 68, 48)))

F += [Spacer(1, 4 * mm),
      callout("What the journey is designed to prevent",
              "Each stage exists to stop a specific, common failure. Stage 1 stops a "
              "truncated file looking like weak trading. Stage 2 stops a disputed number "
              "being unanswerable. Stage 3 stops two versions of the truth entering the "
              "model. Stage 4 stops wrong figures reaching an executive. Stage 5 stops a "
              "silent master-data change invalidating a comparison. Stage 6 stops a stale "
              "copy being reported as live. Stage 7 stops a correct number going unnoticed "
              "because nobody knew what it meant.")]
F.append(PageBreak())

# ---------------------------------------------------------------- Part 1: Fabric
F += [P("Part 1 — Microsoft Fabric workspace setup", "h1"),
      P("Everything in this part is done once, per environment. Three environments are "
        "provisioned (Dev, Test, Prod) so the deployment pipeline in Part 4 has somewhere to "
        "promote to.", "b")]
F.append(steps_table([
    ("1.1", "Create the capacity", "Fabric admin",
     "Azure portal → Create resource → Microsoft Fabric Capacity → F2 or higher, region "
     "South Africa North",
     "Capacity appears in the Fabric admin portal and is Active"),
    ("1.2", "Create three workspaces", "Fabric admin",
     "Fabric → Workspaces → New workspace: WS_MerchantVoucher_Dev / _Test / _Prod. Assign "
     "the capacity under Advanced → License mode → Fabric capacity",
     "All three workspaces show the capacity name, not 'Pro'"),
    ("1.3", "Create the Lakehouse", "Data engineer",
     "In each workspace: New → Lakehouse → LH_MerchantVoucher",
     "Lakehouse opens with empty Tables and Files sections"),
    ("1.4", "Create the landing folder", "Data engineer",
     "LH_MerchantVoucher → Files → New subfolder → landing",
     "Files/landing exists and is writable"),
    ("1.5", "Create the Warehouse", "Data engineer",
     "New → Warehouse → WH_MerchantVoucher. Run sql/01_create_warehouse.sql",
     "gold schema contains 7 dimensions, 4 facts, 2 marts, 2 ML tables"),
    ("1.6", "Register the service principal", "Fabric admin",
     "Entra ID → App registrations → New. Grant the SP Contributor on all three workspaces",
     "SP can authenticate to the Warehouse SQL endpoint"),
    ("1.7", "Capture connection details", "Data engineer",
     "Warehouse → Settings → SQL connection string. Store as FABRIC_SQL_ENDPOINT",
     "Endpoint resolves and the SP can connect"),
]))
F += [Spacer(1, 4 * mm),
      callout("Why a Lakehouse AND a Warehouse",
              "The Lakehouse holds bronze and silver as Delta — schema-on-read, cheap, and "
              "Spark-native for the notebooks. The Warehouse holds gold, because it gives a "
              "T-SQL surface for dbt-fabric and for analysts who will never write PySpark. "
              "Both sit on OneLake, so gold reads silver with no data movement.")]
F.append(PageBreak())

# ---------------------------------------------------------------- Part 2: dbt
F += [P("Part 2 — dbt project", "h1"),
      P("The dbt project runs against a local analytical engine for development (seconds per run, no "
        "cloud cost) and against the Fabric Warehouse in production. Identical SQL — only the "
        "adapter changes, which is the main reason dbt is in this stack at all.", "b")]
F.append(steps_table([
    ("2.1", "Install dbt and the adapters", "BI developer",
     "pip install dbt-core dbt-fabric dbt-duckdb",
     "dbt --version lists both adapters"),
    ("2.2", "Set environment variables", "BI developer",
     "FABRIC_SQL_ENDPOINT, FABRIC_WAREHOUSE, AZURE_TENANT_ID, AZURE_CLIENT_ID, "
     "AZURE_CLIENT_SECRET",
     "dbt debug --target fabric returns All checks passed"),
    ("2.3", "Install package dependencies", "BI developer",
     "dbt deps",
     "dbt_packages/ contains dbt_utils, dbt_expectations, codegen"),
    ("2.4", "Load the seeds", "BI developer",
     "dbt seed",
     "4 seeds loaded: voucher_type, ticket_type, priority, ticket_status reference"),
    ("2.5", "Build everything in DAG order", "BI developer",
     "dbt build",
     "153 pass, 0 warn, 0 error. This runs seeds, the snapshot, 18 models and 132 tests in "
     "dependency order"),
    ("2.6", "Verify the SCD2 snapshot behaves", "BI developer",
     "python scripts/_test_scd2.py",
     "7/7 assertions pass and the harness restores original state"),
    ("2.7", "Generate and publish documentation", "BI developer",
     "dbt docs generate &amp;&amp; dbt docs serve",
     "Lineage graph renders; every model shows a description and its tests"),
    ("2.8", "Reconcile against the reference implementation", "BI developer",
     "python scripts/05_reconcile.py",
     "27 pass, 1 documented rounding warning, 0 fail"),
]))
F += [Spacer(1, 3 * mm), P("Model layers", "h2")]
F.append(steps_table([
    ("", "staging (4 views)", "silver",
     "Type, trim, deduplicate at the declared grain, apply integrity rules",
     "Descriptive attributes dropped — they belong to the dimension"),
    ("", "intermediate (2 ephemeral)", "—",
     "int_merchant_monthly (merchant × month spine, zero-filled) and int_merchant_momentum",
     "Inlined as CTEs; no storage, one definition of 'latest vs prior three'"),
    ("", "snapshots (1)", "SCD2",
     "snap_merchant — check strategy on region, channel, active_status, account_manager, "
     "target",
     "Source has no reliable last-modified column, so timestamp strategy is unsafe"),
    ("", "marts / core (11)", "gold",
     "7 conformed dimensions, 4 facts, plus the Type 2 dimension",
     "Facts at three grains; targets kept in their own month-grain fact"),
    ("", "marts / analytics (2)", "gold",
     "mart_merchant_scorecard and mart_merchant_change_alerts",
     "Health Score computed in SQL so Power BI, Excel and ML all inherit one definition"),
], widths=(12, 42, 22, 76, 48)))
F += [Spacer(1, 4 * mm),
      callout("The snapshot is wired to alerting, not just history",
              "mart_merchant_change_alerts diffs consecutive snapshot versions and emits one "
              "row per changed field with a severity. A merchant moving to 'At Risk' is "
              "Critical; a re-based sales target is High, because it silently invalidates "
              "every period-over-period attainment comparison unless someone is told. "
              "Capturing history nobody reads is not worth the storage — this is what makes "
              "the snapshot earn its place.", AMBER, colors.HexColor("#FEF8EC"))]
F.append(PageBreak())

# ---------------------------------------------------------------- Part 3: ADF
F += [P("Part 3 — Azure Data Factory / Fabric pipeline orchestration", "h1"),
      P("PL_MerchantVoucher_Master.json. Three design decisions carry most of the value and "
        "are called out after the steps.", "b")]
F.append(steps_table([
    ("3.1", "Create the pipeline", "Data engineer",
     "Fabric workspace → New → Data pipeline → PL_MerchantVoucher_Master. Import "
     "datafactory/PL_MerchantVoucher_Master.json",
     "Pipeline canvas shows 6 top-level activities"),
    ("3.2", "Create the linked service", "Data engineer",
     "Manage → Linked services → New → Fabric Warehouse → LS_Fabric_Warehouse, "
     "authenticate with the service principal",
     "Test connection succeeds"),
    ("3.3", "Set the batch ID", "(pipeline)",
     "SetVariable: BatchId = @formatDateTime(utcnow(),'yyyyMMddTHHmmssZ')",
     "Every downstream row carries this batch id for lineage"),
    ("3.4", "Log the run start", "(pipeline)",
     "Script activity → INSERT INTO audit.pipeline_run (... status 'RUNNING')",
     "A row appears in audit.pipeline_run"),
    ("3.5", "Ingest, metadata-driven", "(pipeline)",
     "ForEach over the SourceFiles parameter array (isSequential false, batchCount 4) → "
     "Copy activity → Lakehouse bronze table",
     "4 bronze Delta tables written; retry 3 on transient faults"),
    ("3.6", "Validate row counts", "(pipeline)",
     "IfCondition per iteration: fail when rowsCopied &lt; item().minRows",
     "A truncated file fails loudly instead of silently producing a zero dashboard"),
    ("3.7", "Transform bronze to silver", "(pipeline)",
     "TridentNotebook → notebooks/01_bronze_to_silver.py, parameters batch_id and run_id",
     "4 silver tables written, Z-ORDERed on merchant + date"),
    ("3.8", "Run the data-quality gate", "(pipeline)",
     "TridentNotebook → dbt test. Retry 0 — a failing test is a real defect",
     "Notebook exits PASS or FAIL"),
    ("3.9", "Branch on the gate", "(pipeline)",
     "IfCondition on exitValue = 'PASS'. False branch → Teams webhook → Fail activity",
     "On failure gold is NOT rebuilt and the previous good load stays live"),
    ("3.10", "Build gold", "(pipeline)",
     "TridentNotebook → dbt build --select marts",
     "Dimensions, facts and marts rebuilt in dependency order"),
    ("3.11", "Score the ML models", "(pipeline)",
     "TridentNotebook → notebooks/03_ml_anomaly_and_forecast.py",
     "ml_anomaly_scores and ml_sales_forecast written back to gold"),
    ("3.12", "Frame the semantic model", "(pipeline)",
     "Web activity → POST /v1.0/myorg/groups/{ws}/datasets/{id}/refreshes, MSI auth",
     "Direct Lake model reframed; last refresh timestamp updates"),
    ("3.13", "Schedule it", "Data engineer",
     "Import TR_Daily_0200_SAST.json. Timezone named explicitly, not computed from UTC",
     "Trigger shows Started; next run 02:00 SAST"),
]))
F.append(PageBreak())

F += [P("Part 3b — why the pipeline is shaped this way", "h1")]
F += [callout("1. The data-quality gate sits BETWEEN silver and gold",
              "This is the most important decision in the pipeline. If the gate fails, the "
              "pipeline stops, alerts, and leaves the previous good gold layer in place — so "
              "the report keeps showing yesterday's correct numbers rather than today's wrong "
              "ones. Loading gold first and testing afterwards means the report has already "
              "published bad figures by the time anyone reads the alert. Stale-but-correct "
              "beats fresh-but-wrong: an executive working from a day-old number makes a "
              "slightly late decision; one working from a wrong number makes a wrong "
              "decision.", RED, colors.HexColor("#FDF0EE")),
      Spacer(1, 3 * mm),
      callout("2. Row-count validation catches the failure that does not throw",
              "A truncated or empty source file raises no error. The copy succeeds, the "
              "transformation succeeds, and the dashboard shows zero — which looks exactly "
              "like a genuinely bad trading day. Per-source minimum row counts "
              "(MerchantSales 20,000 · VoucherRedemptions 100,000 · SupportTickets 1,000 · "
              "MerchantReference 20) turn that silent failure into a loud one. Thresholds sit "
              "well below current volumes so normal fluctuation does not trip them, but far "
              "above zero so truncation cannot pass.", AMBER, colors.HexColor("#FEF8EC")),
      Spacer(1, 3 * mm),
      callout("3. Metadata-driven ingest, not four hard-coded copy activities",
              "A SourceFiles parameter array carries one object per source and a ForEach "
              "iterates it. Adding a fifth source is a parameter change, not a pipeline edit "
              "— which matters because pipeline edits require deployment and regression "
              "testing while parameter changes do not. It also guarantees all four copies "
              "behave identically, so a fix to retry behaviour applies everywhere rather than "
              "to whichever activity someone remembered.")]

F += [Spacer(1, 5 * mm), P("Retry policy", "h2")]
F.append(steps_table([
    ("", "Copy to Bronze", "3 retries", "60s interval",
     "Transient storage and network faults are common and genuinely self-healing"),
    ("", "Transform to Silver", "1 retry", "120s interval",
     "Largely deterministic; one retry covers a capacity blip"),
    ("", "Data Quality Gate", "0 retries", "—",
     "A failing test is a real defect. Retrying delays the alert and risks a flaky pass"),
    ("", "Build Gold", "1 retry", "120s interval", "As above"),
    ("", "ML Scoring", "1 retry", "180s interval",
     "Longer running, more exposed to capacity contention"),
    ("", "Refresh Semantic Model", "2 retries", "60s interval",
     "The Power BI REST API returns transient 429s under load"),
], widths=(8, 46, 26, 30, 90)))
F.append(PageBreak())

# ---------------------------------------------------------------- Part 3c: the ERD
F += [P("Part 3c — Gold layer ERD", "h1"),
      P("Generated from the dbt manifest, not drawn. <b>dbt docs shows the DAG</b> — which "
        "model builds from which — and that is build lineage, not entity relationships. It "
        "cannot show that fct_support_tickets.priority_key joins to dim_priority, because "
        "the fact is built from staging, not from the dimension. The real foreign keys live "
        "in the schema tests: every <b>relationships</b> test is an enforced statement that "
        "a column must resolve to another column. This diagram is derived from those tests, "
        "so it cannot drift &mdash; drop a join and the test disappears, and so does the "
        "line.", "b")]

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from _table_registry import (TABLES as _REG, TIERS as _TIERS, SUMMARY as _SUM,
                             COUNTER_ARGUMENT as _CTR, counts as _cnt, TIER_ORDER)
_C = _cnt()

# Relationship list, read from the manifest so the PDF and the ERD page cannot disagree
_man = json.loads((ROOT / "dbt" / "target" / "manifest.json").read_text(encoding="utf-8"))
_fks = []
for _uid, _n in _man["nodes"].items():
    if _n["resource_type"] != "test":
        continue
    _meta = _n.get("test_metadata") or {}
    if _meta.get("name") != "relationships":
        continue
    _kw = _meta.get("kwargs", {})
    _to = re.search(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)", _kw.get("to", "") or "")
    _frm = (_n.get("attached_node") or "").split(".")[-1]
    if _to and _frm and _kw.get("column_name"):
        _fks.append((_frm, _kw["column_name"].strip('"'), _to.group(1),
                     (_kw.get("field") or "").strip('"')))

F.append(steps_table(
    [("", f"{a}", f"{b}", f"{c}.{d}", "Enforced by a dbt relationships test")
     for a, b, c, d in sorted(set(_fks))],
    widths=(6, 46, 40, 52, 56)))

F += [Spacer(1, 4 * mm), P("Why fourteen tables when the README suggests five", "h2"),
      P(_SUM, "b")]
F.append(steps_table([
    ("", _TIERS[t][0], str(_C[t]),
     ", ".join(sorted(k for k, v in _REG.items() if v["tier"] == t)), _TIERS[t][2])
    for t in TIER_ORDER],
    widths=(6, 34, 14, 96, 50)))
F += [Spacer(1, 3 * mm),
      callout("The fair criticism, and the answer", _CTR, AMBER,
              colors.HexColor("#FEF8EC"))]
F.append(PageBreak())

# ---------------------------------------------------------------- Part 3d: controls
F += [P("Part 3d — Reconciliation and financial controls", "h1"),
      P("Controls that PASS matter as much as controls that fail: a control nobody can see "
        "is a control nobody trusts. <b>mart_reconciliation</b> materialises each check with "
        "its expected value, actual value, variance and a derived status.", "b")]
F.append(steps_table([
    ("1", "Source control &mdash; sales value survives bronze to gold", "PASS",
     "R65,521,298.75 both sides",
     "Every step between landing and the star schema is a cast, a filter on invalid rows or "
     "a regroup at the same grain. None may change revenue."),
    ("2", "Source control &mdash; voucher rows survive", "PASS", "120,969 both sides",
     "One row per voucher in, one row out. Any loss is a defect."),
    ("3", "Source control &mdash; ticket rows survive", "PASS", "1,363 both sides",
     "As above for the ticket fact."),
    ("4", "Voucher control &mdash; redeemed + outstanding = issued", "PASS",
     "R22,019,852.75", "A voucher is either redeemed or outstanding. If these do not sum to "
     "value issued, value has been created or destroyed in the model."),
    ("5", "Mart control &mdash; scorecard ties to the sales fact", "PASS",
     "R65,521,298.75", "The scorecard is rebuilt through two ephemeral intermediate models; "
     "a refactor there is exactly what could silently drop a merchant."),
    ("6", "Population control &mdash; the two value facts do NOT tie", "EXPECTED",
     "R43,501,446 variance",
     "The most important control here. MerchantSales is a daily aggregate of ALL "
     "transactions (510,127); VoucherRedemptions is a voucher-level extract covering roughly "
     "1 in 4.2 of them (120,969). They describe different populations and must never be "
     "forced to tie. Recording that as an EXPECTED variance is what stops someone "
     "escalating a R43.5m 'break' &mdash; or dividing one by the other and reporting a "
     "value-based redemption rate against the wrong denominator."),
], widths=(8, 58, 20, 34, 82)))

F += [Spacer(1, 4 * mm), P("Fraud and risk controls &mdash; what the data supports", "h2")]
F.append(steps_table([
    ("", "Reversal ticket rate", "SUPPORTED", "reversal_per_1k_txn",
     "Reversal Query tickets per 1k transactions. Reversals are where value moves back."),
    ("", "Redemption velocity", "SUPPORTED", "same_day_redemption_rate",
     "Same-day redemption share. Legitimate for airtime, unusual in bulk."),
    ("", "Outstanding liability concentration", "SUPPORTED", "outstanding_value",
     "Unredeemed value sitting with one merchant."),
    ("", "Behavioural anomaly", "SUPPORTED", "Isolation Forest",
     "Multivariate shift against a merchant's own history."),
    ("", "Voucher value outliers", "TESTED &mdash; NIL", "value_outlier_vouchers",
     "Implemented and evaluated: ZERO vouchers beyond 3 SD within type, because the "
     "synthetic generator used a bounded distribution. The control runs and correctly "
     "returns zero rather than being quietly omitted."),
    ("", "Duplicate redemption", "NOT SUPPORTED", "&mdash;",
     "voucher_id is unique by construction in the extract, so a duplicate cannot appear. "
     "Needs a raw redemption event log with repeated attempts."),
    ("", "Geographic anomaly", "NOT SUPPORTED", "&mdash;",
     "Needs merchant location, transaction location and timestamp. Only static province at "
     "merchant level is supplied."),
    ("", "PIN / invalid voucher use", "NOT SUPPORTED", "&mdash;",
     "Needs voucher PIN, attempt outcome and failure reason."),
    ("", "Customer velocity / customer CLV / churn", "NOT SUPPORTED", "&mdash;",
     "There is no customer identifier anywhere in the four source files. Merchant-level "
     "lifetime value and attrition risk are built instead, in mart_merchant_value_risk."),
], widths=(6, 46, 26, 34, 88)))
F.append(PageBreak())

# ---------------------------------------------------------------- Part 4: promote & operate
F += [P("Part 4 — Promotion, monitoring and daily operation", "h1")]
F.append(steps_table([
    ("4.1", "Create the deployment pipeline", "Fabric admin",
     "Fabric → Deployment pipelines → New → assign Dev / Test / Prod workspaces",
     "Three stages show item counts"),
    ("4.2", "Parameterise per stage", "Data engineer",
     "Deployment rules: workspace id, semantic model id, notebook ids. Never literals",
     "The same pipeline JSON promotes unchanged"),
    ("4.3", "Deploy Dev → Test", "BI developer",
     "Compare → Deploy. Run the pipeline once end to end in Test",
     "audit.pipeline_run shows SUCCEEDED and dbt tests pass in Test"),
    ("4.4", "Deploy Test → Prod", "Release manager",
     "Compare → Deploy, then enable TR_Daily_0200_SAST",
     "Trigger Started; first scheduled run completes"),
    ("4.5", "Configure failure alerting", "Data engineer",
     "Teams webhook on the DQ-gate false branch; Fabric Monitor → set alert on pipeline "
     "failure",
     "A deliberately failed run posts to the channel"),
    ("4.6", "Configure change alerting", "BI developer",
     "Surface mart_merchant_change_alerts on the Insights page; optionally add a Data "
     "Activator rule on severity = 'Critical'",
     "A merchant moving to 'At Risk' raises an alert within one refresh cycle"),
    ("4.7", "Monitor source freshness", "Data engineer",
     "dbt source freshness — warn at 26h, error at 48h",
     "A stalled upstream feed surfaces as a dbt error, not as stale numbers in the report"),
    ("4.8", "Review the run daily", "BI support",
     "Check audit.pipeline_run, then the dbt test summary, then the report refresh timestamp",
     "Three green signals before 07:00"),
]))

F += [Spacer(1, 4 * mm), P("Daily operational checklist", "h2")]
F.append(steps_table([
    ("1", "Pipeline completed", "audit.pipeline_run", "status = 'SUCCEEDED' for today's batch",
     "If RUNNING past 03:00, check Fabric Monitor for a stuck notebook"),
    ("2", "Quality gate passed", "dbt test output", "153 pass, 0 error",
     "If failed, gold was intentionally not rebuilt — fix the source, do not force the run"),
    ("3", "Row counts sane", "bronze tables", "Within the configured minRows floors",
     "A large drop with a passing pipeline still warrants a look at the source file"),
    ("4", "Semantic model framed", "Power BI dataset", "Last refresh within the last 6 hours",
     "Direct Lake still needs framing after the Delta tables change"),
    ("5", "Change alerts triaged", "mart_merchant_change_alerts",
     "No unreviewed Critical rows", "An 'At Risk' flag should be cross-checked against the "
     "computed health score before anyone acts on it"),
], widths=(10, 44, 40, 56, 50)))

F += [Spacer(1, 5 * mm),
      callout("Known issue to raise with the business on day one",
              "The supplied BaseMonthlySalesTarget sits roughly 6.1x below realised sales for "
              "all 25 merchants, so raw target attainment reads about 614%. The consistency "
              "across every merchant points to a basis or units error rather than genuine "
              "outperformance. The supplied value is retained unchanged for transparency and "
              "the report uses a relative Target Attainment Index instead. Confirming the "
              "intended basis is the first question for Finance.",
              RED, colors.HexColor("#FDF0EE"))]

doc.build(F, onFirstPage=header_footer, onLaterPages=header_footer)
print(f"Wrote {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
