# Business insights and recommendations

Period: 1 January – 31 July 2026. 25 merchants, 5 provinces, 5 voucher types.
R65,521,299 in sales across 510,127 transactions, 120,969 vouchers sold worth
R22,019,853, and 1,363 support tickets.

Every figure below is reproducible: `fabric/sql/03_business_question_queries.sql`
returns them in T-SQL, `build/build_insights.py` in Python, and the same numbers
appear in `dashboard/index.html`.

---

## The headline

**The support queue is being worked in reverse priority order.** This is the
clearest and cheapest finding in the dataset, and nothing else on this page
comes close to it for return on effort.

| Priority | Tickets | SLA target | Average resolution | Breach rate |
|---|---:|---:|---:|---:|
| Critical | 119 | 12h | **52.7h** | **98.3%** |
| High | 270 | 24h | **41.6h** | **82.2%** |
| Medium | 454 | 36h | 19.8h | 4.0% |
| Low | 520 | 48h | 11.3h | 0.2% |

Read the middle two columns against each other. The tickets with the *tightest*
target take the *longest* to resolve. Critical tickets are given 12 hours and
take 52.7; Low tickets are given 48 hours and take 11.3. The relationship
between priority and speed is not weak — it is inverted.

This also explains why the SLA breach model reaches an ROC-AUC of 0.966 while
using nothing but attributes known when the ticket is raised. Breach is close to
deterministic: tell the model the priority tier and it can tell you the outcome,
because resolution time barely varies by tier while the target varies fourfold.
A model that predicts a breach is not the useful artefact here. Fixing the
triage is.

Two readings are consistent with the data, and they need different responses:

- Triage is mislabelling tickets — genuinely urgent work is being tagged Low and
  cleared fast, while Critical is a dumping ground for hard, slow cases.
- Or the SLA targets were set without reference to how long the work takes.

The first is a process fix. The second is a target-setting fix. The data cannot
separate them; a half-hour with the support lead can.

---

## The five questions from the brief

### 1. Which merchants generate the highest sales value and transaction volume?

**Durban Cash Hub** leads at R5,776,119 (8.8% of all sales), followed by
**Kudu Digital Kiosk** (R4,535,330, 6.9%) and **Zebra Route Services**
(R4,519,762, 6.9%).

Concentration is moderate. The top 5 merchants take 35.4% of sales, the top 10
take 61.4%, and it takes 15 of the 25 merchants to reach 80% of revenue. That is
a healthier distribution than most merchant books — there is no single account
whose loss would be existential — but the top three are individually large
enough that any one of them stalling shows up in the group number, which is
exactly what happened in July.

### 2. Which voucher type has the highest redemption rate?

**Airtime, at 92.8%.** Gaming is worst at 76.0% — a spread of 16.9 points.

| Voucher type | Redemption rate | Avg days to redeem | Delayed >7 days | Sales value |
|---|---:|---:|---:|---:|
| Airtime | 92.8% | 3.55 | 13.5% | R14,355,277 |
| Electricity | 87.8% | 3.56 | 13.7% | R17,787,702 |
| Groceries | 82.7% | 3.57 | 13.8% | R11,425,970 |
| Bill Payment | 80.1% | 3.70 | 14.6% | R13,013,794 |
| Gaming | 76.0% | 3.56 | 13.9% | R8,938,556 |

The interesting part is the third column. Redemption *rate* varies by 17 points
while time-to-redeem is flat at about 3.6 days for every type. So the types do
not differ in how fast customers redeem — they differ in **whether** customers
come back at all. That points at the purchase occasion, not at any operational
difference: airtime is bought to be used immediately, gaming credit is bought
speculatively or as a gift.

The commercial consequence sits on Gaming and Bill Payment. A quarter of Gaming
vouchers are never redeemed, which is either a margin windfall or a customer
satisfaction problem depending on whether the business has to hold the float.

### 3. Which region shows declining sales or transaction behaviour?

**Eastern Cape**, and it is the only one.

| Province | Latest month | Prior 3-month average | Momentum |
|---|---:|---:|---:|
| Eastern Cape | R1,264,271 | R1,317,937 | **−4.1%** |
| Free State | R2,836,918 | R2,721,318 | +4.3% |
| Western Cape | R2,087,341 | R1,961,726 | +6.4% |
| Gauteng | R2,597,862 | R2,417,644 | +7.5% |
| KwaZulu-Natal | R1,680,558 | R1,486,255 | +13.1% |

This is a composition effect, not a regional collapse. The Eastern Cape number
is dragged down by individual merchants inside it, not by every merchant there
softening at once. Treat it as a merchant problem that happens to have a
postcode, and do not commission a regional strategy review off the back of it.

### 4. Are ticket volumes, priority or long resolution times associated with weaker merchant performance?

**Ticket volume, yes. Resolution speed, no.**

| Relationship | Correlation |
|---|---:|
| Tickets per 1,000 transactions vs sales growth | **−0.494** |
| Average resolution hours vs sales growth | +0.188 |
| SLA breach rate vs sales growth | +0.169 |

Tested at merchant-month grain, which is where causality would actually show:
months that followed a ticket surge of ten or more averaged **−12.9%** sales
growth, against **+4.4%** in every other month.

Two honest caveats. That comparison rests on only **3 surge months**, so it is a
strong signal on thin evidence — directionally believable, not an estimated
elasticity. And correlation here does not fix direction: tickets may be
suppressing sales, or falling sales may be generating complaints. The Umhlanga
case below is the one place the sequencing is visible.

The practical conclusion is still usable: **ticket volume is a leading indicator
worth alerting on; resolution speed is not.** A merchant whose ticket count
doubles deserves a call. A merchant whose average resolution time drifts up does
not, on this evidence.

