"""
_table_registry.py — single source of truth for WHY each gold table exists.

The supplied README suggests a 5-table model. This solution has 14. That difference has to be
defensible table by table, not waved through as "more is better" — so the justification is
recorded once here and rendered into the ERD, the dbt descriptions, the Word report, the
Excel data dictionary and the dashboard. One edit updates all of them.

TIER classifies how each table earns its place:
  readme     named in the README AND supplied as a CSV — a file exists on disk
  built      named in the README but NOT supplied — the README requires it to be created
  brief      not in the README, but required to satisfy a stated deliverable in the brief
  grain      a modelling necessity — exists because mixing grains would break additivity
  extension  beyond the brief; added on judgement, and labelled as such

'readme' and 'built' were one tier until it was pointed out that the distinction is real and
load-bearing: the drop supplies FOUR CSVs but the README's suggested model lists FIVE tables.
DimDate is the fifth and has no source file — "candidate should create a proper date table".
Labelling it the same as DimMerchant implied a DimDate.csv that has never existed.
"""

TIERS = {
    "readme":    ("Supplied CSV",       "#12305B", "Named in the README and supplied as a file"),
    "built":     ("README-required",    "#1B6CA8", "Named in the README, no file — built here"),
    "brief":     ("Brief deliverable",  "#0E8B8B", "Required by a stated deliverable"),
    "grain":     ("Grain necessity",    "#B8860B", "Separate grain — additivity"),
    "extension": ("My extension",       "#7B4B94", "Beyond the brief, added on judgement"),
}

# The render order of the tiers. This lived as a hardcoded literal in seven separate build
# scripts; adding a tier broke all of them at once. It belongs here with everything else.
TIER_ORDER = list(TIERS)

