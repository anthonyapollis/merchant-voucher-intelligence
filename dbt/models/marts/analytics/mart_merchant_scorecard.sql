{{ config(materialized='table', tags=['gold', 'analytics']) }}

/*
    mart_merchant_scorecard
    -----------------------
    One row per merchant: the drill-through target for the Merchant Analysis page and the
    feature table for the ML layer.

    Refactored to consume int_merchant_monthly and int_merchant_momentum rather than
    rebuilding those joins inline. The model used to be ~200 lines doing everything from raw
    aggregation through to composite scoring; it is now only responsible for the scoring
    logic, which is the part that is genuinely specific to this mart.

    The Health Score is computed HERE in SQL rather than in DAX, deliberately. It requires
    percentile ranking across the whole merchant population — expensive and awkward in DAX —
    and, more importantly, it must be byte-identical in the Power BI report, the Excel pack
    and the ML feature set. One definition in the warehouse is what keeps those three
    artefacts agreeing with each other.

    Health Score weights:
        25%  recent momentum        latest month vs prior 3-month average
        15%  month-on-month change
        15%  structural trend       last 3 months vs first 3 months
        15%  target attainment
        10%  redemption rate
        10%  operational deterioration   ticket volume vs own history
         5%  redemption speed
         5%  SLA breach rate

    Grain: one row per merchant.
*/

with momentum as (

    select * from {{ ref('int_merchant_momentum') }}

),

lifetime as (

    -- Whole-period voucher and ticket rates, taken from the facts rather than averaged
    -- across months. Averaging a monthly rate weights a quiet month equally with a busy
    -- one and gives a different — wrong — answer.
    select
        v.merchant_key,
        v.vouchers_sold,
        v.vouchers_redeemed,
        v.redemption_rate,
        v.avg_days_to_redeem,
        v.delayed_redemption_rate,
        v.outstanding_value,
        coalesce(t.tickets, 0)      as tickets,
        t.avg_resolution_hours,
        coalesce(t.sla_breach_rate, 0) as sla_breach_rate,
        coalesce(t.high_priority_tickets, 0) as high_priority_tickets,
        coalesce(t.open_tickets, 0) as open_tickets
    from (
        select
            merchant_key,
            count(*)                                            as vouchers_sold,
            sum(redeemed_count)                                 as vouchers_redeemed,
            sum(redeemed_count) * 1.0 / count(*)                as redemption_rate,
            avg(days_to_redeem)                                 as avg_days_to_redeem,
            sum(delayed_redemption_count) * 1.0
                / nullif(sum(redeemed_count), 0)                as delayed_redemption_rate,
            sum(outstanding_value)                              as outstanding_value
        from {{ ref('fct_voucher_redemptions') }}
        group by 1
    ) v
    left join (
        select
            merchant_key,
            count(*)                                            as tickets,
            avg(resolution_hours)                               as avg_resolution_hours,
            sum(sla_breach_count) * 1.0 / count(*)              as sla_breach_rate,
            sum(high_priority_count)                            as high_priority_tickets,
            sum(open_count)                                     as open_tickets
        from {{ ref('fct_support_tickets') }}
        group by 1
    ) t using (merchant_key)

),

combined as (

    select
        m.*,
        l.vouchers_sold,
        l.vouchers_redeemed,
        l.redemption_rate,
        l.avg_days_to_redeem,
        l.delayed_redemption_rate,
        l.outstanding_value,
        l.tickets,
        l.avg_resolution_hours,
        l.sla_breach_rate,
        l.high_priority_tickets,
        l.open_tickets,
        l.tickets * 1000.0 / nullif(m.total_transactions, 0)    as tickets_per_1k_txn
    from momentum m
    left join lifetime l using (merchant_key)

),

indexed as (

    select
        *,
        -- Relative index, immune to the ~6.1x calibration error in the supplied targets
        target_attainment
            / nullif((select sum(total_sales) / sum(sales_target) from combined), 0)
                                                                as target_attainment_index,

        -- PERCENT_RANK() = (rank-1)/(n-1). The Python implementation matches this exactly;
        -- pandas' rank(pct=True) returns rank/n and is NOT the same statistic. Using the two
        -- interchangeably previously shifted this score by up to 9.7 points.
        percent_rank() over (order by sales_vs_prior_3m_avg)     as pr_recent,
        percent_rank() over (order by mom_change)                as pr_mom,
        percent_rank() over (order by last3_vs_first3)           as pr_growth,
        percent_rank() over (order by target_attainment)         as pr_target,
        percent_rank() over (order by redemption_rate)           as pr_redeem,
        percent_rank() over (order by avg_days_to_redeem desc)   as pr_speed,
        percent_rank() over (order by tickets_vs_prior_3m_avg desc) as pr_ops,
        percent_rank() over (order by sla_breach_rate desc)      as pr_sla
    from combined

),

scored as (

    select
        *,
        round(100 * (
              0.25 * pr_recent
            + 0.15 * pr_mom
            + 0.15 * pr_growth
            + 0.15 * pr_target
            + 0.10 * pr_redeem
            + 0.10 * pr_ops
            + 0.05 * pr_speed
            + 0.05 * pr_sla
        ), 1)                                                   as health_score,

        rank() over (order by total_sales desc)                 as sales_rank,
        rank() over (order by total_transactions desc)           as transaction_rank,
        total_sales / sum(total_sales) over ()                  as sales_share,
        sum(total_sales) over (order by total_sales desc
                               rows between unbounded preceding and current row)
            / sum(total_sales) over ()                          as cumulative_share,

        -- Revenue at Risk: annualised shortfall against the merchant's OWN recent baseline.
        -- Ranking by percentage decline alone misdirects the account team — a 43% drop at a
        -- small merchant costs less than a 6% slide at a large one.
        greatest(
            (latest_month_sales / nullif(1 + sales_vs_prior_3m_avg, 0)) - latest_month_sales,
            0) * 12                                             as revenue_at_risk_annualised

    from indexed

)

select
    *,
    case
        when health_score < 35 then 'Critical'
        when health_score < 55 then 'Watch'
        when health_score < 75 then 'Healthy'
        else 'Star'
    end                                                         as health_band,
    case when cumulative_share <= 0.80
         then 'Top 80% of revenue' else 'Long tail' end         as pareto_band
from scored
order by total_sales desc
