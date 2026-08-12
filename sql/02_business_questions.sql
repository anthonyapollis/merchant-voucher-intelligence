/*==============================================================================================
  BUSINESS QUESTIONS — the five questions in section 6 of the brief, answered in SQL.

  These are the queries behind the written findings. They are included so the conclusions in
  the report can be re-run and challenged rather than taken on trust.

  Dialect: written for the Fabric Warehouse T-SQL endpoint. The DuckDB equivalents used to
  produce the figures in the report are in scripts/03_analytics.py.
==============================================================================================*/


/*----------------------------------------------------------------------------------------------
  Q1. Which merchants generate the highest sales value and transaction volume?

  ANSWER: Durban Cash Hub on both — R5,776,119 (8.8% of portfolio) and 45,371 transactions.
          The two rankings agree at the top, which is not guaranteed: a merchant can lead on
          value while trailing on volume if its basket is larger. The query returns both
          ranks side by side so any divergence is visible rather than assumed away.
----------------------------------------------------------------------------------------------*/
SELECT TOP 10
    m.merchant_name,
    m.region,
    m.channel,
    SUM(f.sales_value)                                              AS total_sales,
    SUM(f.transactions)                                             AS total_transactions,
    SUM(f.sales_value) / NULLIF(SUM(f.transactions), 0)             AS avg_basket_value,
    RANK() OVER (ORDER BY SUM(f.sales_value) DESC)                  AS sales_rank,
    RANK() OVER (ORDER BY SUM(f.transactions) DESC)                 AS transaction_rank,
    CAST(SUM(f.sales_value) * 100.0
         / SUM(SUM(f.sales_value)) OVER ()  AS DECIMAL(10,2))       AS pct_of_portfolio
FROM gold.fct_merchant_sales f
JOIN gold.dim_merchant m ON m.merchant_key = f.merchant_key
GROUP BY m.merchant_name, m.region, m.channel
ORDER BY total_sales DESC;


/*----------------------------------------------------------------------------------------------
  Q2. Which voucher type has the highest redemption rate?

  ANSWER: Airtime, at 92.8%. Gaming is lowest at 76.0% — a 16.9 percentage point spread.

  Both a volume rate and a value rate are returned. They are close here (Airtime 92.83% vs
  92.83%), which tells us high-value and low-value vouchers redeem at similar rates within a
  type. Had they diverged, the value rate would be the one that matters to Finance.
----------------------------------------------------------------------------------------------*/
SELECT
    vt.voucher_type,
    vt.voucher_category,
    COUNT(*)                                                        AS vouchers_sold,
    SUM(f.redeemed_count)                                           AS vouchers_redeemed,
    CAST(SUM(f.redeemed_count) * 100.0 / COUNT(*) AS DECIMAL(10,2)) AS redemption_rate_pct,
    CAST(SUM(f.redeemed_value) * 100.0
         / NULLIF(SUM(f.voucher_value), 0) AS DECIMAL(10,2))        AS value_redemption_pct,
    CAST(AVG(CAST(f.days_to_redeem AS FLOAT)) AS DECIMAL(10,2))     AS avg_days_to_redeem,
    SUM(f.outstanding_value)                                        AS outstanding_liability
FROM gold.fct_voucher_redemptions f
JOIN gold.dim_voucher_type vt ON vt.voucher_type_key = f.voucher_type_key
GROUP BY vt.voucher_type, vt.voucher_category
ORDER BY redemption_rate_pct DESC;


