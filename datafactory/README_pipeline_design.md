# Data Factory / Fabric Pipeline Design

## Why the pipeline is shaped this way

The orchestration is not incidental to the solution — three specific design decisions in
`PL_MerchantVoucher_Master.json` exist because of failure modes seen in production BI:

### 1. Metadata-driven ingest, not four hard-coded copy activities

The `SourceFiles` parameter carries one object per source file:

```json
{"fileName": "MerchantSales.csv", "bronzeTable": "bronze_merchant_sales", "minRows": 20000}
```

A `ForEach` iterates it. Adding a fifth source is a parameter change, not a pipeline edit —
which matters because pipeline edits require a deployment and a regression test, whereas a
parameter change does not. It also means all four copies are defined identically, so a fix
to retry behaviour applies everywhere instead of to whichever copy activity someone
remembered.

### 2. The data-quality gate sits BETWEEN silver and gold

This is the most important decision in the pipeline.

The dbt test suite (69 tests) runs against silver. Gold is only built if every test passes.
If the gate fails, the pipeline stops, alerts Teams, and **leaves the previous good gold
layer in place**. The Power BI report keeps showing yesterday's correct numbers rather than
today's wrong ones.

The alternative — load gold, then test — means the report has already published bad figures
by the time anyone sees the alert. Stale-but-correct beats fresh-but-wrong: an executive
working from a day-old number makes a slightly late decision, one working from a wrong
number makes a wrong decision.

### 3. Row-count validation catches the failure mode that does not throw

A truncated or empty source file does not error. The copy succeeds, the transformation
succeeds, and the dashboard shows zero — which looks exactly like a genuinely bad trading
day. The `minRows` floor per source turns that silent failure into a loud one:

| Source | Minimum rows | Actual |
|---|---:|---:|
| MerchantReference.csv | 20 | 25 |
| MerchantSales.csv | 20,000 | 26,500 |
| VoucherRedemptions.csv | 100,000 | 120,969 |
| SupportTickets.csv | 1,000 | 1,363 |

Thresholds are set well below current volumes so normal fluctuation does not trip them, but
far above zero so a truncation cannot pass.

## Pipeline flow

```
Set Batch ID
     │
Log Pipeline Start ──────────────► audit.pipeline_run (RUNNING)
     │
ForEach Source File  (parallel, batchCount 4)
     ├─ Copy to Bronze          (retry 3, 60s interval)
     └─ Validate Row Count      → Fail if below minRows
     │
Transform Bronze → Silver       (Fabric notebook, retry 1)
     │
Run Data Quality Gate           (dbt test, retry 0 — a failing test must not be retried)
     │
Check Quality Gate Result
     ├── FAIL ──► Alert Teams ──► Fail Pipeline   (gold untouched)
     │
     └── PASS ──► Build Gold Star Schema   (dbt run --select marts)
                       │
                  Run ML Scoring           (anomaly, propensity, forecast, segmentation)
                       │
                  Refresh Semantic Model   (Direct Lake framing)
                       │
                  Log Pipeline Success ──► audit.pipeline_run (SUCCEEDED)
```

## Retry policy rationale

| Activity | Retries | Why |
|---|---:|---|
| Copy to Bronze | 3 | Transient storage/network faults are common and genuinely self-healing |
| Transform to Silver | 1 | Usually deterministic; one retry covers a capacity blip |
| **Data Quality Gate** | **0** | A failing test is a real defect. Retrying it just delays the alert and risks a flaky pass |
| Build Gold | 1 | As above |
| ML Scoring | 1 | Longer running, more exposed to capacity contention |
| Refresh Semantic Model | 2 | The Power BI REST API returns transient 429s under load |

## Scheduling

`TR_Daily_0200_SAST` fires at 02:00 South Africa Standard Time — after overnight settlement
files land (~01:15) and comfortably before the 07:00 executive review.

The timezone is stated explicitly rather than computed from UTC. SAST is UTC+2 with no
daylight saving, so the arithmetic is currently trivial — but if the Fabric capacity is ever
moved to another region, an implicit UTC offset silently shifts the run by an hour and the
morning report is not ready. Naming the timezone costs nothing and removes the failure.

## Deployment

Pipelines are deployed through Fabric deployment pipelines (Dev → Test → Prod) with
parameters bound per stage. Workspace, semantic model and notebook IDs are all parameters,
never literals, so the same JSON promotes unchanged between environments.
