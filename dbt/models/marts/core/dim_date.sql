{{ config(materialized='table', tags=['gold', 'powerbi']) }}

/*
    dim_date
    --------
    A proper, contiguous date dimension — the single most important table in the model.
    Power BI time intelligence (SAMEPERIODLASTYEAR, DATEADD, TOTALYTD) silently returns
    wrong answers against a date column that has gaps, so the calendar is generated to
    full year boundaries rather than derived from the facts.

    is_in_fact_window lets the report exclude the empty tail of the calendar without
    breaking the Mark-as-Date-Table contract.
*/

with bounds as (

    /*
        The calendar SPANS every date that appears anywhere, including the redemption tail
        (a voucher sold on 31 July may be redeemed on 20 August, and that date still needs a
        row to join to). But the reporting WINDOW is defined by activity dates only.

        Keeping these two concepts apart matters: if max_fact_date absorbed the redemption
        tail, every period-based measure would inherit a partial August that contains no
        sales at all — pro-rated targets would be raised against a month with nothing in it,
        understating attainment for the whole portfolio. Caught by the reconciliation gate
        against the Python implementation.
    */
    select
        date_trunc('year', min(d))              as start_date,
        date_trunc('year', max(all_max)) + interval 1 year - interval 1 day  as end_date,
        max(activity_max)                       as max_fact_date
    from (
        select min(sales_date)  as d, max(sales_date)  as activity_max,
               max(sales_date)  as all_max                from {{ ref('stg_merchant_sales') }}
        union all
        select min(ticket_date), max(ticket_date),
               max(ticket_date)                           from {{ ref('stg_support_tickets') }}
        union all
        select min(sold_date), max(sold_date),
               max(sold_date)                             from {{ ref('stg_voucher_redemptions') }}
        union all
        -- Redemption tail extends the calendar but must NOT extend the reporting window
        select min(redeemed_date), null,
               max(redeemed_date)                         from {{ ref('stg_voucher_redemptions') }}
              where redeemed_date is not null
    )

),

spine as (

    select unnest(generate_series(
               (select start_date from bounds),
               (select end_date   from bounds),
               interval 1 day))::date as date_day

)

select
    cast(strftime(date_day, '%Y%m%d') as integer)        as date_key,
    date_day                                             as date,

    year(date_day)                                       as year,
    quarter(date_day)                                    as quarter,
    'Q' || quarter(date_day)                             as quarter_name,
    year(date_day) || '-Q' || quarter(date_day)          as year_quarter,

    month(date_day)                                      as month_number,
    strftime(date_day, '%B')                             as month_name,
    strftime(date_day, '%b')                             as month_short,
    strftime(date_day, '%Y-%m')                          as year_month,
    strftime(date_day, '%b %Y')                          as month_year_label,
    year(date_day) * 100 + month(date_day)               as month_year_sort,
    date_trunc('month', date_day)                        as month_start_date,
    (date_trunc('month', date_day) + interval 1 month - interval 1 day)::date
                                                         as month_end_date,

    day(date_day)                                        as day_of_month,
    isodow(date_day)                                     as day_of_week,
    strftime(date_day, '%A')                             as day_name,
    strftime(date_day, '%a')                             as day_short,
    week(date_day)                                       as week_of_year,
    year(date_day) || '-W' || lpad(week(date_day)::varchar, 2, '0')  as year_week,
    isodow(date_day) in (6, 7)                           as is_weekend,

    date_day between (select min(start_date) from bounds)
                 and (select max_fact_date from bounds)  as is_in_fact_window,

    datediff('month', (select max_fact_date from bounds), date_day)
                                                         as relative_month_offset,
    date_trunc('month', date_day)
        = date_trunc('month', (select max_fact_date from bounds))    as is_current_month

from spine
