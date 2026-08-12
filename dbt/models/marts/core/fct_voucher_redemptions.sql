{{ config(materialized='table', tags=['gold', 'powerbi']) }}

/*
    fct_voucher_redemptions
    -----------------------
    One row per voucher — an accumulating snapshot fact, because a voucher has two events
    (sold, redeemed) and the row is updated when the second occurs.

    Role-playing dates: the fact carries BOTH sold_date_key and redeemed_date_key. In the
    Power BI model dim_date joins on sold_date_key as the ACTIVE relationship (the business
    reasons about issuance cohorts), with an INACTIVE relationship on redeemed_date_key
    activated inside specific measures via USERELATIONSHIP. This is the single most common
    place a voucher model goes wrong: reporting redemptions on the sale date makes a
    redemption backlog invisible.
*/

with vouchers as (

    select * from {{ ref('stg_voucher_redemptions') }}

)

select
    v.voucher_id,

    -- Foreign keys (role-playing date)
    cast(strftime(v.sold_date, '%Y%m%d') as integer)            as sold_date_key,
    case when v.redeemed_date is not null
         then cast(strftime(v.redeemed_date, '%Y%m%d') as integer) end
                                                                as redeemed_date_key,
    coalesce(m.merchant_key, '-1')                              as merchant_key,
    {{ dbt_utils.generate_surrogate_key(['v.voucher_type']) }}  as voucher_type_key,

    v.sold_date,
    v.redeemed_date,

    -- Measures
    v.voucher_value,
    1                                                           as voucher_count,
    case when v.is_redeemed then 1 else 0 end                   as redeemed_count,
    v.redeemed_value,
    v.outstanding_value,
    case when v.is_expired then v.voucher_value else 0 end      as breakage_value,
    v.days_to_redeem,
    case when v.is_delayed_redemption then 1 else 0 end         as delayed_redemption_count,

    -- Flags
    v.is_redeemed,
    v.is_delayed_redemption,
    v.is_expired,
    v.quality_flag,

    v.batch_id,
    v.ingested_at

from vouchers v
left join {{ ref('dim_merchant') }} m
       on v.merchant_id = m.merchant_id
