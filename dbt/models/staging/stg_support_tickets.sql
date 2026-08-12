{{ config(materialized='view') }}

/*
    stg_support_tickets
    -------------------
    Silver layer for support tickets.

    Note on SLA: SLAHours arrives on the source row and maps 1:1 to Priority
    (Critical 12h, High 24h, Medium 36h, Low 48h). It is kept on the fact rather than
    resolved from the priority dimension, because an SLA policy change must not silently
    restate history — a ticket is judged against the SLA that applied when it was raised.
    This is a slowly-changing-fact consideration and is called out in the documentation.
*/

with source as (

    select * from {{ source('bronze', 'bronze_support_tickets') }}

),

cleaned as (

    select
        trim(TicketID)                                  as ticket_id,
        cast(Date as date)                              as ticket_date,
        upper(trim(MerchantID))                         as merchant_id,
        trim(TicketType)                                as ticket_type,
        trim(Priority)                                  as priority,
        trim(Status)                                    as status,
        cast(ResolutionHours as decimal(10,2))          as resolution_hours,
        cast(SLAHours as integer)                       as sla_hours,
        _batch_id                                       as batch_id,
        cast(_ingested_at as timestamp)                 as ingested_at

    from source
    where TicketID is not null
      and cast(ResolutionHours as decimal(10,2)) >= 0

)

select
    ticket_id,
    ticket_date,
    merchant_id,
    ticket_type,
    priority,
    status,
    resolution_hours,
    sla_hours,

    -- Predicates cannot be selected as columns in T-SQL — mvi_bool wraps each one.
    {{ mvi_bool('resolution_hours > sla_hours') }}      as is_sla_breach,
    -- GREATEST is not a T-SQL function either; the CASE form works on both engines.
    case when resolution_hours - sla_hours > 0
         then resolution_hours - sla_hours else 0 end   as sla_breach_hours,
    resolution_hours / nullif(sla_hours, 0)             as sla_utilisation,

    {{ mvi_bool("priority in (" ~ "'" ~ var('high_priority_levels') | join("','") ~ "'" ~ ")") }}
                                                        as is_high_priority,
    {{ mvi_bool("status <> 'Closed'") }}                as is_open,
    {{ mvi_bool("status = 'Escalated'") }}              as is_escalated,

    batch_id,
    ingested_at

from cleaned
