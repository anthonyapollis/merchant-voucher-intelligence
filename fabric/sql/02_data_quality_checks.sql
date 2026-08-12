/* ===========================================================================
   02_data_quality_checks.sql
   ---------------------------------------------------------------------------
   The gate between Gold and the semantic model refresh. Every check returns
   zero rows when healthy; the union at the bottom returns one row per failure.
   The pipeline runs the union and fails the refresh if it returns anything, so
   a broken load never reaches a dashboard someone is about to present from.

   These are the same 20 assertions build/build_gold.py runs locally, in T-SQL.
   =========================================================================== */

WITH checks AS (

    /* ------------------------------------------- referential integrity --- */
    SELECT 'FactMerchantSales.DateKey -> DimDate' AS check_name,
           COUNT(*) AS failures
    FROM gold.FactMerchantSales f
    LEFT JOIN gold.DimDate d ON d.DateKey = f.DateKey
    WHERE d.DateKey IS NULL

    UNION ALL SELECT 'FactMerchantSales.MerchantKey -> DimMerchant', COUNT(*)
    FROM gold.FactMerchantSales f
    LEFT JOIN gold.DimMerchant m ON m.MerchantKey = f.MerchantKey
    WHERE m.MerchantKey IS NULL

    UNION ALL SELECT 'FactMerchantSales.VoucherTypeKey -> DimVoucherType', COUNT(*)
    FROM gold.FactMerchantSales f
    LEFT JOIN gold.DimVoucherType v ON v.VoucherTypeKey = f.VoucherTypeKey
    WHERE v.VoucherTypeKey IS NULL

    UNION ALL SELECT 'FactVoucherRedemptions.SoldDateKey -> DimDate', COUNT(*)
    FROM gold.FactVoucherRedemptions f
    LEFT JOIN gold.DimDate d ON d.DateKey = f.SoldDateKey
    WHERE d.DateKey IS NULL

    /* RedeemedDateKey is nullable by design, so only non-null values are
       checked. A calendar that stops at the last SALES date would fail this
       one - vouchers sold in the final month get redeemed after it. */
    UNION ALL SELECT 'FactVoucherRedemptions.RedeemedDateKey -> DimDate', COUNT(*)
    FROM gold.FactVoucherRedemptions f
    LEFT JOIN gold.DimDate d ON d.DateKey = f.RedeemedDateKey
    WHERE f.RedeemedDateKey IS NOT NULL AND d.DateKey IS NULL

    UNION ALL SELECT 'FactVoucherRedemptions.MerchantKey -> DimMerchant', COUNT(*)
    FROM gold.FactVoucherRedemptions f
    LEFT JOIN gold.DimMerchant m ON m.MerchantKey = f.MerchantKey
    WHERE m.MerchantKey IS NULL

    UNION ALL SELECT 'FactSupportTickets.DateKey -> DimDate', COUNT(*)
    FROM gold.FactSupportTickets f
    LEFT JOIN gold.DimDate d ON d.DateKey = f.DateKey
    WHERE d.DateKey IS NULL

    UNION ALL SELECT 'FactSupportTickets.MerchantKey -> DimMerchant', COUNT(*)
    FROM gold.FactSupportTickets f
    LEFT JOIN gold.DimMerchant m ON m.MerchantKey = f.MerchantKey
    WHERE m.MerchantKey IS NULL

    UNION ALL SELECT 'FactSupportTickets.PriorityKey -> DimPriority', COUNT(*)
    FROM gold.FactSupportTickets f
    LEFT JOIN gold.DimPriority p ON p.PriorityKey = f.PriorityKey
    WHERE p.PriorityKey IS NULL

    UNION ALL SELECT 'FactSupportTickets.TicketTypeKey -> DimTicketType', COUNT(*)
    FROM gold.FactSupportTickets f
    LEFT JOIN gold.DimTicketType t ON t.TicketTypeKey = f.TicketTypeKey
    WHERE t.TicketTypeKey IS NULL

    /* -------------------------------------------------------- grain ----- */
    UNION ALL SELECT 'FactMerchantSales grain (Date, Merchant, VoucherType)', COUNT(*)
    FROM (
        SELECT DateKey, MerchantKey, VoucherTypeKey
        FROM gold.FactMerchantSales
        GROUP BY DateKey, MerchantKey, VoucherTypeKey
        HAVING COUNT(*) > 1
    ) dupes

    UNION ALL SELECT 'FactVoucherRedemptions grain (VoucherID)', COUNT(*)
    FROM (
        SELECT VoucherID FROM gold.FactVoucherRedemptions
        GROUP BY VoucherID HAVING COUNT(*) > 1
    ) dupes

    UNION ALL SELECT 'FactSupportTickets grain (TicketID)', COUNT(*)
    FROM (
        SELECT TicketID FROM gold.FactSupportTickets
        GROUP BY TicketID HAVING COUNT(*) > 1
    ) dupes

    UNION ALL SELECT 'DimMerchant grain (MerchantKey)', COUNT(*)
    FROM (
        SELECT MerchantKey FROM gold.DimMerchant
        GROUP BY MerchantKey HAVING COUNT(*) > 1
    ) dupes

    /* ------------------------------------------------------- validity ---- */
    UNION ALL SELECT 'Negative SalesValue', COUNT(*)
    FROM gold.FactMerchantSales WHERE SalesValue < 0

    UNION ALL SELECT 'Negative Transactions', COUNT(*)
    FROM gold.FactMerchantSales WHERE Transactions < 0

    UNION ALL SELECT 'Redemption dated before sale', COUNT(*)
    FROM gold.FactVoucherRedemptions WHERE DaysToRedeem < 0

    UNION ALL SELECT 'Redeemed voucher with no redemption date', COUNT(*)
    FROM gold.FactVoucherRedemptions
    WHERE IsRedeemed = 1 AND RedeemedDateKey IS NULL

    UNION ALL SELECT 'Unredeemed voucher carrying a redemption date', COUNT(*)
    FROM gold.FactVoucherRedemptions
    WHERE IsRedeemed = 0 AND RedeemedDateKey IS NOT NULL

    /* A gap in the calendar silently breaks every time-intelligence measure,
       and it breaks them quietly - totals still add up, comparisons do not. */
    UNION ALL SELECT 'DimDate not contiguous', COUNT(*)
    FROM (
        SELECT DATEDIFF(DAY, MIN([Date]), MAX([Date])) + 1 - COUNT(*) AS gap
        FROM gold.DimDate
    ) g WHERE gap <> 0
)
SELECT check_name, failures
FROM checks
WHERE failures > 0
ORDER BY check_name;
