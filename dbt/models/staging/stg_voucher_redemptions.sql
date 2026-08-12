{{ config(materialized='view') }}

/*
    stg_voucher_redemptions
    -----------------------
    Silver layer for voucher issuance and redemption.

    The integrity rule that matters: a voucher only counts as redeemed if it carries a
    valid, non-retrograde redemption date. Trusting the Redeemed flag alone would let a
    corrupt feed inflate the headline redemption rate — the single most scrutinised KPI in
    the report. The flag and the date must agree; where they do not, the record is marked
    and treated as unredeemed, and _quality_flag makes the exception auditable.
*/

with source as (

    select * from {{ source('bronze', 'bronze_voucher_redemptions') }}

),

cleaned as (

    select
        trim(VoucherID)                                     as voucher_id,
        upper(trim(MerchantID))                             as merchant_id,
        trim(VoucherType)                                   as voucher_type,
        cast(SoldDate as date)                              as sold_date,
        try_cast(RedeemedDate as date)                      as redeemed_date,
        cast(VoucherValue as decimal(18,2))                 as voucher_value,
        -- T-SQL has NO boolean column type. A predicate can appear in a WHERE clause but not
        -- in a SELECT list, so every flag has to be materialised as a BIT via CASE. DuckDB
        -- accepts the predicate directly. mvi_bool hides that difference.
        {{ mvi_bool("lower(trim(Redeemed)) = 'yes'") }}      as redeemed_flag,
        _batch_id                                           as batch_id,
        cast(_ingested_at as timestamp)                     as ingested_at

    from source
    where VoucherID is not null

),

validated as (

    select
        *,
        -- The flag alone is not trusted; the date must corroborate it.
        {{ mvi_bool("{} and redeemed_date is not null and redeemed_date >= sold_date"
                    .format(mvi_is_true('redeemed_flag'))) }}   as is_redeemed,

        case
            when {{ mvi_is_true('redeemed_flag') }} and redeemed_date is null
                then 'REDEEM_DATE_MISSING'
            when {{ mvi_is_true('redeemed_flag') }} and redeemed_date < sold_date
                then 'REDEEM_DATE_BEFORE_SALE'
            when not {{ mvi_is_true('redeemed_flag') }} and redeemed_date is not null
                then 'UNREDEEMED_WITH_DATE'
            else 'OK'
        end                                                 as quality_flag

    from cleaned

)

select
    voucher_id,
    merchant_id,
    voucher_type,
    sold_date,
    case when {{ mvi_is_true('is_redeemed') }} then redeemed_date end as redeemed_date,
    voucher_value,
    is_redeemed,

    case when {{ mvi_is_true('is_redeemed') }}
         then {{ mvi_datediff('day', 'sold_date', 'redeemed_date') }} end as days_to_redeem,

    {{ mvi_bool(mvi_is_true('is_redeemed') ~ " and "
                ~ mvi_datediff('day', 'sold_date', 'redeemed_date')
                ~ " > " ~ var('delayed_redemption_days')) }} as is_delayed_redemption,

    case when {{ mvi_is_true('is_redeemed') }} then voucher_value else 0 end as redeemed_value,
    case when {{ mvi_is_true('is_redeemed') }} then 0 else voucher_value end as outstanding_value,

    -- Breakage: unredeemed and past the expiry window as at the latest sale date in the feed
    {{ mvi_bool("not " ~ mvi_is_true('is_redeemed') ~ " and "
                ~ mvi_datediff('day', 'sold_date', '(select max(sold_date) from cleaned)')
                ~ " > " ~ var('voucher_expiry_days')) }}     as is_expired,

    quality_flag,
    batch_id,
    ingested_at

from validated
