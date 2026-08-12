# Data model design decisions

## The shape

A star schema: five conformed dimensions, three fact tables at three different
grains, plus four analytical output tables that hang off `DimMerchant`.

```
                         DimDate
                     (role-playing x2)
                            |
        DimVoucherType -- FactMerchantSales -- DimMerchant
                            |                      |
        DimVoucherType -- FactVoucherRedemptions --|
                                                   |
        DimTicketType  -- FactSupportTickets -------|
        DimPriority    --------^                    |
                                                    |
                            DimMerchantSegment -----|
                            InsightNarrative -------|
                            FactAnomaly ------------|
                            FactSalesForecast (unrelated by design)
```

| Table | Grain | Rows |
|---|---|---:|
| FactMerchantSales | merchant × voucher type × day | 26,500 |
| FactVoucherRedemptions | one voucher | 120,969 |
| FactSupportTickets | one ticket | 1,363 |
| DimDate | one day | 243 |
| DimMerchant | one merchant | 25 |

Three facts at three grains is the reason this is a star and not a single wide
table. Sales are daily aggregates, redemptions are per-voucher, tickets are per
incident. Flattening them into one table would either fan out sales rows against
vouchers — inflating every sales total — or force pre-aggregation that destroys
the ability to answer voucher-level questions.

---

## Decisions worth defending

### Facts carry keys and measures only

`MerchantSales`, `VoucherRedemptions` and `SupportTickets` all arrive carrying
merchant name, region and channel. Silver drops all of them and keeps the
attributes once, in `DimMerchant`.

This is not tidiness. If a merchant moves region, a denormalised fact means
rewriting 26,500 sales rows, 121,000 redemption rows and 1,363 ticket rows, and
any row missed produces a merchant that appears in two regions at once. In the
star, it is one cell.

The duplicates were verified to agree with the reference file on every row
before being dropped, and the DQ gate re-checks referential integrity on every
load.

### `DimDate` is generated, and it is longer than the facts

Generated across whole months, from the earliest date any fact touches to the
latest — which is a **redemption** date (2026-08-20), three weeks past the last
sales date (2026-07-31).

Two failure modes this avoids. A calendar derived from the sales fact would
orphan every August redemption, silently. And a calendar that starts or ends
mid-month makes `TOTALYTD` and `DATEADD` produce partial-period comparisons that
look plausible and are wrong.

`MonthYearSort` exists because "Apr 2026" sorts before "Jan 2026"
alphabetically. Every month-labelled axis in the report depends on it.

> A note on that column: it was originally typed `int16`, and `Year × 100`
> silently overflowed, producing 5993 instead of 202601. Every month-over-month
> comparison in the first build was wrong in a way that still *looked* like a
> sensible ordering. It was caught by a downstream date-parse error, not by
> looking at the numbers — which is the argument for the DQ gate running on
> every load rather than on request.

### Role-playing date — as a *virtual* relationship

`FactVoucherRedemptions` has two date roles. `SoldDateKey` is the active
physical relationship. `RedeemedDateKey` is **not a physical relationship at
all** — `[Redemptions by Redemption Date]` applies it with `TREATAS`.

These answer genuinely different questions. "How many vouchers were redeemed in
July" (redemption date) is not "how many of the vouchers sold in July have been
redeemed" (sold date). Finance wants the first for cash movement; marketing
wants the second for campaign performance.

The obvious implementation is a second, inactive physical relationship activated
per measure with `USERELATIONSHIP`. That is what this model shipped first, and
it was wrong:

> 19,126 of 120,969 vouchers are unredeemed, so `RedeemedDateKey` is null for
> them. A physical relationship on a nullable key makes Power BI add a **blank
> member** to the table on the one side — and that blank then appears as
> "(Blank)" in every date slicer on every page. Crucially, this happens even
> while the relationship is **inactive**, so `USERELATIONSHIP` does not avoid
> it. The defect was visible in the first Desktop open: a "(Blank)" option
> sitting at the top of the month slicer on four pages.

`TREATAS` applies the same filter at query time with no physical relationship,
so `DimDate` stays clean and the nulls keep meaning "not redeemed" rather than
being coalesced to a fake date. `build/validate_pbit.py` now checks every
relationship's source column for nulls against the actual CSV, so this class of
bug fails the build rather than reaching a screenshot.

