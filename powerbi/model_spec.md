# Power BI Semantic Model Specification

Build instructions for the semantic model over the Fabric Lakehouse gold layer, in
**Direct Lake** storage mode.

---

## 1. Tables to load

| Table | Storage mode | Hidden | Notes |
|---|---|---|---|
| `dim_date` | Direct Lake | No | **Mark as Date Table** on `date` |
| `dim_merchant` | Direct Lake | No | |
| `dim_voucher_type` | Direct Lake | No | |
| `dim_priority` | Direct Lake | No | Sort `priority` by `priority_sort` |
| `dim_ticket_type` | Direct Lake | No | |
| `dim_ticket_status` | Direct Lake | No | Sort `status` by `status_sort` |
| `fct_merchant_sales` | Direct Lake | Yes | |
| `fct_voucher_redemptions` | Direct Lake | Yes | |
| `fct_support_tickets` | Direct Lake | Yes | |
| `fct_merchant_target` | Direct Lake | Yes | |
| `mart_merchant_scorecard` | Direct Lake | No | Drill-through detail |
| `ml_anomaly_scores` | Direct Lake | No | Written back by the ML notebook |
| `ml_sales_forecast` | Direct Lake | No | Written back by the ML notebook |
| `_Measures` | Calculated (empty) | No | Measure container only |

Fact tables are hidden so users build visuals from dimensions and measures rather than
dragging raw fact columns onto a canvas — which is how an accidental `SUM(avg_basket_value)`
ends up in a report.

---

## 2. Relationships

| From | To | Cardinality | Direction | Active |
|---|---|---|---|---|
| `fct_merchant_sales[date_key]` | `dim_date[date_key]` | Many→1 | Single | **Yes** |
| `fct_merchant_sales[merchant_key]` | `dim_merchant[merchant_key]` | Many→1 | Single | Yes |
| `fct_merchant_sales[voucher_type_key]` | `dim_voucher_type[voucher_type_key]` | Many→1 | Single | Yes |
| `fct_voucher_redemptions[sold_date_key]` | `dim_date[date_key]` | Many→1 | Single | **Yes** |
| `fct_voucher_redemptions[redeemed_date_key]` | `dim_date[date_key]` | Many→1 | Single | **NO — inactive** |
| `fct_voucher_redemptions[merchant_key]` | `dim_merchant[merchant_key]` | Many→1 | Single | Yes |
| `fct_voucher_redemptions[voucher_type_key]` | `dim_voucher_type[voucher_type_key]` | Many→1 | Single | Yes |
| `fct_support_tickets[date_key]` | `dim_date[date_key]` | Many→1 | Single | Yes |
| `fct_support_tickets[merchant_key]` | `dim_merchant[merchant_key]` | Many→1 | Single | Yes |
| `fct_support_tickets[ticket_type_key]` | `dim_ticket_type[ticket_type_key]` | Many→1 | Single | Yes |
| `fct_support_tickets[priority_key]` | `dim_priority[priority_key]` | Many→1 | Single | Yes |
| `fct_support_tickets[status_key]` | `dim_ticket_status[status_key]` | Many→1 | Single | Yes |
| `fct_merchant_target[date_key]` | `dim_date[date_key]` | Many→1 | Single | Yes |
| `fct_merchant_target[merchant_key]` | `dim_merchant[merchant_key]` | Many→1 | Single | Yes |
| `mart_merchant_scorecard[merchant_key]` | `dim_merchant[merchant_key]` | 1→1 | Single | Yes |
| `ml_anomaly_scores[merchant_key]` | `dim_merchant[merchant_key]` | Many→1 | Single | Yes |

### The one relationship that matters most

`fct_voucher_redemptions[redeemed_date_key] → dim_date[date_key]` is **inactive by design.**

The active relationship is on `sold_date_key`, so the default view answers *"of vouchers
**sold** in July, how many redeemed?"* — an issuance-cohort question, which is what the
business reasons about commercially.

