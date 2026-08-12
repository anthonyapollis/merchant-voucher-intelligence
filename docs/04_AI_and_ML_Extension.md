# AI and ML extension

The brief lists three optional ideas: Copilot/Q&A, notebook anomaly detection,
and narrative insight generation. All three are implemented. This page covers
what was built, how it was evaluated, and — more usefully — where each one is
and is not worth trusting.

---

## 1. Anomaly detection (unsupervised)

`fabric/notebooks/nb_04_ai_anomaly_and_narrative.py` → `FactAnomaly`

Four detectors, because "anomaly" means four different things in this data:

| Detector | Grain | Method |
|---|---|---|
| Daily sales | merchant × day | Robust z against a trailing 28-day window, day-of-week deseasonalised |
| Monthly sales level shift | merchant × month | Month vs prior 3-month mean, ±25% |
| Monthly ticket level shift | merchant × month | Month vs prior 3-month mean, +100% **and** +8 absolute |
| Weekly redemption lag | region × voucher type × week | Robust z against the full series |

### Why median/MAD instead of mean/standard deviation

A single large spike inflates the standard deviation enough to hide itself. If a
merchant's ticket count jumps from 2 to 44, that one point raises σ so much that
the z-score of the spike lands near 2 and never trips a 3σ threshold. The median
absolute deviation does not move when one point moves, so the spike stays
visible. MAD is scaled by 0.6745 to be comparable to a standard deviation on
normally distributed data.

### Why the baseline is *trailing*, not whole-series

This one mattered. The first implementation scored every point against the
median of its own full series, and it **missed two of the four patterns
deliberately planted in the dataset** — Kudu Digital Kiosk's May step-up and
Durban Cash Hub's June ticket surge.

The reason is that a sustained level shift poisons its own baseline. After a
merchant moves to a new level and stays there, the whole-series median settles
between the old and new levels, and neither regime looks unusual. Scoring each
point against the window that *preceded* it flags the step at the moment it
happens — which is also when someone could act on it.

A second bug surfaced in the same pass: for sparse counts, most merchants log
zero tickets on most days, so the median is 0, the MAD is 0, and the z-score
divides by zero and returns 0 for everything. Hence the MAD floor, and hence
weekly rather than daily aggregation for tickets.

### Results

36 anomalies. The four patterns the dataset's README says were planted are all
detected, and all four rank in the top eight by score:

| Detected | Score | Planted pattern |
|---|---:|---|
| Durban Cash Hub, ticket level shift, June | +780% | "one merchant has a support-ticket spike from June" |
| Umhlanga Value Mart, ticket level shift, July | +693% | (accompanies the July decline) |
| Kudu Digital Kiosk, sales level shift, May | +64% | "one merchant grows strongly from May" |
| Umhlanga Value Mart, sales level shift, July | −43% | "one merchant has a visible July sales decline" |
| Western Cape / Bill Payment, redemption lag, April | z = 20.1 | "one region and voucher type has delayed redemptions in April" |

No high-severity false positives. This was a genuine blind test — the detectors
were written against the statistics, not against the README's list, and the
first version failing to find two of them is the reason the trailing-window
approach exists.

---

## 2. Narrative insight generation

`InsightNarrative`, one row per merchant. Example output, unedited:

> Umhlanga Value Mart (Free State, Retail) sharp decline: sales −44.7% month on
> month, driven by transaction volume (−48.1%) rather than basket size (+6.4%).
> Support tickets rose from 3 to 37 over the same period, which is the most
> likely operational cause. Redemption rate moved −9.1 points to 76.6%.

### Why this is rule-based and not LLM-generated

This is a deliberate choice, and the opposite of what "AI extension" usually
means. Three reasons:

**Determinism.** The field drives an operations work queue. The same inputs must
produce the same sentence every night, or two people reading the same dashboard
an hour apart get different explanations for the same number.

