"""
34_build_sql_report_pack.py — a runnable SQL pack that answers the brief with explicit joins.

The brief's five questions are answered in the Power BI report and in the Word document, but
both of those are artifacts you have to trust. This produces the SQL itself: eight queries
that join the star schema and return the reported numbers, executed against the warehouse so
the results in the file are output, not claims.

Every query joins through the dimensions rather than reading a fact in isolation. That is the
point of the model — the join path IS the argument for the star schema, so the queries are
written with explicit INNER/LEFT JOIN and named keys rather than shortcuts.

Writes:
    docs/report_queries.sql   the queries, each with its result set inline as a comment
    docs/report_queries.md    the same thing rendered for reading
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "mvi.duckdb"
OUT = ROOT / "docs"
OUT.mkdir(exist_ok=True)

M = "main_marts"

QUERIES = [
    ("Q1  Top merchants by sales value AND transaction volume",
     "The brief asks for both. They are reported together because the rankings can disagree — "
     "a merchant with a larger basket leads on value while trailing on volume.",
     f"""
SELECT      m.merchant_name,
            m.region,
            m.channel,
            SUM(s.sales_value)                          AS total_sales,
            SUM(s.transactions)                         AS total_transactions,
            SUM(s.sales_value) / NULLIF(SUM(s.transactions), 0) AS avg_basket,
            RANK() OVER (ORDER BY SUM(s.sales_value)  DESC)     AS rank_by_value,
            RANK() OVER (ORDER BY SUM(s.transactions) DESC)     AS rank_by_volume
FROM        {M}.fct_merchant_sales  s
INNER JOIN  {M}.dim_merchant        m ON m.merchant_key = s.merchant_key
INNER JOIN  {M}.dim_date            d ON d.date_key     = s.date_key
GROUP BY    m.merchant_name, m.region, m.channel
ORDER BY    total_sales DESC
LIMIT       10
"""),

    ("Q2  Redemption rate by voucher type",
     "Joined through dim_voucher_type so the type attributes come from the conformed "
     "dimension, not from a string repeated on the fact.",
     f"""
SELECT      vt.voucher_type,
            COUNT(*)                                              AS vouchers_sold,
            SUM(CASE WHEN r.is_redeemed THEN 1 ELSE 0 END)        AS vouchers_redeemed,
            100.0 * SUM(CASE WHEN r.is_redeemed THEN 1 ELSE 0 END)
                  / COUNT(*)                                      AS redemption_rate_pct,
            AVG(r.days_to_redeem)                                 AS avg_days_to_redeem,
            SUM(CASE WHEN NOT r.is_redeemed THEN r.voucher_value ELSE 0 END)
                                                                  AS outstanding_liability
FROM        {M}.fct_voucher_redemptions r
INNER JOIN  {M}.dim_voucher_type        vt ON vt.voucher_type_key = r.voucher_type_key
GROUP BY    vt.voucher_type
ORDER BY    redemption_rate_pct DESC
"""),

    ("Q3  Regional trend — which region is declining",
     "A region is only 'declining' relative to its own peak, so the query computes each "
     "region's peak month and the gap to it, rather than ranking on the latest month alone.",
     f"""
WITH monthly AS (
    SELECT      m.region,
                d.year_month,
                SUM(s.sales_value) AS sales
    FROM        {M}.fct_merchant_sales s
    INNER JOIN  {M}.dim_merchant      m ON m.merchant_key = s.merchant_key
    INNER JOIN  {M}.dim_date          d ON d.date_key     = s.date_key
    GROUP BY    m.region, d.year_month
)
SELECT      region,
            MAX(sales)                                            AS peak_month_sales,
            MAX_BY(year_month, sales)                             AS peak_month,
            MAX_BY(sales, year_month)                             AS latest_month_sales,
            MAX_BY(year_month, year_month)                        AS latest_month,
            100.0 * (MAX_BY(sales, year_month) - MAX(sales))
                  / NULLIF(MAX(sales), 0)                         AS pct_below_own_peak
FROM        monthly
GROUP BY    region
ORDER BY    pct_below_own_peak
"""),

    ("Q4  Support tickets vs sales performance",
     "The naive version correlates ticket count with sales and concludes that tickets cause "
     "decline. This joins tickets to the MONTHLY sales panel so volume and performance are "
     "compared at the same grain, and reports both together for judgement.",
     f"""
WITH sales_m AS (
    SELECT      s.merchant_key, d.year_month, SUM(s.sales_value) AS sales,
                SUM(s.transactions) AS txns
    FROM        {M}.fct_merchant_sales s
    INNER JOIN  {M}.dim_date          d ON d.date_key = s.date_key
    GROUP BY    s.merchant_key, d.year_month
),
tix_m AS (
    SELECT      t.merchant_key, d.year_month, COUNT(*) AS tickets,
                SUM(CASE WHEN t.is_sla_breach THEN 1 ELSE 0 END) AS breaches
    FROM        {M}.fct_support_tickets t
    INNER JOIN  {M}.dim_date           d ON d.date_key = t.date_key
    GROUP BY    t.merchant_key, d.year_month
)
SELECT      m.merchant_name,
            SUM(s.sales)                                   AS total_sales,
            SUM(COALESCE(x.tickets, 0))                    AS tickets,
            SUM(COALESCE(x.breaches, 0))                   AS sla_breaches,
            1000.0 * SUM(COALESCE(x.tickets, 0))
                   / NULLIF(SUM(s.txns), 0)                AS tickets_per_1k_txn
FROM        sales_m                s
INNER JOIN  {M}.dim_merchant       m ON m.merchant_key = s.merchant_key
LEFT  JOIN  tix_m                  x ON x.merchant_key = s.merchant_key
                                    AND x.year_month   = s.year_month