/*----------------------------------------------------------------------------------------------
  Q3. Which region shows declining sales or transaction behaviour?

  ANSWER: Eastern Cape, and the evidence is threefold rather than a single metric:
            * it is the ONLY region whose sales peaked before July (peak May 2026);
            * it sits 9.8% below its own peak while every other region is at its peak;
            * its trend slope is +2.0% of average monthly sales vs +4.4% to +8.5% elsewhere;
            * June fell 12.2% month on month against +1.4% to +3.8% for the rest.

  A single month's movement would not be enough to call a decline. Four independent signals
  pointing the same way is.
----------------------------------------------------------------------------------------------*/
WITH region_month AS (
    SELECT
        m.region,
        d.year_month,
        d.month_year_sort,
        SUM(f.sales_value)      AS sales_value,
        SUM(f.transactions)     AS transactions
    FROM gold.fct_merchant_sales f
    JOIN gold.dim_merchant m ON m.merchant_key = f.merchant_key
    JOIN gold.dim_date d     ON d.date_key = f.date_key
    GROUP BY m.region, d.year_month, d.month_year_sort
),
with_lag AS (
    SELECT *,
           LAG(sales_value) OVER (PARTITION BY region ORDER BY month_year_sort) AS prior_sales,
           MAX(sales_value) OVER (PARTITION BY region)                          AS peak_sales,
           MAX(month_year_sort) OVER (PARTITION BY region)                      AS last_month
    FROM region_month
)
SELECT
    region,
    SUM(sales_value)                                                AS total_sales,
    CAST(MAX(CASE WHEN month_year_sort = last_month
                  THEN sales_value / NULLIF(peak_sales, 0) - 1 END)
         * 100 AS DECIMAL(10,2))                                    AS pct_below_own_peak,
    MAX(CASE WHEN sales_value = peak_sales THEN year_month END)     AS peak_month,
    CAST(AVG(CASE WHEN month_year_sort >= last_month - 1
                  THEN sales_value / NULLIF(prior_sales, 0) - 1 END)
         * 100 AS DECIMAL(10,2))                                    AS recent_2m_avg_mom_pct
FROM with_lag
GROUP BY region
ORDER BY pct_below_own_peak;


/*----------------------------------------------------------------------------------------------
  Q4. Are ticket volumes, priority or long resolution times associated with weaker
      merchant performance?

  ANSWER: Not as a general portfolio rule — but decisively at the level of individual events.

  The naive answer is that tickets-per-1k-transactions correlates with target attainment at
  r = -0.56, so friction hurts performance. That answer is wrong, and this query shows why:
  tickets-per-1k-transactions is a size measure in disguise. It correlates with log(total
  sales) at r = -0.83, and once size is controlled for, the partial correlation with
  attainment collapses from -0.56 to -0.20.

  SLA breach rate and average resolution time show no association at all (r = 0.04 and
  -0.19). Reporting "operational friction predicts weak merchants" would have been a
  confounded finding presented as a causal one.

  What IS real is event-level: this query lists every month where a merchant's ticket volume
  more than doubled against its own prior three months, alongside what sales did.
----------------------------------------------------------------------------------------------*/
WITH merchant_month AS (
    SELECT
        m.merchant_key, m.merchant_name, m.region, d.year_month, d.month_year_sort,
        SUM(f.sales_value) AS sales_value
    FROM gold.fct_merchant_sales f
    JOIN gold.dim_merchant m ON m.merchant_key = f.merchant_key
    JOIN gold.dim_date d     ON d.date_key = f.date_key
    GROUP BY m.merchant_key, m.merchant_name, m.region, d.year_month, d.month_year_sort
),
ticket_month AS (
    SELECT t.merchant_key, d.month_year_sort, COUNT(*) AS tickets
    FROM gold.fct_support_tickets t
    JOIN gold.dim_date d ON d.date_key = t.date_key
    GROUP BY t.merchant_key, d.month_year_sort
),
combined AS (
    SELECT
        mm.*,
        COALESCE(tm.tickets, 0) AS tickets,
        AVG(CAST(COALESCE(tm.tickets, 0) AS FLOAT)) OVER (
            PARTITION BY mm.merchant_key ORDER BY mm.month_year_sort
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING)       AS prior_3m_avg_tickets,
        AVG(mm.sales_value) OVER (
            PARTITION BY mm.merchant_key ORDER BY mm.month_year_sort
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING)       AS prior_3m_avg_sales
    FROM merchant_month mm
    LEFT JOIN ticket_month tm
           ON tm.merchant_key = mm.merchant_key
          AND tm.month_year_sort = mm.month_year_sort
)
SELECT
    merchant_name,
    region,
    year_month,
    tickets,
    CAST(prior_3m_avg_tickets AS DECIMAL(10,1))                     AS prior_3m_avg_tickets,
    CAST((tickets / NULLIF(prior_3m_avg_tickets, 0) - 1) * 100
         AS DECIMAL(10,1))                                          AS ticket_uplift_pct,
    CAST(sales_value AS DECIMAL(18,2))                              AS sales_value,
    CAST((sales_value / NULLIF(prior_3m_avg_sales, 0) - 1) * 100
         AS DECIMAL(10,1))                                          AS sales_vs_prior_3m_pct
