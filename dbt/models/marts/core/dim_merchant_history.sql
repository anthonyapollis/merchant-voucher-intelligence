{{ config(materialized='table', tags=['gold', 'scd2']) }}

/*
    dim_merchant_history — Type 2 merchant dimension
    ------------------------------------------------
    Built on snap_merchant. Where dim_merchant answers "what is this merchant TODAY",
    this answers "what was this merchant WHEN that fact happened".

    Both exist deliberately, and the distinction is the point:

      dim_merchant          Type 1, current state. Joined to the facts in the semantic model.
                            Answers "show me sales for merchants CURRENTLY in Gauteng" —
                            which is what a regional manager asking about their own patch
                            actually means.

      dim_merchant_history  Type 2, versioned. Joined on merchant_key + date range where a
                            question genuinely needs point-in-time truth: "what were sales
                            for merchants that were in Gauteng AT THE TIME".

    Loading only the Type 2 version and forcing every query through a date-range join would
    be technically purer and practically worse — most business questions want current
    grouping, and the range join is easy to get wrong. Loading only Type 1 loses history
    permanently. Both, clearly labelled, is the workable answer.

    Grain: one row per merchant per version (valid_from / valid_to).
*/

with snapshotted as (

    select * from {{ ref('snap_merchant') }}

),

versioned as (

    select
        merchant_id,
        merchant_name,
        region,
        channel,
        active_status,
        account_manager,
        onboarded_date,
        base_monthly_sales_target,

        dbt_valid_from                                          as valid_from,
        -- dbt leaves the current version's valid_to null; a high end-date makes BETWEEN
        -- range joins work without every consumer having to remember the null case.
        coalesce(dbt_valid_to, cast('9999-12-31' as timestamp)) as valid_to,
        dbt_valid_to is null                                    as is_current,

        row_number() over (
            partition by merchant_id order by dbt_valid_from
        )                                                       as version_number,
        count(*) over (partition by merchant_id)                as total_versions

    from snapshotted

)

select
    -- Surrogate is per VERSION, not per merchant — that is what makes it a Type 2 key
    {{ dbt_utils.generate_surrogate_key(['merchant_id', 'valid_from']) }}
                                                    as merchant_version_key,
    -- Durable key, stable across versions, for joining back to the Type 1 dimension
    {{ dbt_utils.generate_surrogate_key(['merchant_id']) }}
                                                    as merchant_key,
    merchant_id,
    merchant_name,
    region,
    channel,
    active_status,
    account_manager,
    onboarded_date,
    base_monthly_sales_target,
    valid_from,
    valid_to,
    is_current,
    version_number,
    total_versions,
    total_versions > 1                              as has_changed
from versioned