**Traceability.** Every clause maps to a computed figure. "Driven by transaction
volume rather than basket size" is not a characterisation — it is the result of
comparing |Δ transactions| to |Δ average basket| and requiring a 1.5× margin
before making the claim. Nothing in the sentence is unattributable.

**No hallucination surface.** An LLM writing "the most likely operational cause"
about a merchant's revenue is generating a causal claim it cannot support. The
rule version makes that claim only when tickets at least doubled *and* exceeded
5, and hedges it as "most likely" rather than asserting it.

The decomposition into volume versus basket size is the part that makes the
output actionable. "Sales fell 45%" tells an account manager nothing they can
act on. "Sales fell 45% on transaction volume while basket size held, in the
same month tickets went from 3 to 37" tells them customers could not transact,
which is a different visit than "customers spent less."

### Where an LLM *does* belong here

Not in generating the facts — in the layer above them. A sensible design uses
the deterministic narrative as grounded input and an LLM for:

- **Summarising across merchants** into a weekly executive briefing, where the
  underlying claims are all pre-verified.
- **Answering follow-ups** over the semantic model via Copilot, where the model
  supplies the numbers and the LLM supplies the phrasing.
- **Drafting the account manager's outreach email**, which is generation work
  with no factual authority.

The dividing line: an LLM should shape how a verified fact is communicated,
never decide what the fact is.

---

## 3. Q&A and Copilot readiness

`qnaEnabled` is set on the model, and the design choices in
[02_Model_Design.md](02_Model_Design.md) that make it browsable are the same
ones that make it answerable: unambiguous names, no attribute duplicated across
tables, implicit measures disabled, every metric pre-defined.

The honest gap is **synonyms**. Someone will type "GP" for Gauteng, "airtime"
meaning the voucher type, or "how are my merchants doing" meaning health score.
Those belong in the linguistic schema, and populating it would be the first
thing to add before putting Q&A in front of executives.

---

## 4. Supervised models

Four, each evaluated on data it never saw. Full metrics in
`data/gold/MLModelPerformance.csv`; the models are in `build/build_ml.py`.

| Model | Rows | Holdout | Metric | Result |
|---|---:|---|---|---:|
| Voucher redemption propensity | 120,969 | Time split, train Jan–May, test Jun–Jul | ROC-AUC | 0.621 |
| Delayed redemption risk | 101,843 | Same time split | ROC-AUC | 0.506 |
| SLA breach risk | 1,363 | Stratified 5-fold CV | ROC-AUC | 0.966 |
| Merchant segmentation | 25 | Silhouette across k=2..6 | Silhouette | 0.350 (k=3) |
| Daily sales forecast | 212 days | Held-out last 28 days | MAPE | 2.47% |

### Time-based splits, not random

Every voucher model splits on time, not at random. A random split would let the
model train on vouchers sold the same day as the ones it is scoring, which is
not how it runs in production — production always scores forward. The behavioural
priors (merchant and voucher-type historical redemption rates) are computed on
the **training window only**, because computing them on the full frame would
leak the test period's outcome into the test features.

### The leakage that was caught and removed

The SLA breach model originally included the ticket's `Status` field, scoring
0.9656. `Status` is only known *after* the ticket has been worked — an
"Escalated" ticket is escalated *because* it ran long — so it is useless at
ticket creation, which is the only moment a breach-risk score could change the
outcome. It was removed.

The instructive part: removing it moved AUC from 0.9656 to **0.9661**. The leak
was real and the feature was rightly cut, but it was not what was carrying the
model. Both numbers are logged in `MLModelPerformance.csv` so the comparison is
visible rather than asserted.

What actually carries it is `SLATargetHours` and `PrioritySort` — the two
highest permutation-importance features by an order of magnitude. Which is the
priority-inversion finding again: breach is near-deterministic given the tier,
because resolution time barely varies while the target varies fourfold. **The
model's high accuracy is a symptom of a process problem, not a modelling win.**

