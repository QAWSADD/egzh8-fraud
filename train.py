"""EDA, 5-fold temporal tuning, calibration, threshold selection and held-out evaluation."""

import hashlib
import json
import time
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, brier_score_loss, confusion_matrix, precision_recall_curve,
    precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from src.features import COMPONENTS, CSV_COLUMNS, FEATURES

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "creditcard.csv"
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"
SEED = 42
MISSED_COST = 25
ALERT_COST = 1


def temporal_folds(rows):
    clock = rows["Time"].to_numpy()
    for train, validation in TimeSeriesSplit(n_splits=5).split(rows):
        train = train[clock[train] < clock[validation[0]]]
        if rows.iloc[train]["Class"].nunique() != 2 or rows.iloc[validation]["Class"].nunique() != 2:
            raise ValueError("Each temporal fold must contain both classes.")
        yield train, validation


def split_data(rows):
    boundaries = [float(rows["Time"].iloc[int(len(rows) * ratio)]) for ratio in (0.60, 0.70, 0.80)]
    groups = np.searchsorted(boundaries, rows["Time"], side="right")
    splits = {name: rows.loc[groups == index] for index, name in enumerate(
        ("train", "calibration", "validation", "test")
    )}
    return splits


def tune(train):
    candidates = {
        "Logistic regression": (
            make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                          LogisticRegression(class_weight="balanced", max_iter=250, random_state=SEED)),
            {"logisticregression__C": [0.1, 1.0]},
        ),
        "Extra Trees": (
            make_pipeline(SimpleImputer(strategy="median"), ExtraTreesClassifier(
                n_estimators=40, min_samples_leaf=3, class_weight="balanced", n_jobs=3, random_state=SEED)),
            {"extratreesclassifier__max_depth": [10, 17]},
        ),
        "Histogram gradient boosting": (
            make_pipeline(SimpleImputer(strategy="median"), HistGradientBoostingClassifier(
                class_weight="balanced", max_iter=65, early_stopping=False, random_state=SEED)),
            {"histgradientboostingclassifier__max_leaf_nodes": [15, 31]},
        ),
    }
    folds = list(temporal_folds(train))
    results = []
    best = None
    for name, (pipeline, space) in candidates.items():
        tick = time.monotonic()
        print(f"5-fold search: {name}", flush=True)
        search = GridSearchCV(pipeline, space, scoring="average_precision", cv=folds, n_jobs=1)
        search.fit(train[FEATURES], train["Class"])
        index = search.best_index_
        results.append({
            "name": name, "average_precision": float(search.best_score_),
            "std": float(search.cv_results_["std_test_score"][index]),
            "fold_ap": [float(search.cv_results_[f"split{i}_test_score"][index]) for i in range(5)],
            "parameters": search.best_params_, "seconds": round(time.monotonic() - tick, 1),
        })
        print(f"  mean AP = {search.best_score_:.4f}", flush=True)
        if best is None or search.best_score_ > best[0]:
            best = search.best_score_, name, search.best_estimator_
    return best[1], best[2], results


def choose_threshold(labels, scores):
    precision, recall, thresholds = precision_recall_curve(labels, scores)
    positives = int(np.sum(labels))
    # At thresholds with a predicted positive, precision is enough to recover FP.
    true_positive = np.rint(recall[:-1] * positives).astype(int)
    false_positive = np.rint(np.divide(true_positive, precision[:-1], out=np.zeros_like(
        precision[:-1]), where=precision[:-1] > 0)).astype(int) - true_positive
    # At the low-precision tail a prediction can contain only negatives.
    order = np.sort(scores)
    count_above = len(scores) - np.searchsorted(order, thresholds)
    false_positive = np.where(precision[:-1] > 0, false_positive, count_above)
    false_negative = positives - true_positive
    cost = MISSED_COST * false_negative + ALERT_COST * false_positive
    minimum = np.min(cost)
    if minimum >= positives * MISSED_COST:
        return float(np.nextafter(np.max(scores), 1.0)), int(positives * MISSED_COST)
    # Prefer greater recall on equal cost.
    best = np.flatnonzero(cost == minimum)[0]
    return float(thresholds[best]), int(cost[best])


