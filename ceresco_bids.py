"""Manually supplied Ceresco commercial bids.

These rows intentionally contain USD basis only because no futures/cash price
was supplied. Update this file when a new Ceresco quote is received.
"""
from __future__ import annotations

import pandas as pd


def collect_ceresco_bids() -> pd.DataFrame:
    rows = []

    def add(location, commodity, delivery, basis, futures_month):
        rows.append({
            "Source": "Ceresco bids",
            "Location": location,
            "Name": commodity,
            "Delivery": delivery,
            "Delivery End": delivery,
            "Futures Month": futures_month,
            "Futures Price": pd.NA,
            "Change": pd.NA,
            "Basis": pd.NA,
            "Basis Change": pd.NA,
            "US Basis (USD/bu)": basis,
            "US Basis Change": pd.NA,
            "Bushel Cash Price": pd.NA,
            "MT Cash Price": pd.NA,
            "Quote Date": pd.NA,
        })

    for location in ("Contrecoeur, QC", "Montreal, QC"):
        add(location, "Soybeans", "Nov 2026", -0.25, "November 2026")
        add(location, "Soybeans", "Dec 2026-Jan 2027", -0.05, "January 2027")
        add(location, "Soybeans", "Feb-Mar 2027", 0.00, "March 2027")

    for delivery, basis, futures in (
        ("Nov 2026", 0.20, "December 2026"),
        ("Dec 2026", 0.25, "December 2026"),
        ("Jan 2027", 0.30, "March 2027"),
        ("Feb 2027", 0.30, "March 2027"),
        ("Mar 2027", 0.30, "March 2027"),
        ("Apr 2027", 0.35, "May 2027"),
        ("May 2027", 0.35, "May 2027"),
        ("Jun 2027", 0.40, "July 2027"),
        ("Jul 2027", 0.05, "July 2027"),
        ("Nov 2027", 0.20, "December 2027"),
    ):
        location = "Montreal only" if delivery in {"Jan 2027", "Feb 2027"} else "Varennes / Saint-Hyacinthe*"
        add(location, "Corn", delivery, basis, futures)

    add("Johnstown, ON", "Corn", "Jan-Feb-Mar 2027", 0.15, "March 2027")
    add("Johnstown, ON", "Corn", "Apr-May 2027", 0.20, "May 2027")
    return pd.DataFrame(rows)
