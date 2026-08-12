# Five-minute interview walkthrough

## 0:00-0:40 | Frame the problem

"I treated this as a decision product rather than a chart exercise. The model keeps sales, redemptions and support tickets at their natural grains, uses one governed merchant dimension and a date table that spans every fact date, and publishes the result through a reproducible Fabric medallion pipeline."

Show the model diagram or Appendix D pipeline evidence.

## 0:40-1:40 | Executive Overview

Lead with the decision, not the totals:

"The support queue is effectively working in reverse priority order. Critical tickets have a 12-hour target but average 52.7 hours and breach 98.3% of the time; Low tickets have a 48-hour target but average 11.3 hours. The first action is to determine whether triage labels or SLA targets are wrong."

Then point out that the portfolio remains diversified and identify the Eastern Cape decline as a merchant-composition issue rather than a broad regional collapse.

## 1:40-2:40 | Merchant Analysis

Select **Umhlanga Value Mart**:

"July sales fell 44.7%, driven by transaction volume rather than basket size. Tickets rose from 3 to 37 and redemption performance also weakened. That combination suggests customers could not transact, so I would start an operational recovery plan rather than a marketing campaign."

Briefly contrast **Kudu Digital Kiosk**, whose May growth step held, and **Durban Cash Hub**, whose support spike has not yet damaged sales.

## 2:40-3:30 | Operational View

Show backlog ownership and SLA performance:

"A single open-ticket number hides two queues: work awaiting us and work awaiting the merchant. I separated ownership so the team can act on the controllable backlog. Ticket volume is a useful event-level warning; average resolution time is not a reliable merchant-performance predictor in this dataset."

## 3:30-4:15 | Intelligence Lab

"The anomaly model recovered all four planted patterns without being given their identities. I kept the models honest: delayed-redemption prediction is near chance, which supports treating Western Cape Bill Payment in April as an isolated incident requiring root-cause analysis rather than automated scoring."

## 4:15-5:00 | Fabric and close

Show Appendix D or the Fabric workspace:

"The source files arrive as a ZIP from a PC, are retained and unpacked in OneLake, written to Bronze with lineage, conformed in Silver, published as Gold facts and dimensions, and checked by a final population gate. The completed pipeline and endpoint counts are included in the report."

Close with:

"The immediate recommendation is to fix support triage, recover Umhlanga Value Mart, and investigate the April settlement incident. The engineering makes those decisions repeatable; it is not the headline by itself."