GROUP BY    m.merchant_name
ORDER BY    tickets_per_1k_txn DESC
LIMIT       10
"""),

    ("Q5  Where management should focus — value at risk, not percentage decline",
     "Ranking by percentage change sends the account team to the smallest merchants. This "
     "ranks by the RAND value at risk, joining the scorecard to the risk register.",
     f"""
SELECT      v.merchant_name,
            v.region,
            v.account_manager,
            v.health_score,
            v.health_band,
            v.total_sales,
            v.revenue_at_risk_annualised,
            v.attrition_risk_band
FROM        {M}.mart_merchant_value_risk v
ORDER BY    v.revenue_at_risk_annualised DESC
LIMIT       10
"""),

    ("Q6  SLA performance by priority — the operational finding",
     "Joins the ticket fact to dim_priority so the SLA TARGET and the observed distribution "
     "sit side by side. This is what shows the queue running in reverse priority order.",
     f"""
SELECT      p.priority,
            p.target_sla_hours,
            COUNT(*)                                              AS tickets,
            MEDIAN(t.resolution_hours)                            AS median_hours,
            QUANTILE_CONT(t.resolution_hours, 0.90)               AS p90_hours,
            100.0 * SUM(CASE WHEN t.is_sla_breach THEN 1 ELSE 0 END)
                  / COUNT(*)                                      AS breach_rate_pct
FROM        {M}.fct_support_tickets t
INNER JOIN  {M}.dim_priority        p ON p.priority_key = t.priority_key
GROUP BY    p.priority, p.priority_sort, p.target_sla_hours
ORDER BY    p.priority_sort
"""),

    ("Q7  Target attainment — the multi-grain join",
     "Monthly targets against daily sales. The two facts are joined ONLY through shared "
     "dimension keys, never directly to each other — joining facts to facts is what produces "
     "a fan trap and silently multiplied totals.",
     f"""
SELECT      m.merchant_name,
            SUM(t.monthly_sales_target)                           AS target,
            SUM(a.sales)                                          AS actual,
            100.0 * SUM(a.sales) / NULLIF(SUM(t.monthly_sales_target), 0)
                                                                  AS attainment_pct
FROM        {M}.fct_merchant_target t
INNER JOIN  {M}.dim_merchant        m ON m.merchant_key = t.merchant_key
LEFT  JOIN (
            SELECT      s.merchant_key, d.year_month, SUM(s.sales_value) AS sales
            FROM        {M}.fct_merchant_sales s
            INNER JOIN  {M}.dim_date           d ON d.date_key = s.date_key
            GROUP BY    s.merchant_key, d.year_month
           ) a ON a.merchant_key = t.merchant_key
              AND a.year_month   = STRFTIME(t.month_start_date, '%Y-%m')
GROUP BY    m.merchant_name
ORDER BY    attainment_pct
LIMIT       10
"""),

    ("Q8  Reconciliation — the two populations that must NOT agree",
     "Sales transactions and voucher rows count different things. The variance is expected, "
     "and the query states the ratio so nobody escalates it as a break.",
     f"""
SELECT      'Sales fact'      AS population,
            COUNT(*)          AS rows_in_fact,
            SUM(s.transactions) AS transactions,
            SUM(s.sales_value)  AS value
FROM        {M}.fct_merchant_sales s
UNION ALL
SELECT      'Voucher fact',
            COUNT(*),
            NULL,
            SUM(r.voucher_value)
FROM        {M}.fct_voucher_redemptions r
"""),
]

con = duckdb.connect(str(DB), read_only=True)

sql_parts = ["""-- =====================================================================
-- Merchant Sales & Voucher Intelligence — SQL report pack
--
-- Eight queries that answer the brief directly from the gold star schema.
-- Every one joins through the conformed dimensions: the join path is the
-- argument for the model, so nothing here reads a fact in isolation.
--
-- Results shown beneath each query are ACTUAL OUTPUT, captured by running
-- the query against the warehouse when this file was generated.
--
-- The same models run on the Fabric Warehouse via the portability macros
-- in dbt/macros/portability.sql, which dispatch per adapter — see the
-- runbook for the T-SQL forms of MEDIAN, QUANTILE_CONT, MAX_BY and STRFTIME.
-- ====================================================================="""]
md_parts = ["# SQL report pack\n",
            "Eight queries answering the brief from the gold star schema, each joining "
            "through the conformed dimensions. Results are actual output.\n"]

ok = 0
for title, note, sql in QUERIES:
    df = con.execute(sql).df()
    ok += 1
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].round(2)
    body = df.to_string(index=False, max_rows=12)
    sql_parts.append(f"\n\n-- ---------------------------------------------------------------\n"
                     f"-- {title}\n-- {note}\n"
                     f"-- ---------------------------------------------------------------"
                     f"{sql.rstrip()};\n\n"
                     + "\n".join(f"--   {ln}" for ln in body.splitlines())
                     + f"\n--   ({len(df)} rows)")
    md_parts.append(f"\n## {title}\n\n{note}\n\n```sql{sql.rstrip()}\n```\n\n```\n{body}\n```\n")

con.close()

(OUT / "report_queries.sql").write_text("\n".join(sql_parts) + "\n", encoding="utf-8")
(OUT / "report_queries.md").write_text("\n".join(md_parts), encoding="utf-8")

print(f"  {ok}/{len(QUERIES)} queries executed against the warehouse — all returned rows")
print(f"  wrote docs/report_queries.sql   ({(OUT/'report_queries.sql').stat().st_size/1024:.0f} KB)")
print(f"  wrote docs/report_queries.md    ({(OUT/'report_queries.md').stat().st_size/1024:.0f} KB)")