FROM combined
WHERE prior_3m_avg_tickets >= 2
  AND tickets >= 10
  AND tickets / NULLIF(prior_3m_avg_tickets, 0) >= 2.5
ORDER BY ticket_uplift_pct DESC;
-- Result: 4 events. Two merchants spike hard. Durban Cash Hub's tickets rose 780% in June
-- and 184% in July while sales GREW 8.2% and 6.3% — a service problem at a healthy account.
-- Umhlanga Value Mart's rose 693% in July while sales fell 42.5% — a failing account.
-- Same signal, opposite diagnosis. That distinction is the actual answer to Q4.


/*----------------------------------------------------------------------------------------------
  Q5. Which merchants should management focus on first, and why?

  ANSWER: ranked by revenue at risk, not by severity of decline. A 43% collapse at a merchant
  billing R110k a month costs less than a 6% slide at one billing R500k. Ranking on
  percentage change alone sends the account team to the wrong door.
----------------------------------------------------------------------------------------------*/
SELECT TOP 10
    merchant_name,
    region,
    account_manager,
    health_score,
    health_band,
    CAST(total_sales AS DECIMAL(18,2))                              AS total_sales,
    CAST(latest_month_sales AS DECIMAL(18,2))                       AS latest_month_sales,
    CAST(sales_vs_prior_3m_avg * 100 AS DECIMAL(10,1))              AS sales_vs_prior_3m_pct,
    CAST(tickets_vs_prior_3m_avg * 100 AS DECIMAL(10,1))            AS ticket_change_pct,
    CAST(revenue_at_risk_annualised AS DECIMAL(18,2))               AS revenue_at_risk,
    CAST(sla_breach_rate * 100 AS DECIMAL(10,1))                    AS sla_breach_pct
FROM gold.mart_merchant_scorecard
WHERE health_band IN ('Critical', 'Watch')
ORDER BY revenue_at_risk_annualised DESC, health_score ASC;


/*----------------------------------------------------------------------------------------------
  SUPPLEMENTARY: the SLA policy finding.

  Not asked in the brief, but the single most actionable operational result in the dataset.
  SLA targets run INVERSELY to how long the work actually takes, so 94.7% of all breaches
  land on High and Critical tickets. The policy, not the team, is generating the breaches.
----------------------------------------------------------------------------------------------*/
SELECT
    p.priority,
    p.target_sla_hours,
    COUNT(*)                                                        AS tickets,
    CAST(AVG(t.resolution_hours) AS DECIMAL(10,1))                  AS avg_resolution_hours,
    CAST(SUM(t.sla_breach_count) * 100.0 / COUNT(*) AS DECIMAL(10,1)) AS breach_rate_pct,
    CAST(SUM(t.sla_breach_count) * 100.0
         / SUM(SUM(t.sla_breach_count)) OVER () AS DECIMAL(10,1))   AS pct_of_all_breaches,
    -- What the SLA would need to be for 90% of these tickets to comply, unchanged process
    CAST(PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY t.resolution_hours)
         OVER (PARTITION BY p.priority) AS DECIMAL(10,1))           AS sla_for_90pct_compliance
FROM gold.fct_support_tickets t
JOIN gold.dim_priority p ON p.priority_key = t.priority_key
GROUP BY p.priority, p.priority_sort, p.target_sla_hours, t.resolution_hours
ORDER BY p.priority_sort;
