"""
08_build_dashboard.py
=====================
Generates report/dashboard.html — a self-contained, interactive replica of the four Power BI
report pages, plus a build walkthrough page for use during the interview.

Why an HTML replica exists at all: the .pbix cannot be opened or run by a reviewer without
Power BI Desktop and a Fabric workspace. This renders the exact same numbers, from the same
gold layer, in something anyone can open. It is a demonstration of the report design and a
proof that the figures are real — not a substitute for the Power BI deliverable.

Everything is inlined (no CDN, no external assets) so the file works offline.
"""
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, str(Path(__file__).parent))
from _table_registry import (TABLES as REG, TIERS, SUMMARY as REG_SUMMARY,
                             COUNTER_ARGUMENT as REG_COUNTER, counts as _tc, TIER_ORDER)
TIER_COUNTS = _tc()

ROOT = Path(__file__).resolve().parents[1]
ANA = ROOT / "data" / "analytics"
ML = ROOT / "data" / "ml"
OUT = ROOT / "report" / "dashboard.html"
OUT.parent.mkdir(parents=True, exist_ok=True)

summary = json.load(open(ROOT / "docs" / "analytics_summary.json"))
mlsum = json.load(open(ROOT / "docs" / "ml_summary.json"))
recon = json.load(open(ROOT / "docs" / "reconciliation.json"))
K = summary["exec_kpis"]
BA = summary["business_answers"]
SZ = summary["size_confounder"]

L = lambda n: pd.read_parquet(ANA / f"{n}.parquet")
M = lambda n: pd.read_parquet(ML / f"{n}.parquet")

trend = L("kpi_monthly_trend")
region = L("kpi_region_performance")
region_m = L("kpi_region_month")
vtype = L("kpi_voucher_type")
vtype_m = L("kpi_voucher_type_month")
score = L("kpi_merchant_scorecard")
tkt_type = L("kpi_ticket_type")
priority = L("kpi_priority")
tkt_month = L("kpi_ticket_month")
alerts = L("kpi_alerts")
events = L("kpi_ticket_spike_events")
friction = L("kpi_friction_quartiles")
daily = L("kpi_merchant_daily")
anom = M("ml_anomalies")
fcast = M("ml_sales_forecast")
segprof = M("ml_segment_profile")
deciles = M("ml_redemption_risk_deciles")

# Data pushed to the browser as JSON — charts are drawn client-side from these arrays.
DATA = {
    "kpis": K,
    "trend": trend.assign(MonthLabel=pd.to_datetime(trend.MonthStartDate).dt.strftime("%b"))
                  [["YearMonth", "MonthLabel", "SalesValue", "Transactions", "SalesMoM",
                    "AvgBasketValue", "RedemptionRate", "AvgDaysToRedeem", "Tickets",
                    "AvgResolutionHours", "SLABreachRate", "SalesTarget"]]
                  .replace({np.nan: None}).to_dict("records"),
    "region": region.replace({np.nan: None}).to_dict("records"),
    "regionMonth": region_m[["Region", "YearMonth", "SalesValue", "Transactions"]]
                   .replace({np.nan: None}).to_dict("records"),
    "voucherType": vtype.replace({np.nan: None}).to_dict("records"),
    "voucherTypeMonth": vtype_m.replace({np.nan: None}).to_dict("records"),
    "merchants": score.replace({np.nan: None}).to_dict("records"),
    "ticketType": tkt_type.replace({np.nan: None}).to_dict("records"),
    "priority": priority.replace({np.nan: None}).to_dict("records"),
    "ticketMonth": tkt_month.replace({np.nan: None}).to_dict("records"),
    "alerts": alerts.replace({np.nan: None}).to_dict("records"),
    "events": events.replace({np.nan: None}).to_dict("records"),
    "friction": friction.astype({"FrictionQuartile": str}).replace({np.nan: None}).to_dict("records"),
    "anomalies": anom.replace({np.nan: None}).to_dict("records"),
    "forecast": fcast.assign(Date=fcast.Date.astype(str)).replace({np.nan: None}).to_dict("records"),
    "segments": segprof.replace({np.nan: None}).to_dict("records"),
    "deciles": deciles.replace({np.nan: None}).to_dict("records"),
    "dailyTotal": (daily.groupby("Date", as_index=False).SalesValue.sum()
                   .assign(Date=lambda d: d.Date.astype(str)).to_dict("records")),
    "backlog": L("kpi_backlog_ownership").replace({np.nan: None}).to_dict("records"),
    "backlogSplit": summary["backlog_ownership"],
    "crmCheck": L("kpi_crm_flag_check").replace({np.nan: None}).to_dict("records"),
    "crmFlag": summary["crm_flag_check"],
    # SLA achievability comes from dim_priority — the diagnostic lives in the model, so the
    # dashboard reads it rather than recomputing it and risking a second definition.
    # SA province geometry + per-province sales. Only 5 of 9 provinces carry merchants; the
    # other 4 are drawn as "no cover" rather than omitted, because an absent province reads
    # as zero sales when it actually means no footprint at all.
    "geo": json.load(open(ROOT / "data" / "reference" / "za_provinces_simplified.json")),
    # Table justification, straight from the shared registry so the dashboard, the ERD, the
    # dbt docs, the Word report and the Excel pack all give the same answer.
    "registry": {
        "summary": REG_SUMMARY,
        "counter": REG_COUNTER,
        "tiers": [{"key": t, "label": TIERS[t][0], "colour": TIERS[t][1],
                   "blurb": TIERS[t][2], "count": TIER_COUNTS[t],
                   "tables": sorted(k for k, v in REG.items() if v["tier"] == t)}
                  for t in TIER_ORDER],
        "tables": [{"name": k, "tier": TIERS[v["tier"]][0], "colour": TIERS[v["tier"]][1],
                    "rows": v["rows"], "why": v["why"], "detail": v["detail"]}
                   for k, v in sorted(REG.items(),
                                      key=lambda kv: (TIER_ORDER
                                                      .index(kv[1]["tier"]), kv[0]))],
    },
    "priorityDiag": duckdb.connect(str(ROOT / "data" / "mvi.duckdb")).execute("""
        SELECT priority AS "Priority", target_sla_hours AS "TargetSLAHours",
               observed_median_hours AS "ObservedMedianHours",
               observed_p90_hours AS "ObservedP90Hours",
               sla_is_achievable AS "SlaIsAchievable",
               sla_for_90pct_compliance AS "SlaFor90pctCompliance"
        FROM main_marts.dim_priority ORDER BY priority_sort""").df().to_dict("records"),
    "ml": mlsum,
    "recon": recon,
    "answers": BA,
    "confounder": SZ,
    "concentration": summary["revenue_concentration"],
    "targetCal": summary["target_calibration"],
}

payload = json.dumps(DATA, default=str, separators=(",", ":"))

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Merchant Sales &amp; Voucher Intelligence</title>
<style>
:root{
  --navy:#12305B; --navy-2:#1B4079; --teal:#0E8B8B; --teal-2:#14B0AC; --amber:#E8A317;
  --red:#C0392B; --green:#1E8449; --purple:#7B4B94; --pink:#D6336C;
  --ink:#12203A; --muted:#5A6672; --line:#DCE4EF; --bg:#F2F5FA; --card:#FFFFFF;
  --shadow:0 2px 4px rgba(18,48,91,.06),0 8px 24px rgba(18,48,91,.08);
  --shadow-lg:0 4px 12px rgba(18,48,91,.10),0 20px 48px rgba(18,48,91,.12);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI",-apple-system,BlinkMacSystemFont,Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--ink);font-size:14px;line-height:1.55;
  -webkit-font-smoothing:antialiased}

/* ---------- header ----------
   Only the NAV is sticky, not the whole masthead. Previously the entire ~330px header was
   position:sticky, which permanently ate 43% of a 768px laptop viewport and left every card
   scrolling underneath it — the "cut off tiles" problem. The title block now scrolls away
   normally and a compact 52px nav bar pins to the top.                                    */
