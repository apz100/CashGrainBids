"""NGG CAD-basis pricing decision support from USD-basis economics."""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd


DECISION_COLUMNS = (
    "FX Neutral CAD Basis", "FX/Futures Adjustment",
    "Maximum Allowed US Basis", "CAD Basis at USD Ceiling",
    "Competitor Benchmark US Basis", "Allowed Competitor Premium",
    "Competitive US Basis Target", "Competitive CAD Basis",
    "Recommended Max CAD Basis", "Current CAD Basis vs Recommended",
    "CAD Basis Change per +0.01 CADUSD", "Pricing Decision Status",
)


def _number(value: Any) -> float:
    raw = str(value).strip().replace("$", "").replace(",", "").replace("'", "-")
    if not raw or raw.lower() in {"nan", "none", "<na>"}:
        return math.nan
    if "-" in raw:
        whole, eighths = raw.rsplit("-", 1)
        try:
            return (float(whole) + float(eighths) / 8) / 100
        except ValueError:
            pass
    try:
        return float(raw)
    except (TypeError, ValueError):
        return math.nan


def _text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _commodity(value: Any) -> str:
    text = _text(value).lower()
    for name in ("soybeans", "corn", "srw", "hrw", "hrs"):
        if name in text:
            if name == "soybeans":
                return "Soybeans"
            if name == "corn":
                return "Corn"
            return name.upper()
    return text


def _crop_stream(delivery: Any) -> str:
    match = re.search(r"(20\d{2})", _text(delivery))
    if not match:
        return "unknown"
    year = int(match.group(1))
    return "current" if year == 2026 else "next" if year == 2027 else "other"


def _futures_key(row: pd.Series) -> str:
    value = row.get("Standard Futures Month")
    if not _text(value) or _text(value).lower() == "nan":
        value = row.get("Futures Month")
    return _text(value).lower()


def _is_ngg(row: pd.Series) -> bool:
    return "north gower" in (_text(row.get("Location")) + " " + _text(row.get("Source"))).lower()


def _competitor_name(row: pd.Series) -> str:
    location = _text(row.get("Location")).lower()
    for name in ("kars", "lansdowne", "vankleek hill"):
        if name in location:
            return name.title()
    return ""


def _config_value(mapping: dict, commodity: str, stream: str):
    value = mapping.get((commodity, stream))
    return mapping.get(commodity) if value is None else value


