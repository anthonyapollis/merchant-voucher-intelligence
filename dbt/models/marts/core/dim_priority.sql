{{ config(materialized='table', tags=['gold', 'powerbi']) }}

/*
    dim_priority
    ------------
    Conformed priority dimension.

    `target_sla_hours` here describes CURRENT policy. The SLA actually applied to a given
    ticket is stored on fct_support_tickets, deliberately — an SLA policy change must not
    retrospectively restate whether a historic ticket breached. Keeping both lets the report
    answer two different questions:

        "did this ticket breach?"           -> fact.sla_hours   (what was promised then)
        "what is our SLA for Critical?"     -> dim.target_sla_hours (what we promise now)

    `sla_is_achievable` is derived rather than declared, and it is the field that surfaces
    the headline operational finding: for Critical and High the current target sits below
    what the work actually takes, so the breach rate is measuring a policy misconfiguration
    rather than team performance.

    Grain: one row per priority level.
*/

with observed as (

    select distinct priority
    from {{ ref('stg_support_tickets') }}

),

actuals as (

    -- Observed effort per priority, used to flag whether the target is reachable at all
    select
        priority,
        avg(resolution_hours)                                       as avg_resolution_hours,
        median(resolution_hours)                                    as median_resolution_hours,
        quantile_cont(resolution_hours, 0.90)                       as p90_resolution_hours
    from {{ ref('stg_support_tickets') }}
    group by 1

),

enriched as (

    select
        o.priority,
        coalesce(r.priority_sort, 99)                               as priority_sort,
        coalesce(r.target_sla_hours, 48)                            as target_sla_hours,
        coalesce(r.severity_weight, 1.0)                            as severity_weight,
        a.avg_resolution_hours,
        a.median_resolution_hours,
        a.p90_resolution_hours
    from observed o
    left join {{ ref('priority_reference') }} r on o.priority = r.priority
    left join actuals a on o.priority = a.priority

)

select
    {{ dbt_utils.generate_surrogate_key(['priority']) }}            as priority_key,
    priority,
    priority_sort,
    target_sla_hours,
    severity_weight,
    priority in ('High', 'Critical')                                as is_high_priority,

    -- Diagnostics: is the current target reachable by the current process?
    round(avg_resolution_hours, 2)                                  as observed_avg_hours,
    round(median_resolution_hours, 2)                               as observed_median_hours,
    round(p90_resolution_hours, 2)                                  as observed_p90_hours,
    median_resolution_hours <= target_sla_hours                     as sla_is_achievable,
    round(p90_resolution_hours, 0)                                  as sla_for_90pct_compliance

from enriched
