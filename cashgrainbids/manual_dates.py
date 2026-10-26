"""Apply user-supplied quote dates to manually entered price rows."""

from __future__ import annotations

import json
from fnmatch import fnmatch
from pathlib import Path

import pandas as pd


def apply_manual_quote_dates(frame: pd.DataFrame, registry_path: Path) -> pd.DataFrame:
    """Fill blank Quote Date values from the editable JSON registry.

    Entries use ``source``, ``location`` (exact text or ``*`` wildcard), and
    ``quote_date`` in YYYY-MM-DD format. Existing dates are never overwritten.
    """
    out = frame.copy()
    if "Quote Date" not in out:
        out["Quote Date"] = pd.NA
    if not registry_path.is_file():
        return out
    try:
        entries = json.loads(registry_path.read_text(encoding="utf-8")).get("entries", [])
    except (OSError, ValueError) as exc:
        print(f"[WARN] Manual quote-date registry could not be read: {exc}")
        return out
    for entry in entries:
        source = str(entry.get("source", "")).strip()
        location_pattern = str(entry.get("location", "*")).strip() or "*"
        quote_date = str(entry.get("quote_date", "")).strip()
        if not source or not quote_date:
            continue
        if pd.isna(pd.to_datetime(quote_date, errors="coerce")):
            print(f"[WARN] Ignoring invalid manual quote date: {quote_date}")
            continue
        mask = (
            out["Source"].astype(str).eq(source)
            & out["Location"].astype(str).map(lambda value: fnmatch(value, location_pattern))
            & pd.to_datetime(out["Quote Date"], errors="coerce").isna()
        )
        out.loc[mask, "Quote Date"] = quote_date
        if mask.any():
            print(f"[INFO] Applied manual quote date {quote_date} to {int(mask.sum())} {source} row(s)")
    return out
