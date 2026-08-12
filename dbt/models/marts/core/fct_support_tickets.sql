{{ config(materialized='table', tags=['gold', 'powerbi']) }}

/*
    fct_support_tickets
    -------------------
    Transaction-grain fact: one row per support ticket.

    sla_hours is deliberately carried on the fact rather than looked up from dim_priority.
    The two agree today, but an SLA policy change must not retrospectively restate whether
    a historic ticket breached — a ticket is judged against the SLA in force when it was
    raised. dim_priority.target_sla_hours therefore describes CURRENT policy and the fact
    records what was actually promised.
*/

with tickets as (

    select * from {{ ref('stg_support_tickets') }}

)

select
    t.ticket_id,

    -- Foreign keys
    cast(strftime(t.ticket_date, '%Y%m%d') as integer)          as date_key,
    coalesce(m.merchant_key, '-1')                              as merchant_key,
    {{ dbt_utils.generate_surrogate_key(['t.ticket_type']) }}   as ticket_type_key,
    {{ dbt_utils.generate_surrogate_key(['t.priority']) }}      as priority_key,
    {{ dbt_utils.generate_surrogate_key(['t.status']) }}        as status_key,

    t.ticket_date,

    -- Measures
    1                                                           as ticket_count,
    t.resolution_hours,
    t.sla_hours,
    t.sla_breach_hours,
    t.sla_utilisation,
    case when t.is_sla_breach   then 1 else 0 end               as sla_breach_count,
    case when t.is_high_priority then 1 else 0 end              as high_priority_count,
    case when t.is_open         then 1 else 0 end               as open_count,
    case when t.is_escalated    then 1 else 0 end               as escalated_count,

    -- Flags
    t.is_sla_breach,
    t.is_high_priority,
    t.is_open,
    t.is_escalated,

    t.batch_id,
    t.ingested_at

from tickets t
left join {{ ref('dim_merchant') }} m
       on t.merchant_id = m.merchant_id
