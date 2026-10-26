"""Source-aware business categories used by reports and future analysis."""

from __future__ import annotations

from typing import Mapping


def classify_bid(row: Mapping[str, object]) -> str:
    """Return the commercial role of a bid without changing the raw source."""
    source = str(row.get("Source", "")).lower()
    location = f"{row.get('Location', '')} {row.get('Name', '')}".lower()
    if "agricharts" in source:
        return "Direct Ship Competitor" if "prescott" in location else "Elevator"
    if "greenfield" in source or "ingredion" in source:
        return "Processor"
    if any(value in source for value in ("bunge", "richard", "richardson", "p&h", "pandh")):
        return "Exporter"
    if "anderson" in source or "macewen" in source:
        return "Direct Ship Competitor"
    if "great lakes" in source:
        return "Direct Ship Competitor" if any(word in location for word in ("port", "sorel", "direct")) else "Elevator"
    if "broadgrain" in source:
        return "Direct Ship Competitor" if any(word in location for word in ("port", "sorel", "terminal")) else "Elevator"
    if "wanna make it" in source:
        bid_type = str(row.get("Bid Type", "")).lower()
        if "fob farm" in bid_type:
            return "FOB Farm Reference"
        if str(row.get("Location", "")).strip().lower() == "wanna make it elevator":
            return "Elevator"
        return "Unclassified"
    return "Unclassified"