header{background:linear-gradient(135deg,var(--navy) 0%,var(--navy-2) 55%,var(--teal) 140%);
  color:#fff;padding:26px 34px 0;box-shadow:var(--shadow-lg);position:relative;z-index:100}
.hrow{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;flex-wrap:wrap}
h1{font-size:25px;font-weight:600;letter-spacing:-.3px}
.sub{font-size:12.5px;opacity:.82;margin-top:5px}
.badges{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
.badge{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.24);
  padding:4px 11px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap;
  backdrop-filter:blur(4px)}
.badge.ok{background:rgba(30,132,73,.34);border-color:rgba(120,220,160,.5)}
nav{display:flex;gap:2px;margin-top:22px;flex-wrap:wrap;position:sticky;top:0;z-index:120;
  background:linear-gradient(135deg,var(--navy) 0%,var(--navy-2) 70%);
  margin-left:-34px;margin-right:-34px;padding:0 34px;
  box-shadow:0 3px 14px rgba(0,0,0,.22)}
nav button{background:transparent;border:0;border-bottom:3px solid transparent;color:rgba(255,255,255,.72);
  padding:11px 17px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;
  border-radius:6px 6px 0 0;transition:all .16s}
nav button:hover{color:#fff;background:rgba(255,255,255,.09)}
nav button.on{color:#fff;border-bottom-color:var(--amber);background:rgba(255,255,255,.13)}

/* ---------- layout ---------- */
main{padding:24px 34px 60px;max-width:1600px;margin:0 auto}
.page{display:none} .page.on{display:block;animation:fade .28s ease}
@keyframes fade{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
.grid{display:grid;gap:16px;margin-bottom:16px}
.g6{grid-template-columns:repeat(6,1fr)}
.g5{grid-template-columns:repeat(5,1fr)} .g4{grid-template-columns:repeat(4,1fr)}
.g3{grid-template-columns:repeat(3,1fr)} .g2{grid-template-columns:repeat(2,1fr)}
.g23{grid-template-columns:2fr 1fr} .g32{grid-template-columns:1fr 2fr}
@media(max-width:1450px){.g6{grid-template-columns:repeat(3,1fr)}}
@media(max-width:1250px){.g6,.g5,.g4{grid-template-columns:repeat(2,1fr)}
  .g3,.g2,.g23,.g32{grid-template-columns:1fr}}

/* ---------- cards ---------- */
.card{background:var(--card);border-radius:11px;box-shadow:var(--shadow);
  border:1px solid var(--line);overflow:hidden}
.card-h{padding:14px 18px 0;font-size:13.5px;font-weight:700;color:var(--navy);
  display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.card-h .hint{font-size:11px;font-weight:500;color:var(--muted)}
.card-b{padding:14px 18px 18px}

/* Fixed height so a long sub-line can never push a tile taller than its neighbours and
   leave the row ragged — the "cut off / uneven tiles" problem. */
.kpi{border-radius:11px;padding:14px 18px;color:#fff;position:relative;overflow:hidden;
  box-shadow:var(--shadow);height:104px;display:flex;flex-direction:column;
  justify-content:center}
.kpi::after{content:"";position:absolute;right:-26px;top:-26px;width:104px;height:104px;
  border-radius:50%;background:rgba(255,255,255,.09)}
.kpi.navy{background:linear-gradient(135deg,var(--navy),var(--navy-2))}
.kpi.teal{background:linear-gradient(135deg,var(--teal),var(--teal-2))}
.kpi.amber{background:linear-gradient(135deg,#C88410,var(--amber));color:#2E2200}
.kpi.red{background:linear-gradient(135deg,#96281B,var(--red))}
.kpi.purple{background:linear-gradient(135deg,#5D3872,var(--purple))}
.kpi .lbl{font-size:10.5px;text-transform:uppercase;letter-spacing:.8px;opacity:.9;
  font-weight:700}
.kpi .val{font-size:27px;font-weight:700;margin:5px 0 2px;letter-spacing:-.6px;
  font-variant-numeric:tabular-nums}
.kpi .sub{font-size:11px;opacity:.86;position:relative;z-index:1}

/* ---------- tables ---------- */
.tbl-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th{background:var(--navy);color:#fff;padding:9px 11px;text-align:left;font-weight:600;
  font-size:11px;text-transform:uppercase;letter-spacing:.4px;position:sticky;top:0;
  white-space:nowrap}
th.r,td.r{text-align:right;font-variant-numeric:tabular-nums}
td{padding:8px 11px;border-bottom:1px solid var(--line);white-space:nowrap}
tbody tr:nth-child(even){background:#FAFCFE}
tbody tr:hover{background:#EAF3FB}
td.name{font-weight:600;white-space:normal;min-width:150px}
.pill{display:inline-block;padding:2px 9px;border-radius:11px;font-size:10.5px;
  font-weight:700;white-space:nowrap}
.p-crit{background:#FBE0DE;color:#922B21} .p-watch{background:#FDEBD0;color:#9C640C}
.p-ok{background:#D5F0E0;color:#186A3B}   .p-star{background:#CFF0EC;color:#0E6E63}
.p-info{background:#E3ECF7;color:#1B4079} .p-purple{background:#EDE1F3;color:#5D3872}
.up{color:var(--green);font-weight:700} .down{color:var(--red);font-weight:700}
.bar{height:7px;border-radius:4px;background:#E7EDF5;overflow:hidden;min-width:56px;
  display:inline-block;vertical-align:middle}
.bar>i{display:block;height:100%;border-radius:4px}

/* ---------- charts ---------- */
.chart{width:100%;display:block}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:11.5px;
  color:var(--muted)}
.legend span{display:flex;align-items:center;gap:6px}
.dot{width:11px;height:11px;border-radius:3px;flex:none}

/* ---------- callouts ---------- */
.note{font-size:12.5px;color:var(--muted);line-height:1.62;margin-top:11px}
.callout{border-left:4px solid var(--teal);background:#F0F9F9;padding:13px 16px;
  border-radius:0 8px 8px 0;font-size:13px;line-height:1.62;margin-top:14px}
.callout.warn{border-left-color:var(--amber);background:#FEF8EC}
.callout.crit{border-left-color:var(--red);background:#FDF0EE}
.callout.good{border-left-color:var(--green);background:#EFF9F2}
.callout b{color:var(--navy)}
.qa{background:var(--card);border-radius:11px;box-shadow:var(--shadow);
  border:1px solid var(--line);margin-bottom:15px;overflow:hidden}
.qa-q{background:linear-gradient(135deg,var(--navy),var(--navy-2));color:#fff;
  padding:14px 19px;font-weight:600;font-size:14.5px;display:flex;gap:13px;align-items:center}
.qa-q .n{background:var(--amber);color:#2E2200;width:29px;height:29px;border-radius:50%;
  display:grid;place-items:center;font-size:12.5px;font-weight:800;flex:none}
.qa-a{padding:16px 19px;font-size:13.2px;line-height:1.68}
.qa-a b{color:var(--navy)} .qa-a ul{margin:9px 0 9px 20px} .qa-a li{margin:5px 0}

/* ---------- walkthrough ---------- */
.step{display:flex;gap:18px;margin-bottom:15px;background:var(--card);border-radius:11px;
  box-shadow:var(--shadow);border:1px solid var(--line);overflow:hidden}
.step-n{background:linear-gradient(160deg,var(--navy),var(--teal));color:#fff;width:66px;
  flex:none;display:flex;flex-direction:column;align-items:center;justify-content:center;
  font-weight:800;font-size:23px;gap:2px}
.step-n small{font-size:9px;font-weight:600;opacity:.8;letter-spacing:.6px}
.step-b{padding:15px 19px 16px;flex:1;min-width:0}
.step-b h4{color:var(--navy);font-size:14.5px;margin-bottom:6px}
.step-b p{font-size:12.8px;color:var(--muted);line-height:1.62}
.step-b .tags{margin-top:9px;display:flex;gap:6px;flex-wrap:wrap}
.tag{background:#EAF1FA;color:var(--navy-2);padding:2.5px 9px;border-radius:5px;
  font-size:10.5px;font-weight:700;font-family:Consolas,Monaco,monospace}
code{background:#F0F4FA;padding:1.5px 6px;border-radius:4px;font-size:11.8px;
  font-family:Consolas,Monaco,monospace;color:var(--navy-2)}
.arch{width:100%;height:auto}
.tbl-note{font-size:11px;color:var(--muted);margin-top:9px;font-style:italic}
.sw{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
.sw div{flex:1;min-width:96px;border-radius:8px;padding:9px 11px;color:#fff;font-size:10.5px;
  font-weight:700}
footer{text-align:center;padding:26px;color:var(--muted);font-size:11.5px;
  border-top:1px solid var(--line);margin-top:26px}

/* ---------- filter chips ----------
   Chips rather than dropdowns: every option is visible without a click, which matters when
   the point is to show WHICH slice is active. Filtering recomputes the headline KPIs from
   the merchant rows, so the numbers stay internally consistent with the tables below. */
#filterbar{max-width:1600px;margin:0 auto;padding:14px 34px 0}
.fbar{background:var(--card);border:1px solid var(--line);border-radius:11px;
  box-shadow:var(--shadow);padding:11px 15px;display:flex;gap:18px;align-items:center;
  flex-wrap:wrap}
.fgrp{display:flex;gap:7px;align-items:center;flex-wrap:wrap}
.flab{font-size:10px;font-weight:800;letter-spacing:.7px;color:var(--muted);
  text-transform:uppercase;margin-right:2px}
.chip{border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:16px;
  padding:4px 12px;font-size:11.5px;font-weight:600;cursor:pointer;font-family:inherit;
  transition:all .14s}
.chip:hover{border-color:var(--teal)}
.chip.on{background:var(--teal);border-color:var(--teal);color:#fff}
.chip.reset{background:transparent;border-style:dashed;color:var(--muted);font-weight:500}
.fcount{margin-left:auto;font-size:11.5px;color:var(--muted);white-space:nowrap}
.badge.btn{cursor:pointer;font-family:inherit}
.badge.btn:hover{background:rgba(255,255,255,.26)}

/* ---------- dark mode ---------- */
body.dark{--ink:#E8EEF6;--muted:#9FB0C4;--line:#2A3646;--bg:#0E141C;--card:#18212C;
  --shadow:0 2px 4px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.4);
  --shadow-lg:0 4px 12px rgba(0,0,0,.4),0 20px 48px rgba(0,0,0,.5)}
body.dark .chip{background:#18212C;color:#E8EEF6}
body.dark .chip.on{background:var(--teal2);border-color:var(--teal2);color:#08131A}
body.dark table th{background:#0B1F3D}
body.dark tbody tr:nth-child(even){background:#1C2733}
body.dark tbody tr:hover{background:#22303F}
body.dark .callout{background:#14262B}
body.dark .callout.warn{background:#2A2213}
body.dark .callout.crit{background:#2B1715}
body.dark .callout.good{background:#132A1D}
body.dark .qa-a,body.dark .step-b{background:var(--card)}
body.dark .tag{background:#22303F;color:#9FD8D6}
body.dark code{background:#22303F;color:#9FD8D6}
body.dark .bar{background:#2A3646}
body.dark svg text{fill:#C8D6E4}
</style>
</head>
<body>

<header>
  <div class="hrow">
    <div>
      <h1>Merchant Sales &amp; Voucher Intelligence</h1>
      <div class="sub">BI Developer Second-Round Practical Task &nbsp;·&nbsp; Microsoft Fabric ·
        Power BI · dbt · Python ML &nbsp;·&nbsp; 1 Jan – 31 Jul 2026</div>
    </div>
    <div class="badges">
      <button id="themeBtn" class="badge btn" title="Toggle dark mode">&#9789; Dark mode</button>
      <span class="badge ok">14/14 warehouse tests</span>
      <span class="badge ok">69/69 dbt tests</span>
      <span class="badge ok">27/28 reconciliation</span>
      <span class="badge">25 merchants</span>
      <span class="badge">120,969 vouchers</span>
      <span class="badge">5 ML models</span>
    </div>
  </div>
  <nav>
    <button class="on" data-p="exec">Executive Overview</button>
    <button data-p="merchant">Merchant Analysis</button>
    <button data-p="geo">Geographic</button>
    <button data-p="ops">Operational View</button>
    <button data-p="ai">AI &amp; Anomalies</button>
    <button data-p="insights">Insights &amp; Answers</button>
    <button data-p="build">How It Was Built</button>
  </nav>
</header>

<main>
  <div id="filterbar"></div>
  <div class="page on" id="p-exec"></div>
  <div class="page" id="p-merchant"></div>
  <div class="page" id="p-geo"></div>
  <div class="page" id="p-ops"></div>
  <div class="page" id="p-ai"></div>
  <div class="page" id="p-insights"></div>
  <div class="page" id="p-build"></div>
</main>

<footer>
  Generated from the gold layer · every figure reconciled between an independent Python and
  dbt implementation · Anthony Apollis · August 2026
</footer>

<script>
const D = __PAYLOAD__;

/* ---------------- formatting helpers ---------------- */
const R  = v => v==null? '–' : 'R' + Math.round(v).toLocaleString('en-ZA');
const Rm = v => v==null? '–' : 'R' + (v/1e6).toFixed(1) + 'm';
const Rk = v => v==null? '–' : 'R' + Math.round(v/1e3).toLocaleString('en-ZA') + 'k';
const N  = v => v==null? '–' : Math.round(v).toLocaleString('en-ZA');
const P1 = v => v==null? '–' : (v*100).toFixed(1) + '%';
const P2 = v => v==null? '–' : (v*100).toFixed(2) + '%';
const PS = v => v==null? '–' : (v>=0?'+':'') + (v*100).toFixed(1) + '%';
const D2 = v => v==null? '–' : v.toFixed(2);
const D1 = v => v==null? '–' : v.toFixed(1);
const cls= v => v==null? '' : (v>=0?'up':'down');
const esc= s => String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

const C = {navy:'#12305B',navy2:'#1B4079',teal:'#0E8B8B',teal2:'#14B0AC',amber:'#E8A317',
           red:'#C0392B',green:'#1E8449',purple:'#7B4B94',pink:'#D6336C',line:'#DCE4EF',
           muted:'#5A6672'};
const SERIES = [C.navy, C.teal, C.amber, C.purple, C.red, C.pink, C.green];

function kpi(theme,lbl,val,sub){
  return `<div class="kpi ${theme}"><div class="lbl">${lbl}</div>
    <div class="val">${val}</div><div class="sub">${sub}</div></div>`;
}
function card(title,hint,body,cls2){
  return `<div class="card ${cls2||''}"><div class="card-h"><span>${title}</span>
    ${hint?`<span class="hint">${hint}</span>`:''}</div><div class="card-b">${body}</div></div>`;
}
function band(b){
  const m={'Critical':'p-crit','Watch':'p-watch','Healthy':'p-ok','Star':'p-star'};
  return `<span class="pill ${m[b]||'p-info'}">${b}</span>`;
}

/* ---------------- SVG chart primitives ----------------
   Charts are hand-drawn SVG rather than a charting library: the file must be fully
   self-contained and open offline with no CDN, and these are simple enough that a
   library would be more weight than value.                                        */

function svgFrame(w,h,pad){
  return {w,h,pad,inner:{w:w-pad.l-pad.r,h:h-pad.t-pad.b}};
}
function yTicks(min,max,n){
  const step=(max-min)/n, out=[];
  for(let i=0;i<=n;i++) out.push(min+step*i);
  return out;
}
function gridY(F,min,max,fmt,n){
  n=n||4;
  return yTicks(min,max,n).map(v=>{
    const y=F.pad.t+F.inner.h-((v-min)/(max-min))*F.inner.h;
    return `<line x1="${F.pad.l}" y1="${y}" x2="${F.pad.l+F.inner.w}" y2="${y}"
              stroke="${C.line}" stroke-width="1"/>
            <text x="${F.pad.l-8}" y="${y+4}" text-anchor="end" font-size="10.5"
              fill="${C.muted}">${fmt(v)}</text>`;
  }).join('');
}

/* Grouped column + line combo */
function comboChart(rows, xKey, barKey, lineKey, fmtBar, fmtLine, barLabel, lineLabel){
  const F=svgFrame(760,300,{l:64,r:60,t:16,b:40});
  const bMax=Math.max(...rows.map(r=>r[barKey]))*1.12;
  const lVals=rows.map(r=>r[lineKey]);
  const lMin=Math.min(...lVals)*0.9, lMax=Math.max(...lVals)*1.06;
  const bw=F.inner.w/rows.length;
  let s=`<svg class="chart" viewBox="0 0 ${F.w} ${F.h}">`;
  s+=gridY(F,0,bMax,fmtBar);
  rows.forEach((r,i)=>{
    const h=(r[barKey]/bMax)*F.inner.h;
    const x=F.pad.l+i*bw+bw*0.22, y=F.pad.t+F.inner.h-h;
    s+=`<rect x="${x}" y="${y}" width="${bw*0.56}" height="${h}" rx="3" fill="${C.teal}"
          opacity=".92"><title>${r[xKey]}: ${fmtBar(r[barKey])}</title></rect>`;
    s+=`<text x="${F.pad.l+i*bw+bw/2}" y="${F.pad.t+F.inner.h+18}" text-anchor="middle"
          font-size="11" fill="${C.muted}">${r[xKey]}</text>`;
  });
  const pts=rows.map((r,i)=>{
    const x=F.pad.l+i*bw+bw/2;
    const y=F.pad.t+F.inner.h-((r[lineKey]-lMin)/(lMax-lMin))*F.inner.h;
    return [x,y];
  });
  s+=`<polyline points="${pts.map(p=>p.join(',')).join(' ')}" fill="none"
        stroke="${C.amber}" stroke-width="2.6" stroke-linejoin="round"/>`;
  pts.forEach((p,i)=>{
    s+=`<circle cx="${p[0]}" cy="${p[1]}" r="4.6" fill="#fff" stroke="${C.amber}"
          stroke-width="2.6"><title>${rows[i][xKey]}: ${fmtLine(rows[i][lineKey])}</title></circle>`;
  });
  yTicks(lMin,lMax,4).forEach(v=>{
    const y=F.pad.t+F.inner.h-((v-lMin)/(lMax-lMin))*F.inner.h;
    s+=`<text x="${F.pad.l+F.inner.w+8}" y="${y+4}" font-size="10.5"
          fill="${C.amber}">${fmtLine(v)}</text>`;
  });
  s+='</svg>';
  s+=`<div class="legend"><span><i class="dot" style="background:${C.teal}"></i>${barLabel}</span>
      <span><i class="dot" style="background:${C.amber}"></i>${lineLabel}</span></div>`;
  return s;
}

/* Multi-series line chart */
function lineChart(series, labels, fmt, opts){
  opts=opts||{};
  const F=svgFrame(opts.w||760,opts.h||300,{l:60,r:16,t:16,b:40});
  const all=series.flatMap(s=>s.values);
  let min=opts.min!=null?opts.min:Math.min(...all)*0.96;
  let max=opts.max!=null?opts.max:Math.max(...all)*1.04;
  const n=labels.length;
  const X=i=> F.pad.l + (n===1?F.inner.w/2 : (i/(n-1))*F.inner.w);
  const Y=v=> F.pad.t + F.inner.h - ((v-min)/(max-min))*F.inner.h;
  let s=`<svg class="chart" viewBox="0 0 ${F.w} ${F.h}">`;
  s+=gridY(F,min,max,fmt);
  labels.forEach((l,i)=>{
    s+=`<text x="${X(i)}" y="${F.pad.t+F.inner.h+18}" text-anchor="middle" font-size="11"
          fill="${C.muted}">${l}</text>`;
  });
  series.forEach((se,k)=>{
    const col=se.color||SERIES[k%SERIES.length];
    const pts=se.values.map((v,i)=>[X(i),Y(v)]);
    s+=`<polyline points="${pts.map(p=>p.join(',')).join(' ')}" fill="none" stroke="${col}"
          stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>`;
    pts.forEach((p,i)=>{
      s+=`<circle cx="${p[0]}" cy="${p[1]}" r="3.8" fill="#fff" stroke="${col}"
            stroke-width="2.2"><title>${se.name} ${labels[i]}: ${fmt(se.values[i])}</title></circle>`;
    });
  });
  s+='</svg>';
  s+='<div class="legend">'+series.map((se,k)=>
      `<span><i class="dot" style="background:${se.color||SERIES[k%SERIES.length]}"></i>${se.name}</span>`
     ).join('')+'</div>';
  return s;
}

/* Horizontal bar chart */
function hBar(rows, labelKey, valKey, fmt, color, opts){
  opts=opts||{};
  const max=Math.max(...rows.map(r=>r[valKey]));
  const min=opts.zeroBase===false? Math.min(...rows.map(r=>r[valKey]))*0.92 : 0;
  return `<div style="display:flex;flex-direction:column;gap:9px">` + rows.map((r,i)=>{
    const pct=((r[valKey]-min)/(max-min))*100;
    const col = typeof color==='function'? color(r,i) : (color||SERIES[i%SERIES.length]);
    return `<div style="display:flex;align-items:center;gap:11px">
      <div style="width:${opts.labelW||132}px;font-size:12px;font-weight:600;flex:none;
        overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
        title="${esc(r[labelKey])}">${esc(r[labelKey])}</div>
      <div style="flex:1;background:#EEF2F8;border-radius:5px;height:22px;position:relative">
        <div style="width:${Math.max(pct,1.5)}%;background:${col};height:100%;border-radius:5px;
          transition:width .5s"></div></div>
      <div style="width:${opts.valW||82}px;text-align:right;font-size:12px;font-weight:700;
        font-variant-numeric:tabular-nums;flex:none">${fmt(r[valKey])}</div></div>`;
  }).join('') + `</div>`;
}

/* Donut chart */
function donut(rows, labelKey, valKey, fmt){
  const total=rows.reduce((a,r)=>a+r[valKey],0);
  const cx=110,cy=110,rO=96,rI=57;
  let ang=-Math.PI/2, s=`<svg class="chart" viewBox="0 0 460 224" style="max-height:230px">`;
  rows.forEach((r,i)=>{
    const frac=r[valKey]/total, a2=ang+frac*Math.PI*2;
    const big=frac>0.5?1:0;
    const p=(rad,a)=>[cx+rad*Math.cos(a),cy+rad*Math.sin(a)];
    const [x1,y1]=p(rO,ang),[x2,y2]=p(rO,a2),[x3,y3]=p(rI,a2),[x4,y4]=p(rI,ang);
    s+=`<path d="M${x1},${y1} A${rO},${rO} 0 ${big},1 ${x2},${y2} L${x3},${y3}
          A${rI},${rI} 0 ${big},0 ${x4},${y4} Z" fill="${SERIES[i%SERIES.length]}"
          opacity=".93"><title>${esc(r[labelKey])}: ${fmt(r[valKey])}</title></path>`;
    ang=a2;
  });
  s+=`<text x="${cx}" y="${cy-4}" text-anchor="middle" font-size="19" font-weight="700"
        fill="${C.navy}">${fmt(total)}</text>
      <text x="${cx}" y="${cy+15}" text-anchor="middle" font-size="10.5"
        fill="${C.muted}">TOTAL</text>`;
  rows.forEach((r,i)=>{
    const y=32+i*26;
    s+=`<rect x="236" y="${y-10}" width="12" height="12" rx="3" fill="${SERIES[i%SERIES.length]}"/>
        <text x="256" y="${y}" font-size="12" fill="${C.navy}" font-weight="600">${esc(r[labelKey])}</text>
        <text x="452" y="${y}" font-size="11.5" fill="${C.muted}" text-anchor="end">
          ${(r[valKey]/total*100).toFixed(1)}%</text>`;
  });
  return s+'</svg>';
}

/* Stacked column chart */
function stacked(labels, series, fmt){
  const F=svgFrame(700,290,{l:52,r:16,t:16,b:40});
  const totals=labels.map((_,i)=>series.reduce((a,s)=>a+s.values[i],0));
  const max=Math.max(...totals)*1.1;
  const bw=F.inner.w/labels.length;
  let s=`<svg class="chart" viewBox="0 0 ${F.w} ${F.h}">`;
  s+=gridY(F,0,max,fmt);
  labels.forEach((l,i)=>{
    let acc=0;
    series.forEach((se,k)=>{
      const h=(se.values[i]/max)*F.inner.h;
      const y=F.pad.t+F.inner.h-h-acc;
      s+=`<rect x="${F.pad.l+i*bw+bw*0.2}" y="${y}" width="${bw*0.6}" height="${h}"
            fill="${se.color||SERIES[k%SERIES.length]}" opacity=".93">
            <title>${l} ${se.name}: ${fmt(se.values[i])}</title></rect>`;
      acc+=h;
    });
    s+=`<text x="${F.pad.l+i*bw+bw/2}" y="${F.pad.t+F.inner.h+18}" text-anchor="middle"
          font-size="11" fill="${C.muted}">${l}</text>`;
  });
  s+='</svg>';
  s+='<div class="legend">'+series.map((se,k)=>
      `<span><i class="dot" style="background:${se.color||SERIES[k%SERIES.length]}"></i>${se.name}</span>`
     ).join('')+'</div>';
  return s;
}

/* Forecast chart with confidence band */
function forecastChart(hist, fc){
  const F=svgFrame(760,300,{l:62,r:16,t:16,b:40});
  const all=[...hist.map(d=>d.SalesValue), ...fc.map(d=>d.Upper95), ...fc.map(d=>d.Lower95)];
  const min=Math.min(...all)*0.92, max=Math.max(...all)*1.04;
  const n=hist.length+fc.length;
  const X=i=>F.pad.l+(i/(n-1))*F.inner.w;
  const Y=v=>F.pad.t+F.inner.h-((v-min)/(max-min))*F.inner.h;
  let s=`<svg class="chart" viewBox="0 0 ${F.w} ${F.h}">`;
  s+=gridY(F,min,max,Rk);
  const off=hist.length;
  // 95% band
  const up=fc.map((d,i)=>[X(off+i),Y(d.Upper95)]);
  const lo=fc.map((d,i)=>[X(off+i),Y(d.Lower95)]).reverse();
  s+=`<polygon points="${[...up,...lo].map(p=>p.join(',')).join(' ')}" fill="${C.amber}"
        opacity=".14"/>`;
  const up8=fc.map((d,i)=>[X(off+i),Y(d.Upper80)]);
  const lo8=fc.map((d,i)=>[X(off+i),Y(d.Lower80)]).reverse();
  s+=`<polygon points="${[...up8,...lo8].map(p=>p.join(',')).join(' ')}" fill="${C.amber}"
        opacity=".22"/>`;
  s+=`<polyline points="${hist.map((d,i)=>[X(i),Y(d.SalesValue)].join(',')).join(' ')}"
        fill="none" stroke="${C.navy}" stroke-width="1.7" opacity=".85"/>`;
  s+=`<polyline points="${fc.map((d,i)=>[X(off+i),Y(d.ForecastSalesValue)].join(',')).join(' ')}"
        fill="none" stroke="${C.amber}" stroke-width="2.6" stroke-dasharray="6 3"/>`;
  s+=`<line x1="${X(off)}" y1="${F.pad.t}" x2="${X(off)}" y2="${F.pad.t+F.inner.h}"
        stroke="${C.red}" stroke-width="1.4" stroke-dasharray="4 3"/>
      <text x="${X(off)+6}" y="${F.pad.t+13}" font-size="10.5" fill="${C.red}"
        font-weight="700">forecast starts</text>`;
  s+=`<text x="${F.pad.l}" y="${F.pad.t+F.inner.h+18}" font-size="10.5" fill="${C.muted}">
        ${hist[0].Date}</text>
      <text x="${F.pad.l+F.inner.w}" y="${F.pad.t+F.inner.h+18}" text-anchor="end"
        font-size="10.5" fill="${C.muted}">${fc[fc.length-1].Date}</text>`;
  s+='</svg>';
  s+=`<div class="legend"><span><i class="dot" style="background:${C.navy}"></i>Actual daily sales</span>
      <span><i class="dot" style="background:${C.amber}"></i>Holt-Winters forecast</span>
      <span><i class="dot" style="background:${C.amber};opacity:.3"></i>80% / 95% interval</span></div>`;
  return s;
}

/* SA province choropleth — FIXED 660x560 viewBox, equirectangular projection fitted to the
   file's own bbox. Fixed dimensions mean the map never reflows or collapses regardless of
   container width; the SVG scales as one unit. */
function choropleth(){
  const g=D.geo, bb=g.bbox;                       // [minLon, minLat, maxLon, maxLat]
  const W=660,H=560,PAD=26;
  const lon0=bb[0],lat0=bb[1],lon1=bb[2],lat1=bb[3];
  // Correct for longitude convergence at this latitude so SA is not stretched sideways
  const midLat=(lat0+lat1)/2*Math.PI/180;
  const spanX=(lon1-lon0)*Math.cos(midLat), spanY=(lat1-lat0);
  const s=Math.min((W-2*PAD)/spanX,(H-2*PAD)/spanY);
  const offX=(W-spanX*s)/2, offY=(H-spanY*s)/2;
  const X=lon=>offX+(lon-lon0)*Math.cos(midLat)*s;
  const Y=lat=>offY+(lat1-lat)*s;

  const byRegion={}; D.region.forEach(r=>byRegion[r.Region]=r);
  const vals=D.region.map(r=>r.TotalSales);
  const mn=Math.min(...vals), mx=Math.max(...vals);
  const shade=v=>{ const t=(v-mn)/(mx-mn||1);
    // navy ramp: light -> dark as sales rise
    const c=[[214,229,245],[143,181,220],[70,124,183],[26,74,133],[12,48,91]];
    const i=Math.min(Math.floor(t*(c.length-1)),c.length-2), f=t*(c.length-1)-i;
    const mix=(a,b)=>Math.round(a+(b-a)*f);
    return `rgb(${mix(c[i][0],c[i+1][0])},${mix(c[i][1],c[i+1][1])},${mix(c[i][2],c[i+1][2])})`;
  };

  let s2=`<svg class="chart" viewBox="0 0 ${W} ${H}" style="max-height:560px">
    <defs><pattern id="nocover" width="7" height="7" patternTransform="rotate(45)"
      patternUnits="userSpaceOnUse">
      <rect width="7" height="7" fill="#F4F7FB"/>
      <line x1="0" y1="0" x2="0" y2="7" stroke="#C9D6E6" stroke-width="2.2"/></pattern></defs>`;

  g.provinces.forEach(p=>{
    const rec=byRegion[p.name];
    const d=p.rings.map(ring=>'M'+ring.map(pt=>`${X(pt[0]).toFixed(1)},${Y(pt[1]).toFixed(1)}`)
                                       .join('L')+'Z').join(' ');
    const fill=rec? shade(rec.TotalSales) : 'url(#nocover)';
    const tip=rec? `${p.name}\n${Rm(rec.TotalSales)} · ${P1(rec.SalesShare)} of sales\n`
                   +`${N(rec.TotalTransactions)} transactions`
                 : `${p.name}\nNo merchant coverage\n${N(p.areaSqKm)} km2`;
    s2+=`<path d="${d}" fill="${fill}" stroke="#fff" stroke-width="1.3"
           style="cursor:pointer"><title>${tip}</title></path>`;
  });

  // Labels, placed at each province centroid from the file
  g.provinces.forEach(p=>{
    const rec=byRegion[p.name];
    const x=X(p.lon), y=Y(p.lat);
    const dark = rec && (rec.TotalSales-mn)/(mx-mn||1) > 0.55;
    s2+=`<text x="${x}" y="${y-2}" text-anchor="middle" font-size="12" font-weight="800"
           fill="${rec? (dark?'#fff':'#12305B') : '#8899AD'}"
           style="pointer-events:none">${p.code}</text>`;
    s2+=`<text x="${x}" y="${y+13}" text-anchor="middle" font-size="10.5" font-weight="600"
           fill="${rec? (dark?'#D6E5F5':'#3D5877') : '#A6B4C6'}"
           style="pointer-events:none">${rec? Rm(rec.TotalSales) : 'no cover'}</text>`;
  });
  s2+='</svg>';
  s2+=`<div class="legend">
      <span><i class="dot" style="background:rgb(214,229,245)"></i>Low ${Rm(mn)}</span>
      <span><i class="dot" style="background:rgb(70,124,183)"></i>Mid</span>
      <span><i class="dot" style="background:rgb(12,48,91)"></i>High ${Rm(mx)}</span>
      <span><i class="dot" style="background:#E4EAF2;border:1px solid #C9D6E6"></i>No merchant coverage</span>
    </div>`;
  return s2;
}

/* Scatter: friction vs performance, sized by revenue */
function scatter(rows,xk,yk,sk,nk,fx,fy){
  const F=svgFrame(700,320,{l:60,r:20,t:16,b:46});
  const xs=rows.map(r=>r[xk]), ys=rows.map(r=>r[yk]);
  const xmin=0, xmax=Math.max(...xs)*1.08;
  const ymin=Math.min(...ys)*1.15, ymax=Math.max(...ys)*1.1;
  const smax=Math.max(...rows.map(r=>r[sk]));
  const X=v=>F.pad.l+((v-xmin)/(xmax-xmin))*F.inner.w;
  const Y=v=>F.pad.t+F.inner.h-((v-ymin)/(ymax-ymin))*F.inner.h;
  let s=`<svg class="chart" viewBox="0 0 ${F.w} ${F.h}">`;
  s+=gridY(F,ymin,ymax,fy);
  const y0=Y(0);
  s+=`<line x1="${F.pad.l}" y1="${y0}" x2="${F.pad.l+F.inner.w}" y2="${y0}"
        stroke="${C.muted}" stroke-width="1.4" stroke-dasharray="4 3"/>`;
  rows.forEach(r=>{
    const rad=6+Math.sqrt(r[sk]/smax)*17;
    const col=r[yk]<0? C.red : (r[yk]>0.1? C.green : C.teal);
    s+=`<circle cx="${X(r[xk])}" cy="${Y(r[yk])}" r="${rad}" fill="${col}" opacity=".5"
          stroke="${col}" stroke-width="1.6">
          <title>${esc(r[nk])}
${fx(r[xk])} tickets/1k · ${fy(r[yk])} momentum · ${Rm(r[sk])} sales</title></circle>`;
  });
  [0,0.25,0.5,0.75,1].forEach(f=>{
    const v=xmin+(xmax-xmin)*f;
    s+=`<text x="${X(v)}" y="${F.pad.t+F.inner.h+18}" text-anchor="middle" font-size="10.5"
          fill="${C.muted}">${fx(v)}</text>`;
  });
  s+=`<text x="${F.pad.l+F.inner.w/2}" y="${F.h-6}" text-anchor="middle" font-size="11"
        fill="${C.muted}" font-weight="600">Tickets per 1,000 transactions →</text>`;
  return s+'</svg>';
}

/* ================= PAGE 1 — EXECUTIVE OVERVIEW ================= */
function pageExec(){
  const K=kpis(), t=D.trend, last=t[t.length-1];
  // Six tiles: every KPI the brief names for page 1, each on its own tile rather than
  // buried in another tile's sub-line (SLA breach % was previously only a sub-line).
  let h = `<div class="grid g6">
    ${kpi('navy','Total Sales',Rm(K.TotalSales),`${N(K.TotalTransactions)} transactions`)}
    ${kpi('navy','Transactions',N(K.TotalTransactions),
          `avg basket ${R(K.AvgBasketValue)}`)}
    ${kpi('teal','Redemption Rate',P1(K.RedemptionRate),
          `${N(K.VouchersRedeemed)} of ${N(K.VouchersSold)}`)}
    ${kpi('teal','Avg Resolution',D1(K.AvgResolutionHours)+'h','median 16.4h')}
    ${kpi('amber','SLA Breach Rate',P1(K.SLABreachRate),
          `${N(Math.round(K.SLABreachRate*K.TotalTickets))} of ${N(K.TotalTickets)} tickets`)}
    ${kpi('red','Outstanding Liability',Rm(K.OutstandingLiability),'unredeemed value')}
  </div>`;

  h += `<div class="grid g23">`;
  h += card('Monthly sales and transaction volume','Jan – Jul 2026',
        comboChart(t,'MonthLabel','SalesValue','Transactions',Rm,N,
                   'Sales value','Transactions') +
        `<div class="callout good"><b>Sales grew every month except February.</b>
          July closed at ${Rm(last.SalesValue)}, ${PS(last.SalesMoM)} month on month and
          ${PS(t[t.length-1].SalesValue/t[0].SalesValue-1)} above January. The dip in
          February is a shorter-month effect, not a demand signal — daily average sales
          actually rose.</div>`);
  h += card('Sales by region','share of R65.5m',
        donut(D.region,'Region','TotalSales',Rm));
  h += `</div>`;

  h += `<div class="grid g2">`;
  h += card('Top 10 merchants by sales value','',
        hBar(D.merchants.slice(0,10),'Merchant','TotalSales',Rm,
             (r,i)=> i<3? C.navy : C.teal, {labelW:150}) +
        `<div class="note">The top 5 merchants carry
          <b>${P1(D.concentration.top5_share)}</b> of revenue and the top 10 carry
          <b>${P1(D.concentration.top10_share)}</b>.
          ${D.concentration.merchants_for_80pct} of 25 merchants account for 80% of sales —
          a concentration worth monitoring as a commercial risk in its own right.</div>`);
  h += card('Redemption rate by voucher type','volume basis',
        hBar(D.voucherType,'VoucherType','RedemptionRate',P1,
             (r)=> r.RedemptionRate>0.9? C.green : r.RedemptionRate<0.8? C.red : C.teal,
             {labelW:110,valW:62}) +
        `<div class="note">A <b>16.9 percentage point</b> spread between Airtime
          (${P1(D.voucherType[0].RedemptionRate)}) and Gaming
          (${P1(D.voucherType[D.voucherType.length-1].RedemptionRate)}).
          Time-to-redeem is effectively identical across types (3.5–3.7 days), so the
          difference is whether customers redeem at all — not how quickly.</div>`);
  h += `</div>`;

  h += card('Regional monthly trend','Eastern Cape is the only region below its own peak',
    lineChart(
      [...new Set(D.regionMonth.map(r=>r.Region))].map(rg=>({
        name:rg,
        values:D.regionMonth.filter(r=>r.Region===rg).map(r=>r.SalesValue)
      })),
      [...new Set(D.regionMonth.map(r=>r.YearMonth))].map(m=>m.slice(5)),
      Rm) +
    `<div class="callout warn"><b>Eastern Cape is declining.</b> It is the only region that
      peaked before July (peak May 2026), sits ${P1(Math.abs(D.answers.Q3_declining_region.vs_peak))}
      below its own peak while every other region is AT its peak, and fell 12.2% in June
      against +1.4% to +3.8% elsewhere. Its trend slope is +2.0% of average monthly sales
      versus +4.4% to +8.5% for the rest. Four independent signals, not one bad month.</div>`);

  const rg=`<div class="tbl-wrap"><table><thead><tr>
      <th>Region</th><th class="r">Total Sales</th><th class="r">Share</th>
      <th class="r">Transactions</th><th class="r">Trend % of Avg</th>
      <th class="r">Last Month MoM</th><th class="r">Peak Month</th><th class="r">vs Own Peak</th>
    </tr></thead><tbody>` + D.region.map(r=>`<tr>
      <td class="name">${esc(r.Region)}</td>
      <td class="r">${R(r.TotalSales)}</td><td class="r">${P1(r.SalesShare)}</td>
      <td class="r">${N(r.TotalTransactions)}</td>
      <td class="r ${cls(r.TrendPctOfAvg)}">${PS(r.TrendPctOfAvg)}</td>
      <td class="r ${cls(r.LastMonthMoM)}">${PS(r.LastMonthMoM)}</td>
      <td class="r">${r.PeakMonth}</td>
      <td class="r ${cls(r.SalesVsPeak)}">${PS(r.SalesVsPeak)}</td></tr>`).join('')
    + `</tbody></table></div>`;
  h += card('Region performance detail','',rg);
  return h;
}

/* ================= PAGE — GEOGRAPHIC INTELLIGENCE ================= */
function pageGeo(){
  const served=D.region.length, total=D.geo.provinces.length;
  const coveredArea=D.geo.provinces.filter(p=>D.region.some(r=>r.Region===p.name))
                      .reduce((a,p)=>a+p.areaSqKm,0);
  const allArea=D.geo.provinces.reduce((a,p)=>a+p.areaSqKm,0);
  let h=`<div class="grid g4">
    ${kpi('navy','Provinces Served',`${served} of ${total}`,
          `${(coveredArea/allArea*100).toFixed(0)}% of national land area`)}
    ${kpi('teal','Largest Region',D.region[0].Region,
          `${Rm(D.region[0].TotalSales)} · ${P1(D.region[0].SalesShare)} of sales`)}
    ${kpi('amber','Weakest Momentum',
          [...D.region].sort((a,b)=>a.Last2MonthAvgMoM-b.Last2MonthAvgMoM)[0].Region,
          `${PS([...D.region].sort((a,b)=>a.Last2MonthAvgMoM-b.Last2MonthAvgMoM)[0].Last2MonthAvgMoM)} recent avg MoM`)}
    ${kpi('purple','Revenue Concentration',P1(D.region[0].SalesShare+D.region[1].SalesShare),
          'top 2 provinces combined')}
  </div>`;

  h+=`<div class="grid g23">`;
  h+=card('Sales by province','choropleth · fixed 660×560 projection', choropleth() +
    `<div class="note">Only <b>${served} of South Africa's ${total} provinces</b> carry
      merchants. The unserved four are drawn as hatched "no cover" rather than omitted,
      because an absent province reads as zero sales when it actually means no footprint at
      all — a different commercial question entirely.</div>`);

  h+=card('Provincial momentum','latest 2-month average MoM',
    hBar([...D.region].sort((a,b)=>a.Last2MonthAvgMoM-b.Last2MonthAvgMoM),
         'Region','Last2MonthAvgMoM',PS,
         (r)=> r.Last2MonthAvgMoM<0? C.red : r.Last2MonthAvgMoM>0.03? C.green : C.amber,
         {labelW:118,valW:62,zeroBase:false}) +
    `<div class="callout warn"><b>Eastern Cape is the only province with negative
      momentum.</b> It is also the only one that peaked before July and sits
      ${P1(Math.abs(D.answers.Q3_declining_region.vs_peak))} below its own peak, while every
      other province is currently at its peak.</div>`);
  h+=`</div>`;

  h+=card('Province league table','',
    `<div class="tbl-wrap"><table><thead><tr><th>Province</th><th class="r">Total Sales</th>
      <th class="r">Share</th><th class="r">Transactions</th><th class="r">Merchants</th>
      <th class="r">Land area (km²)</th><th class="r">Trend % of avg</th>
      <th class="r">Last month MoM</th><th class="r">vs own peak</th></tr></thead><tbody>` +
    D.region.map(r=>{
      const p=D.geo.provinces.find(x=>x.name===r.Region)||{areaSqKm:null};
      const nm=D.merchants.filter(m=>m.Region===r.Region).length;
      return `<tr><td class="name">${esc(r.Region)}</td>
        <td class="r">${R(r.TotalSales)}</td><td class="r">${P1(r.SalesShare)}</td>
        <td class="r">${N(r.TotalTransactions)}</td><td class="r">${nm}</td>
        <td class="r">${p.areaSqKm?N(p.areaSqKm):'–'}</td>
        <td class="r ${cls(r.TrendPctOfAvg)}">${PS(r.TrendPctOfAvg)}</td>
        <td class="r ${cls(r.LastMonthMoM)}">${PS(r.LastMonthMoM)}</td>
        <td class="r ${cls(r.SalesVsPeak)}">${PS(r.SalesVsPeak)}</td></tr>`;}).join('')
    +`</tbody></table></div>
    <div class="note">Land area is shown to make the footprint point concrete, not as a demand
      proxy. No population or GDP feed was supplied, so "unserved provinces represent
      opportunity" would be an assumption, not a finding — the honest statement is that
      ${(100-coveredArea/allArea*100).toFixed(0)}% of the country's land area currently has
      no merchant presence.</div>`);
  return h;
}

/* ================= PAGE 2 — MERCHANT ANALYSIS ================= */
function pageMerchant(){
  const m=activeMerchants();
  if(!m.length) return card('No merchants match the current filters','',
    '<div class="note">Clear a filter above to see data.</div>');
  const worst=[...m].sort((a,b)=>b.FocusPriorityScore-a.FocusPriorityScore).slice(0,5);
  let h=`<div class="grid g4">
    ${kpi('navy','Merchants',N(m.length),`${D.kpis.AtRiskMerchants} flagged At Risk in CRM`)}
    ${kpi('teal','Top 5 Concentration',P1(D.concentration.top5_share),
          `${D.concentration.merchants_for_80pct} merchants = 80% of revenue`)}
    ${kpi('red','Critical Health',N(m.filter(x=>x.HealthBand==='Critical').length),
          'merchants scoring below 35/100')}
    ${kpi('amber','Revenue at Risk',R(m.reduce((a,x)=>a+(x.RevenueAtRiskAnnualised||0),0)),
          'annualised, across all merchants')}
  </div>`;

  h+=`<div class="grid g2">`;
  h+=card('Priority focus list','ranked by revenue at risk, not by % decline',
    `<div class="tbl-wrap"><table><thead><tr><th>Merchant</th><th>Region</th>
      <th class="r">Health</th><th>Band</th><th class="r">Latest Month</th>
      <th class="r">vs Prior 3M</th><th class="r">Tickets</th><th class="r">Revenue at Risk</th>
      </tr></thead><tbody>` + worst.map(r=>`<tr>
      <td class="name">${esc(r.Merchant)}</td><td>${esc(r.Region)}</td>
      <td class="r"><b>${D1(r.HealthScore)}</b></td><td>${band(r.HealthBand)}</td>
      <td class="r">${R(r.LatestMonthSales)}</td>
      <td class="r ${cls(r.SalesVsPrior3Avg)}">${PS(r.SalesVsPrior3Avg)}</td>
      <td class="r ${r.TicketsVsPrior3Avg>1?'down':''}">${PS(r.TicketsVsPrior3Avg)}</td>
      <td class="r"><b>${R(r.RevenueAtRiskAnnualised)}</b></td></tr>`).join('')
    +`</tbody></table></div>
    <div class="callout crit"><b>Why rank by revenue at risk?</b> Severity alone misranks.
      Umhlanga Value Mart's 42.5% collapse and Table Bay Express's 5.9% slide look
      incomparable — but Table Bay is a ${Rm(3325306)} merchant, so its smaller percentage
      decline still puts ${R(354163)} a year at stake against Umhlanga's ${R(571518)}.
      Ranking on percentage change alone sends the account team to the wrong door.</div>`);

  h+=card('Bottom 5 merchants by sales value','the long tail — required by the brief',
    hBar([...m].slice(-5).reverse(),'Merchant','TotalSales',Rm,C.purple,{labelW:150}) +
    `<div class="note">The five smallest merchants together contribute
      ${P1([...m].slice(-5).reduce((a,x)=>a+x.SalesShare,0))} of revenue —
      less than the single largest merchant alone (${P1(m[0].SalesShare)}). Three of them
      also sit in the highest operational-friction quartile, which is a cost-to-serve
      question rather than a growth one.</div>`);

  h+=card('Health score distribution','',
    hBar([...m].sort((a,b)=>b.HealthScore-a.HealthScore).slice(0,14),
         'Merchant','HealthScore',D1,
         (r)=> r.HealthScore<35? C.red : r.HealthScore<55? C.amber :
               r.HealthScore<75? C.teal : C.green, {labelW:150,valW:44}) +
    `<div class="note">Composite of 8 percentile-ranked components, weighted toward recent
      momentum (25%) because the purpose is early warning rather than a retrospective
      league table. Bands: Critical &lt;35 · Watch 35–55 · Healthy 55–75 · Star 75+.</div>`);
  h+=`</div>`;

  h+=card('Full merchant scorecard','all 25 merchants · click a column header concept in the report to sort',
    `<div class="tbl-wrap" style="max-height:520px;overflow-y:auto"><table><thead><tr>
      <th class="r">#</th><th>Merchant</th><th>Region</th><th>Channel</th>
      <th class="r">Total Sales</th><th class="r">Share</th><th class="r">Cum.</th>
      <th class="r">Transactions</th><th class="r">Basket</th><th class="r">Redemption</th>
      <th class="r">Days</th><th class="r">Tickets</th><th class="r">Tkt/1k</th>
      <th class="r">SLA Breach</th><th class="r">MoM</th><th class="r">vs Prior 3M</th>
      <th class="r">Health</th><th>Band</th></tr></thead><tbody>` +
    m.map(r=>`<tr>
      <td class="r">${r.SalesRank}</td><td class="name">${esc(r.Merchant)}</td>
      <td>${esc(r.Region)}</td><td>${esc(r.Channel)}</td>
      <td class="r">${R(r.TotalSales)}</td><td class="r">${P1(r.SalesShare)}</td>
      <td class="r">${P1(r.CumulativeShare)}</td><td class="r">${N(r.TotalTransactions)}</td>
      <td class="r">${R(r.AvgBasketValue)}</td><td class="r">${P1(r.RedemptionRate)}</td>
      <td class="r">${D2(r.AvgDaysToRedeem)}</td><td class="r">${N(r.Tickets)}</td>
      <td class="r">${D2(r.TicketsPer1kTxn)}</td><td class="r">${P1(r.SLABreachRate)}</td>
      <td class="r ${cls(r.MoMChange)}">${PS(r.MoMChange)}</td>
      <td class="r ${cls(r.SalesVsPrior3Avg)}">${PS(r.SalesVsPrior3Avg)}</td>
      <td class="r"><b>${D1(r.HealthScore)}</b></td><td>${band(r.HealthBand)}</td></tr>`).join('')
    +`</tbody></table></div>
    <div class="tbl-note">In Power BI this table is the drill-through target: right-click any
      merchant on the executive page → Drill through → Merchant Detail.</div>`);

  h+=`<div class="grid g2">`;
  h+=card('Revenue contribution — Pareto','cumulative share by merchant size',
    (()=>{const F={w:700,h:280,l:56,r:52,t:16,b:40};
      const iw=F.w-F.l-F.r, ih=F.h-F.t-F.b;
      const mx=Math.max(...m.map(r=>r.TotalSales))*1.08;
      const bw=iw/m.length;
      let s=`<svg class="chart" viewBox="0 0 ${F.w} ${F.h}">`;
      [0,.25,.5,.75,1].forEach(f=>{const y=F.t+ih-f*ih;
        s+=`<line x1="${F.l}" y1="${y}" x2="${F.l+iw}" y2="${y}" stroke="${C.line}"/>
            <text x="${F.l-8}" y="${y+4}" text-anchor="end" font-size="10"
              fill="${C.muted}">${Rm(mx*f)}</text>
            <text x="${F.l+iw+8}" y="${y+4}" font-size="10" fill="${C.amber}">${(f*100).toFixed(0)}%</text>`;});
      m.forEach((r,i)=>{const hh=(r.TotalSales/mx)*ih;
        s+=`<rect x="${F.l+i*bw+bw*.15}" y="${F.t+ih-hh}" width="${bw*.7}" height="${hh}"
              rx="2" fill="${r.CumulativeShare<=0.8?C.teal:C.line}">
              <title>${esc(r.Merchant)}: ${Rm(r.TotalSales)} (${P1(r.SalesShare)})</title></rect>`;});
      const pts=m.map((r,i)=>[F.l+i*bw+bw/2, F.t+ih-r.CumulativeShare*ih]);
      s+=`<polyline points="${pts.map(p=>p.join(',')).join(' ')}" fill="none"
            stroke="${C.amber}" stroke-width="2.4"/>`;
      const y80=F.t+ih-0.8*ih;
      s+=`<line x1="${F.l}" y1="${y80}" x2="${F.l+iw}" y2="${y80}" stroke="${C.red}"
            stroke-width="1.4" stroke-dasharray="5 3"/>
          <text x="${F.l+6}" y="${y80-6}" font-size="10.5" fill="${C.red}"
            font-weight="700">80% of revenue</text>`;
      return s+'</svg>';})() +
    `<div class="note">${D.concentration.merchants_for_80pct} of 25 merchants generate 80% of
      revenue. HHI is ${Math.round(D.concentration.hhi)}, which is moderate concentration —
      no single merchant dominates, but the top tier matters disproportionately.</div>`);

  h+=card('Merchant segments','K-Means, k=4',
    `<div class="tbl-wrap"><table><thead><tr><th>Segment</th><th class="r">Merchants</th>
      <th class="r">Avg Sales</th><th class="r">Tickets/1k</th><th class="r">Growth</th>
      <th class="r">Momentum</th><th class="r">Health</th></tr></thead><tbody>` +
    D.segments.map(s=>`<tr><td class="name">${esc(s.SegmentName)}</td>
      <td class="r">${N(s.Merchants)}</td><td class="r">${Rm(s.AvgSales)}</td>
      <td class="r">${D2(s.AvgTicketsPer1k)}</td>
      <td class="r ${cls(s.AvgGrowth)}">${PS(s.AvgGrowth)}</td>
      <td class="r ${cls(s.AvgRecentMomentum)}">${PS(s.AvgRecentMomentum)}</td>
      <td class="r"><b>${D1(s.AvgHealth)}</b></td></tr>`).join('')
    +`</tbody></table></div>
    <div class="note">The algorithm isolated two merchants into single-member clusters on its
      own — Kudu Digital Kiosk (breakout growth) and Umhlanga Value Mart (deteriorating).
      That is a finding rather than a defect: both are behaviourally unlike anything else in
      the book, which is exactly what an account team needs to know.</div>`);
  h+=`</div>`;
  return h;
}

/* ================= PAGE 3 — OPERATIONAL VIEW ================= */
function pageOps(){
  const K=D.kpis, p=D.priority;
  let h=`<div class="grid g5">
    ${kpi('navy','Total Tickets',N(K.TotalTickets),'1 Jan – 31 Jul 2026')}
    ${kpi('teal','Avg Resolution',D1(K.AvgResolutionHours)+'h','median 16.4h · max 190.7h')}
    ${kpi('red','SLA Breach Rate',P1(K.SLABreachRate),
          `${Math.round(K.SLABreachRate*K.TotalTickets)} of ${N(K.TotalTickets)} tickets`)}
    ${kpi('amber','Open Backlog',N(K.OpenTickets),'Open, Escalated or Pending')}
    ${kpi('purple','Tickets / 1k Txn',D2(K.TicketsPer1kTxn),'portfolio friction rate')}
  </div>`;

  h+=card('THE HEADLINE OPERATIONAL FINDING — SLA targets run inverse to actual workload','',
    `<div class="tbl-wrap"><table><thead><tr><th>Priority</th><th class="r">SLA Target</th>
      <th class="r">Tickets</th><th class="r">Avg Resolution</th><th class="r">Median</th>
      <th class="r">Breaches</th><th class="r">Breach Rate</th>
      <th class="r">Share of All Breaches</th></tr></thead><tbody>` +
    p.map(r=>{const share=r.SLABreaches/p.reduce((a,x)=>a+x.SLABreaches,0);
      return `<tr><td class="name"><span class="pill ${
        r.Priority==='Critical'?'p-crit':r.Priority==='High'?'p-watch':
        r.Priority==='Medium'?'p-info':'p-ok'}">${r.Priority}</span></td>
      <td class="r">${r.TargetSLAHours}h</td><td class="r">${N(r.Tickets)}</td>
      <td class="r"><b>${D1(r.AvgResolutionHours)}h</b></td>
      <td class="r">${D1(r.MedianResolutionHours)}h</td>
      <td class="r">${N(r.SLABreaches)}</td>
      <td class="r ${r.SLABreachRate>0.5?'down':'up'}"><b>${P1(r.SLABreachRate)}</b></td>
      <td class="r">${P1(share)}
        <span class="bar" style="width:56px"><i style="width:${share*100}%;
          background:${C.red}"></i></span></td></tr>`;}).join('')
    +`</tbody></table></div>
    <div class="callout crit"><b>The SLA ladder is upside down.</b> Critical tickets are given
      12 hours but take 52.7 on average — a 98.3% breach rate. Low-priority tickets are given
      48 hours and take 11.3 — a 0.2% breach rate. Because the ladder runs opposite to the
      real workload, <b>94.7% of all 358 breaches land on High and Critical</b>.<br><br>
      This is a policy configuration problem, not a team performance problem: no amount of
      effort makes a 52-hour investigation fit a 12-hour target. Two options —
      <b>(a)</b> re-base SLAs on observed distributions (a 90th-percentile-compliant Critical
      SLA would be roughly 120 hours), or <b>(b)</b> keep the target and resource high-priority
      work separately. Continuing to report a 26% breach rate as a team failing is measuring
      the wrong thing.</div>`);

  h+=`<div class="grid g2">`;
  h+=card('Ticket volume by month and priority','',
    stacked([...new Set(D.ticketMonth.map(r=>r.YearMonth))].map(m=>m.slice(5)),
      ['Critical','High','Medium','Low'].map((pr,i)=>({
        name:pr, color:[C.red,C.amber,C.teal,C.navy][i],
        values:[...new Set(D.ticketMonth.map(r=>r.YearMonth))].map(m=>{
          const row=D.ticketMonth.find(r=>r.YearMonth===m&&r.Priority===pr);
          return row?row.Tickets:0;})
      })), N) +
    `<div class="note">July is the busiest month at 259 tickets, up 31% from the February low
      — but the rise is not broad-based. It is driven almost entirely by two merchants, shown
      below.</div>`);

  h+=card('Ticket type — volume and breach rate','',
    `<div class="tbl-wrap"><table><thead><tr><th>Ticket Type</th><th>Category</th>
      <th class="r">Tickets</th><th class="r">Avg Res.</th><th class="r">Breach Rate</th>
      <th class="r">Breach Hours</th></tr></thead><tbody>` +
    D.ticketType.map(r=>`<tr><td class="name">${esc(r.TicketType)}</td>
      <td><span class="pill p-info">${esc(r.TicketCategory)}</span></td>
      <td class="r">${N(r.Tickets)}</td><td class="r">${D1(r.AvgResolutionHours)}h</td>
      <td class="r">${P1(r.SLABreachRate)}</td>
      <td class="r">${N(r.TotalBreachHours)}</td></tr>`).join('')
    +`</tbody></table></div>
    <div class="note">Volume is remarkably even across the six types (202–253 tickets), and
      breach rates cluster between 19.8% and 32.9%. No single ticket type is driving the
      problem — which reinforces that the issue is the SLA policy, not a specific
      failing process.</div>`);
  h+=`</div>`;

  h+=card('Ticket spike events — the same signal, opposite diagnosis','',
    `<div class="tbl-wrap"><table><thead><tr><th>Merchant</th><th>Region</th><th>Month</th>
      <th class="r">Tickets</th><th class="r">Prior Avg</th><th class="r">Uplift</th>
      <th class="r">Sales</th><th class="r">Sales vs Prior 3M</th><th>Diagnosis</th>
      </tr></thead><tbody>` +
    D.events.map(r=>`<tr><td class="name">${esc(r.Merchant)}</td><td>${esc(r.Region)}</td>
      <td>${r.Month}</td><td class="r"><b>${N(r.Tickets)}</b></td>
      <td class="r">${D1(r.PriorAvgTickets)}</td>
      <td class="r down">${PS(r.TicketUplift)}</td><td class="r">${R(r.SalesValue)}</td>
      <td class="r ${cls(r.SalesVsPrior3Avg)}">${PS(r.SalesVsPrior3Avg)}</td>
      <td><span class="pill ${r.SalesVsPrior3Avg<0?'p-crit':'p-ok'}">${
        r.SalesVsPrior3Avg<0?'Failing account':'Service issue, healthy account'}</span></td>
      </tr>`).join('')
    +`</tbody></table></div>
    <div class="callout warn"><b>Durban Cash Hub</b> spiked +780% in June and +184% in July
      while sales <b>grew</b> 8.2% and 6.3%. <b>Umhlanga Value Mart</b> spiked +693% in July
      while sales <b>fell</b> 42.5%. Identical operational signal, entirely different
      commercial diagnosis — which is why the alerting logic pairs ticket movement with sales
      movement rather than triggering on either in isolation.</div>`);

  h+=`<div class="grid g2">`;
  h+=card('The backlog is two problems, not one','open tickets by who is holding them',
    hBar(D.backlog.filter(r=>r.Ownership!=='Resolved'),'Ownership','Tickets',N,
         (r)=> r.Ownership==='Awaiting us'? C.red : C.amber, {labelW:150,valW:56}) +
    `<div class="callout warn">Of ${N(D.kpis.OpenTickets)} open tickets,
      <b>${N(D.backlogSplit.awaiting_us)} are awaiting us</b> (Open + Escalated) and
      <b>${N(D.backlogSplit.awaiting_customer)} are awaiting the customer</b>
      (Pending Merchant) — ${P1(D.backlogSplit.pct_awaiting_customer)} of the backlog.
      Those need entirely different remediation: one is a capacity problem, the other is a
      chase-the-customer problem. A single "${N(D.kpis.OpenTickets)} open" figure hides the
      distinction, which is why <code>dim_ticket_status</code> carries an explicit
      <code>ownership</code> attribute rather than just an is_open flag.</div>`);

  h+=card('Is the SLA target even achievable?','from dim_priority — derived, not asserted',
    `<div class="tbl-wrap"><table><thead><tr><th>Priority</th><th class="r">Target SLA</th>
      <th class="r">Observed median</th><th class="r">Observed P90</th>
      <th>Achievable?</th><th class="r">SLA for 90% compliance</th></tr></thead><tbody>` +
    D.priorityDiag.map(r=>`<tr><td class="name">${esc(r.Priority)}</td>
      <td class="r">${r.TargetSLAHours}h</td>
      <td class="r">${D1(r.ObservedMedianHours)}h</td>
      <td class="r">${D1(r.ObservedP90Hours)}h</td>
      <td><span class="pill ${r.SlaIsAchievable?'p-ok':'p-crit'}">${
        r.SlaIsAchievable?'Yes':'No'}</span></td>
      <td class="r"><b>${D1(r.SlaFor90pctCompliance)}h</b></td></tr>`).join('')
    +`</tbody></table></div>
    <div class="note">This table is read straight from <code>dim_priority</code>. The
      diagnostic lives in the dimension rather than in a paragraph, so it is sortable,
      filterable and refreshes with the data. Critical carries a 12-hour target against a
      74-hour 90th percentile — the target is not missed, it is unreachable.</div>`);
  h+=`</div>`;

  h+=`<div class="grid g23">`;
  h+=card('Does operational friction predict weaker performance?',
          'bubble size = total sales',
    scatter(D.merchants,'TicketsPer1kTxn','SalesVsPrior3Avg','TotalSales','Merchant',D2,PS) +
    `<div class="callout"><b>The obvious reading is wrong, and it matters.</b>
      Tickets per 1,000 transactions correlates with target attainment at
      r = ${D2(D.confounder.raw_corr_friction_vs_attainment)}, which looks like clear evidence
      that friction hurts performance. It is not. The ratio is strongly size-dependent —
      it correlates with log(total sales) at
      r = ${D2(D.confounder.friction_vs_log_size_pearson)} — so small merchants score badly
      purely because the denominator is small.<br><br>
      Controlling for size, the partial correlation collapses to
      <b>r = ${D2(D.confounder.partial_corr_friction_vs_attainment_controlling_size)}</b>.
      SLA breach rate and average resolution time show no association with performance at all.
      Reporting "friction predicts weak merchants" would have been a confounded finding
      presented as a causal one.</div>`);
  h+=card('Friction quartiles','',
    `<div class="tbl-wrap"><table><thead><tr><th>Quartile</th><th class="r">n</th>
      <th class="r">Tkt/1k</th><th class="r">Growth</th><th class="r">Attainment</th>
      </tr></thead><tbody>` +
    D.friction.map(r=>`<tr><td>${esc(r.FrictionQuartile)}</td>
      <td class="r">${N(r.Merchants)}</td><td class="r">${D2(r.AvgTicketsPer1kTxn)}</td>
      <td class="r ${cls(r.AvgGrowthLast3vsFirst3)}">${PS(r.AvgGrowthLast3vsFirst3)}</td>
      <td class="r">${D2(r.AvgTargetAttainment)}</td></tr>`).join('')
    +`</tbody></table></div>
    <div class="note">The gradient in attainment (7.09 → 4.84) looks convincing until you
      notice the highest-friction quartile is also the smallest-merchant quartile.</div>`);
  h+=`</div>`;
  return h;
}

/* ================= PAGE 4 — AI & ANOMALIES ================= */
function pageAI(){
  const ml=D.ml, rp=ml.redemption_propensity, sf=ml.sales_forecast;
  let h=`<div class="grid g5">
    ${kpi('purple','Models Trained','5','anomaly · propensity · regression · forecast · clustering')}
    ${kpi('navy','Anomalies Flagged',N(ml.anomaly_detection.anomalies_flagged),
          `from ${ml.anomaly_detection.observations_scored} merchant-months`)}
    ${kpi('teal','Forecast MAPE',P2(sf.mape),
          `${P1(sf.improvement_vs_naive)} better than naive`)}
    ${kpi('amber','Propensity AUC',D2(rp.roc_auc),
          `${P1(rp.pct_of_achievable_signal)} of achievable ceiling`)}
    ${kpi('navy','Resolution MAE',D1(ml.resolution_time.mae_hours)+'h',
          `${P1(ml.resolution_time.improvement_vs_naive)} better than naive`)}
  </div>`;

  h+=card('Isolation Forest — detected anomalies',
          'unsupervised · 7 features · each relative to the merchant\\'s own history',
    `<div class="tbl-wrap"><table><thead><tr><th class="r">#</th><th>Merchant</th>
      <th>Region</th><th>Month</th><th class="r">Score</th><th class="r">Sales</th>
      <th class="r">vs Own History</th><th class="r">Tickets</th>
      <th>Why it was flagged</th></tr></thead><tbody>` +
    D.anomalies.map((r,i)=>`<tr><td class="r">${i+1}</td>
      <td class="name">${esc(r.Merchant)}</td><td>${esc(r.Region)}</td><td>${r.YearMonth}</td>
      <td class="r"><b>${D2(r.AnomalyScore)}</b>
        <span class="bar" style="width:44px"><i style="width:${r.AnomalyScore*100}%;
          background:${r.AnomalyScore>0.6?C.red:C.amber}"></i></span></td>
      <td class="r">${R(r.SalesValue)}</td>
      <td class="r ${cls(r.SalesVsOwnHistory)}">${PS(r.SalesVsOwnHistory)}</td>
      <td class="r">${N(r.Tickets)}</td>
      <td style="white-space:normal;min-width:280px">${esc(r.Explanation)}</td></tr>`).join('')
    +`</tbody></table></div>
    <div class="callout good"><b>Independent validation.</b> The dataset documentation states
      four patterns were deliberately embedded. The model was never told what they were, and
      recovered all four unprompted: Umhlanga Value Mart's July collapse (ranked #1), Kudu
      Digital Kiosk's May growth step, Durban Cash Hub's June ticket spike, and a Liberty Lane
      redemption-delay month.<br><br>
      The design decision that makes this work is expressing every feature as a deviation from
      each merchant's <b>own</b> expanding history rather than as an absolute value. Absolute
      features would have ranked merchants by size and flagged the largest accounts every
      month while missing a small merchant collapsing. Every flagged row also carries a
      plain-English reason, because a score with no explanation attached does not get acted on.</div>`);

  h+=`<div class="grid g2">`;
  h+=card('30-day sales forecast','Holt-Winters · weekly seasonality · 80% and 95% intervals',
    forecastChart(D.dailyTotal.slice(-60), D.forecast) +
    `<div class="note">Backtested on the held-out final 30 days: <b>MAPE ${P2(sf.mape)}</b>
      against a naive last-7-day-mean baseline of ${P2(sf.naive_mape)} — a
      ${P1(sf.improvement_vs_naive)} improvement. Forecast total for the next 30 days is
      ${Rm(sf.next30_forecast_total)}, ${PS(sf.forecast_change)} against the last 30 actual.
      Intervals are empirical, from in-sample residual standard deviation.</div>`);

  h+=card('Redemption propensity — risk decile lift','time-split validation',
    `<div class="tbl-wrap"><table><thead><tr><th class="r">Decile</th><th class="r">Vouchers</th>
      <th class="r">Predicted Risk</th><th class="r">Actual Non-Redemption</th>
      <th class="r">Lift</th><th class="r">Value at Risk</th></tr></thead><tbody>` +
    D.deciles.map(r=>`<tr><td class="r"><b>${r.RiskDecile}</b></td>
      <td class="r">${N(r.Vouchers)}</td><td class="r">${P1(r.AvgPredictedRisk)}</td>
      <td class="r">${P1(r.ActualNonRedemptionRate)}
        <span class="bar" style="width:52px"><i style="width:${r.ActualNonRedemptionRate*350}%;
          background:${C.red}"></i></span></td>
      <td class="r">${D2(r.Lift)}×</td><td class="r">${R(r.ValueAtRisk)}</td></tr>`).join('')
    +`</tbody></table></div>
    <div class="callout warn"><b>An AUC of ${D2(rp.roc_auc)} looks weak — so it was tested
      against a ceiling.</b> If redemption is generated purely from voucher type, the best any
      model can achieve is the type-level base rate. That oracle scores AUC
      ${D2(rp.oracle_auc_ceiling)}. The model captures
      <b>${P1(rp.pct_of_achievable_signal)}</b> of the achievable signal, so
      ${D2(rp.roc_auc)} is the practical ceiling of this dataset, not an underfit model.
      Establishing that distinction stops a team spending a sprint chasing an AUC that cannot
      move.<br><br>
      The ranking is still operationally useful: the top decile carries
      ${D1(rp.top_vs_bottom_decile_ratio)}× the non-redemption rate of the bottom, concentrating
      ${R(rp.top_decile_value_at_risk)} of at-risk value into 10% of vouchers.</div>`);
  h+=`</div>`;

  h+=card('Rules-based alerts','deterministic layer, running alongside the ML layer',
    `<div class="tbl-wrap"><table><thead><tr><th>Severity</th><th>Merchant</th><th>Region</th>
      <th>Alert Type</th><th>Detail</th><th class="r">Revenue at Risk</th>
      </tr></thead><tbody>` +
    D.alerts.map(r=>`<tr><td><span class="pill ${
        r.Severity==='Critical'?'p-crit':r.Severity==='High'?'p-watch':'p-info'}">${
        r.Severity}</span></td>
      <td class="name">${esc(r.Merchant)}</td><td>${esc(r.Region)}</td>
      <td>${esc(r.AlertType)}</td>
      <td style="white-space:normal;min-width:300px">${esc(r.Detail)}</td>
      <td class="r">${r.RevenueAtRiskAnnualised>0?R(r.RevenueAtRiskAnnualised):'–'}</td>
      </tr>`).join('')
    +`</tbody></table></div>
    <div class="note">Two detection layers run side by side deliberately. The rules layer is
      transparent, always fires, and can be explained to an account manager in one sentence.
      The ML layer catches multivariate shifts no rule was written for. Neither replaces the
      other.</div>`);

  h+=card('Model inventory','',
    `<div class="tbl-wrap"><table><thead><tr><th>Model</th><th>Algorithm</th>
      <th>Validation approach</th><th>Result</th><th>Business use</th></tr></thead><tbody>
      <tr><td class="name">1. Anomaly detection</td><td><code>IsolationForest</code></td>
        <td>Unsupervised; validated against 4 documented embedded patterns</td>
        <td><b>4 / 4 recovered</b></td><td>Weekly exception list for account managers</td></tr>
      <tr><td class="name">2. Redemption propensity</td>
        <td><code>HistGradientBoostingClassifier</code></td>
        <td>Time split: train Jan–May, test Jun–Jul</td>
        <td>AUC ${D2(rp.roc_auc)} vs ceiling ${D2(rp.oracle_auc_ceiling)}</td>
        <td>Target follow-up on high-risk vouchers</td></tr>
      <tr><td class="name">3. Resolution time</td>
        <td><code>HistGradientBoostingRegressor</code></td>
        <td>Time split: train Jan–May, test Jun–Jul</td>
        <td>MAE ${D1(D.ml.resolution_time.mae_hours)}h · R² ${D2(D.ml.resolution_time.r2)}</td>
        <td>Triage: flag likely breaches before they happen</td></tr>
      <tr><td class="name">4. Sales forecast</td><td><code>ExponentialSmoothing</code></td>
        <td>Backtest on held-out final 30 days</td>
        <td>MAPE ${P2(sf.mape)}</td><td>30-day capacity and revenue planning</td></tr>
      <tr><td class="name">5. Segmentation</td><td><code>KMeans (k=4)</code></td>
        <td>Silhouette compared at k=2..7; k chosen on business grounds</td>
        <td>4 segments, 2 singletons found automatically</td>
        <td>Differentiated account management plays</td></tr>
      </tbody></table></div>
    <div class="note"><b>Every supervised model uses a time-based split, never a random one.</b>
      A random split leaks future information into training and produces a metric that will
      not survive contact with production. Reporting an honest 0.62 that holds is worth more
      than an inflated 0.85 that does not.</div>`);
  return h;
}

/* ================= PAGE 5 — INSIGHTS & ANSWERS ================= */
function pageInsights(){
  const A=D.answers, q1=A.Q1_highest_sales, q2=A.Q2_best_voucher_type, q3=A.Q3_declining_region;
  let h=`<div class="grid g4">
    ${kpi('navy','Total Sales',Rm(D.kpis.TotalSales),'1 Jan – 31 Jul 2026')}
    ${kpi('teal','Redemption Rate',P1(D.kpis.RedemptionRate),'84.2% of 120,969 vouchers')}
    ${kpi('red','SLA Breach Rate',P1(D.kpis.SLABreachRate),'94.7% on High/Critical')}
    ${kpi('amber','Revenue at Risk',R(1215521),'annualised, deteriorating merchants')}
  </div>`;

  const QA=[
    ['1','Which merchants generate the highest sales value and transaction volume?',
     `<b>Durban Cash Hub leads on both</b> — ${R(q1.value)} in sales (${P1(q1.share)} of the
      portfolio) and ${N(q1.transactions)} transactions.
      <ul>
        <li>The two rankings agreeing at the top is not guaranteed. A merchant can lead on
            value while trailing on volume if its basket is larger, so both are reported
            rather than assuming one proxies the other.</li>
        <li>Concentration matters more than the leader: the top 5 carry
            <b>${P1(D.concentration.top5_share)}</b> of revenue, and
            ${D.concentration.merchants_for_80pct} of 25 merchants account for 80%.</li>
        <li>Kudu Digital Kiosk is the one to watch — 2nd by sales, and the fastest-growing
            merchant in the book at +72% post-May.</li>
      </ul>`],
    ['2','Which voucher type has the highest redemption rate?',
     `<b>Airtime, at ${P1(q2.RedemptionRate)}</b>. Gaming is lowest at ${P1(q2.worst_rate)} —
      a <b>16.9 percentage point spread</b>.
      <ul>
        <li>The value-based rate is almost identical to the volume-based rate within each
            type, so high-value and low-value vouchers behave the same way. Had they
            diverged, the value rate would be the one Finance should use.</li>
        <li>Time-to-redeem is effectively flat across all types (3.5–3.7 days). The
            difference is <b>whether</b> customers redeem, not how quickly.</li>
        <li>Gaming's 24% non-redemption is the single largest block of the
            ${Rm(D.kpis.OutstandingLiability)} outstanding liability — worth a targeted
            reminder campaign, which the propensity model can direct.</li>
      </ul>`],
    ['3','Which region shows declining sales or transaction behaviour?',
     `<b>Eastern Cape</b>, on four independent signals rather than one:
      <ul>
        <li>It is the <b>only</b> region that peaked before July (peak May 2026).</li>
        <li>It sits <b>${P1(Math.abs(q3.vs_peak))} below its own peak</b> while every other
            region is currently AT its peak.</li>
        <li>Its trend slope is +2.0% of average monthly sales, against +4.4% to +8.5%
            elsewhere.</li>
        <li>June fell <b>12.2%</b> month-on-month against +1.4% to +3.8% for every other
            region.</li>
      </ul>
      A single month's movement would not justify calling a decline — four signals pointing
      the same way does. Three of the five Critical/Watch merchants sit in Eastern Cape
      (Table Bay Express, Pretoria PayPoint, Mzansi Mini Market), so this is a regional
      pattern rather than one bad account.`],
    ['4','Are ticket volumes, priority or long resolution times associated with weaker merchant performance?',
     `<b>Not as a portfolio rule — but decisively at the level of individual events.</b>
      <ul>
        <li>The tempting answer: tickets per 1,000 transactions correlates with target
            attainment at r = ${D2(D.confounder.raw_corr_friction_vs_attainment)}.
            <b>That answer is confounded.</b></li>
        <li>The ratio is strongly size-dependent — r =
            ${D2(D.confounder.friction_vs_log_size_pearson)} against log(total sales) — so
            small merchants look worse purely because the denominator is small. Controlling
            for size, the partial correlation collapses to
            <b>r = ${D2(D.confounder.partial_corr_friction_vs_attainment_controlling_size)}</b>.</li>
        <li>SLA breach rate and average resolution time show <b>no</b> association with
            performance (r = +0.04 and −0.19).</li>
        <li>What IS real is event-level. Durban Cash Hub's tickets rose <b>+780%</b> while
            sales <b>grew</b> 8.2%; Umhlanga Value Mart's rose <b>+693%</b> while sales
            <b>fell</b> 42.5%. Same signal, opposite diagnosis.</li>
      </ul>
      <b>Practical conclusion:</b> ticket spikes are worth investigating immediately, but they
      do not predict revenue on their own. Alerting must pair operational movement with
      commercial movement — which is how the alert logic in this solution is written.`],
    ['5','Which merchants should management focus on first, and why?',
     `Ranked by <b>revenue at risk</b>, not by severity of decline:
      <ul>` + A.Q5_focus_merchants.map((m,i)=>
        `<li><b>${i+1}. ${esc(m.Merchant)}</b> (${esc(m.Region)}) — health
         ${D1(m.HealthScore)}/100, latest month <b>${PS(m.SalesVsPrior3Avg)}</b> vs prior
         3-month average, <b>${R(m.RevenueAtRiskAnnualised)}</b> annualised at risk${
         m.TicketsVsPrior3Avg? `, tickets ${PS(m.TicketsVsPrior3Avg)}`:''}</li>`).join('')
      + `</ul>
      <b>Why revenue at risk rather than % decline:</b> Umhlanga's 42.5% collapse and Table
      Bay's 5.9% slide are not comparable on their face — but Table Bay is a
      ${Rm(3325306)} merchant, so its smaller percentage still puts ${R(354163)} a year at
      stake. Ranking on percentage change alone sends the account team to the wrong door.<br><br>
      <b>Umhlanga Value Mart is the clear first call:</b> sales down 42.5% and tickets up 693%
      in the same month is an operational failure causing commercial damage, not a demand
      problem — and it is the one case where fixing the service issue plausibly recovers the
      revenue.`],
  ];
  QA.forEach(([n,q,a])=>{
    h+=`<div class="qa"><div class="qa-q"><span class="n">${n}</span>${q}</div>
        <div class="qa-a">${a}</div></div>`;
  });

  h+=card('Does the existing CRM "At Risk" flag already do this job?',
          'testing the assumption before justifying the analytics',
    `<div class="tbl-wrap"><table><thead><tr><th>Merchant</th><th>Region</th>
      <th>CRM flag</th><th>Computed band</th><th class="r">Health</th>
      <th class="r">vs Prior 3M</th><th class="r">Revenue at Risk</th></tr></thead><tbody>` +
    D.crmCheck.map(r=>`<tr><td class="name">${esc(r.Merchant)}</td>
      <td>${esc(r.Region)}</td>
      <td><span class="pill ${r.ActiveStatus==='At Risk'?'p-watch':'p-info'}">${
        esc(r.ActiveStatus)}</span></td>
      <td>${band(r.HealthBand)}</td>
      <td class="r"><b>${D1(r.HealthScore)}</b></td>
      <td class="r ${cls(r.SalesVsPrior3Avg)}">${PS(r.SalesVsPrior3Avg)}</td>
      <td class="r">${r.RevenueAtRiskAnnualised>0?R(r.RevenueAtRiskAnnualised):'–'}</td>
      </tr>`).join('')
    +`</tbody></table></div>
    <div class="callout crit"><b>Zero overlap.</b> The business already has a manual risk
      flag, so the honest first question is whether a computed score adds anything. It does:
      both merchants flagged <b>At Risk</b> are <b>growing</b> and score Healthy
      (${D1(61.7)} and ${D1(68.3)}), while all
      ${D.crmFlag.n_critical} merchants in genuine decline — including the one losing
      ${R(571518)} annualised — are flagged <b>"Active"</b>.
      <b>${R(D.crmFlag.missed_revenue_at_risk)}</b> of at-risk revenue sits in merchants the
      CRM considers fine.<br><br>
      The existing flag is not detecting the problem it exists to detect. That is the
      clearest justification for the Health Score — not that it is more sophisticated, but
      that the incumbent method demonstrably misses the cases that matter.</div>`);

  h+=card('Recommended actions','prioritised',
    `<div class="tbl-wrap"><table><thead><tr><th class="r">#</th><th>Action</th><th>Owner</th>
      <th>Rationale</th><th>Expected impact</th></tr></thead><tbody>
      <tr><td class="r">1</td><td class="name">Site visit to Umhlanga Value Mart this week</td>
        <td>Account Management</td>
        <td>Sales −42.5% and tickets +693% in the same month — an operational failure causing
            commercial damage</td>
        <td><b>${R(571518)}</b> annualised revenue recoverable</td></tr>
      <tr><td class="r">2</td><td class="name">Re-base the SLA policy</td><td>Operations</td>
        <td>94.7% of breaches come from Critical/High because targets run inverse to actual
            workload. The metric is currently unmeasurable, not unmet</td>
        <td>Restores SLA as a usable management signal</td></tr>
      <tr><td class="r">3</td><td class="name">Root-cause Durban Cash Hub's ticket volume</td>
        <td>Operations</td>
        <td>+780% tickets on the largest merchant in the book, while sales still grow — a
            service problem that has not yet become a commercial one</td>
        <td>Protects ${Rm(5776119)} of annual revenue</td></tr>
      <tr><td class="r">4</td><td class="name">Eastern Cape regional review</td>
        <td>Regional Management</td>
        <td>Only region below its own peak; 3 of 5 Critical/Watch merchants sit there</td>
        <td>${Rm(8781130)} region on a declining trajectory</td></tr>
      <tr><td class="r">5</td><td class="name">Gaming voucher redemption campaign</td>
        <td>Commercial</td>
        <td>24% non-redemption vs 7% for Airtime; the propensity model can target the top
            risk decile</td>
        <td>${R(171689)} of at-risk value in the top decile alone</td></tr>
      <tr><td class="r">6</td><td class="name">Confirm the sales target basis with Finance</td>
        <td>Finance / BI</td>
        <td>Targets sit ~6.1× below realised sales for all 25 merchants — a basis error, not
            outperformance</td>
        <td>Makes target attainment reportable at all</td></tr>
      </tbody></table></div>`);
  return h;
}

/* ================= PAGE 6 — HOW IT WAS BUILT ================= */
function pageBuild(){
  let h = card('Solution architecture','Microsoft Fabric medallion + dbt + Power BI Direct Lake',
    `<svg class="arch" viewBox="0 0 1120 400" style="max-width:100%">
      <defs>
        <linearGradient id="gb" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#8B6914"/><stop offset="1" stop-color="#C89B3C"/></linearGradient>
        <linearGradient id="gs" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#5A6672"/><stop offset="1" stop-color="#8C9AA8"/></linearGradient>
        <linearGradient id="gg" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#0E8B8B"/><stop offset="1" stop-color="#14B0AC"/></linearGradient>
        <linearGradient id="gp" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#12305B"/><stop offset="1" stop-color="#1B4079"/></linearGradient>
        <marker id="ar" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
          <path d="M0,0 L10,4 L0,8 z" fill="#8C9AA8"/></marker>
      </defs>

      <text x="24" y="26" font-size="13" font-weight="700" fill="#12305B">SOURCE</text>
      <rect x="16" y="38" width="150" height="200" rx="9" fill="#EEF3F9" stroke="#DCE4EF"/>
      ${['MerchantSales.csv','VoucherRedemptions.csv','SupportTickets.csv','MerchantReference.csv']
        .map((f,i)=>`<rect x="28" y="${52+i*46}" width="126" height="34" rx="5" fill="#fff"
          stroke="#C9D6E6"/><text x="91" y="${73+i*46}" font-size="9.5" text-anchor="middle"
          fill="#12305B" font-weight="600">${f}</text>`).join('')}

      <text x="200" y="26" font-size="13" font-weight="700" fill="#8B6914">BRONZE</text>
      <rect x="192" y="38" width="150" height="200" rx="9" fill="url(#gb)" opacity=".13"
        stroke="#C89B3C"/>
      <text x="267" y="72" font-size="10.5" text-anchor="middle" fill="#6B5410"
        font-weight="700">Delta tables</text>
      ${['Raw, as received','+ _batch_id','+ _ingested_at','+ _source_file','No business logic']
        .map((t,i)=>`<text x="267" y="${98+i*24}" font-size="9.5" text-anchor="middle"
          fill="#6B5410">${t}</text>`).join('')}

      <text x="376" y="26" font-size="13" font-weight="700" fill="#5A6672">SILVER</text>
      <rect x="368" y="38" width="150" height="200" rx="9" fill="url(#gs)" opacity=".13"
        stroke="#8C9AA8"/>
      <text x="443" y="72" font-size="10.5" text-anchor="middle" fill="#3D4854"
        font-weight="700">Cleansed</text>
      ${['Typed &amp; trimmed','Deduplicated','Conformed','Business rules','Quality flags']
        .map((t,i)=>`<text x="443" y="${98+i*24}" font-size="9.5" text-anchor="middle"
          fill="#3D4854">${t}</text>`).join('')}

      <text x="552" y="26" font-size="13" font-weight="700" fill="#0E8B8B">GOLD</text>
      <rect x="544" y="38" width="168" height="200" rx="9" fill="url(#gg)" opacity=".14"
        stroke="#0E8B8B"/>
      <text x="628" y="72" font-size="10.5" text-anchor="middle" fill="#0A5F5F"
        font-weight="700">Kimball star schema</text>
      ${['6 dimensions','4 fact tables','1 analytics mart','2 ML output tables','Direct Lake ready']
        .map((t,i)=>`<text x="628" y="${98+i*24}" font-size="9.5" text-anchor="middle"
          fill="#0A5F5F">${t}</text>`).join('')}

      <text x="746" y="26" font-size="13" font-weight="700" fill="#12305B">CONSUME</text>
      <rect x="738" y="38" width="168" height="200" rx="9" fill="url(#gp)" opacity=".13"
        stroke="#1B4079"/>
      ${['Power BI · 4 pages','Excel pack · 10 sheets','Fabric ML notebooks','Copilot / Q&amp;A']
        .map((t,i)=>`<rect x="750" y="${58+i*46}" width="144" height="34" rx="5" fill="#fff"
          stroke="#C9D6E6"/><text x="822" y="${79+i*46}" font-size="9.5" text-anchor="middle"
          fill="#12305B" font-weight="600">${t}</text>`).join('')}

      ${[176,352,528,722].map(x=>`<line x1="${x}" y1="138" x2="${x+14}" y2="138"
        stroke="#8C9AA8" stroke-width="2" marker-end="url(#ar)"/>`).join('')}

      <rect x="16" y="262" width="890" height="52" rx="9" fill="#FEF8EC" stroke="#E8A317"/>
      <text x="32" y="284" font-size="11.5" font-weight="700" fill="#8B6914">
        ORCHESTRATION — Azure Data Factory / Fabric Pipelines</text>
      <text x="32" y="302" font-size="10" fill="#6B5410">
        Metadata-driven ForEach ingest · row-count validation · dbt test gate BETWEEN silver
        and gold · ML scoring · semantic model refresh · daily 02:00 SAST</text>

      <rect x="16" y="326" width="890" height="52" rx="9" fill="#F0F9F9" stroke="#0E8B8B"/>
      <text x="32" y="348" font-size="11.5" font-weight="700" fill="#0A5F5F">
        QUALITY — 14 warehouse tests · 69 dbt tests · 28 reconciliation checks</text>
      <text x="32" y="366" font-size="10" fill="#0A5F5F">
        The gold layer is built TWICE by independent implementations (pandas and dbt SQL).
        Every headline figure agrees to the cent — that is what makes "the numbers tie" a
        verifiable claim rather than an assertion.</text>

      <rect x="922" y="262" width="182" height="116" rx="9" fill="#EEF3F9" stroke="#DCE4EF"/>
      <text x="1013" y="284" font-size="11" font-weight="700" text-anchor="middle"
        fill="#12305B">BY THE NUMBERS</text>
      ${[['149,857','rows processed'],['13','dbt models'],['31','DAX measures validated'],
         ['5','ML models']].map((r,i)=>
        `<text x="940" y="${304+i*19}" font-size="10.5" font-weight="700"
          fill="#0E8B8B">${r[0]}</text>
         <text x="990" y="${304+i*19}" font-size="10" fill="#5A6672">${r[1]}</text>`).join('')}
    </svg>`);

  const steps=[
    ['01','Profile before modelling anything',
     `Ran a full profile of all four files first: grain, key uniqueness, null patterns, date
      coverage, referential integrity and categorical inventories. This is what surfaced the
      mis-calibrated sales targets and confirmed that the fact-embedded Merchant/Region/Channel
      columns agree with MerchantReference in 100% of cases — which is what made dropping
      them from the facts a safe, lossless decision rather than a guess.`,
     ['scripts/01_profile.py','docs/profile_report.json']],
    ['02','Build the medallion layers',
     `Bronze lands raw with lineage columns only. Silver types, trims, deduplicates at the
      declared grain and applies business rules — including the redemption integrity rule that
      only counts a voucher as redeemed if the flag AND a valid non-retrograde date agree.
      Gold is a Kimball star schema with integer surrogate keys and an Unknown dimension
      member so a future unmatched fact lands somewhere visible instead of vanishing.`,
     ['scripts/02_build_warehouse.py','notebooks/01_bronze_to_silver.py','sql/01_create_warehouse.sql']],
    ['03','Model the star schema deliberately',
     `Four facts at three different grains. The voucher fact is an accumulating snapshot with
      role-playing dates — sold_date_key ACTIVE, redeemed_date_key INACTIVE, activated by
      USERELATIONSHIP inside specific measures. Without that separation a redemption backlog
      is invisible, because late redemptions get attributed back to the month of sale. The
      target fact sits at MONTH grain in its own table rather than being forced into the
      daily sales fact.`,
     ['dim_date','dim_merchant','fct_merchant_sales','fct_voucher_redemptions','fct_merchant_target']],
    ['04','Express the same logic in dbt',
     `18 models across staging → intermediate → marts, plus a Type 2 snapshot, 4 seeds and
      132 tests. A full <code>dbt build</code> completes 153 pass / 0 warn / 0 error. The
      tests that earn their place are the ones covering what actually breaks reports:
      dim_date contiguity (time intelligence returns wrong answers, not errors, on a gapped
      calendar), revenue reconciliation bronze→gold, a plausible-range guard on the
      redemption rate, and completeness assertions so a refactor cannot silently drop a
      merchant.`,
     ['dbt build → 153 pass','132 tests','1 snapshot (SCD2)','dbt docs generate']],
    ['05','Fix two modelling gaps found on review',
     `The first build unioned ticket type, priority and status into one table behind a
      discriminator. That meant the three foreign keys on the ticket fact could not be tested
      for referential integrity — a relationships test could not tell "priority_key resolves
      to a priority" from "resolves to something, somewhere" — and Power BI cannot build three
      independent filter paths off one physical table. Splitting them added 9 referential
      tests that previously could not exist.<br><br>
      Second, MerchantReference is a current-state extract: every load overwrites the last, so
      merchant status and account-manager history is destroyed at source. A Type 2 snapshot
      now captures it, validated by a harness that simulates a change and asserts history was
      recorded correctly (7/7) before restoring state.`,
     ['dim_ticket_type','dim_priority','dim_ticket_status','snap_merchant','dim_merchant_history']],
    ['06','Reconcile the two implementations',
     `The gold layer is built twice — once in pandas, once in dbt SQL — and every headline
      figure is compared. This caught two genuine defects that no unit test would have found:
      dim_date was absorbing the August redemption tail into the reporting window (inflating
      pro-rated targets by R984k), and the Python and SQL percentile-rank conventions differed,
      shifting the Health Score by up to 9.7 points. Both fixed; 27 of 28 checks now tie
      exactly, and the one remaining is a documented 0.1 rounding-convention difference.`,
     ['scripts/05_reconcile.py','27 PASS · 1 WARN · 0 FAIL']],
    ['07','Write and validate the DAX',
     `31+ measures across sales, redemption, operations, time intelligence, ranking and
      narrative. DAX cannot be executed outside Power BI, so each measure carries a SQL
      reference definition evaluated against gold to produce an expected value — an acceptance
      test to check every card against once the measures are entered.`,
     ['dax/*.dax','docs/dax_validation.csv']],
    ['08','Train the ML layer honestly',
     `Five models. Every supervised model uses a time-based split, never random — a random
      split leaks future information and produces a metric that will not survive production.
      Where a metric looked weak (redemption AUC 0.62) it was tested against a theoretical
      ceiling rather than explained away: the model captures 99.8% of achievable signal, so
      the limit is the data, not the model.`,
     ['scripts/04_ml_models.py','notebooks/03_ml_anomaly_and_forecast.py','MLflow']],
    ['09','Orchestrate and gate',
     `Data Factory pipeline with metadata-driven ingest, per-source row-count floors to catch
      the truncation failure that does not throw, and — the key decision — the dbt test gate
      sits BETWEEN silver and gold. If quality fails, gold is not rebuilt and the report keeps
      showing yesterday's correct numbers. Stale-but-correct beats fresh-but-wrong.`,
     ['datafactory/PL_MerchantVoucher_Master.json','TR_Daily_0200_SAST']],
  ];
  h+=`<div style="margin-top:16px">`+steps.map(([n,t,d,tags])=>
    `<div class="step"><div class="step-n">${n}<small>STEP</small></div>
      <div class="step-b"><h4>${t}</h4><p>${d}</p>
      <div class="tags">${tags.map(g=>`<span class="tag">${esc(g)}</span>`).join('')}</div>
      </div></div>`).join('')+`</div>`;

  h+=`<div class="grid g2">`;
  h+=card('Report page design','4 pages, as specified in the brief',
    `<div class="tbl-wrap"><table><thead><tr><th>Page</th><th>Contents</th>
      <th>Interaction</th></tr></thead><tbody>
      <tr><td class="name">1. Executive Overview</td>
        <td>5 KPI cards, sales trend combo, region donut, top merchants, voucher redemption</td>
        <td>Slicers: date, region, channel, voucher type. Right-click → drill through to
            Merchant Detail</td></tr>
      <tr><td class="name">2. Merchant Analysis</td>
        <td>Top/bottom ranking, Pareto contribution, health scorecard, segment table</td>
        <td>Drill-through target page; tooltip page shows 6-month sparkline + narrative</td></tr>
      <tr><td class="name">3. Operational View</td>
        <td>SLA policy table, ticket volume by month/priority, ticket type, spike events,
            friction scatter</td>
        <td>Cross-filter from priority to merchant; conditional formatting on breach rate</td></tr>
      <tr><td class="name">4. Insights &amp; Notes</td>
        <td>Narrative summary, the 5 business questions, assumptions, limitations, AI output</td>
        <td>Q&amp;A visual with configured synonyms; smart narrative</td></tr>
      </tbody></table></div>`);

  h+=card('Why 14 tables when the README suggests 5','every table justified individually',
    `<div class="callout warn">${esc(D.registry.summary)}</div>
    <div class="tbl-wrap" style="margin-top:12px"><table><thead><tr><th>Tier</th>
      <th class="r">Count</th><th>Tables</th><th>What the tier means</th></tr></thead><tbody>` +
    D.registry.tiers.map(t=>`<tr>
      <td><span class="pill" style="background:${t.colour};color:#fff">${esc(t.label)}</span></td>
      <td class="r"><b>${t.count}</b></td>
      <td style="white-space:normal"><code>${t.tables.map(esc).join('</code> <code>')}</code></td>
      <td style="white-space:normal;color:var(--muted)">${esc(t.blurb)}</td></tr>`).join('')
    +`</tbody></table></div>
    <div class="tbl-wrap" style="margin-top:14px;max-height:420px;overflow-y:auto">
      <table><thead><tr><th>Table</th><th>Tier</th><th class="r">Rows</th>
      <th>Why it exists</th></tr></thead><tbody>` +
    D.registry.tables.map(t=>`<tr><td class="name"><code>${esc(t.name)}</code></td>
      <td><span class="pill" style="background:${t.colour};color:#fff">${esc(t.tier)}</span></td>
      <td class="r">${N(t.rows)}</td>
      <td style="white-space:normal;min-width:420px"><b>${esc(t.why)}</b>
        <span style="color:var(--muted)"> ${esc(t.detail)}</span></td></tr>`).join('')
    +`</tbody></table></div>
    <div class="callout"><b>The fair criticism, and the answer.</b>
      ${esc(D.registry.counter)}</div>`);

  h+=card('Design decisions worth defending','',
    `<div style="display:flex;flex-direction:column;gap:11px">
      <div class="callout"><b>Dropped redundant fact attributes.</b> Merchant, Region and
        Channel appear on the sales fact and on MerchantReference. Profiling proved 100%
        agreement, so they were dropped from the facts — preventing two competing versions of
        "Region" from ever existing in the model.</div>
      <div class="callout"><b>SLA hours stored on the fact, not resolved from the dimension.</b>
        They agree today, but a future SLA policy change must not retrospectively restate
        whether a historic ticket breached. A ticket is judged against the SLA in force when
        it was raised.</div>
      <div class="callout"><b>Health Score computed in SQL, not DAX.</b> It requires percentile
        ranking across the whole merchant population — expensive in DAX, and it must be
        byte-identical in Power BI, the Excel pack and the ML feature set. One definition in
        the warehouse is what keeps three artefacts agreeing.</div>
      <div class="callout warn"><b>Kept the broken target field.</b> Targets are ~6.1× below
        realised sales. Rather than silently rescaling the client's number, it is retained
        unchanged, flagged as a data-quality finding, and a relative Target Attainment Index
        is reported alongside it. Confirming the intended basis is the first question for the
        business.</div>
    </div>`);
  h+=`</div>`;

  h+=card('Colour system','applied consistently across Power BI, Excel and this dashboard',
    `<div class="sw">
      <div style="background:#12305B">NAVY<br>#12305B<br><span style="opacity:.8">Primary,
        headers, sales</span></div>
      <div style="background:#0E8B8B">TEAL<br>#0E8B8B<br><span style="opacity:.8">Secondary,
        redemption</span></div>
      <div style="background:#E8A317;color:#2E2200">AMBER<br>#E8A317<br><span
        style="opacity:.8">Warning, targets</span></div>
      <div style="background:#C0392B">RED<br>#C0392B<br><span style="opacity:.8">Critical,
        breaches</span></div>
      <div style="background:#1E8449">GREEN<br>#1E8449<br><span style="opacity:.8">Positive,
        healthy</span></div>
      <div style="background:#7B4B94">PURPLE<br>#7B4B94<br><span style="opacity:.8">ML and
        predictions</span></div>
    </div>
    <div class="note">Semantic rather than decorative: red always means a threshold breach,
      green always means healthy, amber always means watch. Conditional formatting thresholds
      live in DAX measures (<code>Colour | Sales MoM</code>, <code>Colour | SLA Breach</code>)
      so the whole report restates consistently when a threshold changes, instead of needing
      each visual edited by hand.</div>`);
  return h;
}

/* ================= FILTERS =================
   State is a set of selected values per dimension; empty set means "all". Filtering is
   applied to the MERCHANT rows and the headline KPIs are recomputed from them, so a filtered
   view is internally consistent rather than showing national totals above a filtered table.

   Redemption rate is recomputed as a WEIGHTED figure (sum redeemed / sum sold), never as an
   average of per-merchant rates — averaging a ratio would weight a 3,500-voucher merchant
   the same as a 5,400-voucher one. */
const F = {Region:new Set(), Channel:new Set(), MerchantSizeBand:new Set()};
const FDIMS = [['Region','Region'],['Channel','Channel'],['MerchantSizeBand','Size band']];

function activeMerchants(){
  return D.merchants.filter(m =>
    (!F.Region.size || F.Region.has(m.Region)) &&
    (!F.Channel.size || F.Channel.has(m.Channel)) &&
    (!F.MerchantSizeBand.size || F.MerchantSizeBand.has(m.MerchantSizeBand)));
}
function anyFilter(){ return FDIMS.some(([k])=>F[k].size>0); }

/* Headline KPIs recomputed from whatever is selected. Falls back to the pre-aggregated
   gold figures when nothing is filtered, so the unfiltered view matches the warehouse
   exactly rather than being a client-side approximation of it. */
function kpis(){
  if(!anyFilter()) return D.kpis;
  const m = activeMerchants();
  const sum = k => m.reduce((a,x)=>a+(x[k]||0),0);
  const sales=sum('TotalSales'), txn=sum('TotalTransactions');
  const vs=sum('VouchersSold'), vr=m.reduce((a,x)=>a+(x.RedemptionRate||0)*(x.VouchersSold||0),0);
  const tk=sum('Tickets');
  return Object.assign({}, D.kpis, {
    TotalSales:sales, TotalTransactions:txn,
    AvgBasketValue: txn? sales/txn : 0,
    VouchersSold:vs, VouchersRedeemed:Math.round(vr),
    RedemptionRate: vs? vr/vs : 0,
    OutstandingLiability:sum('OutstandingValue'),
    TotalTickets:tk,
    SLABreachRate: tk? m.reduce((a,x)=>a+(x.SLABreachRate||0)*(x.Tickets||0),0)/tk : 0,
    TicketsPer1kTxn: txn? tk*1000/txn : 0,
    Merchants:m.length,
    _filtered:true
  });
}

function renderFilters(){
  const vals = k => [...new Set(D.merchants.map(m=>m[k]).filter(Boolean))].sort();
  const m = activeMerchants();
  let h = '<div class="fbar">';
  FDIMS.forEach(([k,label])=>{
    h += `<div class="fgrp"><span class="flab">${label}</span>` +
      vals(k).map(v=>`<button class="chip ${F[k].has(v)?'on':''}" data-dim="${k}"
        data-val="${esc(v)}">${esc(v)}</button>`).join('') + '</div>';
  });
  h += `<button class="chip reset" id="fReset">Reset</button>`;
  h += `<span class="fcount"><b>${m.length}</b> of ${D.merchants.length} merchants`
     + (anyFilter()? ` &middot; ${Rm(m.reduce((a,x)=>a+x.TotalSales,0))} of ${Rm(D.kpis.TotalSales)}`:'')
     + `</span></div>`;
  document.getElementById('filterbar').innerHTML = h;

  document.querySelectorAll('#filterbar .chip[data-dim]').forEach(b=>b.onclick=()=>{
    const s=F[b.dataset.dim];
    s.has(b.dataset.val)? s.delete(b.dataset.val) : s.add(b.dataset.val);
    refresh();
  });
  document.getElementById('fReset').onclick=()=>{
    FDIMS.forEach(([k])=>F[k].clear()); refresh();
  };
}

/* Rebuild the current page from scratch on any filter change — simpler and less error-prone
   than patching individual visuals, and fast enough at this data volume. */
function refresh(){
  renderFilters();
  const p = document.querySelector('nav button.on').dataset.p;
  built[p] = 0;
  show(p);
}

/* ---------------- dark mode ---------------- */
function initTheme(){
  const btn=document.getElementById('themeBtn');
  const set=d=>{
    document.body.classList.toggle('dark', d);
    btn.innerHTML = d ? '&#9788; Light mode' : '&#9789; Dark mode';
    try{ localStorage.setItem('mvi-dark', d?'1':'0'); }catch(e){}
  };
  let dark=false;
  try{ dark = localStorage.getItem('mvi-dark')==='1'; }catch(e){}
  set(dark);
  btn.onclick=()=>{ dark=!dark; set(dark);
    const p=document.querySelector('nav button.on').dataset.p; built[p]=0; show(p); };
}

/* ---------------- router ---------------- */
const PAGES={exec:pageExec,merchant:pageMerchant,geo:pageGeo,ops:pageOps,ai:pageAI,
             insights:pageInsights,build:pageBuild};
const built={};
function show(p){
  if(!built[p]){ document.getElementById('p-'+p).innerHTML = PAGES[p](); built[p]=1; }
  document.querySelectorAll('.page').forEach(e=>e.classList.remove('on'));
  document.getElementById('p-'+p).classList.add('on');
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.p===p));
  window.scrollTo({top:0,behavior:'smooth'});
}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>show(b.dataset.p));
// Filters only apply where merchant-level slicing is meaningful. Showing chips on the
// build walkthrough would imply they do something there.
const FILTERABLE = new Set(['exec','merchant','geo','ops']);
const _show = show;
show = function(p){
  document.getElementById('filterbar').style.display =
    FILTERABLE.has(p) ? 'block' : 'none';
  _show(p);
};
initTheme();
renderFilters();
show('exec');
</script>
</body>
</html>
"""

OUT.write_text(HTML.replace("__PAYLOAD__", payload), encoding="utf-8")
print(f"Wrote {OUT}")
print(f"  {OUT.stat().st_size / 1024:.0f} KB, 7 pages, fully self-contained (no external assets)")
