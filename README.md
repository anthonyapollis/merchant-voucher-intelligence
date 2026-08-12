# Merchant Sales & Voucher Intelligence

**BI Developer — Second-Round Practical Task**
Microsoft Fabric · Power BI · dbt · SQL · Python ML

A production-minded analytics solution over the supplied merchant voucher dataset: a Fabric
medallion pipeline feeding a Kimball star schema, a dbt transformation layer with a 69-test
suite, an eight-page Power BI project centred on executive, merchant and operational views,
and five machine-learning models.

---

## Start here

| If you want to… | Open |
|---|---|
| **See the report** | [`report/dashboard.html`](report/dashboard.html) — interactive, 6 pages, opens in any browser, no dependencies |
| **Read the submission** | [`report/OPEN_THIS_FINAL_MERGED_SUBMISSION.docx`](report/) |
| **Check brief coverage** | [`docs/05_Interview_Assessment_Matrix.md`](docs/05_Interview_Assessment_Matrix.md) |
| **Practise the walkthrough** | [`docs/06_Five_Minute_Demo_Script.md`](docs/06_Five_Minute_Demo_Script.md) |
| **Work with the numbers** | [`excel/Merchant_Voucher_Intelligence_Report.xlsx`](excel/) — 10 sheets |
| **Review the engineering** | [`dbt/`](dbt/), [`sql/`](sql/), [`notebooks/`](notebooks/), [`datafactory/`](datafactory/) |
| **Check the measures** | [`dax/`](dax/) and [`docs/dax_validation.csv`](docs/) |
| **Rebuild everything** | See *Reproducing the results* below |

---

## Headline results

| Metric | Value |
|---|---:|
| Total sales | R65,521,299 |
| Transactions | 510,127 |
| Average basket value | R128.44 |
| Redemption rate | 84.19% |
| Avg days to redeem | 3.58 (median 2) |
| Outstanding liability | R3,541,563 |
| Support tickets | 1,363 |
| SLA breach rate | 26.27% |

### The four findings that matter

1. **Umhlanga Value Mart is failing, and it is operational, not demand.** July sales fell
   42.5% against its own prior three-month average while support tickets rose 693% in the
   same month. R571,518 annualised revenue at risk — and plausibly recoverable, because the
   two moving together points to a service breakdown rather than lost demand.

2. **The SLA policy is configured backwards.** Critical tickets get a 12-hour target but take
   52.7 hours on average (98.3% breach rate); Low gets 48 hours and takes 11.3 (0.2%). The
   ladder runs opposite to the actual workload, so **94.7% of all 358 breaches land on High
   and Critical**. The reported 26% breach rate is measuring a policy misconfiguration, not
   team performance.

3. **Eastern Cape is the one declining region**, on four independent signals: the only region
   that peaked before July, 9.8% below its own peak while every other region is at its peak,
   the flattest trend slope, and a 12.2% June fall against +1.4% to +3.8% elsewhere.

4. **Operational friction does *not* predict merchant performance — and the obvious analysis
   says it does.** Tickets per 1,000 transactions correlates with target attainment at
   r = −0.56, which looks conclusive. It is confounded: the ratio is size-dependent
   (r = −0.83 against log total sales). Controlling for size, the partial correlation
   collapses to **r = −0.20**. The real signal is event-level, not portfolio-level.

5. **The CRM "At Risk" flag has zero overlap with actual deterioration.** Both merchants
   flagged At Risk (Mango Tree Mobile, Ubuntu Trading Post) are *growing* and score Healthy
   (61.7 and 68.3). Every merchant in genuine decline — including Umhlanga Value Mart at
   −42.5% with R571k annualised at risk — is flagged **"Active"**. R1.08m of at-risk revenue
   sits in merchants the CRM considers fine. The existing manual flag is not detecting the
   problem it exists to detect, which is the clearest argument for the computed Health Score.

6. **The open-ticket backlog is not one problem, it is two.** Of 239 open tickets, **146 are
   awaiting us** (Open + Escalated) and **93 are awaiting the customer** (Pending Merchant).
   Those need different remediation, and a single "239 open" figure hides the distinction
   entirely — which is why `dim_ticket_status` carries an explicit `ownership` attribute.

---