### The model that found nothing, and why that is a result

Delayed-redemption risk scores 0.506 forward — chance. A diagnostic run trained
on Jan–Mar and tested on April, the month containing the known Western Cape
delay incident, scored **0.457** — below chance.

Reported rather than dropped. If the delay had a standing structural cause
attributable to a merchant, region, channel or value band, the model would have
found it. It did not, in either direction. That is positive evidence that the
April episode was an isolated operational incident, and it changes the
recommendation from "build a delay-prediction model" to "find out what happened
in the Western Cape settlement path in April."

### The forecast bake-off

Five candidates on the same held-out 28 days, including the benchmark:

| Model | MAPE |
|---|---:|
| **Holt-Winters, damped trend + additive seasonal** | **2.47%** |
| Holt-Winters, additive trend + multiplicative seasonal | 2.55% |
| *Seasonal naive (last week repeated)* — benchmark | *2.65%* |
| Holt-Winters, additive trend + additive seasonal | 3.33% |
| OLS linear trend + day-of-week | 6.12% |

The first implementation used additive trend and additive seasonality, scored
3.33%, and **lost to repeating last week**. That is the outcome a single-model
forecast quietly ships. Damping the trend fixed it — an undamped trend
extrapolates the recent upward drift too aggressively over a 28-day horizon.

The winning margin is 0.18 percentage points. Real, but slim, and worth
re-backtesting as history accumulates. The benchmark stays in the candidate list
permanently for exactly this reason.

### Why there is no churn model

25 merchants. A supervised risk classifier fitted on 25 entities cannot be
honestly validated — any held-out set is single digits, and any AUC computed on
it is noise. The Merchant Health Score is instead a **transparent weighted
percentile index**:

| Component | Weight |
|---|---:|
| Growth slope | +30% |
| Target attainment | +20% |
| Redemption rate | +20% |
| Tickets per 1k transactions | −15% |
| SLA breach rate | −10% |
| Delayed redemption rate | −5% |

Every component is a percentile rank within the merchant base, so the score
answers "how does this merchant compare to its peers" — the question an account
manager actually asks. The weights are a stated business judgement, visible and
re-weightable, not a fitted parameter presented as objective.

The trade-off, stated plainly: because it is percentile-based, roughly a quarter
of merchants always land in the bottom tier regardless of how healthy the book
is. It ranks relative risk. It does not measure absolute health.

### Segmentation

K-Means on 9 standardised behavioural features, k chosen by silhouette rather
than assumed (k=2: 0.309, **k=3: 0.350**, k=4: 0.192, k=5: 0.198, k=6: 0.220).
Cluster labels are derived from centroid percentile ranks, not hand-typed, so
they stay correct if the data changes.

| Segment | Count | Profile |
|---|---:|---|
| Steady core | 20 | R2.9m avg sales, +4.2%/mo, 2.8 tickets/1k tx |
| High-friction accounts | 4 | R0.7m avg sales, +2.6%/mo, **11.7 tickets/1k tx** |
| Scale drivers | 1 | R4.5m, **+13.0%/mo**, 1.8 tickets/1k tx |

Silhouette 0.350 is weak-to-moderate — the merchant base does not fall into
sharply separated groups, and the segments should be used as a lens rather than
as a hard classification. The single-member cluster would normally suggest
over-fitting; here it is the finding, since Kudu Digital Kiosk's 64% May level
shift genuinely makes it unlike the other 24.

---

## Operationalising

`nb_05_ml_models` runs **weekly, not nightly** (Sundays, in
`pl_merchant_daily_refresh`). The models do not move materially day to day, and
retraining nightly would churn segment labels underneath the account managers
who work from them. Anomaly detection and narrative generation *do* run nightly,
because their whole value is timeliness.

Model performance is written to a gold table on every run and surfaced on the
report's Intelligence page. A model whose held-out metric is visible to its
users is a model that gets retired when it stops working.
