/*
    Singular test: no fact may be dated after the reporting window closes.

    A future-dated sale or ticket is invariably a timezone or date-parsing defect, and it
    quietly distorts every "latest month" measure — including the momentum inputs to the
    Health Score and the anomaly model. Cheap to test, expensive to miss.
*/

{% set cutoff = var('reporting_end_date') %}

select 'fct_merchant_sales' as model, sales_date::varchar as offending_date, count(*) as rows
from {{ ref('fct_merchant_sales') }}
where sales_date > cast('{{ cutoff }}' as date)
group by 1, 2

union all

select 'fct_support_tickets', ticket_date::varchar, count(*)
from {{ ref('fct_support_tickets') }}
where ticket_date > cast('{{ cutoff }}' as date)
group by 1, 2

union all

select 'fct_voucher_redemptions (sold)', sold_date::varchar, count(*)
from {{ ref('fct_voucher_redemptions') }}
where sold_date > cast('{{ cutoff }}' as date)
group by 1, 2

-- NOTE: redeemed_date is deliberately NOT tested against the cutoff. A voucher sold on
-- 31 July may legitimately be redeemed in August; that is the redemption tail, not an error.
