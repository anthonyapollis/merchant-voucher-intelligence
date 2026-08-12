{{ config(materialized='view') }}

/*
    stg_merchant_sales
    ------------------
    Silver layer for daily sales. Two decisions worth noting:

    1. Descriptive attributes (Merchant, Region, Channel) are DROPPED here. They are
       carried redundantly on the source file but belong to the merchant dimension.
       Profiling confirmed zero disagreement between the fact-embedded values and
       MerchantReference, so dropping them is lossless and prevents the model from
       developing two competing versions of "Region".

    2. The grain is re-asserted with a group by. The source is currently clean, but a
       re-delivered or partially reloaded file would otherwise double-count silently.
*/

with source as (

    select * from {{ source('bronze', 'bronze_merchant_sales') }}

),

cleaned as (

    select
        cast(Date as date)                          as sales_date,
        upper(trim(MerchantID))                     as merchant_id,
        trim(VoucherType)                           as voucher_type,
        cast(SalesValue as decimal(18,2))           as sales_value,
        cast(Transactions as integer)               as transactions,
        _batch_id                                   as batch_id,
        cast(_ingested_at as timestamp)             as ingested_at

    from source
    where Date is not null
      and MerchantID is not null
      and cast(SalesValue as decimal(18,2)) >= 0    -- guard against credit/reversal rows

),

deduplicated as (

    select
        sales_date,
        merchant_id,
        voucher_type,
        sum(sales_value)        as sales_value,
        sum(transactions)       as transactions,
        max(batch_id)           as batch_id,
        max(ingested_at)        as ingested_at
    from cleaned
    -- Columns named explicitly, not `group by 1, 2, 3`. Positional GROUP BY is a DuckDB /
    -- Postgres convenience; T-SQL rejects it outright with
    --   "Each GROUP BY expression must contain at least one column that is not an outer
    --    reference"
    -- which is an unhelpful message for what is really "positional grouping unsupported".
    group by sales_date, merchant_id, voucher_type

)

select
    {{ dbt_utils.generate_surrogate_key(['sales_date', 'merchant_id', 'voucher_type']) }}
                                                    as sales_key,
    sales_date,
    merchant_id,
    voucher_type,
    sales_value,
    transactions,
    case when transactions > 0
         then sales_value / transactions end        as avg_basket_value,
    batch_id,
    ingested_at
from deduplicated