## Architecture

```
LANDING          BRONZE            SILVER              GOLD                 CONSUME
4 CSV files  →   Delta,        →   typed, cleansed, →  Kimball star     →   Power BI (Direct Lake)
                 raw + lineage     deduplicated,       6 dims · 4 facts     Excel pack
                 no logic          conformed,          1 mart · 2 ML        Fabric notebooks
                                   business rules      output tables        Copilot / Q&A

         ORCHESTRATION — Data Factory, metadata-driven, daily 02:00 SAST
         with the dbt test gate sitting BETWEEN silver and gold
```

### Why 14 tables when the README suggests 5

The supplied README suggests a 5-table model. This solution has 14. That difference is
justified table by table — the rationale lives in one place
([`scripts/_table_registry.py`](scripts/_table_registry.py)) and is rendered into the ERD,
the dbt model descriptions, the Word report, the Excel data dictionary and the dashboard, so
the same answer appears wherever the question is asked.

| Tier | Count | Tables |
|---|---:|---|
| **README model** — named in the supplied README | 5 | `dim_date` `dim_merchant` `fct_merchant_sales` `fct_support_tickets` `fct_voucher_redemptions` |
| **Brief deliverable** — required by a stated report requirement | 4 | `dim_priority` `dim_ticket_status` `dim_ticket_type` `dim_voucher_type` |
| **Grain necessity** — separate grain, additivity | 1 | `fct_merchant_target` |
| **My extension** — beyond the brief, added on judgement | 4 | `dim_merchant_history` `mart_merchant_change_alerts` `mart_merchant_scorecard` `snap_merchant` |

The honest split is a **10-table core plus 4 extensions**. Presenting all 14 as though the
brief demanded them would be overselling it.

**The four attribute dimensions** exist because the brief's own §5 report requirements
(voucher type performance, ticket priority, SLA risk, backlog) need somewhere to put those
attributes, and because they carry metadata absent from the source — `dim_priority` holds the
derived `sla_is_achievable`, `dim_ticket_status` holds the `ownership` split that separates
"awaiting us" (146) from "awaiting customer" (93).

**`fct_merchant_target` is a grain decision.** `BaseMonthlySalesTarget` could sit on
`dim_merchant`, but it is a *monthly* measure against *daily* sales — on the dimension it
would re-count once per fact row.

**The fair criticism:** four dimensions of 4–6 rows is over-normalisation, and some modellers
would keep them as degenerate columns on the ticket fact. That was in fact the first design
here, and it was worse: the three FKs on `fct_support_tickets` could not be
relationship-tested (a test cannot distinguish "priority_key resolves to a priority" from
"resolves to *something*"), and Power BI cannot build three independent filter paths off one
physical table. Splitting them added **9 enforced foreign keys that previously could not
exist**.

### Three engineering decisions worth reviewing

**The data-quality gate sits between silver and gold.** The dbt suite runs against silver and
gold is only rebuilt if every test passes. On failure the pipeline stops and leaves the
previous good gold layer in place, so the report keeps showing yesterday's correct numbers
rather than today's wrong ones. Stale-but-correct beats fresh-but-wrong.

**The gold layer is built twice.** Once in pandas (`scripts/02_build_warehouse.py`), once in
dbt SQL (`dbt/models/`). `scripts/05_reconcile.py` compares every headline figure. Two
different engines agreeing to the cent is what makes "the numbers tie" verifiable rather than
asserted — and it caught two real defects that no unit test would have found (see below).

