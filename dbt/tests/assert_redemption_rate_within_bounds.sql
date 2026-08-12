/*
    Singular test: the headline redemption rate must stay inside a plausible band.

    This is a business-logic guard, not a schema check. A rate of 0% or 100% almost always
    means the Redeemed flag stopped parsing (an upstream format change) rather than a
    genuine collapse in customer behaviour. Catching that in the pipeline is far cheaper
    than an executive noticing it in the report.

    Returns rows only on failure, per dbt convention.
*/

with rate as (

    select
        sum(redeemed_count) * 1.0 / nullif(count(*), 0) as redemption_rate,
        count(*)                                        as vouchers
    from {{ ref('fct_voucher_redemptions') }}

)

select
    redemption_rate,
    vouchers,
    'Redemption rate outside the plausible 50%-100% band - check the Redeemed flag parsing'
        as failure_reason
from rate
where redemption_rate is null
   or redemption_rate < 0.50
   or redemption_rate > 1.00
