{{ config(materialized='table', tags=['gold', 'powerbi']) }}

/*
    dim_voucher_type
    ----------------
    Small conformed dimension shared by the sales fact and the redemption fact. The
    category and margin band are business metadata that do not exist in the source files;
    they are maintained as a dbt seed (seeds/voucher_type_reference.csv) so the commercial
    team can change them without a code deployment.
*/

with types as (

    select distinct voucher_type from {{ ref('stg_merchant_sales') }}
    union
    select distinct voucher_type from {{ ref('stg_voucher_redemptions') }}

),

enriched as (

    select
        t.voucher_type,
        coalesce(r.voucher_category, 'Uncategorised')    as voucher_category,
        coalesce(r.margin_band, 'Unknown')               as margin_band,
        coalesce(r.sort_order, 99)                       as voucher_type_sort
    from types t
    left join {{ ref('voucher_type_reference') }} r
           on t.voucher_type = r.voucher_type

)

select
    {{ dbt_utils.generate_surrogate_key(['voucher_type']) }}  as voucher_type_key,
    voucher_type,
    voucher_category,
    margin_band,
    voucher_type_sort
from enriched
