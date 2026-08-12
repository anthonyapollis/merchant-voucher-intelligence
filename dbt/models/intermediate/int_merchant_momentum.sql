{{ config(materialized='ephemeral', tags=['intermediate']) }}

/*
    int_merchant_momentum
    ---------------------
    Collapses the merchant × month spine to one row per merchant, carrying the
    period-comparison measures that the scorecard, the alerting rules and the ML feature set
    all need.

    Isolating this is what removed a real bug. Momentum was previously computed in two
    places — once in the scorecard model and once in the Python analytics layer — using
    subtly different window definitions, and the two only agreed by accident. Defining
    "latest month versus the prior three" exactly once means every consumer inherits the same
    answer.

    On the choice of measure: `sales_vs_prior_3m_avg` is the primary momentum signal rather
    than a simple month-on-month change, because MoM is noisy at merchant level and a
    six-month trend line averages a single-month collapse away entirely. Comparing the latest
    month against the mean of the prior three is sensitive enough to catch a sudden break and
    stable enough not to fire on ordinary variation. That is the measure that surfaces
    Umhlanga Value Mart's July collapse; the trend line does not.

    Grain: one row per merchant.
*/

with monthly as (

    select * from {{ ref('int_merchant_monthly') }}

),

ranked as (

    select
        *,
        row_number() over (partition by merchant_key order by month_year_sort desc) as rn_desc,
        row_number() over (partition by merchant_key order by month_year_sort)      as rn_asc,
        count(*)     over (partition by merchant_key)                               as n_months
    from monthly

)

select
    merchant_key,
    merchant_id,
    max(merchant_name)                                              as merchant_name,
    max(region)                                                     as region,
    max(channel)                                                    as channel,
    max(active_status)                                              as active_status,
    max(account_manager)                                            as account_manager,
    max(merchant_size_band)                                         as merchant_size_band,
    max(n_months)                                                   as months_observed,

    -- Totals
    sum(sales_value)                                                as total_sales,
    sum(transactions)                                               as total_transactions,
    sum(sales_value) / nullif(sum(transactions), 0)                 as avg_basket_value,
    sum(sales_target)                                               as sales_target,
    sum(sales_value) / nullif(sum(sales_target), 0)                 as target_attainment,

    -- Period positions
    max(case when rn_desc = 1 then sales_value end)                 as latest_month_sales,
    max(case when rn_desc = 2 then sales_value end)                 as prior_month_sales,
    avg(case when rn_desc between 2 and 4 then sales_value end)     as prior_3m_avg_sales,
    avg(case when rn_desc <= 3 then sales_value end)                as last_3m_avg_sales,
    avg(case when rn_asc  <= 3 then sales_value end)                as first_3m_avg_sales,
    max(case when rn_desc = 1 then year_month end)                  as latest_month,

    -- Momentum
    max(case when rn_desc = 1 then sales_value end)
        / nullif(max(case when rn_desc = 2 then sales_value end), 0) - 1
                                                                    as mom_change,
    max(case when rn_desc = 1 then sales_value end)
        / nullif(avg(case when rn_desc between 2 and 4 then sales_value end), 0) - 1
                                                                    as sales_vs_prior_3m_avg,
    avg(case when rn_desc <= 3 then sales_value end)
        / nullif(avg(case when rn_asc <= 3 then sales_value end), 0) - 1
                                                                    as last3_vs_first3,
    max(case when rn_desc = 1 then sales_value end)
        / nullif(max(sales_value), 0) - 1                           as sales_vs_peak,
    -- arg_max returns the year_month AT which sales_value is highest. A window function
    -- cannot be nested inside an aggregate, so the obvious
    -- `max(case when sales_value = max(sales_value) over () ...)` is not valid SQL.
    arg_max(year_month, sales_value)                                as peak_month,

    -- Ticket momentum, on the same window definition as sales
    max(case when rn_desc = 1 then tickets end)                     as latest_month_tickets,
    avg(case when rn_desc between 2 and 4 then tickets end)         as prior_3m_avg_tickets,
    max(case when rn_desc = 1 then tickets end)
        / nullif(avg(case when rn_desc between 2 and 4 then tickets end), 0) - 1
                                                                    as tickets_vs_prior_3m_avg

from ranked
group by merchant_key, merchant_id
