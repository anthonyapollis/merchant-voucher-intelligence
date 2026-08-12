/*
    Singular test: dim_date must be unique AND contiguous.

    This is the highest-value test in the project. Power BI time intelligence
    (DATEADD, SAMEPERIODLASTYEAR, TOTALYTD) does not error on a date table with a missing
    day — it silently returns a wrong number. A single absent date will quietly understate
    a month-on-month comparison and nobody notices until someone reconciles by hand.

    Two assertions, expressed as aggregates (which is why this is a singular test rather
    than a schema test — dbt_utils.expression_is_true renders into a WHERE clause and
    cannot contain aggregates).
*/

with checks as (

    select
        count(*)                                            as row_count,
        count(distinct date_key)                            as distinct_keys,
        datediff('day', min(date), max(date)) + 1           as expected_days,
        min(date)                                           as first_date,
        max(date)                                           as last_date
    from {{ ref('dim_date') }}

)

select
    row_count,
    distinct_keys,
    expected_days,
    first_date,
    last_date,
    case
        when row_count <> distinct_keys then 'dim_date contains duplicate date_key values'
        else 'dim_date has gaps - time intelligence will silently return wrong results'
    end                                                     as failure_reason
from checks
where row_count <> distinct_keys
   or row_count <> expected_days
