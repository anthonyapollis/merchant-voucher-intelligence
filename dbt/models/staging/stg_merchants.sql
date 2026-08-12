{{ config(materialized='view') }}

/*
    stg_merchants
    -------------
    Silver layer for merchant master data. Responsibilities: cast types, trim and
    standardise text, deduplicate on the natural key, and derive tenure. No business
    aggregation happens here — that belongs in marts.
*/

with source as (

    select * from {{ source('bronze', 'bronze_merchant_reference') }}

),

cleaned as (

    select
        upper(trim(MerchantID))                             as merchant_id,
        trim(Merchant)                                      as merchant_name,
        trim(Region)                                        as region,
        trim(Channel)                                       as channel,
        trim(ActiveStatus)                                  as active_status,
        trim(AccountManager)                                as account_manager,
        cast(OnboardedDate as date)                         as onboarded_date,
        cast(BaseMonthlySalesTarget as decimal(18,2))       as base_monthly_sales_target,

        -- Audit lineage carried through every layer
        _batch_id                                           as batch_id,
        cast(_ingested_at as timestamp)                     as ingested_at,

        row_number() over (
            partition by upper(trim(MerchantID))
            order by _ingested_at desc
        )                                                   as _rn

    from source
    where MerchantID is not null

),

final as (

    select
        merchant_id,
        merchant_name,
        region,
        channel,
        active_status,
        account_manager,
        onboarded_date,
        base_monthly_sales_target,
        base_monthly_sales_target * 12                      as annualised_sales_target,
        -- mvi_datediff dispatches on target.type: DuckDB wants datediff('month', a, b) with
        -- the part as a STRING, T-SQL wants DATEDIFF(month, a, b) with it as a bare keyword.
        -- Connecting to Fabric is what surfaced this; it fails on the first staging model.
        {{ mvi_datediff('month', 'onboarded_date',
                        "cast('" ~ var('reporting_end_date') ~ "' as date)") }}
                                                            as tenure_months,
        case
            when {{ mvi_datediff('month', 'onboarded_date',
                    "cast('" ~ var('reporting_end_date') ~ "' as date)") }} < 12
                then '< 1 year'
            when {{ mvi_datediff('month', 'onboarded_date',
                    "cast('" ~ var('reporting_end_date') ~ "' as date)") }} < 24
                then '1-2 years'
            when {{ mvi_datediff('month', 'onboarded_date',
                    "cast('" ~ var('reporting_end_date') ~ "' as date)") }} < 36
                then '2-3 years'
            else '3+ years'
        end                                                 as tenure_band,
        {{ mvi_bool("active_status = 'At Risk'") }}          as is_at_risk,
        batch_id,
        ingested_at

    from cleaned
    where _rn = 1        -- keep the latest record per merchant

)

select * from final
