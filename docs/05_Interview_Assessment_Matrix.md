# Interview assessment matrix

This matrix maps the supplied BI Developer practical brief to evidence already present in the submission. It is intentionally concise so an interviewer can verify coverage without reading the full technical report first.

| Brief requirement | Delivered evidence | Where to review |
|---|---|---|
| FactMerchantSales | Daily merchant and voucher-type sales fact at a declared grain | Power BI model; `data/gold/FactMerchantSales.csv`; `docs/02_Model_Design.md` |
| FactVoucherRedemptions | Voucher-level fact with sold-date and redeemed-date analysis | Power BI model; `data/gold/FactVoucherRedemptions.csv`; reusable redemption DAX |
| FactSupportTickets | Ticket-level operational fact with priority, status, SLA and ownership | Power BI model; `data/gold/FactSupportTickets.csv`; Operational View |
| DimMerchant | One governed merchant dimension sourced from MerchantReference | Power BI model; `data/gold/DimMerchant.csv` |
| Proper DimDate | Generated date dimension spanning every fact date, including August redemptions | `data/gold/DimDate.csv`; `docs/02_Model_Design.md` |
| Document assumptions | Grain, null handling, date roles, targets, limitations and ML caveats documented | `docs/01_Assumptions_and_Data_Quality.md` |
| Reusable DAX | Core, time-intelligence, operational, ranking and narrative measures | `dax/01_core_measures.dax` through `dax/04_ranking_and_narrative.dax` |
| Executive view | Portfolio KPIs, trend, target attainment, priority exceptions and management narrative | Power BI page: **Executive Overview** |
| Merchant detail view | Merchant selector, performance trend, mix, operations and drill-through context | Power BI page: **Merchant Analysis** plus drill-through page |
| Operational view | Ticket backlog, ownership, priority, SLA breach and resolution performance | Power BI page: **Operational View** |
| AI/anomaly extension | Isolation Forest anomalies, merchant segmentation, forecasts and governed narratives | Power BI page: **Intelligence Lab**; `docs/04_AI_and_ML_Extension.md` |
| Microsoft Fabric | PC ZIP ingestion, Bronze-Silver-Gold notebooks, Data Factory orchestration and quality gate | Report Appendices C-D; completed pipeline run `30f66673-261b-43cc-8d1b-58bf9516f3f0` |

## Embedded-pattern recovery

| Supplied pattern | Recovered finding | Decision implication |
|---|---|---|
| Visible July sales decline | **Umhlanga Value Mart:** July sales fell 44.7% month on month while tickets rose from 3 to 37 | Treat as an operational recovery case rather than a demand problem |
| Strong growth from May | **Kudu Digital Kiosk:** sales stepped up approximately 64% from May and held the higher level | Protect capacity and understand the repeatable growth driver |
| Support-ticket spike from June | **Durban Cash Hub:** ticket volume rose from roughly 5 per month to 44 in June and 52 in July | Intervene before the largest merchant's still-growing sales are affected |
| April delayed-redemption combination | **Western Cape + Bill Payment:** average lag reached 15.4 days versus an approximately 3.8-day baseline | Run a settlement-path root-cause review; the episode is operational and isolated |

## What distinguishes the submission

The required patterns are not merely labelled. Each is connected to a management action, reproduced in SQL/Python, represented in reusable DAX, and supported by an auditable Fabric pipeline. The optional AI layer is used selectively: a failed delayed-redemption model is reported as evidence of an isolated incident rather than dressed up as predictive value.