def add_pricing_decision_columns(
    df: pd.DataFrame,
    previous: pd.DataFrame | Path | str | None = None,
    *,
    ceilings: dict | None = None,
    premiums: dict | None = None,
    benchmark_method: str | None = None,
    selected_competitor: str | None = None,
) -> pd.DataFrame:
    """Append decision calculations without changing existing source fields.

    FX Rate is CADUSD, expressed as USD per CAD, matching fx_rates.py.
    Competitors are matched only on commodity, delivery, and futures reference.
    """
    out = df.copy()
    for column in DECISION_COLUMNS:
        out[column] = pd.NA
    ceilings = ceilings or {}
    premiums = premiums or {}
    method = (benchmark_method or os.getenv("NGG_BENCHMARK_METHOD", "average_competitor")).lower()
    selected = (selected_competitor or os.getenv("NGG_SELECTED_COMPETITOR", "")).lower()

    if isinstance(previous, (str, Path)):
        try:
            previous = pd.read_csv(previous)
        except Exception:
            previous = None
    previous_lookup = {}
    if previous is not None and not previous.empty:
        for _, row in previous.iterrows():
            if _is_ngg(row):
                key = (_commodity(row.get("Name")), _text(row.get("Delivery")).lower(),
                       _text(row.get("Delivery End")).lower(), _futures_key(row))
                previous_lookup[key] = row

    comparable = {}
    competitors = out[out["Location"].astype(str).str.contains(
        r"Kars|Lansdowne|Vankleek Hill", case=False, regex=True, na=False)]
    for _, row in competitors.iterrows():
        key = (_commodity(row.get("Name")), _text(row.get("Delivery")).lower(),
               _text(row.get("Delivery End")).lower(), _futures_key(row))
        us = _number(row.get("Standardized US Basis (USD/bu)"))
        if math.isnan(us):
            us = _number(row.get("US Basis (USD/bu)"))
        if not math.isnan(us):
            comparable.setdefault(key, []).append((_competitor_name(row), us))

    for index, row in out.iterrows():
        if not _is_ngg(row):
            continue
        commodity = _commodity(row.get("Name"))
        stream = _crop_stream(row.get("Delivery"))
        current_cad = _number(row.get("Basis"))
        futures = _number(row.get("Futures Price"))
        fx = _number(row.get("FX Rate"))
        if math.isnan(fx) or fx <= 0:
            out.at[index, "Pricing Decision Status"] = "Missing CADUSD FX rate"
            continue

        key = (commodity, _text(row.get("Delivery")).lower(),
               _text(row.get("Delivery End")).lower(), _futures_key(row))
        prior = previous_lookup.get(key)
        prior_us = _number(prior.get("US Basis (USD/bu)")) if prior is not None else math.nan
        prior_cad = _number(prior.get("Basis")) if prior is not None else math.nan
        current_us = _number(row.get("US Basis (USD/bu)"))
        if not math.isnan(futures) and not math.isnan(prior_us):
            neutral = (futures + prior_us) / fx - futures
            out.at[index, "FX Neutral CAD Basis"] = neutral
            if not math.isnan(prior_cad):
                out.at[index, "FX/Futures Adjustment"] = neutral - prior_cad
        if not math.isnan(futures) and not math.isnan(current_us):
            out.at[index, "CAD Basis Change per +0.01 CADUSD"] = (
                -(futures + current_us) / (fx * fx) * 0.01)

        ceiling = _config_value(ceilings, commodity, stream)
        premium = _config_value(premiums, commodity, stream)
        if ceiling is not None:
            out.at[index, "Maximum Allowed US Basis"] = float(ceiling)
        if premium is not None:
            out.at[index, "Allowed Competitor Premium"] = float(premium)
        if not math.isnan(futures) and ceiling is not None:
            out.at[index, "CAD Basis at USD Ceiling"] = (futures + float(ceiling)) / fx - futures

        benchmark_values = comparable.get(key, [])
        benchmark = math.nan
        if benchmark_values:
            values = [value for _, value in benchmark_values]
            if method == "best_competitor":
                benchmark = max(values)
            elif method == "second_best_competitor":
                benchmark = sorted(values, reverse=True)[min(1, len(values) - 1)]
            elif method == "selected_competitor":
                selected_values = [value for name, value in benchmark_values if name.lower() == selected]
                benchmark = selected_values[0] if selected_values else math.nan
            elif method == "average_kars_lansdowne":
                selected_values = [value for name, value in benchmark_values if name.lower() in {"Kars", "Lansdowne"}]
                benchmark = sum(selected_values) / len(selected_values) if selected_values else math.nan
            else:
                benchmark = sum(values) / len(values)
        if not math.isnan(benchmark):
            out.at[index, "Competitor Benchmark US Basis"] = benchmark
        if premium is not None and not math.isnan(benchmark):
            target = benchmark + float(premium)
            out.at[index, "Competitive US Basis Target"] = target
            if not math.isnan(futures):
                out.at[index, "Competitive CAD Basis"] = (futures + target) / fx - futures

        ceiling_cad = _number(out.at[index, "CAD Basis at USD Ceiling"])
        competitive_cad = _number(out.at[index, "Competitive CAD Basis"])
        if not math.isnan(ceiling_cad) and not math.isnan(competitive_cad):
            recommended = min(ceiling_cad, competitive_cad)
            out.at[index, "Recommended Max CAD Basis"] = recommended
            if not math.isnan(current_cad):
                out.at[index, "Current CAD Basis vs Recommended"] = current_cad - recommended
            out.at[index, "Pricing Decision Status"] = "Complete"
        elif math.isnan(benchmark):
            out.at[index, "Pricing Decision Status"] = "No comparable competitor quote"
        elif premium is None or math.isnan(futures):
            out.at[index, "Pricing Decision Status"] = "Missing premium or futures price"
        elif ceiling is None:
            out.at[index, "Pricing Decision Status"] = "Missing USD ceiling"
        else:
            out.at[index, "Pricing Decision Status"] = "Incomplete"
    return out
