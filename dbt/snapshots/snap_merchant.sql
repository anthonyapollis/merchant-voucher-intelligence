{% snapshot snap_merchant %}

{{
    config(
        target_schema='snapshots',
        unique_key='merchant_id',
        strategy='check',
        check_cols=['region', 'channel', 'active_status', 'account_manager',
                    'base_monthly_sales_target'],
        invalidate_hard_deletes=True
    )
}}

/*
    snap_merchant — Slowly Changing Dimension Type 2 capture
    -------------------------------------------------------
    MerchantReference is a CURRENT-STATE extract: it carries today's region, channel,
    account manager, ActiveStatus and target, and each daily load overwrites the last. The
    source system keeps no history, so unless we capture it here it is gone permanently.

    That matters because the attributes being tracked are exactly the ones an analyst will
    eventually need to reason about historically:

      * active_status              two merchants are currently 'At Risk'. When did that
                                   change? Did performance decline before or after the flag?
                                   Without history, that question is unanswerable.
      * account_manager            reassignments are a natural experiment on whether account
                                   coverage affects merchant performance.
      * base_monthly_sales_target  targets get re-based. Comparing attainment across periods
                                   is meaningless if the target silently changed underneath.
      * region / channel           re-segmentation would otherwise retrospectively restate
                                   every historic regional total.

    STRATEGY: 'check' rather than 'timestamp', because the source has no reliable
    last-modified column. OnboardedDate is the date the merchant joined, not the date the
    row was last edited, so using it as a timestamp key would miss every subsequent change.
    The check strategy compares column values directly and is the correct choice when the
    source cannot tell you when it changed.

    invalidate_hard_deletes=True closes out a merchant that disappears from the feed rather
    than leaving it open-ended and apparently still active forever.

    Note this snapshot only accumulates history from the first run onward — it cannot
    reconstruct changes that happened before it existed. Today it holds a single version per
    merchant, which is the honest starting position.
*/

select
    merchant_id,
    merchant_name,
    region,
    channel,
    active_status,
    account_manager,
    onboarded_date,
    base_monthly_sales_target,
    ingested_at
from {{ ref('stg_merchants') }}

{% endsnapshot %}
