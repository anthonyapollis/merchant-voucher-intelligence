"""
build_ml.py
===========
Machine-learning layer over the certified gold star schema.

Five models, each chosen because the data can actually support it, and each
evaluated on data the model never saw:

  1. Voucher redemption propensity   121k rows, time-based split (train Jan-May,
                                     test Jun-Jul). Gradient boosting vs a
                                     logistic baseline; the better held-out
                                     ROC-AUC wins.
  2. Delayed-redemption classifier   same split, predicts >7-day redemption lag.
  3. SLA breach classifier           1.4k rows, stratified 5-fold CV.
  4. Merchant segmentation           K-Means on 9 standardised behavioural
                                     features, k chosen by silhouette, PCA for
                                     plotting.
  5. Daily sales forecast            Holt-Winters (additive trend + weekly
                                     seasonality), backtested on a held-out
                                     28-day window before refitting on all data.

Plus a transparent Merchant Health Score. That one is deliberately NOT a
trained model: with 25 merchants there is no honest way to fit and validate a
churn classifier, and a weighted index whose components are visible is more
useful to an account manager than a black box fitted to 25 points.

Outputs (all land in data/gold as report-ready tables)
  DimMerchantSegment.csv      segment label, PCA coords, health score
  FactSalesForecast.csv       30-day forward forecast with prediction interval
  MLModelPerformance.csv      one row per model: metric, value, holdout method
  MLFeatureImportance.csv     top drivers per model
  MLVoucherRiskScore.csv      merchant x voucher-type non-redemption risk
  docs/_ml_results.json       everything above, for the docs and dashboard

Run:  python build/build_ml.py   (after build_gold.py)
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             roc_auc_score)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.metrics import silhouette_score
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
DOCS = ROOT / "docs"
RANDOM_STATE = 42

perf: list[dict] = []
importance: list[dict] = []


def log_metric(model: str, metric: str, value: float, holdout: str,
               n_train: int, n_test: int, note: str = "") -> None:
    perf.append({"Model": model, "Metric": metric, "Value": round(float(value), 4),
                 "HoldoutMethod": holdout, "TrainRows": n_train,
                 "TestRows": n_test, "Note": note})


def load() -> dict[str, pd.DataFrame]:
    t = {n: pd.read_csv(GOLD / f"{n}.csv") for n in
         ("DimDate", "DimMerchant", "DimVoucherType", "DimTicketType",
          "DimPriority", "FactMerchantSales", "FactVoucherRedemptions",
          "FactSupportTickets")}
    t["DimDate"]["Date"] = pd.to_datetime(t["DimDate"]["Date"])
    return t


# ============================================================ 1 + 2. vouchers
def voucher_models(t: dict[str, pd.DataFrame]) -> dict:
    d = t["DimDate"][["DateKey", "Date", "MonthYearSort", "DayOfWeek", "IsWeekend",
                      "Day"]]
    m = t["DimMerchant"][["MerchantKey", "Merchant", "Region", "Channel",
                          "ActiveStatus", "TenureMonths"]]
    v = t["DimVoucherType"][["VoucherTypeKey", "SettlementModel"]]

    df = (t["FactVoucherRedemptions"]
          .merge(d.rename(columns={"DateKey": "SoldDateKey", "Date": "SoldDate"}),
                 on="SoldDateKey")
          .merge(m, on="MerchantKey")
          .merge(v, on="VoucherTypeKey"))

    # Time-based split. A random split would let the model see vouchers sold on
    # the same day as the ones it is scoring, which is not how it runs in
    # production - production always scores forward in time.
    cutoff = 202606
    train = df[df["MonthYearSort"] < cutoff].copy()
    test = df[df["MonthYearSort"] >= cutoff].copy()

    # Merchant and voucher-type behavioural priors, computed on the TRAIN window
    # only, then applied to both. Computing them on the full frame would leak
    # the test period's outcome into the test features.
    prior_m = train.groupby("MerchantKey")["IsRedeemed"].mean().rename("MerchantPrior")
    prior_v = train.groupby("VoucherTypeKey")["IsRedeemed"].mean().rename("VTypePrior")
    global_prior = train["IsRedeemed"].mean()
    for frame in (train, test):
        frame["MerchantPrior"] = frame["MerchantKey"].map(prior_m).fillna(global_prior)
        frame["VTypePrior"] = frame["VoucherTypeKey"].map(prior_v).fillna(global_prior)
        # Voucher value relative to that voucher type's typical ticket.
        frame["ValueBand"] = pd.cut(frame["VoucherValue"],
                                    bins=[0, 50, 100, 200, 500, 10_000],
                                    labels=["<50", "50-100", "100-200",
                                            "200-500", "500+"]).astype(str)

    cat = ["VoucherTypeKey", "Region", "Channel", "SettlementModel", "ValueBand",
           "ActiveStatus"]
    num = ["VoucherValue", "DayOfWeek", "IsWeekend", "Day", "TenureMonths",
           "MerchantPrior", "VTypePrior"]
    feats = cat + num

    results: dict = {}

    for target, label in (("IsRedeemed", "Voucher Redemption Propensity"),
                          ("IsDelayedRedemption", "Delayed Redemption Risk")):
        tr, te = train.copy(), test.copy()
        if target == "IsDelayedRedemption":
            # Only redeemed vouchers have a delay outcome at all.
            tr = tr[tr["IsRedeemed"] == 1]
            te = te[te["IsRedeemed"] == 1]
        y_tr, y_te = tr[target].astype(int), te[target].astype(int)

        pre = ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat),
            ("num", StandardScaler(), num),
        ])

        candidates = {
            "Logistic regression": Pipeline([
                ("pre", pre),
                ("clf", LogisticRegression(max_iter=2000, C=1.0,
                                           random_state=RANDOM_STATE)),
            ]),
            "Gradient boosting": Pipeline([
                ("pre", ColumnTransformer([
                    ("cat", OneHotEncoder(handle_unknown="ignore",
                                          sparse_output=False), cat),
                    ("num", "passthrough", num),
                ])),
                ("clf", HistGradientBoostingClassifier(
                    max_iter=250, learning_rate=0.08, max_depth=6,
                    early_stopping=True, validation_fraction=0.15,
                    random_state=RANDOM_STATE)),
            ]),
        }

        scored = {}
        for name, pipe in candidates.items():
            pipe.fit(tr[feats], y_tr)
            p = pipe.predict_proba(te[feats])[:, 1]
            scored[name] = (pipe, p, roc_auc_score(y_te, p))

        best_name = max(scored, key=lambda k: scored[k][2])
        best_pipe, p_best, auc = scored[best_name]

        log_metric(label, "ROC-AUC", auc, f"Time split: train <{cutoff}, test >=",
                   len(tr), len(te), f"winning algorithm: {best_name}")
        log_metric(label, "PR-AUC", average_precision_score(y_te, p_best),
                   f"Time split: train <{cutoff}, test >=", len(tr), len(te),
                   f"base rate {y_te.mean():.3f}")
        log_metric(label, "Brier score", brier_score_loss(y_te, p_best),
                   f"Time split: train <{cutoff}, test >=", len(tr), len(te),
                   "lower is better; measures probability calibration")
        for name, (_, _, a) in scored.items():
            if name != best_name:
                log_metric(label, f"ROC-AUC ({name})", a,
                           f"Time split: train <{cutoff}, test >=", len(tr), len(te),
                           "challenger")

        # Permutation importance on the held-out set: how much does held-out
        # AUC drop when this feature is shuffled? Model-agnostic and honest.
        sample = te.sample(min(20_000, len(te)), random_state=RANDOM_STATE)
        pi = permutation_importance(
            best_pipe, sample[feats], sample[target].astype(int),
            scoring="roc_auc", n_repeats=5, random_state=RANDOM_STATE)
        for f_name, mean_drop in sorted(zip(feats, pi.importances_mean),
                                        key=lambda x: -x[1])[:8]:
            importance.append({"Model": label, "Feature": f_name,
                               "ImportanceAUCDrop": round(float(mean_drop), 5)})

        results[target] = {
            "label": label, "algorithm": best_name, "auc": round(float(auc), 4),
            "base_rate": round(float(y_te.mean()), 4),
            "n_train": int(len(tr)), "n_test": int(len(te)),
            "pipe": best_pipe, "test": te, "proba": p_best, "feats": feats,
        }

    # --- diagnostic: is the delay signal absent, or just absent in Jun-Jul? --
    # The forward-looking model scores near chance. This second evaluation
    # trains on Jan-Mar and tests on April, the month containing the known
    # Western Cape / Bill Payment delay incident. If AUC jumps here but not in
    # the forward window, the delay is an isolated incident rather than a
    # standing pattern - which is a business finding, not a modelling failure.
    dr = df[df["IsRedeemed"] == 1].copy()
    dr["MerchantPrior"] = dr["MerchantKey"].map(prior_m).fillna(global_prior)
    dr["VTypePrior"] = dr["VoucherTypeKey"].map(prior_v).fillna(global_prior)
    dr["ValueBand"] = pd.cut(dr["VoucherValue"], bins=[0, 50, 100, 200, 500, 10_000],
                             labels=["<50", "50-100", "100-200", "200-500",
                                     "500+"]).astype(str)
    a_tr = dr[dr["MonthYearSort"] < 202604]
    a_te = dr[dr["MonthYearSort"] == 202604]
    diag = Pipeline([
        ("pre", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat),
            ("num", StandardScaler(), num),
        ])),
        ("clf", LogisticRegression(max_iter=2000, random_state=RANDOM_STATE)),
    ]).fit(a_tr[feats], a_tr["IsDelayedRedemption"].astype(int))
    a_auc = roc_auc_score(a_te["IsDelayedRedemption"].astype(int),
                          diag.predict_proba(a_te[feats])[:, 1])
    log_metric("Delayed Redemption Risk", "ROC-AUC (Jan-Mar -> April diagnostic)",
               a_auc, "Time split: train <202604, test = April",
               len(a_tr), len(a_te),
               "tests whether the April incident was predictable from prior months")

    # --- merchant x voucher-type non-redemption risk table -----------------
    r = results["IsRedeemed"]
    te = r["test"].copy()
    te["PredRedeemProb"] = r["proba"]
    risk = (te.groupby(["MerchantKey", "Merchant", "Region", "VoucherTypeKey"],
                       as_index=False)
            .agg(Vouchers=("VoucherID", "count"),
                 PredictedRedemptionRate=("PredRedeemProb", "mean"),
                 ActualRedemptionRate=("IsRedeemed", "mean"),
                 VoucherValue=("VoucherValue", "sum")))
    risk["PredictedRedemptionRate"] *= 100
    risk["ActualRedemptionRate"] *= 100
    risk["NonRedemptionRisk"] = 100 - risk["PredictedRedemptionRate"]
    # Rand value of vouchers the model expects never to be redeemed - the
    # breakage liability sitting on the balance sheet.
    risk["ExpectedUnredeemedValue"] = (risk["VoucherValue"]
                                       * risk["NonRedemptionRisk"] / 100)
    risk = risk.sort_values("ExpectedUnredeemedValue", ascending=False)
    risk.round(2).to_csv(GOLD / "MLVoucherRiskScore.csv", index=False)

    return {k: {kk: vv for kk, vv in val.items()
                if kk not in ("pipe", "test", "proba", "feats")}
            for k, val in results.items()} | {
        "risk_table": risk.round(2).head(15).to_dict("records"),
        "expected_breakage_value": round(float(risk["ExpectedUnredeemedValue"].sum()), 2),
    }


# ================================================================= 3. SLA
def sla_model(t: dict[str, pd.DataFrame]) -> dict:
    d = t["DimDate"][["DateKey", "Date", "DayOfWeek", "IsWeekend", "MonthNumber"]]
    m = t["DimMerchant"][["MerchantKey", "Merchant", "Region", "Channel",
                          "TenureMonths"]]
    p = t["DimPriority"][["PriorityKey", "SLATargetHours", "PrioritySort"]]
    tt = t["DimTicketType"][["TicketTypeKey", "TicketCategory"]]

    df = (t["FactSupportTickets"].merge(d, on="DateKey").merge(m, on="MerchantKey")
          .merge(p, on="PriorityKey").merge(tt, on="TicketTypeKey"))

    # Merchant workload at the moment the ticket was raised: how many tickets
    # that merchant logged in the preceding 14 days. Known at creation time,
    # unlike Status.
    df = df.sort_values("Date").reset_index(drop=True)
    load = []
    for mk, grp in df.groupby("MerchantKey"):
        counts = (grp.set_index("Date")["TicketID"].resample("D").count()
                  .rolling(14, min_periods=1).sum().shift(1).fillna(0))
        load.append(grp.assign(MerchantTicketLoad14d=grp["Date"].map(counts)))
    df = pd.concat(load).sort_values("Date").reset_index(drop=True)
    df["MerchantTicketLoad14d"] = df["MerchantTicketLoad14d"].fillna(0)

    # Status is deliberately excluded. It is only known after the ticket has
    # been worked - an 'Escalated' ticket is escalated *because* it ran long -
    # so including it inflates AUC while being useless at ticket creation,
    # which is the only moment a breach-risk score can change the outcome.
    cat = ["PriorityKey", "TicketTypeKey", "TicketCategory", "Region", "Channel"]
    num = ["SLATargetHours", "PrioritySort", "DayOfWeek", "IsWeekend",
           "MonthNumber", "TenureMonths", "MerchantTicketLoad14d"]
    feats = cat + num
    y = df["IsSLABreach"].astype(int)

    # 1,363 rows is too few for a single held-out split to give a stable
    # estimate, so this one uses repeated stratified CV instead.
    pipe = Pipeline([
        ("pre", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat),
            ("num", StandardScaler(), num),
        ])),
        ("clf", LogisticRegression(max_iter=2000, random_state=RANDOM_STATE)),
    ])
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    proba = cross_val_predict(pipe, df[feats], y, cv=cv, method="predict_proba")[:, 1]
    auc = roc_auc_score(y, proba)

    log_metric("SLA Breach Risk", "ROC-AUC", auc, "Stratified 5-fold CV",
               int(len(df) * 0.8), int(len(df) * 0.2),
               f"base breach rate {y.mean():.3f}; Status excluded as leakage")
    log_metric("SLA Breach Risk", "PR-AUC", average_precision_score(y, proba),
               "Stratified 5-fold CV", int(len(df) * 0.8), int(len(df) * 0.2), "")

    # Documented for contrast: what the same model scores if Status is left in.
    # The gap is the size of the leak, not a better model.
    leak = Pipeline([
        ("pre", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
             cat + ["Status"]),
            ("num", StandardScaler(), num),
        ])),
        ("clf", LogisticRegression(max_iter=2000, random_state=RANDOM_STATE)),
    ])
    leak_proba = cross_val_predict(leak, df[feats + ["Status"]], y, cv=cv,
                                   method="predict_proba")[:, 1]
    log_metric("SLA Breach Risk", "ROC-AUC (with leaked Status feature)",
               roc_auc_score(y, leak_proba), "Stratified 5-fold CV",
               int(len(df) * 0.8), int(len(df) * 0.2),
               "rejected: Status is unknown at ticket creation")

    pipe.fit(df[feats], y)
    pi = permutation_importance(pipe, df[feats], y, scoring="roc_auc",
                                n_repeats=10, random_state=RANDOM_STATE)
    for f_name, mean_drop in sorted(zip(feats, pi.importances_mean),
                                    key=lambda x: -x[1])[:8]:
        importance.append({"Model": "SLA Breach Risk", "Feature": f_name,
                           "ImportanceAUCDrop": round(float(mean_drop), 5)})

    df["PredBreachProb"] = proba
    by_merchant = (df.groupby(["MerchantKey", "Merchant"], as_index=False)
                   .agg(Tickets=("TicketID", "count"),
                        PredBreachRate=("PredBreachProb", "mean"),
                        ActualBreachRate=("IsSLABreach", "mean")))
    by_merchant[["PredBreachRate", "ActualBreachRate"]] *= 100

    return {"auc": round(float(auc), 4), "base_rate": round(float(y.mean()), 4),
            "n": int(len(df)),
            "by_merchant": by_merchant.round(2).sort_values(
                "ActualBreachRate", ascending=False).to_dict("records")}


# ======================================================== 4. segmentation
def segment_merchants(t: dict[str, pd.DataFrame]) -> dict:
    d = t["DimDate"][["DateKey", "MonthYearSort"]]
    sales = t["FactMerchantSales"].merge(d, on="DateKey")
    red = t["FactVoucherRedemptions"].merge(
        d.rename(columns={"DateKey": "SoldDateKey"}), on="SoldDateKey")
    tick = t["FactSupportTickets"].merge(d, on="DateKey")

    base = (sales.groupby("MerchantKey", as_index=False)
            .agg(TotalSales=("SalesValue", "sum"),
                 TotalTransactions=("Transactions", "sum")))
    base["AvgBasket"] = base["TotalSales"] / base["TotalTransactions"]

    # Growth slope: OLS on monthly sales, normalised by the merchant's own mean
    # so a big merchant and a small one growing at the same rate score the same.
    monthly = (sales.groupby(["MerchantKey", "MonthYearSort"], as_index=False)
               .agg(SalesValue=("SalesValue", "sum")))
    slopes = []
    for mk, grp in monthly.groupby("MerchantKey"):
        grp = grp.sort_values("MonthYearSort")
        x = np.arange(len(grp))
        slope = np.polyfit(x, grp["SalesValue"], 1)[0]
        slopes.append({"MerchantKey": mk,
                       "GrowthSlopePct": slope / grp["SalesValue"].mean() * 100,
                       "Volatility": grp["SalesValue"].std() / grp["SalesValue"].mean()})
    base = base.merge(pd.DataFrame(slopes), on="MerchantKey")

    r = (red.groupby("MerchantKey", as_index=False)
         .agg(RedemptionRate=("IsRedeemed", "mean"),
              AvgDaysToRedeem=("DaysToRedeem", "mean"),
              DelayedRate=("IsDelayedRedemption", "mean")))
    r[["RedemptionRate", "DelayedRate"]] *= 100
    base = base.merge(r, on="MerchantKey", how="left")

    tk = (tick.groupby("MerchantKey", as_index=False)
          .agg(Tickets=("TicketID", "count"),
               AvgResolutionHours=("ResolutionHours", "mean"),
               SLABreachRate=("IsSLABreach", "mean")))
    tk["SLABreachRate"] *= 100
    base = base.merge(tk, on="MerchantKey", how="left").fillna(
        {"Tickets": 0, "AvgResolutionHours": 0, "SLABreachRate": 0})
    base["TicketsPer1kTx"] = base["Tickets"] / base["TotalTransactions"] * 1000

    base = base.merge(t["DimMerchant"], on="MerchantKey")
    # Target attainment uses the reference table's monthly target x 7 months.
    months = sales["MonthYearSort"].nunique()
    base["TargetAttainmentPct"] = (base["TotalSales"]
                                   / (base["BaseMonthlySalesTarget"] * months) * 100)

    features = ["TotalSales", "AvgBasket", "GrowthSlopePct", "Volatility",
                "RedemptionRate", "DelayedRate", "TicketsPer1kTx",
                "SLABreachRate", "TargetAttainmentPct"]
    X = StandardScaler().fit_transform(base[features])

    # k selected by silhouette rather than assumed. With 25 merchants the
    # sensible search range is small.
    scores = {}
    for k in range(2, 7):
        km = KMeans(n_clusters=k, n_init=25, random_state=RANDOM_STATE).fit(X)
        scores[k] = float(silhouette_score(X, km.labels_))
    best_k = max(scores, key=scores.get)
    km = KMeans(n_clusters=best_k, n_init=25, random_state=RANDOM_STATE).fit(X)
    base["SegmentID"] = km.labels_

    log_metric("Merchant Segmentation", "Silhouette score", scores[best_k],
               f"K-Means, k={best_k} of {list(scores)} by silhouette",
               len(base), 0, f"all k: " + ", ".join(f"k={k}:{v:.3f}"
                                                    for k, v in scores.items()))

    pca = PCA(n_components=2, random_state=RANDOM_STATE)
    coords = pca.fit_transform(X)
    base["PCA1"], base["PCA2"] = coords[:, 0], coords[:, 1]
    log_metric("Merchant Segmentation", "PCA variance explained (2 components)",
               float(pca.explained_variance_ratio_.sum()), "n/a", len(base), 0,
               "how much of the 9-feature spread the scatter plot shows")

    # Name each cluster from its own centroid rather than by hand, so the label
    # stays correct if the data changes.
    profile = base.groupby("SegmentID")[features].mean()
    ranks = profile.rank(pct=True)
    names, descriptions = {}, {}
    for seg in profile.index:
        row = ranks.loc[seg]
        if row["TotalSales"] >= 0.75 and row["GrowthSlopePct"] >= 0.5:
            name = "Scale drivers"
        elif row["TicketsPer1kTx"] >= 0.75 or row["SLABreachRate"] >= 0.75:
            name = "High-friction accounts"
        elif row["GrowthSlopePct"] <= 0.25:
            name = "Stalling accounts"
        elif row["TotalSales"] <= 0.35:
            name = "Long-tail small merchants"
        else:
            name = "Steady core"
        while name in names.values():
            name += " (2)"
        names[seg] = name
        descriptions[seg] = (
            f"{len(base[base.SegmentID == seg])} merchants | "
            f"avg sales R{profile.loc[seg, 'TotalSales']:,.0f} | "
            f"growth slope {profile.loc[seg, 'GrowthSlopePct']:+.1f}%/mo | "
            f"{profile.loc[seg, 'TicketsPer1kTx']:.2f} tickets/1k tx | "
            f"redemption {profile.loc[seg, 'RedemptionRate']:.1f}%")
    base["Segment"] = base["SegmentID"].map(names)
    base["SegmentProfile"] = base["SegmentID"].map(descriptions)

    # --- Merchant Health Score --------------------------------------------
    # Transparent weighted index, not a fitted model. Each component is a
    # percentile rank within the merchant base, so the score answers "how does
    # this merchant compare to its peers", which is the question an account
    # manager actually asks. Weights are a stated business judgement.
    weights = {"GrowthSlopePct": 0.30, "TargetAttainmentPct": 0.20,
               "RedemptionRate": 0.20, "TicketsPer1kTx": -0.15,
               "SLABreachRate": -0.10, "DelayedRate": -0.05}
    score = pd.Series(0.0, index=base.index)
    for col, w in weights.items():
        pct = base[col].rank(pct=True)
        score += (pct if w > 0 else (1 - pct)) * abs(w)
        base[f"HC_{col}"] = (pct * 100).round(1)
    base["HealthScore"] = (score / sum(abs(w) for w in weights.values()) * 100).round(1)
    base["RiskTier"] = pd.cut(base["HealthScore"], bins=[-1, 35, 55, 75, 101],
                              labels=["Critical", "At risk", "Watch", "Healthy"]
                              ).astype(str)

    out_cols = ["MerchantKey", "Merchant", "Region", "Channel", "ActiveStatus",
                "AccountManager", "Segment", "SegmentID", "SegmentProfile",
                "PCA1", "PCA2", "HealthScore", "RiskTier", "TotalSales",
                "TotalTransactions", "AvgBasket", "GrowthSlopePct", "Volatility",
                "RedemptionRate", "AvgDaysToRedeem", "DelayedRate", "Tickets",
                "TicketsPer1kTx", "AvgResolutionHours", "SLABreachRate",
                "BaseMonthlySalesTarget", "TargetAttainmentPct"]
    seg_out = base[out_cols].round(3).sort_values("HealthScore")
    seg_out.to_csv(GOLD / "DimMerchantSegment.csv", index=False)

    return {
        "k": best_k, "silhouette_by_k": {str(k): round(v, 4) for k, v in scores.items()},
        "pca_variance": round(float(pca.explained_variance_ratio_.sum()), 4),
        "segments": [
            {"SegmentID": int(s), "Segment": names[s], "Profile": descriptions[s],
             "Merchants": base.loc[base.SegmentID == s, "Merchant"].tolist(),
             "Count": int((base.SegmentID == s).sum())}
            for s in sorted(profile.index)],
        "merchants": seg_out.to_dict("records"),
        "feature_names": features,
        "health_weights": weights,
    }


# =========================================================== 5. forecasting
def forecast_sales(t: dict[str, pd.DataFrame], horizon: int = 30) -> dict:
    d = t["DimDate"][["DateKey", "Date"]]
    sales = t["FactMerchantSales"].merge(d, on="DateKey")
    daily = (sales.groupby("Date", as_index=False)
             .agg(SalesValue=("SalesValue", "sum")).sort_values("Date"))
    series = daily.set_index("Date")["SalesValue"].asfreq("D")

    # Candidate bake-off. Picking a model family up front and reporting only
    # its error is how a forecast ends up worse than repeating last week.
    # Every candidate here is scored on the same held-out window, including
    # the naive benchmark, and the winner is whichever actually wins.
    def hw(train: pd.Series, **kw):
        return ExponentialSmoothing(train, seasonal_periods=7,
                                    initialization_method="estimated",
                                    **kw).fit()

    def ols_trend_dow(train: pd.Series, steps: int):
        """Linear trend + day-of-week factors, fitted by least squares."""
        x = np.arange(len(train))
        dow = pd.get_dummies(train.index.dayofweek, prefix="d", drop_first=True)
        X = np.column_stack([np.ones(len(train)), x, dow.values.astype(float)])
        beta, *_ = np.linalg.lstsq(X, train.values, rcond=None)
        future_idx = pd.date_range(train.index[-1] + pd.Timedelta(days=1),
                                   periods=steps)
        fx = np.arange(len(train), len(train) + steps)
        fdow = pd.get_dummies(future_idx.dayofweek, prefix="d", drop_first=True)
        fdow = fdow.reindex(columns=dow.columns, fill_value=0)
        FX = np.column_stack([np.ones(steps), fx, fdow.values.astype(float)])
        return pd.Series(FX @ beta, index=future_idx)

    candidates = {
        "Holt-Winters (add trend, add seasonal)":
            lambda tr, h: hw(tr, trend="add", seasonal="add").forecast(h),
        "Holt-Winters (damped trend, add seasonal)":
            lambda tr, h: hw(tr, trend="add", damped_trend=True,
                             seasonal="add").forecast(h),
        "Holt-Winters (add trend, mul seasonal)":
            lambda tr, h: hw(tr, trend="add", seasonal="mul").forecast(h),
        "OLS linear trend + day-of-week": ols_trend_dow,
        "Seasonal naive (last week repeated)":
            lambda tr, h: pd.Series(
                np.resize(tr.values[-7:], h),
                index=pd.date_range(tr.index[-1] + pd.Timedelta(days=1), periods=h)),
    }

    # Backtest on a held-out 28-day tail before trusting the forward numbers.
    holdout = 28
    train, test = series[:-holdout], series[-holdout:]

    scores = {}
    for name, fn in candidates.items():
        try:
            pred = fn(train, holdout)
            pred.index = test.index
            scores[name] = {
                "mape": float(np.mean(np.abs((test - pred) / test)) * 100),
                "mae": float(np.mean(np.abs(test - pred))),
                "pred": pred,
            }
        except Exception as exc:  # a candidate failing is a result, not a crash
            scores[name] = {"mape": np.inf, "mae": np.inf, "pred": None,
                            "error": str(exc)}

    benchmark = "Seasonal naive (last week repeated)"
    best_name = min(scores, key=lambda k: scores[k]["mape"])
    mape, mae = scores[best_name]["mape"], scores[best_name]["mae"]
    naive_mape = scores[benchmark]["mape"]

    for name, s in sorted(scores.items(), key=lambda kv: kv[1]["mape"]):
        tag = ("selected" if name == best_name
               else "benchmark" if name == benchmark else "challenger")
        log_metric("Daily Sales Forecast", f"MAPE % - {name}", s["mape"],
                   f"Held-out last {holdout} days", len(train), holdout, tag)
    log_metric("Daily Sales Forecast", "MAE (ZAR)", mae,
               f"Held-out last {holdout} days", len(train), holdout,
               f"selected model: {best_name}")
    log_metric("Daily Sales Forecast", "MAPE improvement vs benchmark (pp)",
               naive_mape - mape, f"Held-out last {holdout} days", len(train),
               holdout, "positive means the selected model beats seasonal naive")

    # Refit the winner on the full series and project forward.
    fc = candidates[best_name](series, horizon)
    in_sample = candidates[best_name](series[:-holdout], holdout)
    in_sample.index = test.index
    resid_sd = float(np.std(test.values - in_sample.values, ddof=1))
    pred = scores[best_name]["pred"]
    idx = pd.date_range(series.index[-1] + pd.Timedelta(days=1), periods=horizon)
    forecast = pd.DataFrame({
        "Date": idx,
        "ForecastSalesValue": fc.values.round(2),
        # Interval widens with the square root of horizon, the standard
        # random-walk error accumulation.
        "LowerBound": (fc.values - 1.96 * resid_sd * np.sqrt(
            np.arange(1, horizon + 1) ** 0.5)).round(2),
        "UpperBound": (fc.values + 1.96 * resid_sd * np.sqrt(
            np.arange(1, horizon + 1) ** 0.5)).round(2),
    })
    forecast["LowerBound"] = forecast["LowerBound"].clip(lower=0)
    # Scope, not MerchantKey: the total-level forecast has no merchant, and an
    # always-null key column in a gold table is a trap for the next reader.
    # Per-merchant forecasts live in FactMerchantForecast.
    forecast["Scope"] = "Total"

    # Per-merchant next-30-day totals, using each merchant's own recent level
    # and trend. Merchant-level daily series are too noisy for Holt-Winters, so
    # this uses a damped linear extrapolation of the last 8 weeks instead.
    per_merchant = []
    for mk, grp in sales.groupby("MerchantKey"):
        s = (grp.groupby("Date")["SalesValue"].sum().asfreq("D").fillna(0)
             .sort_index())
        recent = s[-56:]
        x = np.arange(len(recent))
        slope, intercept = np.polyfit(x, recent.values, 1)
        # Damping factor 0.6: trends observed over 8 weeks rarely persist at
        # full strength for another month.
        future_x = np.arange(len(recent), len(recent) + horizon)
        proj = intercept + slope * (len(recent) + (future_x - len(recent)) * 0.6)
        per_merchant.append({
            "MerchantKey": mk,
            "Last30DaysActual": round(float(s[-30:].sum()), 2),
            "Next30DaysForecast": round(float(np.clip(proj, 0, None).sum()), 2),
        })
    pm = pd.DataFrame(per_merchant)
    pm["ExpectedChangePct"] = ((pm["Next30DaysForecast"] / pm["Last30DaysActual"] - 1)
                               * 100).round(2)
    pm = pm.merge(t["DimMerchant"][["MerchantKey", "Merchant", "Region",
                                    "BaseMonthlySalesTarget"]], on="MerchantKey")
    pm["ForecastVsTargetPct"] = (pm["Next30DaysForecast"]
                                 / pm["BaseMonthlySalesTarget"] * 100).round(1)
    pm = pm.sort_values("ExpectedChangePct")

    forecast.to_csv(GOLD / "FactSalesForecast.csv", index=False)
    pm.to_csv(GOLD / "FactMerchantForecast.csv", index=False)

    backtest = pd.DataFrame({"Date": test.index, "Actual": test.values.round(2),
                             "Predicted": pred.values.round(2)})

    return {
        "selected_model": best_name,
        "candidates": {n: round(s["mape"], 3) for n, s in
                       sorted(scores.items(), key=lambda kv: kv[1]["mape"])},
        "mape": round(mape, 2), "mae": round(mae, 2),
        "naive_mape": round(naive_mape, 2),
        "beats_benchmark": bool(mape <= naive_mape),
        "horizon_days": horizon,
        "forecast_total": round(float(fc.sum()), 2),
        "last_30d_actual": round(float(series[-30:].sum()), 2),
        "forecast": forecast.assign(
            Date=forecast["Date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
        "backtest": backtest.assign(
            Date=backtest["Date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
        "per_merchant": pm.to_dict("records"),
    }


def main() -> None:
    t = load()

    print("1/5  voucher redemption + delayed-redemption models ...")
    vouchers = voucher_models(t)
    print("2/5  SLA breach model ...")
    sla = sla_model(t)
    print("3/5  merchant segmentation ...")
    seg = segment_merchants(t)
    print("4/5  sales forecast ...")
    fc = forecast_sales(t)
    print("5/5  writing outputs ...")

    perf_df = pd.DataFrame(perf)
    perf_df.to_csv(GOLD / "MLModelPerformance.csv", index=False)
    imp_df = pd.DataFrame(importance)
    imp_df.to_csv(GOLD / "MLFeatureImportance.csv", index=False)

    results = {"vouchers": vouchers, "sla": sla, "segmentation": seg,
               "forecast": fc, "performance": perf_df.to_dict("records"),
               "importance": imp_df.to_dict("records")}
    (DOCS / "_ml_results.json").write_text(json.dumps(results, indent=1, default=str),
                                           encoding="utf8")

    pd.set_option("display.width", 200)
    print()
    print(perf_df.to_string(index=False))
    print()
    print(f"Segmentation: k={seg['k']}  silhouette by k: {seg['silhouette_by_k']}")
    for s in seg["segments"]:
        print(f"  [{s['Segment']}] {s['Profile']}")
    print()
    print("Health score - bottom 6:")
    print(pd.DataFrame(seg["merchants"])[
        ["Merchant", "Segment", "HealthScore", "RiskTier", "GrowthSlopePct",
         "TicketsPer1kTx"]].head(6).to_string(index=False))
    print()
    print("Forecast bake-off (held-out MAPE %):")
    for n, v in fc["candidates"].items():
        print(f"  {v:>6.2f}  {n}")
    print(f"Selected: {fc['selected_model']} | next {fc['horizon_days']}d = "
          f"R{fc['forecast_total']:,.0f} vs last 30d R{fc['last_30d_actual']:,.0f} "
          f"({'beats' if fc['beats_benchmark'] else 'DOES NOT BEAT'} naive benchmark)")
    print(f"Expected breakage liability: "
          f"R{vouchers['expected_breakage_value']:,.0f}")


if __name__ == "__main__":
    main()
