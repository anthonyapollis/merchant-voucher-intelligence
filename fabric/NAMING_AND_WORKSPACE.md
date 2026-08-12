# Fabric workspace structure and naming convention

## Workspace layout

One workspace per environment, with the environment in the name so a
mis-targeted deployment is obvious in the URL rather than discovered later.

```
ws-merchant-analytics-dev
ws-merchant-analytics-test
ws-merchant-analytics-prod
```

Items inside each:

| Item | Name | Purpose |
|---|---|---|
| Lakehouse | `lh_merchant_bronze` | Raw landing, append-only, replayable |
| Lakehouse | `lh_merchant_silver` | Cleaned, typed, conformed business entities |
| Lakehouse | `lh_merchant_gold` | Star schema the semantic model reads |
| Warehouse | `wh_merchant_analytics` | Optional T-SQL surface over the same star schema |
| Notebook | `nb_01_bronze_ingest` | Land the four sources |
| Notebook | `nb_02_silver_conform` | Clean, de-duplicate, conform |
| Notebook | `nb_03_gold_star_schema` | Build dimensions and facts |
| Notebook | `nb_04_ai_anomaly_and_narrative` | Anomaly table and narrative table |
| Notebook | `nb_05_ml_models` | Segmentation, propensity, forecast |
| Pipeline | `pl_merchant_daily_refresh` | Orchestrates the above, nightly |
| Semantic model | `sm_merchant_intelligence` | The shared model |
| Report | `rpt_merchant_intelligence` | The four-page report |

The deployment pipeline promotes dev to test to prod. Only the lakehouse
connection and the landing folder differ between stages, and both are
parameters, so nothing in a notebook needs editing to promote it.

## Naming rules

**Layer prefixes on tables.** Bronze `br_`, Silver `slv_`, Gold none. Gold
tables carry the star-schema convention instead: `Dim` or `Fact` followed by
the business entity in PascalCase (`DimMerchant`, `FactMerchantSales`). Gold is
the layer business users see, so it reads like a model rather than like
plumbing.

**Keys end in `Key`.** `MerchantKey`, `DateKey`, `VoucherTypeKey`. A column
called `MerchantID` is a source system's identifier; a column called
`MerchantKey` is this model's. The rename happens once, in Silver.

**Flags start with `Is` and are 0/1 integers, never text.** `IsRedeemed`,
`IsSLABreach`, `IsOpen`. Integers so they can be summed directly in DAX;
`SUM(IsSLABreach)` is a breach count and `AVERAGE(IsSLABreach)` is a breach
rate, with no `IF` in sight.

**Measures are business language, not column names.** `Total Sales`, not
`Sum of SalesValue`. Spaces are fine and expected in measure names; they are
read by executives, not typed by developers.

**Nothing in the model is called `Amount`, `Value`, `Count` or `Date` on its
own.** Those names collide the moment a second fact table arrives.

**Lineage columns are underscore-prefixed.** `_ingested_at_utc`, `_run_id`,
`_source_file`. The prefix keeps them sorted together and makes it obvious
they are not business data. They stop at Silver and never reach Gold.

## Layer contract

| | Bronze | Silver | Gold |
|---|---|---|---|
| Schema | As received | Typed and named | Star schema |
| Cleaning | None | De-duplicated, trimmed, validated | Already clean |
| Grain | As received | One row per business key | Fact grain |
| Deletes | Never | Never | Rebuilt each run |
| Who reads it | Engineers | Engineers, analysts | Everyone |

The important rule is the Bronze one. Bronze is never corrected. If a source
file is wrong, Bronze stays wrong and Silver fixes it, because that is what
makes a Silver bug provable and a reload repeatable.

## Refresh sequence

`pl_merchant_daily_refresh`, nightly at 02:00 SAST:

1. `nb_01_bronze_ingest` — fails the run if any source lands zero rows
2. `nb_02_silver_conform` — fails the run on an orphan merchant key
3. `nb_03_gold_star_schema`
4. `02_data_quality_checks.sql` — fails the run if it returns any row
5. `nb_04_ai_anomaly_and_narrative`
6. `nb_05_ml_models` — Sundays only; the models do not move daily
7. Semantic model refresh
8. On failure at any step: Teams alert to the BI channel, and the semantic
   model is left on the previous good refresh rather than half-updated

Step 4 is the one that matters. A pipeline that refreshes a dashboard with
broken data is worse than a pipeline that fails loudly, because someone will
present from it before anyone notices.
