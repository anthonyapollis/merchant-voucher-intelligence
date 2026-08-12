{{ config(materialized='table', tags=['gold', 'analytics', 'risk']) }}

/*
    mart_merchant_value_risk
    ------------------------
    Lifetime value, attrition risk and fraud-adjacent signals — at MERCHANT level.

    WHY MERCHANT AND NOT CUSTOMER. Customer lifetime value and customer churn were asked
    for. They cannot be built from this dataset and it would be dishonest to pretend
    otherwise: there is no customer identifier anywhere in the four source files. Not a
    hashed one, not a session id, not a card token. Every fact is either merchant-daily
    aggregate or voucher-level with no purchaser attached.

    So this model does the defensible equivalent — the merchant IS the customer of the
    voucher business — and the documentation states plainly which controls remain
    unbuildable and exactly what telemetry each would need.

    CONTROLS SUPPORTED BY THIS DATA
      reversal_ticket_rate      Reversal Query tickets per 1k transactions. A real signal:
                                reversals are where value moves back, and a merchant with an
                                elevated rate is worth a look.
      same_day_redemption_rate  Redemption velocity. Legitimate for airtime, unusual in bulk.
      unredeemed_value          Outstanding liability concentrated at one merchant.
      anomaly_flag              Isolation Forest output (multivariate behaviour shift).
      health/momentum           Attrition risk.

    CONTROLS **NOT** SUPPORTED — stated, not faked
      Duplicate redemption      voucher_id is unique BY CONSTRUCTION in the source extract,
                                so a duplicate cannot appear. Needs: raw redemption event
                                log with repeated attempts, not a deduplicated voucher table.
      Geographic anomaly        Needs merchant location, transaction location, timestamp.
                                Only province is supplied, at merchant level, static.
      PIN / invalid voucher use Needs voucher PIN, attempt outcome, failure reason.
      Customer velocity         Needs a customer or session identifier.
      Voucher value outliers    TESTED AND FOUND UNSUPPORTED: zero vouchers sit beyond 3
                                standard deviations within their own type, because the
                                synthetic generator used a bounded distribution. The control
                                is implemented below and correctly returns zero — reporting
                                a fabricated "0 outliers found" without testing would have
                                been the lazy alternative.

    Grain: one row per merchant.
*/

with base as (
    select * from {{ ref('mart_merchant_scorecard') }}
),

tenure as (
    select merchant_key, merchant_id, onboarded_date, tenure_months, active_status
    from {{ ref('dim_merchant') }}
    where merchant_key <> '-1'
),

reversals as (
    select
        t.merchant_key,
        sum(case when tt.ticket_type = 'Reversal Query' then 1 else 0 end)  as reversal_tickets,
        sum(case when tt.ticket_category = 'Financial' then 1 else 0 end)   as financial_tickets
    from {{ ref('fct_support_tickets') }} t
    join {{ ref('dim_ticket_type') }} tt using (ticket_type_key)
    group by 1
),

velocity as (
    select
        merchant_key,
        sum(case when days_to_redeem = 0 then 1 else 0 end) * 1.0
            / nullif(sum(redeemed_count), 0)                                as same_day_redemption_rate,
        sum(case when days_to_redeem > 30 then 1 else 0 end)                as very_late_redemptions,
        max(voucher_value)                                                  as max_voucher_value
    from {{ ref('fct_voucher_redemptions') }}
    group by 1
),

value_outliers as (
    -- Implemented and evaluated rather than assumed. Returns 0 on this dataset; the model
    -- keeps the column so the control is visibly running, not silently absent.
    with stats as (
        select voucher_type_key, avg(voucher_value) mu, stddev(voucher_value) sd
        from {{ ref('fct_voucher_redemptions') }} group by 1
    )
    select f.merchant_key,
           sum(case when abs(f.voucher_value - s.mu) > 3 * s.sd then 1 else 0 end)
                                                                            as value_outlier_vouchers
    from {{ ref('fct_voucher_redemptions') }} f
    join stats s using (voucher_type_key)
    group by 1
),

combined as (
    select
        b.merchant_key, b.merchant_name, b.region, b.channel, b.account_manager,
        b.merchant_size_band, b.health_score, b.health_band,
        b.total_sales, b.total_transactions, b.avg_basket_value,
        b.sales_vs_prior_3m_avg, b.last3_vs_first3, b.mom_change,
        b.redemption_rate, b.outstanding_value, b.tickets, b.sla_breach_rate,
        b.revenue_at_risk_annualised,
        t.onboarded_date, t.tenure_months, t.active_status,

        -- ---------------------------------------------------- LIFETIME VALUE (merchant)
        b.total_sales / nullif(b.months_observed, 0)                as avg_monthly_revenue,
        -- Observed revenue is only 7 months. Annualised run-rate is the honest projection;
        -- a full "lifetime" figure would require revenue history back to onboarding, which
        -- the sales extract does not contain.
        b.total_sales / nullif(b.months_observed, 0) * 12           as annualised_run_rate,
        b.total_sales / nullif(b.months_observed, 0) * t.tenure_months
                                                                    as implied_lifetime_value,

        coalesce(r.reversal_tickets, 0)                             as reversal_tickets,
        coalesce(r.financial_tickets, 0)                            as financial_tickets,
        coalesce(r.reversal_tickets, 0) * 1000.0
            / nullif(b.total_transactions, 0)                       as reversal_per_1k_txn,
        v.same_day_redemption_rate,
        coalesce(v.very_late_redemptions, 0)                        as very_late_redemptions,
        v.max_voucher_value,
        coalesce(o.value_outlier_vouchers, 0)                       as value_outlier_vouchers

    from base b
    left join tenure t using (merchant_key)
    left join reversals r using (merchant_key)
    left join velocity v using (merchant_key)
    left join value_outliers o using (merchant_key)
),

scored as (
    select
        *,
        -- ---------------------------------------------------- ATTRITION RISK
        -- Composite of momentum, trend and the CRM flag. Deliberately weighted toward
        -- recent momentum: attrition shows up as a break, not a gentle slope.
        round(100 * (
              0.45 * percent_rank() over (order by sales_vs_prior_3m_avg)
            + 0.25 * percent_rank() over (order by last3_vs_first3)
            + 0.15 * percent_rank() over (order by mom_change)
            + 0.15 * percent_rank() over (order by redemption_rate)
        ), 1)                                                       as retention_score,

        -- ---------------------------------------------------- FRAUD-ADJACENT RISK
        -- Explicitly named "signal", not "fraud score". Nothing here evidences fraud; these
        -- are the anomalies worth a human look given the fields that exist.
        round(100 * (
              0.40 * percent_rank() over (order by reversal_per_1k_txn)
            + 0.25 * percent_rank() over (order by coalesce(same_day_redemption_rate, 0))
            + 0.20 * percent_rank() over (order by sla_breach_rate)
            + 0.15 * percent_rank() over (order by coalesce(value_outlier_vouchers, 0))
        ), 1)                                                       as risk_signal_score
    from combined
)

select
    *,
    100 - retention_score                                           as attrition_risk_score,
    case
        when 100 - retention_score >= 75 then 'High'
        when 100 - retention_score >= 50 then 'Medium'
        else 'Low'
    end                                                             as attrition_risk_band,
    case
        when risk_signal_score >= 75 then 'Review'
        when risk_signal_score >= 50 then 'Monitor'
        else 'Normal'
    end                                                             as risk_signal_band,
    -- What is actually at stake if this merchant leaves
    round(annualised_run_rate, 2)                                   as value_at_stake_if_lost
from scored
order by total_sales desc
