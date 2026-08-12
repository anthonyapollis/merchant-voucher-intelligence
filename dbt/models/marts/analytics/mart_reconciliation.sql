{{ config(materialized='table', tags=['gold', 'analytics', 'controls']) }}

/*
    mart_reconciliation
    -------------------
    Financial control layer: does every number tie, and where it does not, is the difference
    EXPLAINED or UNEXPLAINED?

    The single most important thing this model establishes is that fct_merchant_sales and
    fct_voucher_redemptions describe DIFFERENT POPULATIONS and must never be expected to tie:

        sales fact      R65,521,299 across 510,127 transactions
        voucher fact    R22,019,853 across 120,969 vouchers
        ratio           4.2 transactions per voucher row

    MerchantSales is a daily AGGREGATE of all transactions. VoucherRedemptions is a
    voucher-level extract covering roughly one in every four transactions. A naive analyst
    looks at R65.5m against R22.0m, calls it a R43.5m reconciliation break, and escalates it
    — or worse, divides one by the other and reports a meaningless "redemption rate by value"
    against the wrong denominator.

    Recording the expected relationship here, as a control with a documented status, is what
    stops that happening. Controls that PASS are as important to state as controls that fail:
    a control nobody can see is a control nobody trusts.

    Grain: one row per control check.
*/

with sales as (
    select sum(sales_value) v, sum(transactions) t, count(*) rows_
    from {{ ref('fct_merchant_sales') }}
),
vouchers as (
    select sum(voucher_value) v, sum(redeemed_value) rv, sum(outstanding_value) ov,
           count(*) rows_, sum(redeemed_count) redeemed
    from {{ ref('fct_voucher_redemptions') }}
),
tickets as (select count(*) rows_, sum(resolution_hours) hrs from {{ ref('fct_support_tickets') }}),
src_sales as (
    select sum(cast(SalesValue as decimal(18,2))) v, count(*) rows_
    from {{ source('bronze', 'bronze_merchant_sales') }}
    where cast(SalesValue as decimal(18,2)) >= 0
),
src_vouchers as (select count(*) rows_ from {{ source('bronze', 'bronze_voucher_redemptions') }}),
src_tickets as (select count(*) rows_ from {{ source('bronze', 'bronze_support_tickets') }}),
scorecard as (select sum(total_sales) v, count(*) n from {{ ref('mart_merchant_scorecard') }}),

checks as (

    -- ---------------------------------------------------------------- SOURCE CONTROL
    select 1 as control_order, 'Source control' as control_family,
        'Sales value survives bronze to gold' as control_name,
        (select v from src_sales) as expected_value,
        (select v from sales) as actual_value,
        (select v from src_sales) - (select v from sales) as variance,
        'Every transformation between landing and the star schema is a cast, a filter on '
        || 'invalid rows, or a regroup at the same grain. None may change the revenue total.'
            as rationale

    union all
    select 2, 'Source control', 'Voucher row count survives bronze to gold',
        (select rows_ from src_vouchers), (select rows_ from vouchers),
        (select rows_ from src_vouchers) - (select rows_ from vouchers),
        'One row per voucher in, one row per voucher out. Any loss is a defect.'

    union all
    select 3, 'Source control', 'Ticket row count survives bronze to gold',
        (select rows_ from src_tickets), (select rows_ from tickets),
        (select rows_ from src_tickets) - (select rows_ from tickets),
        'As above for the ticket fact.'

    -- ---------------------------------------------------------------- VOUCHER CONTROL
    union all
    select 10, 'Voucher control', 'Redeemed + outstanding = value sold',
        (select v from vouchers), (select rv + ov from vouchers),
        (select v - rv - ov from vouchers),
        'A voucher is either redeemed or outstanding. If these do not sum to the value '
        || 'issued, value has been created or destroyed in the model.'

    -- ---------------------------------------------------------------- MART CONTROL
    union all
    select 20, 'Mart control', 'Scorecard total ties to the sales fact',
        (select v from sales), (select v from scorecard),
        (select v from sales) - (select v from scorecard),
        'The merchant scorecard is rebuilt through two ephemeral intermediate models. A '
        || 'refactor there is exactly what could silently drop a merchant.'

    -- ---------------------------------------------------------------- POPULATION CONTROL
    union all
    select 30, 'Population control',
        'Sales fact and voucher fact are DIFFERENT populations (expected variance)',
        (select v from sales), (select v from vouchers),
        (select v from sales) - (select v from vouchers),
        'EXPECTED, NOT A BREAK. MerchantSales is a daily aggregate of all transactions; '
        || 'VoucherRedemptions is a voucher-level extract covering roughly 1 in 4.2 '
        || 'transactions. The two must never be forced to tie, and value-based redemption '
        || 'rate must use the voucher fact for BOTH numerator and denominator.'

)

/*
    Status is DERIVED, not asserted. The population control is expected to vary, so it is
    judged on whether the transactions-per-voucher ratio stays in a plausible band rather
    than on a zero variance — which is the whole point of distinguishing an explained
    difference from a break.
*/
select
    c.control_order,
    c.control_family,
    c.control_name,
    round(c.expected_value, 2)                                  as expected_value,
    round(c.actual_value, 2)                                    as actual_value,
    round(c.variance, 2)                                        as variance,
    abs(c.variance) / nullif(abs(c.expected_value), 0)          as variance_pct,
    case
        when c.control_family = 'Population control'
            then case when r.txn_per_voucher between 3.5 and 5.0
                      then 'EXPECTED' else 'INVESTIGATE' end
        when abs(c.variance) <= 0.01 then 'PASS'
        else 'FAIL'
    end                                                         as control_status,
    round(r.txn_per_voucher, 3)                                 as txn_per_voucher,
    c.rationale
from checks c
cross join (
    select (select t from sales) * 1.0 / (select rows_ from vouchers) as txn_per_voucher
) r
order by c.control_order
