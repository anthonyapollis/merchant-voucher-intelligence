# Assumptions, data quality and limitations

## Assumptions

Each of these is a decision that changes a number in the report. They are
parameters in code, not constants buried in a formula, so a business owner who
disagrees can change one value and rebuild.

**A voucher redeemed more than 7 days after sale counts as "delayed."**
The observed median lag is about 3 days and is remarkably stable across all five
voucher types (3.55–3.70 days), so 7 days sits well outside normal behaviour
without being so far out that it only catches extremes. Set by
`delayed_redemption_threshold_days` in `nb_02_silver_conform` and
`DELAY_THRESHOLD_DAYS` in `build/build_gold.py`.

**Unredeemed vouchers are excluded from the delay rate, not counted as
on-time.** `IsDelayedRedemption` is NULL when `IsRedeemed = 0`. A voucher nobody
has come back for is not "on time" — it has no outcome yet. Counting it as a
zero would drag the delay rate down by the ~16% of vouchers that are unredeemed
and make a rising delay problem look like an improving one.

**Merchant name, region and channel come from the reference file only.**
All three fact files repeat these attributes. They were checked row by row and
agree with `MerchantReference` on every single row, so the duplicates are
dropped in Silver rather than reconciled. If they ever disagree, the reference
file wins and the DQ gate raises it.

**`SLAHours` is a property of the priority tier, not of the ticket.** Verified
one-to-one: Critical 12h, High 24h, Medium 36h, Low 48h, with no exceptions.
It is promoted to `DimPriority` so an SLA policy change is a four-row update
rather than a rewrite of 1,363 fact rows.

**Sales targets are `BaseMonthlySalesTarget` × months in the selected period.**
No phasing, seasonality or working-day adjustment is applied, because none was
supplied. A part-month counts as a whole month, which will overstate the target
on any partial period.

**Voucher types are classed by settlement model.** Airtime, Electricity and
Gaming are treated as prepaid; Bill Payment and Groceries as third-party
settled. This is an analyst's inference from the redemption behaviour, not
something stated in the source, and it is used only for grouping — no measure
depends on it being right.

**Ticket categories** (Financial / Fulfilment / Service) are likewise an
analytical grouping applied in Gold, not a source field.

---

## Data quality

The supplied data is clean. All 20 automated checks pass — referential
integrity across every fact-to-dimension join, grain uniqueness on all three
facts, no negative sales or transaction counts, no redemption dated before its
sale, no redeemed voucher missing a redemption date, and a contiguous calendar.

Run `python build/build_gold.py` (Python) or
`fabric/sql/02_data_quality_checks.sql` (T-SQL) to reproduce.

That said, three things are worth knowing before trusting a number:

**Resolution hours mix two definitions.** The supplied data dictionary states
that `ResolutionHours` is "hours to resolve **or current elapsed hours**." 239
of 1,363 tickets are not Closed, so for those the value is elapsed time, not
time to resolution. This is not separable from what was supplied — there is no
resolution timestamp to recompute from.

The consequence is that `Average Resolution Hours` is a blend, and it
**understates** true resolution time, because an open ticket's clock is still
running and will only get larger. `Average Resolution Hours (Closed)` is
provided alongside it for anywhere the distinction matters. The headline
priority-inversion finding survives either way: it holds on closed tickets
alone.

**Support tickets carry no voucher type.** There is no way to attribute a ticket
to a voucher type, so the voucher-type slicer cannot filter ticket visuals.
Rather than silently drop ticket rows when that slicer is used — which would
understate the operational picture without saying so — the filter is left
un-applied to ticket visuals and the filter bar states this on screen.

**Redemption dates extend past the sales window.** Sales and tickets end
2026-07-31; redemptions run to 2026-08-20, because vouchers sold in July get
redeemed in August. `DimDate` is generated to cover the latest date *any* fact
points at, not the latest sales date. A calendar that stopped at the last sales
date would silently orphan 
those August redemptions.

---

## Limitations

**Seven months, one year.** No year-on-year comparison is possible, and annual
seasonality cannot be separated from underlying trend. Every "growth" figure in
this report is month-on-month or against a three-month base, and none of it is
seasonally adjusted because there is no second year to estimate seasonality
from. The upward drift visible across all merchants may be genuine growth, a
seasonal ramp, or a synthetic data artefact — seven months cannot distinguish
these.

**25 merchants is too few for a supervised risk model.** A churn or
decline classifier fitted on 25 entities cannot be validated honestly; any
held-out set is single digits. The Merchant Health Score is therefore a
**transparent weighted percentile index**, not a fitted model — every component
and weight is visible in `build_ml.py` and can be re-weighted by the business.

**The health score is relative by construction.** Because every component is a
percentile rank within the merchant base, roughly a quarter of merchants always
fall in the bottom tier no matter how healthy the book is. It answers "who
should I worry about first," never "is this merchant in trouble in absolute
terms."

**The delayed-redemption model scores at chance** (AUC 0.51 forward, 0.46 on the
April diagnostic). Reported rather than dropped, because a model failing to find
signal is evidence that the April incident had no standing structural cause.

**The forecast's margin is slim.** Holt-Winters with a damped trend beats a
seasonal-naive benchmark by 0.18 percentage points of MAPE (2.47% vs 2.65%) on
28 held-out days. That is a real win — the naive benchmark is genuinely hard to
beat on a series this smooth — but it is not a large one, and it should be
re-backtested as history accumulates. Three of the five candidate models tested
were *worse* than the benchmark, which is exactly why the bake-off is in the
code rather than a single model being asserted.

**Ticket-surge evidence rests on 3 merchant-months.** The −12.9% vs +4.4%
comparison in finding 4 is directionally clear but statistically thin. It should
drive an alert, not a forecast.

**Geographic analysis has no demand denominator.** Coverage can only be assessed
against land area, which says nothing about how many people live there.
Conclusions about "unserved opportunity" are therefore about footprint, not
about market.

**Causality is not established anywhere in this analysis.** The ticket-volume
relationship is a correlation with a plausible mechanism and one well-sequenced
case study. It is not an estimated causal effect and should not be used to
forecast the sales impact of a ticket reduction programme.
