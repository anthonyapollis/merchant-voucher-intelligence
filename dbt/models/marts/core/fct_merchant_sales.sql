{{ config(
    materialized='incremental',
    unique_key='sales_key',
    incremental_strategy='merge',
    tags=['gold', 'powerbi']
) }}

/*
    fct_merchant_sales
    ------------------
    Daily sales fact at Date x Merchant x VoucherType.

    Materialised incrementally with a merge so a same-day re-run restates only the affected
    partition instead of rebuilding 26,500 rows. A 3-day lookback window is used rather than
    "greater than max date" because late-arriving corrections to the previous couple of days
    are normal in settlement data and a strict watermark would silently miss them.
*/

with sales as (

    select * from {{ ref('stg_merchant_sales') }}

    {% if is_incremental() %}
      -- dbt.dateadd dispatches to the adapter's own syntax (DATEADD on Fabric T-SQL,
      -- date arithmetic on DuckDB), so the same model runs on dev and production.
      where sales_date >= (
          select {{ dbt.dateadd('day', -3, 'max(sales_date)') }} from {{ this }}
      )
    {% endif %}

),

final as (

    select
        s.sales_key,

        -- Foreign keys
        cast(strftime(s.sales_date, '%Y%m%d') as integer)    as date_key,
        coalesce(m.merchant_key, '-1')                       as merchant_key,
        {{ dbt_utils.generate_surrogate_key(['s.voucher_type']) }}  as voucher_type_key,

        -- Degenerate attributes retained for drill-through
        s.sales_date,

        -- Additive measures
        s.sales_value,
        s.transactions,

        -- Non-additive: exposed for row-level drill only. Aggregation must recompute
        -- as SUM(sales_value)/SUM(transactions), which is how the DAX measure is written.
        s.avg_basket_value,

        s.batch_id,
        s.ingested_at

    from sales s
    left join {{ ref('dim_merchant') }} m
           on s.merchant_id = m.merchant_id

)

select * from final