The inactive relationship answers the operational question: *"how many redemptions were
**processed** in July?"* It is activated inside specific measures with `USERELATIONSHIP`
(see `dax/01_core_measures.dax`).

Without this separation, late redemptions are attributed back to the month of sale and a
redemption backlog becomes completely invisible.

**Do not set both active.** Power BI will reject it, and if you work around it by duplicating
`dim_date` you lose the ability to slice both views with one date slicer.

---

## 3. Model configuration

- **Mark as Date Table**: `dim_date` on `dim_date[date]`. Time intelligence returns *wrong
  answers*, not errors, without this.
- **Sort by column**:
  - `dim_date[month_year_label]` → `dim_date[month_year_sort]`
  - `dim_date[month_name]` → `dim_date[month_number]`
  - `dim_date[day_name]` → `dim_date[day_of_week]`
  - `dim_priority[priority]` → `dim_priority[priority_sort]`
  - `dim_voucher_type[voucher_type]` → `dim_voucher_type[voucher_type_sort]`
- **Hide from report view**: every `*_key` column, all `_batch_id` / `_ingested_at` columns.
- **Summarize by = None** on every key and on `fct_merchant_sales[avg_basket_value]` — the
  latter is non-additive and must never be summed.
- **Data categories**: `dim_merchant[region]` → State or Province (enables the map visual).

---

## 4. Page design

### Page 1 — Executive Overview
- KPI cards: Total Sales · Total Transactions · Redemption Rate % · Avg Resolution Hours ·
  Outstanding Liability
- Combo chart: monthly sales value (column) + transactions (line, secondary axis)
- Donut: sales share by region
- Bar: top 10 merchants by sales value
- Bar: redemption rate by voucher type
- Slicers: date range, region, channel, voucher type
- **Drill-through**: right-click any merchant → Merchant Detail

### Page 2 — Merchant Analysis
- Matrix: full 25-merchant scorecard with conditional formatting
- Pareto combo: sales by merchant (column) + cumulative share (line) with an 80% reference line
- Bar: health score, coloured by band
- Table: merchant segments from the K-Means output
- **This is the drill-through target page.** Set `dim_merchant[merchant_name]` as the
  drill-through field and keep "Keep all filters" on.

### Page 3 — Operational View
- Table: SLA policy by priority — target vs actual vs breach rate (the headline finding)
- Stacked column: ticket volume by month and priority
- Table: ticket type with breach rate and total breach hours
- Table: ticket spike events, paired with sales movement
- Scatter: tickets per 1k transactions vs recent sales momentum, bubble-sized by total sales

### Page 4 — Insights / Notes
- Smart narrative bound to `[Executive Summary Narrative]`
- Q&A visual
- Text boxes: assumptions, data-quality findings, limitations
- Table: anomaly detections with the plain-English explanation column

### Tooltip page (`TT_Merchant`)
Set page size to Tooltip, `Allow use as tooltip = On`. Contains:
- Merchant name, region, account manager
- 6-month sales sparkline
- Health score gauge
- `[Merchant Narrative]` measure as a card

---

## 5. Performance notes

- Direct Lake means **no import refresh** — but the semantic model still needs *framing*
  after the underlying Delta tables change. The Data Factory pipeline handles this as its
  final step.
- The silver tables are `OPTIMIZE ... ZORDER BY (merchant_id, date)`, matching the columns
  the report filters on most. Direct Lake reads Delta files directly, so file layout *is*
  query performance.
- The Health Score is pre-computed in `mart_merchant_scorecard` rather than calculated in
  DAX. It requires percentile ranking across the full merchant population, which is expensive
  in DAX — and it must be identical in Power BI, the Excel pack and the ML feature set.
- Avoid bi-directional filtering entirely. The star schema does not need it, and it
  introduces ambiguity that is difficult to debug later.
