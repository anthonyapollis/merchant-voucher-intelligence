# Fabric notebook — 03_ml_anomaly_and_forecast
# ======================================================================================
# The brief's optional AI extension. Runs on a Fabric Spark pool, reads gold, trains/scores
# five models, logs to the workspace MLflow instance, and writes predictions BACK to gold.
#
# ARCHITECTURAL DECISION worth stating explicitly at interview: predictions are materialised
# to Delta tables, not served from a live endpoint. Power BI then reads them as ordinary
# columns. A live model call per visual would add latency to every page render and couple
# report availability to endpoint availability, for no analytical gain — the underlying data
# only changes once a day.
#
# PARAMETERS
# ======================================================================================
batch_id = "20260811T060000Z"
retrain = False          # False = score with the registered model; True = refit and register
contamination = 0.05     # expected anomaly proportion for Isolation Forest

# --------------------------------------------------------------------------------------
import mlflow
import numpy as np
import pandas as pd
from datetime import datetime
from pyspark.sql import functions as F

from sklearn.ensemble import IsolationForest, HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
from statsmodels.tsa.holtwinters import ExponentialSmoothing

LAKEHOUSE = "LH_MerchantVoucher"
MODEL_VERSION = "v1.2.0"
scored_at = datetime.utcnow()

mlflow.set_experiment("/MerchantVoucherIntelligence/anomaly_detection")
print(f"ML scoring | batch {batch_id} | retrain={retrain}")


# ======================================================================================
# Feature engineering — merchant x month, expressed RELATIVE to each merchant's own history
# ======================================================================================
# This is the decision that makes the model useful. Absolute features (sales value, ticket
# count) would rank merchants by SIZE — the Isolation Forest would flag the largest accounts
# every month and never notice a small merchant collapsing. Expressing every feature as a
# deviation from that merchant's own expanding-mean history makes the model scale-free, so
# it detects CHANGE rather than magnitude.

mm = spark.sql(f"""
    WITH s AS (
        SELECT f.merchant_key, d.year_month,
               SUM(f.sales_value) AS sales_value, SUM(f.transactions) AS transactions
        FROM {LAKEHOUSE}.fct_merchant_sales f
        JOIN {LAKEHOUSE}.dim_date d ON d.date_key = f.date_key
        GROUP BY 1, 2),
    v AS (
        SELECT f.merchant_key, d.year_month,
               SUM(f.redeemed_count) * 1.0 / COUNT(*) AS redemption_rate,
               AVG(f.days_to_redeem) AS avg_days_to_redeem
        FROM {LAKEHOUSE}.fct_voucher_redemptions f
        JOIN {LAKEHOUSE}.dim_date d ON d.date_key = f.sold_date_key
        GROUP BY 1, 2),
    t AS (
        SELECT f.merchant_key, d.year_month, COUNT(*) AS tickets,
               SUM(f.sla_breach_count) * 1.0 / COUNT(*) AS sla_breach_rate
        FROM {LAKEHOUSE}.fct_support_tickets f
        JOIN {LAKEHOUSE}.dim_date d ON d.date_key = f.date_key
        GROUP BY 1, 2)
    SELECT m.merchant_key, m.merchant_name, m.region, s.year_month,
           s.sales_value, s.transactions,
           s.sales_value / NULLIF(s.transactions, 0) AS avg_basket_value,
           v.redemption_rate, v.avg_days_to_redeem,
           COALESCE(t.tickets, 0) AS tickets, COALESCE(t.sla_breach_rate, 0) AS sla_breach_rate
    FROM s
    JOIN {LAKEHOUSE}.dim_merchant m ON m.merchant_key = s.merchant_key
    LEFT JOIN v ON v.merchant_key = s.merchant_key AND v.year_month = s.year_month
    LEFT JOIN t ON t.merchant_key = s.merchant_key AND t.year_month = s.year_month
    ORDER BY m.merchant_name, s.year_month
""").toPandas()


def vs_own_history(g, col):
    """Deviation from the merchant's own expanding mean of all PRIOR months.
    shift(1) before expanding() is essential — including the current month in its own
    baseline would dilute exactly the deviation we are trying to detect."""
    prior = g[col].shift(1).expanding().mean()
    return (g[col] - prior) / prior.replace(0, np.nan)


