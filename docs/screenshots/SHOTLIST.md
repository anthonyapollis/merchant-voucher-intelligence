# Screenshot shot list — Fabric proof, start to finish

Save each shot into this folder using the **exact filename** in the left column. The build
matches on the prefix, so `01_workspace.png`, `01_workspace_v2.png` and `01_workspace-fin.jpg`
all work — anything starting with that prefix is picked up.

Then run:

```powershell
python scripts\20_embed_screenshots.py
```

It rebuilds the runbook PDF and the Word report with every image embedded, captioned and
placed in its section. Shots you skip are left out — nothing breaks.

**Format**: PNG preferred, full window rather than the whole desktop. `Win + Shift + S` →
*Window* snip, or `Alt + PrtScn` to copy the active window.

**Status**: 8 of 30 slots filled. The 8 already present are generated artifacts (terminal
output, the lineage DAG, the ERD); the rest are portal and desktop captures.

---

## Part 0 — Ingestion, start to finish

This is the sequence that tells the whole story: a supplied ZIP arrives, is detected and
unpacked, lands as bronze Delta, is cleansed to silver, conformed to gold, and read by the
report. Capture these **in order** — the order is the argument.

| Filename | What to capture | Why it matters |
|---|---|---|
| `23_landing_zip.png` | Lakehouse → `Files/landing` with the supplied ZIP present | The raw input, before anything has run |
| `24_notebook_unzip.png` | `nb_01_pc_zip_to_bronze` open, showing the extract-and-write cells | The autoloader detects csv, zip, xlsx, parquet and json — not one hard-coded format |
| `25_files_extracted.png` | `Files/` after extraction, four CSVs unpacked | Proves the unzip step actually produced the sources |
| `26_bronze_tables.png` | `Tables/dbo` with the four `bronze_*` Delta tables, one opened showing rows | Bronze exists **in Fabric**, with real data and row counts |
| `27_silver_tables.png` | The silver tables — typed, cleansed, conformed | The layer where the duplicated Merchant/Region/Channel columns are resolved |
| `28_gold_tables.png` | The gold star schema tables | What Power BI actually reads |
| `29_pipeline_canvas.png` | `pl_pc_ingestion_bronze_silver_gold` on the Data Factory canvas | The four stages wired in dependency order |
| `30_pipeline_run.png` | A completed run: per-activity status and duration | **Run history is the proof it executes**, not merely that it was authored |

## Part 1 — Fabric workspace

| Filename | What to capture | Why it matters |
|---|---|---|
| `01_workspace.png` | `WS_MerchantVoucher` list view, all items visible | The workspace exists on trial capacity |
| `02_capacity.png` | Workspace settings → License mode → **Fabric capacity / Trial** | This is what a Free account cannot do |
| `03_lakehouse.png` | `LH_MerchantVoucher` open, Tables and Files panes both visible | The medallion landing target |
| `05_sql_endpoint.png` | Warehouse → Settings → SQL endpoint connection string | The endpoint dbt connects to. The string is not a secret — but do not capture a token |

`04_warehouse` is already filled from REST API output.

## Part 3 — Orchestration

| Filename | What to capture | Why it matters |
|---|---|---|
| `11_pipeline.png` | The pipeline item in the workspace list | — |
| `12_trigger_disabled.png` | The schedule pane showing the trigger **disabled**, end date 2026-10-03 | The cost control, evidenced rather than described |
| `13_notebook.png` | `00_autoload_landing` — the generic autoloader | Handles new files of any supported type without a code change |
| `14_monitor.png` | Fabric **Monitor** → run history | Independent record that runs happened |

## Part 4 — Power BI

Take these from Power BI Desktop with `MerchantVoucherIntelligence.pbit` open.

| Filename | What to capture |
|---|---|
| `15_pbi_exec.png` | Executive Overview |
| `16_pbi_business_answers.png` | Business Answers — the five brief questions |
| `17_pbi_reconciliation.png` | Reconciliation & Controls, including the explained R43.5m population variance |
| `18_pbi_value_risk.png` | Merchant Value & Risk |
| `19_pbi_mobile.png` | View → Mobile layout, phone canvas |

## Part 5 — Cost control

| Filename | What to capture | Why it matters |
|---|---|---|
| `21_trial_days.png` | Trial days remaining against the 2026-10-10 expiry | Ties the kill-switch dates to what the portal reports |

`20_cost_guard` is already filled from command output.

---

## A note on what these prove

The terminal captures are the stronger evidence and are already in place: command output
cannot be staged, whereas a portal screenshot shows a state without showing how it was
reached. The portal shots matter for a different reason — they show the artifacts existing in
Fabric rather than described in a document. Both belong in the appendix, which is why the two
kinds sit side by side there.
