{#
    Reusable business-logic macros.

    The point of these is single-definition KPIs. "Redemption rate" appears in the executive
    page, the merchant scorecard, the voucher analysis and the ML feature set. If each one
    hand-writes the arithmetic, they drift — usually via a COUNT that quietly excludes nulls
    differently. Defining it once here means a change is made in one place and every
    consumer inherits it.
#}

{% macro redemption_rate(redeemed_col='redeemed_count', total_col='voucher_count') %}
    sum({{ redeemed_col }}) * 1.0 / nullif(sum({{ total_col }}), 0)
{% endmacro %}


{% macro sla_breach_rate(breach_col='sla_breach_count') %}
    sum({{ breach_col }}) * 1.0 / nullif(count(*), 0)
{% endmacro %}


{% macro avg_basket_value(value_col='sales_value', txn_col='transactions') %}
    {# Deliberately SUM/SUM, never AVG of a per-row ratio. Averaging a ratio weights a
       1-transaction day the same as a 500-transaction day and is the classic way an
       "average basket" measure ends up wrong. #}
    sum({{ value_col }}) / nullif(sum({{ txn_col }}), 0)
{% endmacro %}


{% macro tickets_per_1k_transactions(ticket_col='ticket_count', txn_col='transactions') %}
    sum({{ ticket_col }}) * 1000.0 / nullif(sum({{ txn_col }}), 0)
{% endmacro %}


{% macro pct_change(current_expr, prior_expr) %}
    ({{ current_expr }} / nullif({{ prior_expr }}, 0)) - 1
{% endmacro %}


{% macro cents_safe_divide(numerator, denominator, default_value='null') %}
    case when {{ denominator }} = 0 or {{ denominator }} is null
         then {{ default_value }}
         else {{ numerator }} / {{ denominator }} end
{% endmacro %}