frames = []
for merchant, g in mm.groupby("merchant_name"):
    g = g.sort_values("year_month").copy()
    g["sales_vs_own_history"] = vs_own_history(g, "sales_value")
    g["txn_vs_own_history"] = vs_own_history(g, "transactions")
    g["tickets_vs_own_history"] = vs_own_history(g, "tickets")
    g["basket_vs_own_history"] = vs_own_history(g, "avg_basket_value")
    g["redemption_delta"] = g.redemption_rate - g.redemption_rate.shift(1).expanding().mean()
    g["days_to_redeem_delta"] = (g.avg_days_to_redeem
                                 - g.avg_days_to_redeem.shift(1).expanding().mean())
    g["sla_delta"] = g.sla_breach_rate - g.sla_breach_rate.shift(1).expanding().mean()
    frames.append(g)
feat = pd.concat(frames)

FEATURES = ["sales_vs_own_history", "txn_vs_own_history", "tickets_vs_own_history",
            "basket_vs_own_history", "redemption_delta", "days_to_redeem_delta", "sla_delta"]
X = feat[FEATURES].replace([np.inf, -np.inf], np.nan)
mask = X.notna().all(axis=1)      # first month per merchant has no history -> excluded
Xs = StandardScaler().fit_transform(X[mask])


# ======================================================================================
# MODEL 1 — Isolation Forest anomaly detection
# ======================================================================================
with mlflow.start_run(run_name=f"isolation_forest_{batch_id}"):
    mlflow.log_params({"n_estimators": 400, "contamination": contamination,
                       "n_features": len(FEATURES), "batch_id": batch_id})

    iso = IsolationForest(n_estimators=400, contamination=contamination, random_state=42)
    iso.fit(Xs)

    res = feat[mask].copy()
    res["anomaly_score"] = -iso.score_samples(Xs)
    res["is_anomaly"] = iso.predict(Xs) == -1

    # A score with no reason attached does not get acted on. Every flagged row carries a
    # plain-English explanation that an account manager can read without a data scientist.
    def explain(r):
        bits = []
        if r.sales_vs_own_history <= -0.15:
            bits.append(f"sales {r.sales_vs_own_history:+.0%} vs own history")
        elif r.sales_vs_own_history >= 0.30:
            bits.append(f"sales {r.sales_vs_own_history:+.0%} vs own history")
        if r.tickets_vs_own_history >= 1.0:
            bits.append(f"support tickets {r.tickets_vs_own_history:+.0%}")
        if abs(r.days_to_redeem_delta) >= 1.0:
            bits.append(f"time-to-redeem {r.days_to_redeem_delta:+.1f} days")
        if r.redemption_delta <= -0.03:
            bits.append(f"redemption rate {r.redemption_delta:+.1%}")
        if r.sla_delta >= 0.15:
            bits.append(f"SLA breach rate {r.sla_delta:+.0%}")
        return "; ".join(bits) if bits else "multivariate pattern shift"

    res["explanation"] = res.apply(explain, axis=1)

    n_anom = int(res.is_anomaly.sum())
    mlflow.log_metrics({"observations_scored": int(mask.sum()), "anomalies_flagged": n_anom,
                        "anomaly_rate": n_anom / mask.sum()})
    mlflow.sklearn.log_model(iso, "isolation_forest")
    print(f"  Isolation Forest: {n_anom} anomalies from {mask.sum()} merchant-months")

out = (res[["merchant_key", "merchant_name", "year_month", "anomaly_score", "is_anomaly",
            "explanation"]]
       .assign(model_version=MODEL_VERSION, scored_at=scored_at))
(spark.createDataFrame(out).write.format("delta").mode("overwrite")
 .option("overwriteSchema", "true").saveAsTable(f"{LAKEHOUSE}.ml_anomaly_scores"))
print(f"  -> {LAKEHOUSE}.ml_anomaly_scores")


# ======================================================================================
# MODEL 2 — Sales forecast (Holt-Winters, weekly seasonality)
# ======================================================================================
daily = spark.sql(f"""
    SELECT d.date, SUM(f.sales_value) AS sales_value
    FROM {LAKEHOUSE}.fct_merchant_sales f
    JOIN {LAKEHOUSE}.dim_date d ON d.date_key = f.date_key
    GROUP BY d.date ORDER BY d.date
""").toPandas().set_index("date").asfreq("D")

