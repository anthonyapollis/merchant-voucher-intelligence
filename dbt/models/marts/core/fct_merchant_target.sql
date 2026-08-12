{{ config(materialized='table', tags=['gold', 'powerbi']) }}

/*
    fct_merchant_target
    -------------------
    Monthly sales target per merchant — a periodic snapshot fact at a COARSER grain than
    fct_merchant_sales (month vs day). Mixing the two grains in one table would break every
    additive measure, so the target lives in its own fact joined to dim_date at the month
    start. In Power BI both facts filter through the same dim_date and dim_merchant, which
    is the standard Kimball answer to multi-grain reporting.

    Targets are pro-rated by days covered so a part-month never shows a false shortfall.
*/

with months as (

    select
        month_start_date,
        count(*)                                    as days_covered
    from {{ ref('dim_date') }}
    where is_in_fact_window
    group by 1

),

month_length as (

    select month_start_date, count(*) as days_in_month
    from {{ ref('dim_date') }}
    group by 1

),

merchants as (

    select merchant_key, base_monthly_sales_target
    from {{ ref('dim_merchant') }}
    where merchant_key <> '-1'

)

select
    cast(strftime(mo.month_start_date, '%Y%m%d') as integer)     as date_key,
    m.merchant_key,
    mo.month_start_date,
    round(m.base_monthly_sales_target * mo.days_covered / ml.days_in_month, 2)
                                                                as monthly_sales_target,
    m.base_monthly_sales_target,
    mo.days_covered,
    ml.days_in_month
from months mo
cross join merchants m
join month_length ml using (month_start_date)