The same rule removed the `FactAnomaly` → `DimMerchant` relationship: 10 of its
36 rows are region-scope anomalies with no merchant, and the blank member was
turning up in the Region and Channel slicers.

### `SLAHours` moved to `DimPriority`

It arrives on every ticket but is a fixed property of the tier (verified 1:1).
Promoting it makes `Resolution vs SLA Target` a clean comparison of a measure to
a dimension attribute, and makes an SLA policy change a four-row update.

### Flags are 0/1 integers, never text

`IsRedeemed`, `IsSLABreach`, `IsDelayedRedemption`, `IsOpen`. This makes
`SUM(IsSLABreach)` the breach count and `AVERAGE(IsSLABreach)` the breach rate —
no `IF` inside an aggregation, no `CALCULATE(COUNTROWS(...), Status = "Breach")`
pattern that has to be rewritten every time someone adds a status value.

`IsDelayedRedemption` is deliberately NULL rather than 0 for unredeemed
vouchers, which makes `AVERAGE` compute over redeemed vouchers automatically,
with no filter argument and no chance of a colleague forgetting it.

### Implicit measures are disabled

`discourageImplicitMeasures` is set on the model, and every key and raw numeric
column is hidden. A user cannot drag `SalesValue` onto a chart and get a silent
`SUM` with no format string, no name and no definition. Every number in the
report goes through a named, documented measure.

### Measures live in a dedicated `_Measures` table

Not scattered across the fact tables. The field list then reads as business
concepts — Sales, Redemption, Operations, Intelligence — rather than as storage
layout, and a measure that spans two facts has no arbitrary "home" table to
argue about.

### `DIVIDE()`, never `/`

`DIVIDE` returns BLANK on a zero denominator; `/` returns Infinity, which
renders in a card visual as a very large number rather than as an error. A
merchant with zero transactions showing an average basket of ∞ is how a report
loses its audience.

### `ALLSELECTED` for share, not `ALL`

`Sales Share of Total %` uses `ALLSELECTED(DimMerchant)`. With `ALL`, filtering
to one region would still show each merchant as a share of the *national* total,
so the visible bars would sum to 25% and look broken. Share should be of what
the user is currently looking at.

### The ML tables join on `MerchantKey` and filter one way only

`DimMerchantSegment`, `InsightNarrative` and `FactAnomaly` are one-to-one or
one-to-many extensions of `DimMerchant`, with single-direction filtering **from**
the dimension. A merchant slicer drives them; they never filter back. Bidirectional
filtering here would let a segment slicer silently restrict the sales fact through
a path nobody drew on the diagram.

`FactSalesForecast` is deliberately **not** related to `DimDate`. Its rows sit
beyond the last actual date, so under the page's date filter a related table
would return blank on every view that ends at today. `Forecast Next 30 Days`
uses `ALL(DimDate)` instead.

---

## Storage and refresh

Import mode, not DirectQuery. The gold layer is ~150,000 rows across all tables
— trivially small for VertiPaq, and import gives sub-second visuals and full DAX
support. DirectQuery would buy nothing here and cost time intelligence
performance.

For a Fabric deployment, Direct Lake over the gold Delta tables is the better
option and requires no model changes: only the partition source in each
`.tmdl` file changes from `Csv.Document` to the Lakehouse. The `GoldFolder`
parameter exists so the model opens and loads from this repo without a capacity.

The two large facts are Z-ordered on `(DateKey, MerchantKey)` — the columns
every page filters hardest.

---

## What this model supports next

**Self-service.** Dimensions are conformed, keys are hidden, measures are named
in business language and organised into display folders. A user who has never
seen the schema can build "redemption rate by region by month" without help.

**Q&A and Copilot.** The same properties that make it browsable make it
answerable in natural language: unambiguous table and column names, no
duplicated attributes across tables to disambiguate between, and every metric
pre-defined as a measure so "total sales" resolves to one thing. `qnaEnabled` is
set. The main gap is synonyms — "GP" for Gauteng, "airtime" for the voucher
type — which belong in the linguistic schema and would be the first addition.

**Row-level security.** `DimMerchant[AccountManager]` is already in the model. A
role filtering that column to `USERPRINCIPALNAME()` would scope every page to an
account manager's own book with no other change, because every fact reaches
merchant through a single relationship path.

**Extension.** A fourth fact — settlements, chargebacks, campaign spend — joins
the existing dimensions without touching anything that already works. That is
the property a wide flat table does not have.