def score_metrics(labels, scores, threshold):
    predictions = scores >= threshold
    tn, fp, fn, tp = [int(v) for v in confusion_matrix(labels, predictions, labels=[0, 1]).ravel()]
    return {
        "average_precision": float(average_precision_score(labels, scores)),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "brier": float(brier_score_loss(labels, scores)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "tn": tn, "fp": fp, "fn": fn, "tp": tp, "cost": MISSED_COST * fn + ALERT_COST * fp,
    }


def make_figures(rows, splits, test_labels, test_scores, metrics):
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    forest, orange = "#1b5448", "#b45321"

    def save(fig, filename):
        fig.tight_layout()
        fig.savefig(FIGURES / filename, dpi=155, facecolor="white")
        plt.close(fig)

    counts = rows["Class"].value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(8, 3.7))
    bars = ax.bar(["Legitimate", "Fraud"], counts, color=[forest, orange], width=0.45)
    ax.bar_label(bars, labels=[f"{count:,}" for count in counts], padding=6)
    ax.set(yscale="log", ylim=(1, 850000), ylabel="Count (log scale)", title="Class imbalance after deduplication")
    save(fig, "01_classes.png")

    fig, ax = plt.subplots(figsize=(8, 3.7))
    for label, color in ((0, forest), (1, orange)):
        ax.hist(np.log1p(rows.loc[rows.Class == label, "Amount"]), bins=np.linspace(0, 10.5, 35),
                density=True, histtype="step", linewidth=2, color=color, label=["Legitimate", "Fraud"][label])
    ax.set(xlabel="log(1 + Amount)", ylabel="Density within class", title="Transaction amount by class")
    ax.legend(frameon=False)
    save(fig, "02_amount.png")

    fig, ax = plt.subplots(figsize=(8, 3.7))
    fraud = rows.loc[rows.Class == 1, "Time"] / 3600
    ax.hist(fraud, bins=np.arange(0, 50, 2), color=orange, alpha=0.9, label="Fraud count")
    for key, color in zip(("calibration", "validation", "test"), ("#335b72", "#1b5448", "#423962")):
        ax.axvline(splits[key].Time.min() / 3600, color=color, linestyle="--", label=f"{key.title()} start")
    ax.set(xlabel="Hours from dataset start", ylabel="Fraud cases", title="Time split and fraud distribution")
    ax.legend(frameon=False, fontsize=8)
    save(fig, "03_time.png")

    fig, ax = plt.subplots(figsize=(8, 3.7))
    corr = rows[["Time", *FEATURES]].corrwith(rows.Class).sort_values(key=abs).tail(9)
    ax.barh(corr.index, corr, color=[forest if x > 0 else orange for x in corr])
    ax.set(xlabel="Pearson correlation with Class", title="Largest absolute correlations")
    save(fig, "04_correlations.png")

    fig, ax = plt.subplots(figsize=(8, 3.7))
    data = [rows.loc[rows.Class == label, "V14"] for label in (0, 1)]
    ax.boxplot(data, tick_labels=["Legitimate", "Fraud"], showfliers=False)
    ax.set(ylabel="V14 component", title="Anonymous component V14 by class (fliers hidden)")
    save(fig, "05_component.png")

    precision, recall, _ = precision_recall_curve(test_labels, test_scores)
    fig, ax = plt.subplots(figsize=(8, 3.7))
    ax.step(recall, precision, where="post", color=forest, label="Held-out test")
    ax.axhline(test_labels.mean(), color=orange, linestyle="--", label="Prevalence baseline")
    ax.set(xlabel="Recall", ylabel="Precision", xlim=(0, 1), ylim=(0, 1.04), title="Precision–recall on the test set")
    ax.legend(frameon=False)
    save(fig, "06_precision_recall.png")

    fig, ax = plt.subplots(figsize=(5.2, 3.9))
    matrix = [[metrics["tn"], metrics["fp"]], [metrics["fn"], metrics["tp"]]]
    ax.imshow(np.log1p(matrix), cmap="Greens")
    ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["No alert", "Alert"],
           yticklabels=["Legitimate", "Fraud"], xlabel="Prediction", ylabel="Actual", title="Test confusion matrix")
    for row in range(2):
        for col in range(2):
            value = matrix[row][col]
            ax.text(col, row, f"{value:,}", ha="center", va="center", color="white" if value > 10000 else "#182e2c")
    save(fig, "07_confusion.png")

    fig, ax = plt.subplots(figsize=(8, 3.7))
    observed, predicted = calibration_curve(test_labels, test_scores, n_bins=8, strategy="uniform")
    ax.plot([0, 1], [0, 1], "--", color="#64746d")
    ax.plot(predicted, observed, marker="o", color=forest)
    ax.set(xlabel="Mean predicted risk", ylabel="Observed fraud share", title="Reliability of risk estimates on test")
    save(fig, "08_calibration.png")


def summarize_errors(test, scores, threshold, count=5):
    labels = test.Class.to_numpy()
    errors = np.flatnonzero((scores >= threshold) != labels)
    confidence = np.where(labels == 1, 1 - scores, scores)
    selected = errors[np.argsort(confidence[errors])[::-1]][:count]
    output = []
    for index in selected:
        row = test.iloc[index]
        largest = row[COMPONENTS].abs().nlargest(2).index.tolist()
        output.append({
            "row": int(row.name), "actual": int(labels[index]), "score": float(scores[index]),
            "time": float(row.Time), "amount": float(row.Amount),
            "largest_components": {name: float(row[name]) for name in largest},
            "type": "FN" if labels[index] else "FP",
        })
    return output


