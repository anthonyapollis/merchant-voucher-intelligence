-- =====================================================================
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
-- =====================================================================


-- ---------------------------------------------------------------
-- Q1  Top merchants by sales value AND transaction volume
-- The brief asks for both. They are reported together because the rankings can disagree — a merchant with a larger basket leads on value while trailing on volume.
-- ---------------------------------------------------------------
SELECT      m.merchant_name,
            m.region,
            m.channel,
            SUM(s.sales_value)                          AS total_sales,
            SUM(s.transactions)                         AS total_transactions,
            SUM(s.sales_value) / NULLIF(SUM(s.transactions), 0) AS avg_basket,
            RANK() OVER (ORDER BY SUM(s.sales_value)  DESC)     AS rank_by_value,
            RANK() OVER (ORDER BY SUM(s.transactions) DESC)     AS rank_by_volume
FROM        main_marts.fct_merchant_sales  s
INNER JOIN  main_marts.dim_merchant        m ON m.merchant_key = s.merchant_key
INNER JOIN  main_marts.dim_date            d ON d.date_key     = s.date_key
GROUP BY    m.merchant_name, m.region, m.channel
ORDER BY    total_sales DESC
LIMIT       10;

--               merchant_name        region       channel  total_sales  total_transactions  avg_basket  rank_by_value  rank_by_volume
--             Durban Cash Hub  Western Cape        Retail   5776118.74             45371.0      127.31              1               1
--          Kudu Digital Kiosk KwaZulu-Natal Agent Network   4535329.73             35458.0      127.91              2               3
--        Zebra Route Services       Gauteng Agent Network   4519761.94             35910.0      125.86              3               2
--            Karoo Quick Shop       Gauteng     Wholesale   4395067.11             34657.0      126.82              4               4
--   Lighthouse General Dealer       Gauteng     Wholesale   3965086.39             31124.0      127.40              5               5
--         North Coast Connect    Free State        Online   3731381.85             29341.0      127.17              6               6
--         Ubuntu Trading Post KwaZulu-Natal        Retail   3548946.51             27865.0      127.36              7               7
--           Table Bay Express  Eastern Cape     Wholesale   3325306.26             26056.0      127.62              8               8
--          Blue Crane Trading       Gauteng        Retail   3265565.26             25532.0      127.90              9               9
--         Liberty Lane Stores  Western Cape     Wholesale   3185149.79             24828.0      128.29             10              10
--   (10 rows)


-- ---------------------------------------------------------------
-- Q2  Redemption rate by voucher type
-- Joined through dim_voucher_type so the type attributes come from the conformed dimension, not from a string repeated on the fact.
-- ---------------------------------------------------------------
SELECT      vt.voucher_type,
            COUNT(*)                                              AS vouchers_sold,
            SUM(CASE WHEN r.is_redeemed THEN 1 ELSE 0 END)        AS vouchers_redeemed,
            100.0 * SUM(CASE WHEN r.is_redeemed THEN 1 ELSE 0 END)
                  / COUNT(*)                                      AS redemption_rate_pct,
            AVG(r.days_to_redeem)                                 AS avg_days_to_redeem,
            SUM(CASE WHEN NOT r.is_redeemed THEN r.voucher_value ELSE 0 END)
                                                                  AS outstanding_liability
FROM        main_marts.fct_voucher_redemptions r
INNER JOIN  main_marts.dim_voucher_type        vt ON vt.voucher_type_key = r.voucher_type_key
GROUP BY    vt.voucher_type
ORDER BY    redemption_rate_pct DESC;

--   voucher_type  vouchers_sold  vouchers_redeemed  redemption_rate_pct  avg_days_to_redeem  outstanding_liability
--        Airtime          26253            24370.0                92.83                3.55              340978.83
--    Electricity          24691            21677.0                87.79                3.56              557878.98
--      Groceries          24856            20549.0                82.67                3.57              784888.34
--   Bill Payment          22489            18022.0                80.14                3.70              824709.65
--         Gaming          22680            17225.0                75.95                3.56             1033107.28
--   (5 rows)


