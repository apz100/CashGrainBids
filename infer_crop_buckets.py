# infer_crop_buckets.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd

# Harvest delivery-month windows (calendar months)
HARVEST_WINDOW = {
    "corn": {10, 11, 12},       # Oct-Dec
    "soybeans": {9, 10, 11},    # Sep-Nov
}

def _parse_month_label(s: Any) -> Optional[pd.Timestamp]:
    """Parse labels like 'Jan 2026', 'January 2026', 'Jan-26', etc -> Timestamp (first of month)."""
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None

    fmts = ["%b %Y", "%B %Y", "%b-%y", "%b-%Y", "%b %y", "%B %y"]
    for fmt in fmts:
        try:
            dt = pd.to_datetime(t, format=fmt)
            # normalize to first of month
            return pd.Timestamp(dt.year, dt.month, 1)
        except Exception:
            pass

    # last resort
    try:
        dt = pd.to_datetime(t, errors="coerce")
        if pd.isna(dt):
            return None
        return pd.Timestamp(dt.year, dt.month, 1)
    except Exception:
        return None

def _mode(series: pd.Series) -> Optional[str]:
    s = series.dropna().astype(str).str.strip()
    s = s[s != ""]
    if s.empty:
        return None
    return s.mode().iloc[0]

def infer_old_new_crop_specs(
    df: pd.DataFrame,
    *,
    commodity: str,
    exclude_locations: Optional[List[str]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Dict[str, Optional[str]]]:
    """
    Infer (delivery, futures_month) for:
      - old: nearest delivery month available (>= current month)
      - new: latest delivery month inside harvest window (if present),
             else farthest delivery month available (>= current month)

    Returns:
      {"old": {"delivery": str|None, "futures_month": str|None},
       "new": {"delivery": str|None, "futures_month": str|None}}
    """
    now = now or datetime.now()
    commodity_norm = commodity.strip().lower()

    d = df.copy()

    # commodity filter (CSV 'Name' column contains 'Corn'/'Soybeans')
    d = d[d["Name"].astype(str).str.strip().str.lower() == commodity_norm]

    # exclude resale destinations from competitor universe
    if exclude_locations:
        excl = {str(x).strip().lower() for x in exclude_locations}
        d = d[~d["Location"].astype(str).str.strip().str.lower().isin(excl)]

    if d.empty:
        raise ValueError(f"No rows for commodity={commodity!r} after exclusions.")

    d["_delivery_dt"] = d["Delivery"].apply(_parse_month_label)
    d = d.dropna(subset=["_delivery_dt"]).copy()

    if d.empty:
        raise ValueError(f"No parsable Delivery values for commodity={commodity!r}.")

    # OLD: earliest delivery month available (regardless of current date)
    old_dt = d["_delivery_dt"].min()
    old_bucket = d[d["_delivery_dt"] == old_dt].copy()
    old_delivery = _mode(old_bucket["Delivery"]) or str(old_bucket["Delivery"].iloc[0]).strip()
    old_fut = _mode(old_bucket["Futures Month"])

    # NEW: latest delivery month available (preferring harvest window, excluding old)
    new_candidates = d[d["_delivery_dt"] > old_dt].copy()
    if new_candidates.empty:
        # Only one delivery available; use it for both
        new_candidates = d.copy()

    harvest_months = HARVEST_WINDOW.get(commodity_norm, set())
    harvest = new_candidates[new_candidates["_delivery_dt"].dt.month.isin(harvest_months)].copy()

    if not harvest.empty:
        new_dt = harvest["_delivery_dt"].max()
        new_bucket = harvest[harvest["_delivery_dt"] == new_dt].copy()
    else:
        new_dt = new_candidates["_delivery_dt"].max()
        new_bucket = new_candidates[new_candidates["_delivery_dt"] == new_dt].copy()

    new_delivery = _mode(new_bucket["Delivery"]) or str(new_bucket["Delivery"].iloc[0]).strip()
    new_fut = _mode(new_bucket["Futures Month"])

    return {
        "old": {"delivery": old_delivery, "futures_month": old_fut},  # placeholder
        "new": {"delivery": new_delivery, "futures_month": new_fut},
    }
