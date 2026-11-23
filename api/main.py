import json
from functools import lru_cache
from mimetypes import add_type
from typing import Annotated

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from src.decision import ROOT, Engine, log_decision
from src.rules import hit

add_type("font/ttf", ".ttf")
app = FastAPI(title="Антифрод · ЕГЖ‑8", version="1.0.0")
app.mount("/assets", StaticFiles(directory=ROOT / "app" / "assets"), name="assets")

Component = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Vector = Annotated[list[Component | None], Field(min_length=28, max_length=28)]


class Transaction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    amount: float = Field(ge=0, le=100_000_000, description="Amount in the benchmark's units")
    time: int = Field(ge=0, le=315_360_000, description="Elapsed seconds from the benchmark origin")
    count_10m: int | None = Field(None, ge=1, le=10_000, description="Includes current operation")
    seconds_since_previous: int | None = Field(None, ge=0, le=31_536_000)
    watchlist_match: bool = False
    components: Vector | None = None


@lru_cache
def engine():
    return Engine()


@app.exception_handler(RequestValidationError)
async def invalid_input(request: Request, error: RequestValidationError):
    fields = {"amount": "R2", "time": "R3", "count_10m": "R5", "seconds_since_previous": "R6"}
    issues = []
    for item in error.errors():
        location = item["loc"][1:]
        field = location[0] if location else None
        if field == "components":
            code = "R8" if len(location) > 1 else "R4"
        else:
            code = fields.get(field, "R1")
        field = field if field in Transaction.model_fields else "body"
        issues.append((field, code))
    rules = [hit(code) for code in dict.fromkeys(code for _, code in issues)]
    result = {
        "status": "invalid", "source": "validation", "rules": rules,
        "probability": None, "top_features": [],
        "errors": [{"field": field, "rule": code} for field, code in issues],
    }
    log_decision(request.url.path, {"fields": list(dict.fromkeys(field for field, _ in issues))}, result)
    return JSONResponse(result, status_code=422)


def evaluate(payload, endpoint):
    transaction = payload.model_dump()
    result = engine().decide(transaction)
    log_decision(endpoint, transaction, result)
    return JSONResponse(result, status_code=422 if result["status"] == "invalid" else 200)


@app.post("/predict")
def predict(payload: Transaction):
    return evaluate(payload, "/predict")


@app.post("/explain")
def explain(payload: Transaction):
    return evaluate(payload, "/explain")


@app.get("/health")
def health():
    info = engine().stats
    return {"status": "ok", "model": info["selected_model"], "threshold": info["threshold"]}


@app.get("/metrics")
def metrics():
    info = engine().stats
    return {key: info[key] for key in (
        "dataset", "splits", "cv", "selected_model", "threshold", "review_width",
        "test", "test_at_0_5", "pr_curve", "test_prevalence", "cost_weights",
    )}


@app.get("/examples")
def examples():
    return json.loads((ROOT / "data" / "demo_cases.json").read_text(encoding="utf-8"))


@app.get("/")
def home():
    return FileResponse(ROOT / "app" / "index.html")
