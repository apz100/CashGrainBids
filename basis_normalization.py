"""Normalize commercial-buyer basis quotes to a common futures month."""
from __future__ import annotations

import re
import pandas as pd


MONTH_NUM = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


def _number(value):
    raw = str(value).strip().replace("$", "").replace(",", "").replace("'", "-")
    if not raw or raw.lower() in {"nan", "none", "<na>"}:
        return None
    if "-" in raw:
        whole, eighths = raw.rsplit("-", 1)
        try:
            return (float(whole) + float(eighths) / 8) / 100
        except ValueError:
            pass
    try:
        return float(raw)
    except ValueError:
        return None


def _month_key(value):
    match = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})", str(value), re.I)
    if not match:
        return None
    month = next(name for name in MONTH_NUM if name.lower() == match.group(1).lower())
    return f"{month} {match.group(2)}"


def _delivery_key(value):
    match = re.search(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\w*[- ]?(\d{4})", str(value), re.I)
    if not match:
        return str(value).strip().lower()
    month = match.group(1)[:3].title()
    return f"{month} {match.group(2)}"


def add_standardized_commercial_basis(df: pd.DataFrame) -> pd.DataFrame:
    """Add equivalent USD basis using the prevailing futures month convention.

    The target month is the most common futures reference among commercial
    quotes for the same commodity and delivery-month group. Original quote
    columns are preserved. AgriCharts current futures values provide the
    reference curve; conflicting values use the median and are flagged.
    """
    out = df.copy()
    for column in ("Standard Futures Month", "Standard Futures Price", "Standardized US Basis (USD/bu)", "Basis Normalization Status"):
        out[column] = pd.NA
    if "Source" not in out or "Name" not in out:
        return out

    commodity = out["Name"].astype(str).str.extract(r"(Corn|Soybeans|SRW|HRW|HRS)", expand=False)
    out["_norm_commodity"] = commodity
    out["_norm_futures_month"] = out.get("Futures Month", pd.Series("", index=out.index)).map(_month_key)
    out["_norm_delivery"] = out.get("Delivery", pd.Series("", index=out.index)).map(_delivery_key)

    # Prefer the newest available futures quote across all collected sources.
    # AgriCharts is preferred when it has the contract; commercial quote rows
    # fill contracts that are not present on the current AgriCharts tables.
    futures_rows = out[out["_norm_commodity"].notna() & out["_norm_futures_month"].notna()].copy()
    futures_rows["_curve_price"] = futures_rows.get("Futures Price", pd.Series(index=futures_rows.index)).map(_number)
    futures_rows["_curve_date"] = pd.to_datetime(futures_rows.get("Quote Date", pd.Series(index=futures_rows.index)), errors="coerce")
    curve = {}
    for (kind, futures_month), group in futures_rows.groupby(["_norm_commodity", "_norm_futures_month"], dropna=True):
        dated = group[group["_curve_date"].notna()]
        if not dated.empty:
            group = dated[dated["_curve_date"].eq(dated["_curve_date"].max())]
        values = group["_curve_price"].dropna()
        if not values.empty:
            curve[(kind, futures_month)] = (float(values.median()), bool(values.nunique() > 1))

    commercial_mask = out["Source"].astype(str).str.contains(
        "greenfield|ingredion|bunge|richard|p&h|pandh|anderson|broadgrain|ceresco",
        case=False, regex=True, na=False,
    )
    commercial = out[commercial_mask & out["_norm_commodity"].notna() & out["_norm_delivery"].notna()]
    targets = {}
    for key, group in commercial.groupby(["_norm_commodity", "_norm_delivery"], dropna=True):
        months = group["_norm_futures_month"].dropna()
        if not months.empty:
            targets[key] = months.mode().iloc[0]

    for index, row in out.loc[commercial_mask].iterrows():
        kind = row.get("_norm_commodity")
        delivery = row.get("_norm_delivery")
        original_month = row.get("_norm_futures_month")
        target_month = targets.get((kind, delivery))
        if not kind or not delivery or not original_month or not target_month:
            continue
        original_basis = _number(row.get("US Basis (USD/bu)"))
        if original_basis is None:
            continue
        original_price = _number(row.get("Futures Price"))
        if original_price is None:
            original_curve = curve.get((kind, original_month))
            original_price = original_curve[0] if original_curve else None
        target_curve = curve.get((kind, target_month))
        if original_price is None or target_curve is None:
            out.at[index, "Basis Normalization Status"] = "Missing futures price"
            continue
        target_price, target_conflict = target_curve
        normalized = original_price + original_basis - target_price
        out.at[index, "Standard Futures Month"] = target_month
        out.at[index, "Standard Futures Price"] = target_price
        out.at[index, "Standardized US Basis (USD/bu)"] = normalized
        status = "Standardized" if target_month != original_month else "Already standard"
        if target_conflict:
            status += "; AgriCharts values differed"
        out.at[index, "Basis Normalization Status"] = status

    return out.drop(columns=["_norm_commodity", "_norm_futures_month", "_norm_delivery"])