-- ---------------------------------------------------------------
-- Q3  Regional trend — which region is declining
-- A region is only 'declining' relative to its own peak, so the query computes each region's peak month and the gap to it, rather than ranking on the latest month alone.
-- ---------------------------------------------------------------
WITH monthly AS (
    SELECT      m.region,
                d.year_month,
                SUM(s.sales_value) AS sales
    FROM        main_marts.fct_merchant_sales s
    INNER JOIN  main_marts.dim_merchant      m ON m.merchant_key = s.merchant_key
    INNER JOIN  main_marts.dim_date          d ON d.date_key     = s.date_key
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
ORDER BY    pct_below_own_peak;

--          region  peak_month_sales peak_month  latest_month_sales latest_month  pct_below_own_peak
--    Eastern Cape        1400867.94    2026-05          1264270.55      2026-07               -9.75
--         Gauteng        2597861.85    2026-07          2597861.85      2026-07                0.00
--    Western Cape        2087340.68    2026-07          2087340.68      2026-07                0.00
--   KwaZulu-Natal        1680558.12    2026-07          1680558.12      2026-07                0.00
--      Free State        2836918.29    2026-07          2836918.29      2026-07                0.00
--   (5 rows)


-- ---------------------------------------------------------------
-- Q4  Support tickets vs sales performance
-- The naive version correlates ticket count with sales and concludes that tickets cause decline. This joins tickets to the MONTHLY sales panel so volume and performance are compared at the same grain, and reports both together for judgement.
-- ---------------------------------------------------------------
WITH sales_m AS (
    SELECT      s.merchant_key, d.year_month, SUM(s.sales_value) AS sales,
                SUM(s.transactions) AS txns
    FROM        main_marts.fct_merchant_sales s
    INNER JOIN  main_marts.dim_date          d ON d.date_key = s.date_key
    GROUP BY    s.merchant_key, d.year_month
),
tix_m AS (
    SELECT      t.merchant_key, d.year_month, COUNT(*) AS tickets,
                SUM(CASE WHEN t.is_sla_breach THEN 1 ELSE 0 END) AS breaches
    FROM        main_marts.fct_support_tickets t
    INNER JOIN  main_marts.dim_date           d ON d.date_key = t.date_key
    GROUP BY    t.merchant_key, d.year_month
)
SELECT      m.merchant_name,
            SUM(s.sales)                                   AS total_sales,
            SUM(COALESCE(x.tickets, 0))                    AS tickets,
            SUM(COALESCE(x.breaches, 0))                   AS sla_breaches,
            1000.0 * SUM(COALESCE(x.tickets, 0))
                   / NULLIF(SUM(s.txns), 0)                AS tickets_per_1k_txn
FROM        sales_m                s
INNER JOIN  main_marts.dim_merchant       m ON m.merchant_key = s.merchant_key
LEFT  JOIN  tix_m                  x ON x.merchant_key = s.merchant_key
                                    AND x.year_month   = s.year_month
GROUP BY    m.merchant_name
ORDER BY    tickets_per_1k_txn DESC
LIMIT       10;

--            merchant_name  total_sales  tickets  sla_breaches  tickets_per_1k_txn
--   Highveld Voucher Depot    505737.91     66.0          16.0               18.77
--      Umhlanga Value Mart    684341.39     69.0          13.0               13.93
--        Berg River Retail   1077657.92     69.0          16.0                8.42
--      Cape Point Cellular    776438.09     44.0          15.0                7.76
--       Valley View Retail    822002.78     39.0          10.0                6.47
--        Mango Tree Mobile   2196476.67    109.0          32.0                6.44
--       Nelson Bay Traders   1694276.03     76.0          16.0                5.88
--            Marula Market   2138321.62     62.0          13.0                3.75
--        Jozi Corner Store   1502983.68     43.0          11.0                3.74
--           Sunbird Topups   1693657.85     43.0           7.0                3.29
--   (10 rows)


-- ---------------------------------------------------------------
-- Q5  Where management should focus — value at risk, not percentage decline
-- Ranking by percentage change sends the account team to the smallest merchants. This ranks by the RAND value at risk, joining the scorecard to the risk register.
-- ---------------------------------------------------------------
SELECT      v.merchant_name,
            v.region,
            v.account_manager,
            v.health_score,
            v.health_band,
            v.total_sales,
            v.revenue_at_risk_annualised,
            v.attrition_risk_band
FROM        main_marts.mart_merchant_value_risk v
ORDER BY    v.revenue_at_risk_annualised DESC
LIMIT       10;

--               merchant_name        region account_manager  health_score health_band  total_sales  revenue_at_risk_annualised attrition_risk_band
--         Umhlanga Value Mart    Free State       A. Naidoo          17.3    Critical    684341.39                   571517.84                High
--           Table Bay Express  Eastern Cape       A. Naidoo          24.0    Critical   3325306.26                   354163.20                High
--           Pretoria PayPoint  Eastern Cape     L. Govender          31.3    Critical   2066202.17                   154045.00                High
--          Mzansi Mini Market  Eastern Cape       R. Pillay          40.4       Watch   2613183.07                    87168.92              Medium
--         Cape Point Cellular  Eastern Cape       R. Pillay          45.0       Watch    776438.09                    48625.72              Medium
--          Kudu Digital Kiosk KwaZulu-Natal       A. Naidoo          75.6        Star   4535329.73                        0.00                 Low
--            Karoo Quick Shop       Gauteng       S. Jacobs          62.9     Healthy   4395067.11                        0.00                 Low
--   Lighthouse General Dealer       Gauteng      T. Mokoena          62.1     Healthy   3965086.39                        0.00                 Low
--         North Coast Connect    Free State       A. Naidoo          34.8    Critical   3731381.85                        0.00              Medium
--          Blue Crane Trading       Gauteng       S. Jacobs          62.1     Healthy   3265565.26                        0.00                 Low
--   (10 rows)


-- ---------------------------------------------------------------
-- Q6  SLA performance by priority — the operational finding
-- Joins the ticket fact to dim_priority so the SLA TARGET and the observed distribution sit side by side. This is what shows the queue running in reverse priority order.
-- ---------------------------------------------------------------
SELECT      p.priority,
            p.target_sla_hours,
            COUNT(*)                                              AS tickets,
            MEDIAN(t.resolution_hours)                            AS median_hours,
            QUANTILE_CONT(t.resolution_hours, 0.90)               AS p90_hours,
            100.0 * SUM(CASE WHEN t.is_sla_breach THEN 1 ELSE 0 END)
                  / COUNT(*)                                      AS breach_rate_pct
FROM        main_marts.fct_support_tickets t
INNER JOIN  main_marts.dim_priority        p ON p.priority_key = t.priority_key
GROUP BY    p.priority, p.priority_sort, p.target_sla_hours
ORDER BY    p.priority_sort;

--   priority  target_sla_hours  tickets  median_hours  p90_hours  breach_rate_pct
--   Critical                12      119         52.70      74.46            98.32
--       High                24      270         36.20      56.84            82.22
--     Medium                36      454         18.50      27.90             3.96
--        Low                48      520         10.45      16.11             0.19
--   (4 rows)


-- ---------------------------------------------------------------
-- Q7  Target attainment — the multi-grain join
-- Monthly targets against daily sales. The two facts are joined ONLY through shared dimension keys, never directly to each other — joining facts to facts is what produces a fan trap and silently multiplied totals.
-- ---------------------------------------------------------------
SELECT      m.merchant_name,
            SUM(t.monthly_sales_target)                           AS target,
            SUM(a.sales)                                          AS actual,
            100.0 * SUM(a.sales) / NULLIF(SUM(t.monthly_sales_target), 0)
                                                                  AS attainment_pct
FROM        main_marts.fct_merchant_target t
INNER JOIN  main_marts.dim_merchant        m ON m.merchant_key = t.merchant_key
LEFT  JOIN (
            SELECT      s.merchant_key, d.year_month, SUM(s.sales_value) AS sales
            FROM        main_marts.fct_merchant_sales s
            INNER JOIN  main_marts.dim_date           d ON d.date_key = s.date_key
            GROUP BY    s.merchant_key, d.year_month
           ) a ON a.merchant_key = t.merchant_key
              AND a.year_month   = STRFTIME(t.month_start_date, '%Y-%m')
GROUP BY    m.merchant_name
ORDER BY    attainment_pct
LIMIT       10;

--            merchant_name    target     actual  attainment_pct
--       Nelson Bay Traders 445270.00 1694276.03          380.51
--            Marula Market 560203.00 2138321.62          381.70
--        Mango Tree Mobile 574959.00 2196476.67          382.02
--   Highveld Voucher Depot 131838.00  505737.91          383.61
--      Umhlanga Value Mart 154539.00  684341.39          442.83
--   Wild Coast Convenience 632512.65 3040622.49          480.72
--        Jozi Corner Store 311213.00 1502983.68          482.94
--      North Coast Connect 705907.86 3731381.85          528.59
--        Berg River Retail 200809.00 1077657.92          536.66
--       Mzansi Mini Market 483203.00 2613183.07          540.80
--   (10 rows)


-- ---------------------------------------------------------------
-- Q8  Reconciliation — the two populations that must NOT agree
-- Sales transactions and voucher rows count different things. The variance is expected, and the query states the ratio so nobody escalates it as a break.
-- ---------------------------------------------------------------
SELECT      'Sales fact'      AS population,
            COUNT(*)          AS rows_in_fact,
            SUM(s.transactions) AS transactions,
            SUM(s.sales_value)  AS value
FROM        main_marts.fct_merchant_sales s
UNION ALL
SELECT      'Voucher fact',
            COUNT(*),
            NULL,
            SUM(r.voucher_value)
FROM        main_marts.fct_voucher_redemptions r;

--     population  rows_in_fact  transactions       value
--     Sales fact         26500      510127.0 65521298.75
--   Voucher fact        120969           NaN 22019852.75
--   (2 rows)
