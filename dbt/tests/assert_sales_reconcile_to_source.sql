/*
    Singular test: total sales value must survive the bronze -> gold journey unchanged.

    Every transformation between the landing file and the star schema is either a cast, a
    filter on invalid rows, or a regrouping at the same grain. None of them may change the
    revenue total. A one-cent tolerance allows for decimal representation only.

    This single assertion is what lets us tell Finance the dashboard ties to source.
*/

with source_total as (

    select sum(cast(SalesValue as decimal(18,2))) as total
    from {{ source('bronze', 'bronze_merchant_sales') }}
    where cast(SalesValue as decimal(18,2)) >= 0

),

gold_total as (

    select sum(sales_value) as total
    from {{ ref('fct_merchant_sales') }}

)

select
    s.total                     as source_total,
    g.total                     as gold_total,
    abs(s.total - g.total)      as variance,
    'Sales value does not reconcile between bronze and gold' as failure_reason
from source_total s
cross join gold_total g
where abs(s.total - g.total) > 0.01
