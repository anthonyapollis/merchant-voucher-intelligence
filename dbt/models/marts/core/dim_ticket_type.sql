{{ config(materialized='table', tags=['gold', 'powerbi']) }}

/*
    dim_ticket_type
    ---------------
    Conformed ticket-type dimension.

    This replaces the earlier `dim_ticket_attributes` model, which unioned ticket type,
    priority and status into a single table behind a `dimension_type` discriminator. That
    was a shortcut with two real costs:

      1. No referential integrity could be tested. fct_support_tickets carries three
         separate foreign keys, but they all pointed at one table with a mixed key space, so
         a `relationships` test could not distinguish "priority_key resolves to a priority"
         from "priority_key resolves to something, somewhere".
      2. Power BI cannot build three independent filter paths off one physical table without
         either three role-playing copies or a bridge — both worse than just modelling the
         three dimensions properly.

    Six rows is not too small to deserve its own table. Dimension count is not the thing
    worth optimising; join clarity is.

    Grain: one row per ticket type.
*/

with observed as (

    -- Driven off what actually appears in the data, not off the seed, so a new ticket type
    -- appearing upstream still lands in the dimension rather than orphaning its facts.
    select distinct ticket_type
    from {{ ref('stg_support_tickets') }}

),

enriched as (

    select
        o.ticket_type,
        coalesce(r.ticket_category, 'Uncategorised')     as ticket_category,
        coalesce(r.impact_area, 'Unclassified')          as impact_area
    from observed o
    left join {{ ref('ticket_type_reference') }} r
           on o.ticket_type = r.ticket_type

)

select
    {{ dbt_utils.generate_surrogate_key(['ticket_type']) }}  as ticket_type_key,
    ticket_type,
    ticket_category,
    impact_area,
    ticket_category || ' - ' || impact_area                 as ticket_type_group
from enriched
