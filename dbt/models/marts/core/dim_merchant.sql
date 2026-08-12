{{ config(materialized='table', tags=['gold', 'powerbi']) }}

/*
    dim_merchant
    ------------
    Conformed merchant dimension — the single point of filter for every fact in the model.
    Size banding is derived from realised sales rather than the supplied target, because
    profiling showed the target field is mis-calibrated by roughly 6x (documented as a
    known data-quality issue) and would produce misleading bands.

    An "Unknown" member (-1) is emitted so that a future fact row with an unmatched
    merchant lands somewhere visible instead of vanishing from the report.
*/

with merchants as (

    select * from {{ ref('stg_merchants') }}

),

sales_totals as (

    select
        merchant_id,
        sum(sales_value)    as total_sales,
        sum(transactions)   as total_transactions
    from {{ ref('stg_merchant_sales') }}
    group by 1

),

banded as (

    select
        m.*,
        s.total_sales,
        s.total_transactions,
        ntile(4) over (order by s.total_sales) as size_quartile
    from merchants m
    left join sales_totals s using (merchant_id)

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['merchant_id']) }}  as merchant_key,
        merchant_id,
        merchant_name,
        region,
        channel,
        active_status,
        is_at_risk,
        account_manager,
        onboarded_date,
        tenure_months,
        tenure_band,
        base_monthly_sales_target,
        annualised_sales_target,
        case size_quartile
            when 1 then 'Small'
            when 2 then 'Mid'
            when 3 then 'Large'
            when 4 then 'Strategic'
        end                                                     as merchant_size_band,
        batch_id,
        ingested_at
    from banded

)

select * from final

union all

-- Unknown member: guarantees referential integrity for late-arriving dimension rows
select
    '-1', 'UNKNOWN', 'Unknown Merchant', 'Unknown', 'Unknown', 'Unknown', false,
    'Unassigned', null, null, 'Unknown', null, null, 'Unknown', 'SYSTEM',
    current_timestamp
