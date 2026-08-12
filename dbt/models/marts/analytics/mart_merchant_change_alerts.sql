{{ config(materialized='table', tags=['gold', 'analytics', 'alerting']) }}

/*
    mart_merchant_change_alerts
    ---------------------------
    Turns the Type 2 snapshot from a passive history store into an active alerting feed.

    Capturing history is only half the value. snap_merchant records that a merchant's
    ActiveStatus, account manager, region or target changed — but nobody reads a snapshot
    table. This model diffs consecutive versions and emits one row per CHANGED FIELD, with a
    severity, so the change can be surfaced on the report, emailed by the pipeline, or picked
    up by a Data Activator rule in Fabric.

    Why severity differs by field:
      * active_status to 'At Risk'   Critical. This is the business declaring a problem.
      * base_monthly_sales_target    High. A re-based target silently invalidates every
                                     period-over-period attainment comparison. If nobody is
                                     told, the report keeps comparing against a moved
                                     goalpost.
      * account_manager              Medium. A reassignment is a coverage risk and also a
                                     natural experiment worth tracking against performance.
      * region / channel             High. Re-segmentation retrospectively restates regional
                                     totals; Finance needs to know before month-end.

    Grain: one row per merchant per version-change per changed field.
*/

with versions as (

    select
        merchant_key,
        merchant_id,
        merchant_name,
        region,
        channel,
        active_status,
        account_manager,
        base_monthly_sales_target,
        valid_from,
        version_number,
        lag(region)                    over w as prev_region,
        lag(channel)                   over w as prev_channel,
        lag(active_status)             over w as prev_active_status,
        lag(account_manager)           over w as prev_account_manager,
        lag(base_monthly_sales_target) over w as prev_target
    from {{ ref('dim_merchant_history') }}
    window w as (partition by merchant_id order by version_number)

),

changed as (

    select * from versions where version_number > 1

),

unpivoted as (

    select merchant_key, merchant_id, merchant_name, valid_from as changed_at,
           'Active status'  as field_changed,
           prev_active_status as old_value, active_status as new_value
    from changed where active_status is distinct from prev_active_status

    union all
    select merchant_key, merchant_id, merchant_name, valid_from,
           'Account manager', prev_account_manager, account_manager
    from changed where account_manager is distinct from prev_account_manager

    union all
    select merchant_key, merchant_id, merchant_name, valid_from,
           'Region', prev_region, region
    from changed where region is distinct from prev_region

    union all
    select merchant_key, merchant_id, merchant_name, valid_from,
           'Channel', prev_channel, channel
    from changed where channel is distinct from prev_channel

    union all
    select merchant_key, merchant_id, merchant_name, valid_from,
           'Monthly sales target',
           cast(round(prev_target, 2) as varchar), cast(round(base_monthly_sales_target, 2) as varchar)
    from changed where base_monthly_sales_target is distinct from prev_target

)

select
    u.merchant_key,
    u.merchant_id,
    u.merchant_name,
    u.changed_at,
    u.field_changed,
    u.old_value,
    u.new_value,

    case
        when u.field_changed = 'Active status' and u.new_value = 'At Risk' then 'Critical'
        when u.field_changed = 'Active status'                             then 'Medium'
        when u.field_changed in ('Region', 'Channel')                      then 'High'
        when u.field_changed = 'Monthly sales target'                      then 'High'
        else 'Medium'
    end                                                     as severity,

    case
        when u.field_changed = 'Active status' and u.new_value = 'At Risk'
            then u.merchant_name || ' was flagged At Risk in the CRM. Cross-check against the '
                 || 'computed health score before actioning.'
        when u.field_changed = 'Monthly sales target'
            then u.merchant_name || ' had its monthly target re-based from ' || u.old_value
                 || ' to ' || u.new_value || '. Target attainment is no longer comparable '
                 || 'across the change date.'
        when u.field_changed = 'Account manager'
            then u.merchant_name || ' was reassigned from ' || coalesce(u.old_value, 'unassigned')
                 || ' to ' || u.new_value || '.'
        else u.merchant_name || ' ' || lower(u.field_changed) || ' changed from '
             || coalesce(u.old_value, '(none)') || ' to ' || coalesce(u.new_value, '(none)') || '.'
    end                                                     as alert_message,

    -- Joined so an alert can be triaged by how much revenue it concerns, not just by field
    s.total_sales                                           as merchant_total_sales,
    s.health_score,
    s.health_band

from unpivoted u
left join {{ ref('mart_merchant_scorecard') }} s using (merchant_key)
order by
    case when u.field_changed = 'Active status' and u.new_value = 'At Risk' then 0 else 1 end,
    s.total_sales desc nulls last,
    u.changed_at desc