**Three conformed ticket dimensions, not one combined table.** `dim_ticket_type`,
`dim_priority` and `dim_ticket_status` were originally unioned into a single table behind a
`dimension_type` discriminator. That had two real costs: the three foreign keys on
`fct_support_tickets` could not be tested for referential integrity (a `relationships` test
could not distinguish "priority_key resolves to a priority" from "resolves to something,
somewhere"), and Power BI cannot build three independent filter paths off one physical table
without role-playing copies. Six rows is not too small to deserve its own dimension — join
clarity matters more than table count.

**A Type 2 snapshot on merchant attributes.** `MerchantReference` is a current-state extract:
each load overwrites the last, so `active_status`, `account_manager` and
`base_monthly_sales_target` history is destroyed at source. `snap_merchant` captures it using
the `check` strategy (the source has no reliable last-modified column — `OnboardedDate` is
when the merchant joined, not when the row was edited). `dim_merchant_history` exposes it as
a versioned dimension alongside the Type 1 `dim_merchant`. Both exist deliberately: current
state for the default report joins, versioned for point-in-time questions. Validated with
`scripts/_test_scd2.py`, which simulates a real change and asserts history was captured
correctly — 7/7 assertions — then restores the original state.

**Role-playing dates on the voucher fact.** `sold_date_key` is the active relationship,
`redeemed_date_key` inactive and activated via `USERELATIONSHIP`. Without that separation,
late redemptions are attributed back to the month of sale and a redemption backlog is
invisible.

---

## Quality gates

| Gate | Result |
|---|---|
| Warehouse integrity tests | **14 / 14** |
| dbt build (models + seeds + snapshot + tests) | **153 pass · 0 warn · 0 error** |
| dbt tests | **132** |
| SCD Type 2 behaviour assertions | **7 / 7** |
| Python ↔ dbt reconciliation | **27 pass · 1 documented warning · 0 fail** |
| DAX measures with SQL-derived expected values | **31** |
| Dashboard static validation | **24 / 24** |

### Two defects the reconciliation caught

Worth calling out because both would have shipped silently:

1. **`dim_date` was absorbing the August redemption tail into the reporting window.** A
   voucher sold on 31 July can be redeemed on 20 August, so the calendar must *span* those
   dates — but the reporting *window* must not. The bug inflated pro-rated sales targets by
   **R984,046** against a month containing no sales at all.

2. **Python and SQL percentile-rank conventions differ.** `pandas.rank(pct=True)` returns
   `rank/n`; ANSI `PERCENT_RANK()` returns `(rank−1)/(n−1)`. Using them interchangeably
   shifted the Health Score by up to **9.7 points**.

The one remaining warning is a 0.1 difference on the Health Score from Python's banker's
rounding versus SQL's round-half-up. Every *input* to the score reconciles to 0.000000, which
is what proves it is a presentation artefact — and that proof is only available because the
inputs are compared individually rather than just the result.

---

## Machine learning

| Model | Algorithm | Validation | Result |
|---|---|---|---|
| Anomaly detection | Isolation Forest | Unsupervised, checked against 4 documented embedded patterns | **4 / 4 recovered unprompted** |
| Redemption propensity | HistGradientBoostingClassifier | Time split (train Jan–May, test Jun–Jul) | AUC 0.620 vs ceiling 0.621 |
| Resolution time | HistGradientBoostingRegressor | Time split | MAE 9.8h, 23% better than naive |
| Sales forecast | Holt-Winters | Backtest on held-out 30 days | MAPE 4.69%, 50% better than naive |
| Segmentation | K-Means (k=4) | Silhouette across k=2..7 | 4 segments, 2 singletons found automatically |

**Every supervised model uses a time-based split, never random.** A random split leaks future
information and produces a metric that will not survive production.

**On the 0.620 AUC.** Rather than explaining it away, it was tested against a theoretical
ceiling: if redemption is generated purely from voucher type, the best any model can achieve
is the type-level base rate — an oracle scoring 0.621. The model captures **99.8% of the
achievable signal**, so the limit is the data, not the model. Establishing that distinction
stops a team spending a sprint chasing an AUC that cannot move. The ranking is still useful:
the top risk decile carries 3.4× the non-redemption rate of the bottom.

---

## Note: two builds coexist in this folder

This folder already contained an **earlier, independent build of the same task** dated
5–6 August 2026. It has been left completely untouched — it uses PascalCase table names
(`DimDate.parquet`, `FactMerchantSales.parquet`) while this build uses snake_case
(`dim_date.parquet`, `fact_merchant_sales.parquet`), so nothing collided or was overwritten.

The earlier build contributes something this one does not: an actual **Power BI PBIP/PBIT
project** (`powerbi/MerchantVoucherIntelligence.pbip`, `.pbit`, and the packaged
`MerchantVoucherIntelligence_PowerBI.zip`) with 8 report pages defined in TMDL. That is the
openable Power BI artefact for the submission. This build contributes the dbt layer, the
reconciliation harness, the Excel pack, the validated DAX reference and the Word submission.

| From the 6 Aug build | From this build |
|---|---|
| `powerbi/*.pbip` / `.pbit` / `.Report` / `.SemanticModel` (TMDL) | `dbt/` — 13 models, 69 tests |
| `MerchantVoucherIntelligence_PowerBI.zip` (packaged, `OPEN_ME_FIRST.txt`) | `report/dashboard.html`, `…Submission.docx` |
| `dashboard/index.html` | `excel/…Report.xlsx` |
| `fabric/` notebooks, SQL, pipeline | `sql/`, `notebooks/`, `datafactory/` |
| `build/`, `docs/01–04*.md` | `scripts/`, `docs/*.json`, `docs/dax_validation.csv` |
| `data/gold/*PascalCase*` | `data/gold/*snake_case*`, `data/mvi.duckdb` |

**The two agree exactly.** `scripts/_crosscheck_prior_build.py` compares them:

```
Metric                 6 Aug build     11 Aug build    Variance
Sales value          65,521,298.75    65,521,298.75        0.00
Transactions            510,127.00       510,127.00        0.00
Voucher value        22,019,852.75    22,019,852.75        0.00
Resolution hours         32,343.50        32,343.50        0.00
```

Three independent implementations — the earlier build, this pandas build, and the dbt SQL
build — produce identical totals. Before submitting, decide which set of artefacts to lead
with; the duplication is deliberate but should not go to a reviewer unexplained.

---

## Repository layout

```
├── data/            bronze / silver / gold / analytics / ml as parquet + mvi.duckdb
├── dbt/             13 models, 69 tests, 3 seeds, 3 exposures, macros
├── sql/             Fabric Warehouse DDL + the business-question queries
├── notebooks/       Fabric PySpark: bronze→silver, ML scoring with MLflow
├── datafactory/     Pipeline JSON, schedule trigger, design rationale
├── dax/             31+ measures across 4 files, with commentary
├── powerbi/         Semantic model spec, Q&A synonym schema
├── excel/           10-sheet Excel pack
├── report/          Interactive dashboard + Word submission
├── scripts/         Runnable reference implementation (01–09)
└── docs/            Profile, analytics summary, ML summary, reconciliation, DAX validation
```

---

## Reproducing the results

Requires Python 3.11+ with `pandas`, `duckdb`, `scikit-learn`, `statsmodels`, `xlsxwriter`,
`python-docx`, and `dbt-duckdb`. Runs end to end in under two minutes.

```bash
python scripts/01_profile.py          # profile sources, confirm embedded patterns
python scripts/02_build_warehouse.py  # bronze → silver → gold + 14 integrity tests
python scripts/03_analytics.py        # KPI / semantic layer
python scripts/04_ml_models.py        # 5 models
python scripts/_load_bronze_duckdb.py # register bronze for dbt
cd dbt && dbt deps && dbt seed && dbt run && dbt test && cd ..
python scripts/05_reconcile.py        # Python ↔ dbt cross-validation
python scripts/06_validate_dax.py     # SQL-derived expected values per measure
python scripts/07_build_excel.py      # Excel pack
python scripts/08_build_dashboard.py  # interactive dashboard
python scripts/09_build_report_docx.py
```

---

## Assumptions and known issues

Fully documented in section 9 of the submission and sheet 10 of the Excel pack. The two that
most affect interpretation:

**Sales targets are mis-calibrated.** `BaseMonthlySalesTarget` sits ~6.1× below realised sales
for *all 25 merchants*, so raw target attainment reads 614%. The consistency across every
merchant points to a basis or units error rather than genuine outperformance. The supplied
value is retained unchanged for transparency, and the report uses a relative **Target
Attainment Index** (merchant attainment ÷ portfolio attainment) which is immune to the error.
Confirming the intended basis is the first question for the business.

**Seven months of data.** No year-on-year comparison is possible. The YoY measures are written
and will work once a second year exists, but currently return `BLANK` by design rather than a
misleading zero.

---

*All findings describe the supplied synthetic dataset. The anomaly model independently
recovering the four embedded patterns validates the method; it does not validate the
conclusions against real trading behaviour.*
