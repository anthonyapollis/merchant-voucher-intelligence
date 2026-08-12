{{ config(materialized='ephemeral', tags=['intermediate']) }}

/*
    int_merchant_monthly
    --------------------
    The merchant × month spine: one row per merchant per month, with sales, voucher and
    ticket measures brought onto a single grain.

    This exists because three separate consumers were each rebuilding the same joins:
    mart_merchant_scorecard, the anomaly-detection feature set, and the ticket-momentum
    calculation. Three copies of a join is three chances for them to drift apart — and they
    did: the scorecard and the ML features disagreed on whether a month with zero tickets
    should be a zero or a missing row, which changed the "tickets vs own history" figure.

    The spine is built from a CROSS JOIN of merchants and months, not from the facts, so a
    month in which a merchant sold nothing or logged no tickets is a ZERO rather than a gap.
    That distinction matters for every period-over-period calculation downstream: a missing
    row silently shortens the comparison window, a zero correctly reports a collapse.

    Materialised ephemeral — it is inlined as a CTE wherever it is referenced, so there is no
    intermediate table to keep in sync and no extra storage.

    Grain: merchant × month.
*/

with months as (

    select distinct
        year_month,
        month_start_date,
        month_year_sort
    from {{ ref('dim_date') }}
    where is_in_fact_window

),

merchants as (

    select merchant_key, merchant_name, merchant_id, region, channel, active_status,
           account_manager, merchant_size_band
    from {{ ref('dim_merchant') }}
    where merchant_key <> '-1'          -- exclude the Unknown member from the spine

),

spine as (

    -- Every merchant × every month, so gaps become zeros rather than absent rows
    select m.*, mo.year_month, mo.month_start_date, mo.month_year_sort
    from merchants m
    cross join months mo

),

sales as (

    select
        f.merchant_key,
        d.year_month,
        sum(f.sales_value)      as sales_value,
        sum(f.transactions)     as transactions
    from {{ ref('fct_merchant_sales') }} f
    join {{ ref('dim_date') }} d on d.date_key = f.date_key
    group by 1, 2

),

vouchers as (

    select
        f.merchant_key,
        d.year_month,
        count(*)                                        as vouchers_sold,
        sum(f.redeemed_count)                           as vouchers_redeemed,
        sum(f.voucher_value)                            as voucher_value_sold,
        sum(f.redeemed_value)                           as voucher_value_redeemed,
        sum(f.outstanding_value)                        as outstanding_value,
        avg(f.days_to_redeem)                           as avg_days_to_redeem,
        sum(f.delayed_redemption_count)                 as delayed_redemptions
    from {{ ref('fct_voucher_redemptions') }} f
    join {{ ref('dim_date') }} d on d.date_key = f.sold_date_key
    group by 1, 2

),

tickets as (

    select
        f.merchant_key,
        d.year_month,
        count(*)                                        as tickets,
        avg(f.resolution_hours)                         as avg_resolution_hours,
        sum(f.sla_breach_count)                         as sla_breaches,
        sum(f.high_priority_count)                      as high_priority_tickets,
        sum(f.open_count)                               as open_tickets
    from {{ ref('fct_support_tickets') }} f
    join {{ ref('dim_date') }} d on d.date_key = f.date_key
    group by 1, 2

),

targets as (

    select
        f.merchant_key,
        d.year_month,
        sum(f.monthly_sales_target)                     as sales_target
    from {{ ref('fct_merchant_target') }} f
    join {{ ref('dim_date') }} d on d.date_key = f.date_key
    group by 1, 2

)

select
    sp.merchant_key,
    sp.merchant_id,
    sp.merchant_name,
    sp.region,
    sp.channel,
    sp.active_status,
    sp.account_manager,
    sp.merchant_size_band,
    sp.year_month,
    sp.month_start_date,
    sp.month_year_sort,

    -- Zero-filled: a month with no activity is a zero, never a missing row
    coalesce(s.sales_value, 0)                          as sales_value,
    coalesce(s.transactions, 0)                         as transactions,
    s.sales_value / nullif(s.transactions, 0)           as avg_basket_value,

    t.sales_target,
    s.sales_value / nullif(t.sales_target, 0)           as target_attainment,

    coalesce(v.vouchers_sold, 0)                        as vouchers_sold,
    coalesce(v.vouchers_redeemed, 0)                    as vouchers_redeemed,
    v.vouchers_redeemed * 1.0 / nullif(v.vouchers_sold, 0)  as redemption_rate,
    v.voucher_value_sold,
    v.voucher_value_redeemed,
    v.outstanding_value,
    v.avg_days_to_redeem,
    coalesce(v.delayed_redemptions, 0) * 1.0
        / nullif(v.vouchers_redeemed, 0)                as delayed_redemption_rate,

    coalesce(tk.tickets, 0)                             as tickets,
    tk.avg_resolution_hours,
    coalesce(tk.sla_breaches, 0) * 1.0
        / nullif(tk.tickets, 0)                         as sla_breach_rate,
    coalesce(tk.high_priority_tickets, 0)               as high_priority_tickets,
    coalesce(tk.open_tickets, 0)                        as open_tickets,
    coalesce(tk.tickets, 0) * 1000.0
        / nullif(s.transactions, 0)                     as tickets_per_1k_txn

from spine sp
left join sales    s  on s.merchant_key  = sp.merchant_key and s.year_month  = sp.year_month
left join vouchers v  on v.merchant_key  = sp.merchant_key and v.year_month  = sp.year_month
left join tickets  tk on tk.merchant_key = sp.merchant_key and tk.year_month = sp.year_month
left join targets  t  on t.merchant_key  = sp.merchant_key and t.year_month  = sp.year_month
