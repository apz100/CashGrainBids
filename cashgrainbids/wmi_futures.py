"""Timestamp-aware verification of WMI's stated nearby futures price."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd


DEFAULT_DELAY_MINUTES = (0, 5, 10, 15)


def verify_nearby_futures_price(
    stated_price: float,
    email_timestamp: datetime,
    historical_quotes: pd.DataFrame,
    *,
    delay_minutes: Iterable[int] = DEFAULT_DELAY_MINUTES,
    price_tolerance: float = 0.03,
    time_window_minutes: int = 2,
) -> dict[str, object]:
    """Match an email's nearby futures value to timestamped contract quotes.

    ``historical_quotes`` must contain ``Timestamp``, ``Contract`` and
    ``Price`` columns. The function never guesses when the best candidates
    are effectively tied; this is important during contract rolls.
    """
    required = {"Timestamp", "Contract", "Price"}
    if not required.issubset(historical_quotes.columns):
        return {"status": "No historical quote data", "contract": "", "delay_minutes": ""}

    quotes = historical_quotes.copy()
    quotes["Timestamp"] = pd.to_datetime(quotes["Timestamp"], errors="coerce")
    quotes["Price"] = pd.to_numeric(quotes["Price"], errors="coerce")
    quotes = quotes.dropna(subset=["Timestamp", "Price"])
    if quotes.empty:
        return {"status": "No historical quote data", "contract": "", "delay_minutes": ""}

    candidates: list[dict[str, object]] = []
    for delay in delay_minutes:
        target_time = email_timestamp - timedelta(minutes=int(delay))
        nearby = quotes[(quotes["Timestamp"] - target_time).abs() <= pd.Timedelta(minutes=time_window_minutes)].copy()
        nearby["time_diff"] = (nearby["Timestamp"] - target_time).abs().dt.total_seconds() / 60
        nearby["price_diff"] = (nearby["Price"] - float(stated_price)).abs()
        nearby = nearby[nearby["price_diff"] <= price_tolerance]
        for _, row in nearby.iterrows():
            candidates.append({
                "contract": str(row["Contract"]),
                "delay_minutes": int(delay),
                "matched_timestamp": row["Timestamp"].isoformat(),
                "matched_price": float(row["Price"]),
                "price_diff": float(row["price_diff"]),
                "time_diff": float(row["time_diff"]),
            })

    if not candidates:
        return {"status": "No historical match", "contract": "", "delay_minutes": ""}

    candidates.sort(key=lambda item: (item["price_diff"], item["time_diff"]))
    best = candidates[0]
    if len(candidates) > 1:
        second = candidates[1]
        tied = (
            abs(float(second["price_diff"]) - float(best["price_diff"])) <= 0.005
            and abs(float(second["time_diff"]) - float(best["time_diff"])) <= 1
            and second["contract"] != best["contract"]
        )
        if tied:
            return {"status": "Ambiguous contract/timing", **best}

    return {"status": "Verified", **best}
