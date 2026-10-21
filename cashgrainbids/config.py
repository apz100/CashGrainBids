"""Central configuration for the Eastern Ontario cash-bid collector."""

from __future__ import annotations

from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_DIR / "EasternOntarioBids"
REPORT_DIR = OUTPUT_DIR / "Reports"
LOG_DIR = PROJECT_DIR / "logs"
FX_DIR = OUTPUT_DIR / "FX"

INGREDION_URL = "https://ag.ingredion.com/cash-bids"
GREENFIELD_URL = "https://ggi.marketplace.barchart.com/cash-bids"
GREAT_LAKES_URL = "https://www.greatlakesgrain.com/cash-bids"
INGREDION_STORAGE_STATE = PROJECT_DIR / "ingredion_storage_state.json"

# Adding or removing an AgriCharts location is a configuration change, not a
# change to the collector itself.
AGRICHARTS_TARGETS = (
    {"name": "Brinston Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=3614"},
    {"name": "Brinston Soybeans", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=3615"},
    {"name": "Brinston Wheat", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=79461"},
    {"name": "Cardinal Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=4193"},
    {"name": "Chesterville Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=3371"},
    {"name": "Chesterville Soybeans", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=3382"},
    {"name": "Dalkeith Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85515"},
    {"name": "Dalkeith Soybeans", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85516"},
    {"name": "Dalkeith Wheat", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85517"},
    {"name": "Johnstown Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=7568"},
    {"name": "Kars Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=62198"},
    {"name": "Kars Soybeans", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=62199"},
    {"name": "Lansdowne Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85846"},
    {"name": "Lansdowne Soybeans", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85847"},
    {"name": "Lansdowne Wheat", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85845"},
    {"name": "North Gower Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=2640"},
    {"name": "North Gower Soybeans", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=2642"},
    {"name": "North Gower Wheat", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=2641"},
    {"name": "Prescott Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=64539"},
    {"name": "Prescott Soybeans", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=27183"},
    {"name": "Prescott Wheat", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=4427"},
    {"name": "Vankleek Hill Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=73813"},
    {"name": "Vankleek Hill Soybeans", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=73814"},
    {"name": "Winchester Corn", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=1965"},
    {"name": "Winchester Soybeans", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=1992"},
)

# Restrict only email sources. Website sources are explicitly configured above.
EMAIL_LOCATION_ALLOWLIST = {
    "andersons email bids": ("johnstown", "prescott", "picton terminal"),
    "macewen email bids": ("prescott/cardinal/johnstown", "port prescott"),
}

OUTPUT_COLUMNS = (
    "Source", "Location", "Name", "Delivery", "Delivery End", "Futures Month",
    "Futures Price", "Change", "Basis", "Basis Change", "US Basis (USD/bu)", "US Basis Change",
    "Bushel Cash Price", "MT Cash Price", "Quote Date",
)
