"""
build_dashboard.py
==================
Generates dashboard/index.html - a single self-contained file that mirrors the
Power BI report page-for-page, so the solution can be demonstrated without a
Fabric capacity or Power BI Desktop.

The data is embedded as compact columnar arrays and every visual is computed in
the browser from those arrays, so the slicers genuinely cross-filter rather than
switching between pre-rendered pictures.

Run:  python build/build_dashboard.py   (after build_gold.py, build_insights.py,
                                         build_ml.py)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
DOCS = ROOT / "docs"
DASH = ROOT / "dashboard"
TEMPLATES = Path(__file__).resolve().parent / "dashboard_assets"


def build_payload() -> dict:
    dim_date = pd.read_csv(GOLD / "DimDate.csv", parse_dates=["Date"])
    merch = pd.read_csv(GOLD / "DimMerchant.csv")
    vt = pd.read_csv(GOLD / "DimVoucherType.csv")
    tt = pd.read_csv(GOLD / "DimTicketType.csv")
    prio = pd.read_csv(GOLD / "DimPriority.csv").sort_values("PrioritySort")
    sales = pd.read_csv(GOLD / "FactMerchantSales.csv")
    red = pd.read_csv(GOLD / "FactVoucherRedemptions.csv")
    tick = pd.read_csv(GOLD / "FactSupportTickets.csv")
    seg = pd.read_csv(GOLD / "DimMerchantSegment.csv")
    anomaly = pd.read_csv(GOLD / "FactAnomaly.csv")
    narrative = pd.read_csv(GOLD / "InsightNarrative.csv")
    forecast = pd.read_csv(GOLD / "FactSalesForecast.csv", parse_dates=["Date"])
    mforecast = pd.read_csv(GOLD / "FactMerchantForecast.csv")
    perf = pd.read_csv(GOLD / "MLModelPerformance.csv")
    imp = pd.read_csv(GOLD / "MLFeatureImportance.csv")
    vrisk = pd.read_csv(GOLD / "MLVoucherRiskScore.csv")
    ml = json.loads((DOCS / "_ml_results.json").read_text(encoding="utf8"))
    fig = json.loads((DOCS / "_computed_findings.json").read_text(encoding="utf8"))

    # Only calendar days a fact can land on; the tail of DimDate exists for
    # redemption dates and would otherwise pad every axis with empty months.
    used = sorted(set(sales["DateKey"]) | set(tick["DateKey"]))
    dd = dim_date[dim_date["DateKey"].isin(used)].sort_values("DateKey")
    date_idx = {int(k): i for i, k in enumerate(dd["DateKey"])}
    months = (dd[["MonthYear", "MonthYearSort"]].drop_duplicates()
              .sort_values("MonthYearSort"))
    month_idx = {int(s): i for i, s in enumerate(months["MonthYearSort"])}
    dd = dd.assign(_mi=dd["MonthYearSort"].map(month_idx))

    m_idx = {k: i for i, k in enumerate(merch["MerchantKey"])}
    v_idx = {k: i for i, k in enumerate(vt["VoucherTypeKey"])}
    t_idx = {k: i for i, k in enumerate(tt["TicketTypeKey"])}
    p_idx = {k: i for i, k in enumerate(prio["PriorityKey"])}

    seg_by_key = seg.set_index("MerchantKey")
    nar_by_key = narrative.set_index("MerchantKey")
    fc_by_key = mforecast.set_index("MerchantKey")

    merchants = []
    for _, r in merch.iterrows():
        k = r["MerchantKey"]
        s = seg_by_key.loc[k]
        merchants.append({
            "k": k, "n": r["Merchant"], "r": r["Region"], "c": r["Channel"],
            "st": r["ActiveStatus"], "am": r["AccountManager"],
            "tgt": float(r["BaseMonthlySalesTarget"]),
            "seg": s["Segment"], "hs": float(s["HealthScore"]),
            "tier": s["RiskTier"], "p1": float(s["PCA1"]), "p2": float(s["PCA2"]),
            "slope": float(s["GrowthSlopePct"]),
            "att": float(s["TargetAttainmentPct"]),
            "nar": (nar_by_key.loc[k, "Narrative"] if k in nar_by_key.index else ""),
            "flag": (nar_by_key.loc[k, "ActionFlag"] if k in nar_by_key.index else ""),
            "mom": (float(nar_by_key.loc[k, "SalesMoMPct"])
                    if k in nar_by_key.index else 0.0),
            "fc": (float(fc_by_key.loc[k, "Next30DaysForecast"])
                   if k in fc_by_key.index else 0.0),
            "fcchg": (float(fc_by_key.loc[k, "ExpectedChangePct"])
                      if k in fc_by_key.index else 0.0),
        })

    s = sales.copy()
    s["d"] = s["DateKey"].map(date_idx)
    s["m"] = s["MerchantKey"].map(m_idx)
    s["v"] = s["VoucherTypeKey"].map(v_idx)
    sales_cols = {
        "d": s["d"].tolist(), "m": s["m"].tolist(), "v": s["v"].tolist(),
        "s": s["SalesValue"].round(2).tolist(), "t": s["Transactions"].tolist(),
    }

    # Redemptions are cubed rather than shipped row by row: 121k rows would
    # bloat the file, and every visual on the page needs them only at
    # merchant x voucher-type x sold-month grain.
    r = red.copy()
    r["mo"] = (r["SoldDateKey"] // 100 % 100
               + (r["SoldDateKey"] // 10000) * 100).map(month_idx)
    r["m"] = r["MerchantKey"].map(m_idx)
    r["v"] = r["VoucherTypeKey"].map(v_idx)
    cube = (r.groupby(["m", "v", "mo"], as_index=False)
            .agg(n=("VoucherID", "count"), rd=("IsRedeemed", "sum"),
                 val=("VoucherValue", "sum"),
                 sd=("DaysToRedeem", "sum"),
                 dl=("IsDelayedRedemption", "sum")))
    red_cols = {c: cube[c].fillna(0).round(2).tolist() for c in
                ("m", "v", "mo", "n", "rd", "val", "sd", "dl")}

    tk = tick.copy()
    tk["d"] = tk["DateKey"].map(date_idx)
    tk["m"] = tk["MerchantKey"].map(m_idx)
    tk["tt"] = tk["TicketTypeKey"].map(t_idx)
    tk["p"] = tk["PriorityKey"].map(p_idx)
    tick_cols = {
        "d": tk["d"].tolist(), "m": tk["m"].tolist(), "tt": tk["tt"].tolist(),
        "p": tk["p"].tolist(), "res": tk["ResolutionHours"].round(1).tolist(),
        "br": tk["IsSLABreach"].tolist(), "op": tk["IsOpen"].tolist(),
    }

    # Weekly region x voucher-type redemption lag, for the delay heat strip.
    lag = pd.DataFrame(fig["lag_grid"])

    # --- geography ---------------------------------------------------------
    geo = json.loads((ROOT / "data" / "reference" /
                      "za_provinces_simplified.json").read_text(encoding="utf8"))
    covered = set(merch["Region"])
    for province in geo["provinces"]:
        # Flagged rather than dropped: the four provinces with no merchants are
        # the most interesting thing on the map, and a province absent from a
        # choropleth reads as "zero sales" when it actually means "no presence".
        province["covered"] = province["name"] in covered
        province["merchants"] = int((merch["Region"] == province["name"]).sum())

    return {
        "meta": {
            "months": months["MonthYear"].tolist(),
            "periodStart": str(dd["Date"].min().date()),
            "periodEnd": str(dd["Date"].max().date()),
            "generated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        },
        "dates": [d.strftime("%Y-%m-%d") for d in dd["Date"]],
        "dateMonth": dd["_mi"].tolist(),
        "merch": merchants,
        "vt": vt["VoucherTypeKey"].tolist(),
        "tt": tt["TicketTypeKey"].tolist(),
        "ttCat": tt.set_index("TicketTypeKey")["TicketCategory"].to_dict(),
        "prio": [{"n": r["PriorityKey"], "sla": int(r["SLATargetHours"])}
                 for _, r in prio.iterrows()],
        "sales": sales_cols,
        "red": red_cols,
        "tick": tick_cols,
        "lag": lag.to_dict("records"),
        "geo": geo,
        "anomalies": anomaly.fillna("").to_dict("records"),
        "correlation": fig["correlation"],
        "concentration": fig["concentration"],
        "ml": {
            "performance": perf.fillna("").to_dict("records"),
            "importance": imp.to_dict("records"),
            "segments": ml["segmentation"]["segments"],
            "silhouette": ml["segmentation"]["silhouette_by_k"],
            "k": ml["segmentation"]["k"],
            "pcaVar": ml["segmentation"]["pca_variance"],
            "healthWeights": ml["segmentation"]["health_weights"],
            "forecast": [
                {"d": d.strftime("%Y-%m-%d"), "f": float(f), "lo": float(lo),
                 "hi": float(hi)}
                for d, f, lo, hi in zip(forecast["Date"],
                                        forecast["ForecastSalesValue"],
                                        forecast["LowerBound"],
                                        forecast["UpperBound"])],
            "backtest": ml["forecast"]["backtest"],
            "candidates": ml["forecast"]["candidates"],
            "selected": ml["forecast"]["selected_model"],
            "mape": ml["forecast"]["mape"],
            "naiveMape": ml["forecast"]["naive_mape"],
            "voucherRisk": vrisk.head(12).to_dict("records"),
            "breakage": ml["vouchers"]["expected_breakage_value"],
            "slaAuc": ml["sla"]["auc"],
            "redeemAuc": ml["vouchers"]["IsRedeemed"]["auc"],
            "delayAuc": ml["vouchers"]["IsDelayedRedemption"]["auc"],
        },
    }


def main() -> None:
    payload = build_payload()
    css = (TEMPLATES / "styles.css").read_text(encoding="utf8")
    js = (TEMPLATES / "app.js").read_text(encoding="utf8")
    body = (TEMPLATES / "body.html").read_text(encoding="utf8")

    data_json = json.dumps(payload, separators=(",", ":"), default=str)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Merchant Sales &amp; Voucher Intelligence</title>
<style>
{css}
</style>
</head>
<body data-palette="#2a78d6,#eb6834,#1baf7a,#eda100,#e87ba4" data-mode="light">
{body}
<script>
const DATA = {data_json};
</script>
<script>
{js}
</script>
</body>
</html>
"""
    DASH.mkdir(exist_ok=True)
    out = DASH / "index.html"
    out.write_text(html, encoding="utf8")
    size_kb = out.stat().st_size / 1024
    print(f"dashboard/index.html written ({size_kb:,.0f} KB)")
    print(f"  sales rows embedded : {len(payload['sales']['d']):,}")
    print(f"  redemption cube rows: {len(payload['red']['m']):,}")
    print(f"  ticket rows         : {len(payload['tick']['d']):,}")
    print(f"  merchants           : {len(payload['merch'])}")


if __name__ == "__main__":
    main()
