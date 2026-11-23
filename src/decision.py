"""Hybrid fraud triage with per-transaction explanations and SQLite audit."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.features import COMPONENTS, FEATURES
from src.rules import after, before

ROOT = Path(__file__).resolve().parents[1]


def log_decision(endpoint, payload, result):
    path = Path(os.environ.get("FRAUD_LOG", ROOT / "logs" / "decisions.sqlite"))
    path.parent.mkdir(exist_ok=True, parents=True)
    with sqlite3.connect(path, timeout=10) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY, time TEXT NOT NULL, endpoint TEXT NOT NULL,
                input TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL, result TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO decisions(time, endpoint, input, status, source, result) VALUES(?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), endpoint, json.dumps(payload, ensure_ascii=False),
             result["status"], result["source"], json.dumps(result, ensure_ascii=False)),
        )


class Engine:
    def __init__(self, path=None):
        bundle = joblib.load(path or ROOT / "models" / "model.joblib")
        self.model = bundle["model"]
        self.stats = bundle["metadata"]

    def decide(self, tx, explain=True):
        status, trace = before(tx, self.stats)
        response = {
            "status": status, "source": "rules", "rules": trace, "probability": None,
            "threshold": self.stats["threshold"], "review_width": self.stats["review_width"],
            "top_features": [],
        }
        if status is not None:
            return response

        row = dict(zip(COMPONENTS, tx["components"]))
        row["Amount"] = tx["amount"]
        frame = pd.DataFrame([row], columns=FEATURES, dtype="float64")
        score = float(self.model.predict_proba(frame)[0, 1])
        status, trace = after(tx, score, self.stats)
        response.update(status=status, source="hybrid", rules=trace, probability=score)
        if explain:
            variants = [dict(row, **{name: self.stats["feature_baselines"][name]}) for name in FEATURES]
            scores = self.model.predict_proba(pd.DataFrame(variants, columns=FEATURES, dtype="float64"))[:, 1]
            contributions = sorted(
                ({"feature": name, "impact": float(delta)} for name, delta in zip(FEATURES, score - scores)),
                key=lambda item: abs(item["impact"]),
                reverse=True,
            )
            response["top_features"] = contributions[:5]
        return response