def save_examples(test, scores, threshold):
    labels = test.Class.to_numpy()
    amount = test.Amount.to_numpy()
    ordinary = np.flatnonzero((labels == 0) & (scores < threshold) & (25 <= amount) & (amount <= 100))
    if not len(ordinary):
        ordinary = np.flatnonzero(labels == 0)
    normal_index = ordinary[len(ordinary) // 2]
    borderline_index = int(np.argmin(np.abs(scores - threshold)))
    positive = np.flatnonzero(labels == 1)
    fraud_index = positive[np.argmax(scores[positive])]

    def payload(row):
        return {"amount": float(row.Amount), "time": int(row.Time),
                "components": [float(row[name]) if not pd.isna(row[name]) else None for name in COMPONENTS]}

    examples = [
        {"id": key, "payload": payload(test.iloc[index]), "actual": int(labels[index])}
        for key, index in (("normal", normal_index), ("borderline", borderline_index), ("fraud", fraud_index))
    ]
    examples.append({"id": "invalid", "payload": dict(examples[0]["payload"], amount=-20), "actual": None})
    (ROOT / "data" / "demo_cases.json").write_text(json.dumps(examples, indent=2), encoding="utf-8")


def main():
    print(f"Loading {RAW}", flush=True)
    raw = pd.read_csv(RAW)
    if list(raw.columns) != CSV_COLUMNS or set(raw.Class.unique()) != {0, 1}:
        raise ValueError("Unexpected MLG-ULB schema.")
    rows = raw.drop_duplicates().sort_values("Time", kind="stable")
    splits = split_data(rows)
    train, calibration, validation, test = (splits[k] for k in ("train", "calibration", "validation", "test"))
    with threadpool_limits(limits=2):
        name, best, cv = tune(train)
        print(f"Calibrating {name}", flush=True)
        model = CalibratedClassifierCV(FrozenEstimator(best), method="sigmoid")
        model.fit(calibration[FEATURES], calibration.Class)
        validation_scores = model.predict_proba(validation[FEATURES])[:, 1]
        threshold, cost = choose_threshold(validation.Class.to_numpy(), validation_scores)
        test_scores = model.predict_proba(test[FEATURES])[:, 1]
        test_labels = test.Class.to_numpy()
        metrics = score_metrics(test_labels, test_scores, threshold)
        importance = permutation_importance(model, test[FEATURES], test_labels, scoring="average_precision",
                                           n_repeats=3, max_samples=min(20000, len(test)), random_state=SEED, n_jobs=1)
    precision, recall, _ = precision_recall_curve(test_labels, test_scores, drop_intermediate=True)
    boundaries = np.unique(np.linspace(0, len(precision) - 1, min(220, len(precision))).astype(int))
    width = max(0.0005, threshold * 0.15)
    metadata = {
        "dataset": {"rows": len(raw), "fraud": int(raw.Class.sum()), "prevalence": float(raw.Class.mean()),
                    "deduplicated_rows": len(rows), "duplicates": len(raw) - len(rows),
                    "nulls": {name: int(raw[name].isna().sum()) for name in raw.columns},
                    "zero_amount": int(raw.Amount.eq(0).sum()), "max_amount": float(raw.Amount.max()),
                    "sha256": hashlib.sha256(RAW.read_bytes()).hexdigest()},
        "splits": {key: {"rows": len(value), "fraud": int(value.Class.sum()), "min_time": int(value.Time.min()),
                         "max_time": int(value.Time.max())} for key, value in splits.items()},
        "cv": cv, "selected_model": name, "threshold": threshold, "review_width": width,
        "cost_weights": {"fn": MISSED_COST, "fp": ALERT_COST}, "validation_cost": cost,
        "validation": score_metrics(validation.Class, validation_scores, threshold),
        "test": metrics, "test_at_0_5": score_metrics(test_labels, test_scores, 0.5),
        "pr_curve": [[float(recall[k]), float(precision[k])] for k in boundaries],
        "test_prevalence": float(test_labels.mean()),
        "high_amount": float(train.Amount.quantile(0.995)),
        "extreme_amount": float(train.Amount.quantile(0.999)),
        "feature_baselines": train[FEATURES].median().to_dict(),
        "importance": sorted([{"feature": name, "ap_drop": float(mean), "std": float(std)}
                              for name, mean, std in zip(FEATURES, importance.importances_mean, importance.importances_std)],
                             key=lambda item: item["ap_drop"], reverse=True),
        "errors": summarize_errors(test, test_scores, threshold),
    }
    joblib.dump({"model": model, "metadata": metadata}, ROOT / "models" / "model.joblib", compress=3)
    (RESULTS / "metrics.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    save_examples(test, test_scores, threshold)
    make_figures(rows, splits, test_labels, test_scores, metrics)
    print(json.dumps({"model": name, "threshold": threshold, "test": metrics}, indent=2), flush=True)


if __name__ == "__main__":
    main()
