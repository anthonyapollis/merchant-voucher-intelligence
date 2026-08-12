/* ===========================================================================
   03_business_question_queries.sql
   ---------------------------------------------------------------------------
   The five questions from the brief, answered in T-SQL against the gold star
   schema. These are the queries behind the numbers on the Insights page - kept
   in the repo so any figure in the report can be re-derived without opening
   Power BI.
   =========================================================================== */

/* ---------------------------------------------------------------------------
   Q1. Which merchants generate the highest sales value and transaction volume,
       and how concentrated is the book?
   --------------------------------------------------------------------------- */
WITH merchant_totals AS (
    SELECT  m.MerchantKey,
            m.Merchant,
            m.Region,
            m.Channel,
            SUM(f.SalesValue)   AS SalesValue,
            SUM(f.Transactions) AS Transactions
    FROM gold.FactMerchantSales f
    JOIN gold.DimMerchant m ON m.MerchantKey = f.MerchantKey
    GROUP BY m.MerchantKey, m.Merchant, m.Region, m.Channel
)
SELECT  Merchant,
        Region,
        Channel,
        SalesValue,
        Transactions,
        SalesValue / NULLIF(Transactions, 0)                      AS AvgBasket,
        ROW_NUMBER() OVER (ORDER BY SalesValue DESC)               AS SalesRank,
        100.0 * SalesValue / SUM(SalesValue) OVER ()               AS SharePct,
        100.0 * SUM(SalesValue) OVER (ORDER BY SalesValue DESC
              ROWS UNBOUNDED PRECEDING) / SUM(SalesValue) OVER ()  AS CumulativeSharePct
FROM merchant_totals
ORDER BY SalesValue DESC;


/* ---------------------------------------------------------------------------
   Q2. Which voucher type has the highest redemption rate?

   Reported alongside time-to-redeem and the delayed share, because a type can
   redeem often but slowly - and slowly is the part operations feels.
   --------------------------------------------------------------------------- */
SELECT  v.VoucherType,
        v.SettlementModel,
        COUNT(*)                                                    AS VouchersSold,
        SUM(CAST(r.IsRedeemed AS INT))                              AS Redeemed,
        100.0 * SUM(CAST(r.IsRedeemed AS INT)) / COUNT(*)           AS RedemptionRatePct,
        AVG(CAST(r.DaysToRedeem AS FLOAT))                          AS AvgDaysToRedeem,
        100.0 * SUM(CAST(r.IsDelayedRedemption AS INT))
              / NULLIF(SUM(CAST(r.IsRedeemed AS INT)), 0)           AS DelayedOver7DaysPct,
        SUM(CASE WHEN r.IsRedeemed = 0 THEN r.VoucherValue ELSE 0 END)
                                                                    AS UnredeemedValue
FROM gold.FactVoucherRedemptions r
JOIN gold.DimVoucherType v ON v.VoucherTypeKey = r.VoucherTypeKey
GROUP BY v.VoucherType, v.SettlementModel
ORDER BY RedemptionRatePct DESC;


/* ---------------------------------------------------------------------------
   Q3. Which region shows declining sales or transaction behaviour?

   Latest month against the average of the prior three, rather than against the
   single prior month - one soft month is noise, a step away from a three-month
   base is a trend.
   --------------------------------------------------------------------------- */
WITH region_month AS (
    SELECT  m.Region,
            d.MonthYearSort,
            d.MonthYear,
            SUM(f.SalesValue)   AS SalesValue,
            SUM(f.Transactions) AS Transactions
    FROM gold.FactMerchantSales f
    JOIN gold.DimMerchant m ON m.MerchantKey = f.MerchantKey
    JOIN gold.DimDate     d ON d.DateKey     = f.DateKey
    GROUP BY m.Region, d.MonthYearSort, d.MonthYear
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY Region
                                 ORDER BY MonthYearSort DESC) AS rn
    FROM region_month
)
SELECT  latest.Region,
        latest.MonthYear                                            AS LatestMonth,
        latest.SalesValue                                           AS LatestSales,
        prior.Prior3MonthAvg,
        100.0 * (latest.SalesValue - prior.Prior3MonthAvg)
              / NULLIF(prior.Prior3MonthAvg, 0)                     AS MomentumPct,
        latest.Transactions                                         AS LatestTransactions
FROM ranked latest
JOIN (
    SELECT Region, AVG(SalesValue) AS Prior3MonthAvg
    FROM ranked WHERE rn BETWEEN 2 AND 4
    GROUP BY Region
) prior ON prior.Region = latest.Region
WHERE latest.rn = 1
ORDER BY MomentumPct ASC;


/* ---------------------------------------------------------------------------
   Q4. Are ticket volumes, priority or long resolution times associated with
       weaker merchant performance?

   Two views. The first is the per-merchant profile; the second tests whether a
   ticket SURGE in a month is followed by weaker growth, which is the causal
   direction management actually cares about.
   --------------------------------------------------------------------------- */