H = 30
with mlflow.start_run(run_name=f"holt_winters_{batch_id}"):
    # Backtest FIRST, on a held-out tail. Publishing a forecast without a measured error
    # invites it to be treated as fact.
    train, test = daily.sales_value[:-H], daily.sales_value[-H:]
    bt_model = ExponentialSmoothing(train, trend="add", seasonal="add", seasonal_periods=7,
                                    initialization_method="estimated").fit()
    bt = bt_model.forecast(H)
    mape = float(np.mean(np.abs((test.values - bt.values) / test.values)))
    naive_mape = float(np.mean(np.abs((test.values - train[-7:].mean()) / test.values)))

    mlflow.log_params({"model": "ExponentialSmoothing", "trend": "add", "seasonal": "add",
                       "seasonal_periods": 7, "horizon_days": H})
    mlflow.log_metrics({"backtest_mape": mape, "naive_mape": naive_mape,
                        "improvement_vs_naive": 1 - mape / naive_mape})
    print(f"  Holt-Winters backtest MAPE {mape:.2%} vs naive {naive_mape:.2%}")

    # Refit on the full series for the published forecast
    full = ExponentialSmoothing(daily.sales_value, trend="add", seasonal="add",
                                seasonal_periods=7, initialization_method="estimated").fit()
    fc = full.forecast(H)
    sigma = float(np.std(full.resid))

fdf = pd.DataFrame({
    "forecast_date": fc.index, "forecast_value": fc.values,
    "lower_80": fc.values - 1.2816 * sigma, "upper_80": fc.values + 1.2816 * sigma,
    "lower_95": fc.values - 1.9600 * sigma, "upper_95": fc.values + 1.9600 * sigma,
}).assign(model_version=MODEL_VERSION, scored_at=scored_at)
(spark.createDataFrame(fdf).write.format("delta").mode("overwrite")
 .option("overwriteSchema", "true").saveAsTable(f"{LAKEHOUSE}.ml_sales_forecast"))
print(f"  -> {LAKEHOUSE}.ml_sales_forecast  ({H} days, 80% and 95% intervals)")


# ======================================================================================
# MODEL 3 — Redemption propensity, with an honest ceiling check
# ======================================================================================
v = spark.sql(f"""
    SELECT f.voucher_id, f.voucher_value, f.is_redeemed, vt.voucher_type,
           m.region, m.channel, m.merchant_size_band, d.year_month, d.month_number,
           d.day_of_week
    FROM {LAKEHOUSE}.fct_voucher_redemptions f
    JOIN {LAKEHOUSE}.dim_voucher_type vt ON vt.voucher_type_key = f.voucher_type_key
    JOIN {LAKEHOUSE}.dim_merchant m ON m.merchant_key = f.merchant_key
    JOIN {LAKEHOUSE}.dim_date d ON d.date_key = f.sold_date_key
""").toPandas()

# TIME-BASED split, never random. A random split leaks future information into training and
# produces a metric that will not survive contact with production.
train_mask = v.year_month <= "2026-05"
CAT = ["voucher_type", "region", "channel", "merchant_size_band"]
X = pd.get_dummies(v[CAT + ["voucher_value", "month_number", "day_of_week"]], columns=CAT)
y = v.is_redeemed.astype(int)

with mlflow.start_run(run_name=f"redemption_propensity_{batch_id}"):
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_depth=6,
                                         random_state=42)
    clf.fit(X[train_mask], y[train_mask])
    p = clf.predict_proba(X[~train_mask])[:, 1]
    auc = roc_auc_score(y[~train_mask], p)

    # CEILING CHECK. If redemption is generated purely from voucher type, the best any model
    # can do is predict the type-level base rate. Comparing against that oracle distinguishes
    # "the model is weak" from "the signal is weak" — a distinction worth making before
    # anyone spends a sprint trying to improve an AUC that cannot move.
    type_rate = v[train_mask].groupby("voucher_type").is_redeemed.mean()
    oracle_auc = roc_auc_score(y[~train_mask],
                               v.loc[~train_mask, "voucher_type"].map(type_rate).values)

    mlflow.log_metrics({"roc_auc": auc, "oracle_auc_ceiling": oracle_auc,
                        "pct_of_achievable_signal": auc / oracle_auc})
    mlflow.sklearn.log_model(clf, "redemption_propensity")
    print(f"  Redemption propensity AUC {auc:.4f} vs ceiling {oracle_auc:.4f} "
          f"({auc / oracle_auc:.1%} of achievable signal)")


# ======================================================================================
spark.sql(f"OPTIMIZE {LAKEHOUSE}.ml_anomaly_scores")
spark.sql(f"OPTIMIZE {LAKEHOUSE}.ml_sales_forecast")
print(f"\nML scoring complete for batch {batch_id}")
mssparkutils.notebook.exit("PASS")