TABLES = {
    # ---------------------------------------------------------------- README model
    "dim_date": dict(
        tier="built", rows=365,
        why="README: 'DimDate: candidate should create a proper date table'. This is the one "
            "table in the suggested model with NO source CSV — it is built, not loaded.",
        detail="Generated to full calendar-year boundaries rather than derived from the "
               "facts. Power BI time intelligence (DATEADD, SAMEPERIODLASTYEAR, TOTALYTD) "
               "does not error on a gapped calendar — it silently returns a wrong number. "
               "Contiguity is therefore tested, not assumed."),
    "dim_merchant": dict(
        tier="readme", rows=26,
        why="README: DimMerchant from MerchantReference.csv.",
        detail="Conformed dimension — the single filter path for every fact. Carries an "
               "Unknown (-1) member so a future unmatched fact row lands somewhere visible "
               "instead of vanishing from every total."),
    "fct_merchant_sales": dict(
        tier="readme", rows=26_500,
        why="README: FactMerchantSales from MerchantSales.csv.",
        detail="Grain Date x Merchant x VoucherType. Merchant/Region/Channel were DROPPED "
               "from the fact — profiling proved 100% agreement with MerchantReference, so "
               "keeping both would allow two competing versions of 'Region' in one model."),
    "fct_voucher_redemptions": dict(
        tier="readme", rows=120_969,
        why="README: FactVoucherRedemptions from VoucherRedemptions.csv.",
        detail="Accumulating snapshot — one row per voucher, updated when the second event "
               "(redemption) occurs. Carries TWO date foreign keys: sold_date_key active, "
               "redeemed_date_key inactive. Without that split, late redemptions are "
               "attributed back to the month of sale and a backlog is invisible."),
    "fct_support_tickets": dict(
        tier="readme", rows=1_363,
        why="README: FactSupportTickets from SupportTickets.csv.",
        detail="One row per ticket. sla_hours is stored ON the fact, not resolved from the "
               "priority dimension, so a future SLA policy change cannot retrospectively "
               "restate whether a historic ticket breached."),

    # ---------------------------------------------------------------- brief deliverables
    "dim_voucher_type": dict(
        tier="brief", rows=5,
        why="Brief section 5 requires 'voucher type performance' on the Merchant page.",
        detail="Used by BOTH the sales fact and the redemption fact — the textbook "
               "definition of a conformed dimension. Also carries category and margin band, "
               "which do not exist in the source and are maintained as a dbt seed so the "
               "commercial team can change them without a code deployment."),
    "dim_priority": dict(
        tier="brief", rows=4,
        why="Brief section 5 requires 'ticket priority' and 'SLA risk'; section 4 requires "
            "an SLA breach indicator.",
        detail="Carries target_sla_hours plus observed median/P90 resolution time, and "
               "derives sla_is_achievable from them. This is what turns the headline "
               "operational finding into DATA rather than prose: Critical has a 12h target "
               "against a 74h P90, and the model says so in a sortable column."),
    "dim_ticket_type": dict(
        tier="brief", rows=6,
        why="Brief section 5 requires ticket analysis on the Operational page.",
        detail="Adds category (Fulfilment / Financial / Commercial) and impact area "
               "(Customer vs Merchant impacting) — groupings that do not exist in the "
               "source but are how operations actually triage."),
    "dim_ticket_status": dict(
        tier="brief", rows=4,
        why="Brief section 5 requires ticket status and backlog visibility.",
        detail="Carries an explicit `ownership` attribute that splits the backlog into "
               "'awaiting us' (146 tickets) and 'awaiting customer' (93). A single "
               "'239 open' figure conflates a capacity problem with a chase-the-customer "
               "problem — different remediation entirely."),

    # ---------------------------------------------------------------- grain necessity
    "fct_merchant_target": dict(
        tier="grain", rows=175,
        why="Brief section 4 requires period comparison and a target measure; "
            "BaseMonthlySalesTarget is supplied on MerchantReference.",
        detail="Could have been an attribute on dim_merchant — but it is a MONTHLY measure "
               "while sales are DAILY. On the dimension it would re-count once per fact "
               "row. A separate fact at month grain, joined only through shared dimensions, "
               "is the standard Kimball answer to multi-grain reporting. 25 merchants x 7 "
               "months = 175 rows. Targets are pro-rated by days covered so a part-month "
               "never shows a false shortfall."),

    # ---------------------------------------------------------------- extensions
    "snap_merchant": dict(
        tier="extension", rows=25,
        why="NOT requested. Added because MerchantReference is a current-state extract.",
        detail="Each load overwrites the last, so active_status, account_manager, region and "
               "target history is destroyed at source. Two merchants are currently flagged "
               "'At Risk' — 'when did that change, and did performance decline before or "
               "after?' is otherwise unanswerable forever. Uses the `check` strategy because "
               "the source has no reliable last-modified column (OnboardedDate is when the "
               "merchant joined, not when the row was edited)."),
    "dim_merchant_history": dict(
        tier="extension", rows=25,
        why="NOT requested. The Type 2 face of snap_merchant.",
        detail="dim_merchant answers 'what is this merchant TODAY' and is what the semantic "
               "model joins to. This answers 'what was this merchant WHEN that fact "
               "happened'. Loading only Type 2 and forcing every query through a date-range "
               "join would be purer and practically worse; loading only Type 1 loses history "
               "permanently. Both, clearly labelled, is the workable answer."),
    "mart_merchant_scorecard": dict(
        tier="extension", rows=25,
        why="NOT requested. Drill-through target for the Merchant page and feature table "
            "for the ML layer.",
        detail="Holds the composite Health Score. Computed in SQL rather than DAX "
               "deliberately: it needs percentile ranking across the whole merchant "
               "population (expensive and awkward in DAX) and it must be byte-identical in "
               "Power BI, the Excel pack and the ML feature set. One definition in the "
               "warehouse is what keeps three artefacts agreeing."),
    "mart_merchant_change_alerts": dict(
        tier="extension", rows=0,
        why="NOT requested. Makes the snapshot actionable.",
        detail="Diffs consecutive snapshot versions and emits one row per changed field with "
               "a severity. A merchant moving to 'At Risk' is Critical; a re-based sales "
               "target is High, because it silently invalidates every period-over-period "
               "attainment comparison unless someone is told. Capturing history that nobody "
               "reads is not worth the storage — this is what makes the snapshot earn its "
               "place. Currently 0 rows: no change has occurred since first capture."),
}

# Honest framing used verbatim across the deliverables.
SUMMARY = (
    "The supplied README suggests a 5-table model. This solution has 14. Five come straight "
    "from the README; four exist because the brief's own report requirements (voucher type "
    "performance, ticket priority, SLA risk, backlog) need somewhere to put those "
    "attributes; one is a grain necessity; and four are extensions I added on judgement and "
    "have labelled as such. Presenting all 14 as though the brief demanded them would be "
    "overselling it — the honest split is a 10-table core plus 4 extensions."
)

COUNTER_ARGUMENT = (
    "The fair criticism is that four dimensions of 4-6 rows each is over-normalisation, and "
    "some modellers would keep those as degenerate columns on the ticket fact. That was in "
    "fact the first design here — all three ticket dimensions unioned into one table behind "
    "a discriminator — and it was worse for two concrete reasons. The three foreign keys on "
    "fct_support_tickets could not be relationship-tested, because a test cannot distinguish "
    "'priority_key resolves to a priority' from 'resolves to something, somewhere'. And "
    "Power BI cannot build three independent filter paths off one physical table without "
    "role-playing copies. Splitting them added 9 enforced foreign keys that previously could "
    "not exist."
)


def tier_of(table):
    return TABLES.get(table, {}).get("tier", "extension")


def counts():
    from collections import Counter
    return Counter(v["tier"] for v in TABLES.values())