-- 4a. Per-merchant operational profile against growth
WITH sales_m AS (
    SELECT MerchantKey, SUM(SalesValue) AS SalesValue,
           SUM(Transactions) AS Transactions
    FROM gold.FactMerchantSales GROUP BY MerchantKey
),
tick_m AS (
    SELECT  MerchantKey,
            COUNT(*)                                        AS Tickets,
            AVG(CAST(ResolutionHours AS FLOAT))             AS AvgResolutionHours,
            100.0 * SUM(CAST(IsSLABreach AS INT)) / COUNT(*) AS SLABreachPct
    FROM gold.FactSupportTickets GROUP BY MerchantKey
)
SELECT  m.Merchant,
        m.Region,
        s.SalesValue,
        ISNULL(t.Tickets, 0)                                        AS Tickets,
        1000.0 * ISNULL(t.Tickets, 0) / NULLIF(s.Transactions, 0)   AS TicketsPer1kTx,
        t.AvgResolutionHours,
        t.SLABreachPct
FROM sales_m s
JOIN gold.DimMerchant m ON m.MerchantKey = s.MerchantKey
LEFT JOIN tick_m t      ON t.MerchantKey = s.MerchantKey
ORDER BY TicketsPer1kTx DESC;

-- 4b. Does a ticket surge precede weaker growth?
WITH sm AS (
    SELECT  f.MerchantKey, d.MonthYearSort, SUM(f.SalesValue) AS SalesValue
    FROM gold.FactMerchantSales f
    JOIN gold.DimDate d ON d.DateKey = f.DateKey
    GROUP BY f.MerchantKey, d.MonthYearSort
),
tm AS (
    SELECT  f.MerchantKey, d.MonthYearSort, COUNT(*) AS Tickets
    FROM gold.FactSupportTickets f
    JOIN gold.DimDate d ON d.DateKey = f.DateKey
    GROUP BY f.MerchantKey, d.MonthYearSort
),
panel AS (
    SELECT  sm.MerchantKey,
            sm.MonthYearSort,
            sm.SalesValue,
            LAG(sm.SalesValue) OVER (PARTITION BY sm.MerchantKey
                                     ORDER BY sm.MonthYearSort)  AS PrevSales,
            ISNULL(tm.Tickets, 0)                                AS Tickets,
            LAG(ISNULL(tm.Tickets, 0)) OVER (PARTITION BY sm.MerchantKey
                                     ORDER BY sm.MonthYearSort)  AS PrevTickets
    FROM sm
    LEFT JOIN tm ON tm.MerchantKey = sm.MerchantKey
                AND tm.MonthYearSort = sm.MonthYearSort
)
SELECT  CASE WHEN Tickets - PrevTickets >= 10
             THEN 'Ticket surge (>= +10 vs prior month)'
             ELSE 'No surge' END                                  AS Cohort,
        COUNT(*)                                                  AS MerchantMonths,
        AVG(100.0 * (SalesValue - PrevSales) / NULLIF(PrevSales, 0)) AS AvgSalesMoMPct
FROM panel
WHERE PrevSales IS NOT NULL AND PrevTickets IS NOT NULL
GROUP BY CASE WHEN Tickets - PrevTickets >= 10
              THEN 'Ticket surge (>= +10 vs prior month)' ELSE 'No surge' END;


/* ---------------------------------------------------------------------------
   Q5. Which merchants should management focus on first?

   Ranked by the size of the decline in rand terms, not in percent - a 45% fall
   at a small merchant costs less than a 6% fall at the largest one, and the
   queue should be ordered by money.
   --------------------------------------------------------------------------- */
WITH sm AS (
    SELECT  f.MerchantKey, d.MonthYearSort, SUM(f.SalesValue) AS SalesValue
    FROM gold.FactMerchantSales f
    JOIN gold.DimDate d ON d.DateKey = f.DateKey
    GROUP BY f.MerchantKey, d.MonthYearSort
),
mom AS (
    SELECT  MerchantKey, MonthYearSort, SalesValue,
            LAG(SalesValue) OVER (PARTITION BY MerchantKey
                                  ORDER BY MonthYearSort) AS PrevSales,
            ROW_NUMBER() OVER (PARTITION BY MerchantKey
                               ORDER BY MonthYearSort DESC) AS rn
    FROM sm
)
SELECT  m.Merchant,
        m.Region,
        m.AccountManager,
        seg.Segment,
        seg.HealthScore,
        seg.RiskTier,
        mom.PrevSales                                   AS PriorMonthSales,
        mom.SalesValue                                  AS LatestMonthSales,
        mom.SalesValue - mom.PrevSales                  AS RandChange,
        100.0 * (mom.SalesValue - mom.PrevSales)
              / NULLIF(mom.PrevSales, 0)                AS PctChange,
        n.Narrative
FROM mom
JOIN gold.DimMerchant m       ON m.MerchantKey   = mom.MerchantKey
LEFT JOIN gold.DimMerchantSegment seg ON seg.MerchantKey = mom.MerchantKey
LEFT JOIN gold.InsightNarrative   n   ON n.MerchantKey   = mom.MerchantKey
WHERE mom.rn = 1
ORDER BY RandChange ASC;