### 5. Which merchants should management focus on first, and why?

**Umhlanga Value Mart, first and alone at the top of the list.**

Sales fell **44.7%** month on month (R116,532 → R64,394). The auto-generated
narrative decomposes it: the fall came from **transaction volume (−48.1%)**, not
basket size (+6.4%). In the same month, support tickets went from **3 to 37**,
and the redemption rate dropped 9.1 points to 76.6%.

That combination — volume collapsing while basket size holds, alongside a
twelve-fold ticket spike — reads as customers being unable to transact rather
than choosing not to. It is an operational failure, not lost demand, and
operational failures are recoverable.

Second tier, by health score: **Pretoria PayPoint** (29.0), **Umhlanga Value
Mart** (30.0), **Wild Coast Convenience** (34.8) are in the Critical band, with
**Nelson Bay Traders** (36.4), **Table Bay Express** (38.2) and **Cape Point
Cellular** (39.4) At risk.

One caveat on that ranking, stated because it changes how it should be used: the
health score is a **percentile** index, so roughly a quarter of merchants land in
the bottom tier by construction. It ranks relative risk inside the book. It does
not assert that six merchants are in trouble.

Separately, **Durban Cash Hub** — the largest merchant — had its ticket volume
step from about 5 per month to 44 in June and 52 in July, an 8-fold rise, while
its sales kept growing. Sales have not been hit yet. On the leading-indicator
finding above, that is precisely the pattern worth acting on before it is.

---

## What the models add

| Model | Metric | Result | What it means |
|---|---|---:|---|
| Voucher redemption propensity | ROC-AUC (held out on Jun–Jul) | 0.621 | Modest but real. Almost all of it comes from voucher type. |
| Delayed redemption risk | ROC-AUC | 0.506 | No forward signal — see below. |
| SLA breach risk | ROC-AUC (5-fold CV) | 0.966 | Near-deterministic given priority. A symptom of the triage problem. |
| Merchant segmentation | Silhouette (k=3) | 0.350 | Weak-to-moderate separation; useful as a lens, not as a hard grouping. |
| Daily sales forecast | MAPE (28 held-out days) | 2.47% | Beats a seasonal-naive benchmark by 0.18pp. |

**The delayed-redemption model failing is a finding, not a failure.** Western
Cape Bill Payment vouchers ran at roughly four times normal redemption lag
through April (15.4 days against a 3.8-day baseline), then returned to normal.
A model trained on January–March could not predict April (AUC 0.46, below
chance), and one trained through May could not predict June–July (AUC 0.51).

That is the useful answer. If the delay had a standing structural cause — a
merchant, a channel, a value band — the model would have found it. It did not,
which says the April episode was an **isolated operational incident**. The right
response is a root-cause review of what happened in the Western Cape settlement
path that month, not a predictive model.

**Segmentation** put 20 merchants in a Steady core, 4 in High-friction accounts
(11.7 tickets per 1k transactions against 2.8 for the core), and **1 alone** in
Scale drivers. A single-member cluster usually indicates over-fitting; here it is
the point — Kudu Digital Kiosk stepped its sales level up 64% in May and has held
it, which makes it genuinely unlike the other 24.

**Non-redemption exposure** is modelled at roughly **R1.0m** of voucher value at
low probability of ever being redeemed. Finance should carry that as a breakage
estimate with a stated confidence, not as certain revenue.

---

## Geographic picture

The network serves **5 of South Africa's 9 provinces**. Limpopo, Mpumalanga,
North West and Northern Cape have no merchants at all — **56% of the country's
land area**.

Density varies enormously: Gauteng generates R885k of sales per 1,000 km² from
4 merchants on 18,248 km², while Free State generates R139k per 1,000 km² from
10 merchants on 129,899 km².

That comparison needs a caveat before anyone acts on it. **Land area is not
demand.** Northern Cape is the largest province and among the least populated;
its absence from the network may be entirely rational. No population, GDP or
outlet-count reference feed was supplied with this dataset, so coverage can only
be assessed against area, which is the weakest possible denominator. Adding a
population feed is the single highest-value data addition available here.

---

## Recommended actions, in priority order

1. **Re-triage the support queue this week.** Critical tickets breach 98.3% of
   the time at 4.4× their target while Low tickets clear at a quarter of theirs.
   Establish whether the labels are wrong or the targets are. No new data or
   tooling is required, and nothing else on this list is as cheap.

2. **Put Umhlanga Value Mart on a recovery plan.** Sales −44.7% on volume, with
   tickets 3 → 37 in the same month. Clear the ticket backlog first and confirm
   whether transactions recover, which also tests the causal direction of
   finding 4.

3. **Call Durban Cash Hub before the number moves.** Tickets up 8-fold since
   June, sales not yet affected. This is the leading-indicator finding being
   actionable in real time rather than in hindsight.

4. **Run a root-cause review on the April Western Cape redemption incident.**
   Not a model — a review. The modelling establishes that it had no predictable
   structural cause, which is precisely why someone needs to find out what
   happened operationally.

5. **Book the R1.0m non-redemption exposure** as a breakage estimate with the
   model's confidence attached, rather than treating unredeemed voucher value as
   settled revenue.

6. **Understand Kudu Digital Kiosk's May step-change** before assuming it
   repeats or that it generalises. It is a 64% level shift that has held for
   three months, and it is the only one in the book.

7. **Add a population or outlet-count reference feed.** Until then, provincial
   coverage can only be judged against land area, which materially overstates the
   opportunity in large, sparsely populated provinces.
