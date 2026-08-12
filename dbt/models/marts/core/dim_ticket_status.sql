{{ config(materialized='table', tags=['gold', 'powerbi']) }}

/*
    dim_ticket_status
    -----------------
    Conformed ticket-status dimension.

    `is_open_status` is the single source of truth for what counts as backlog. Three statuses
    are open in different senses — Open (with us), Escalated (with us, urgent) and Pending
    Merchant (with the customer) — and it matters that they are grouped but distinguishable:
    a backlog that is mostly "Pending Merchant" is not the same operational problem as one
    that is mostly "Escalated", and reporting a single backlog number hides that entirely.

    Grain: one row per ticket status.
*/

with observed as (

    select distinct status
    from {{ ref('stg_support_tickets') }}

),

enriched as (

    select
        o.status,
        coalesce(r.status_sort, 99)                     as status_sort,
        coalesce(r.status_group, 'Unclassified')        as status_group,
        coalesce(r.is_open_status, o.status <> 'Closed') as is_open_status
    from observed o
    left join {{ ref('ticket_status_reference') }} r
           on o.status = r.status

)

select
    {{ dbt_utils.generate_surrogate_key(['status']) }}  as status_key,
    status,
    status_sort,
    status_group,
    is_open_status,
    -- Distinguishes "waiting on us" from "waiting on them" — different remediation entirely
    case
        when status = 'Closed'           then 'Resolved'
        when status = 'Pending Merchant' then 'Awaiting customer'
        else 'Awaiting us'
    end                                                 as ownership
from enriched
