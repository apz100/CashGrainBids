"""Shared bid-table parsing, normalization, filtering, and history helpers."""

from __future__ import annotations

import io
import math
import re
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd
from bs4 import BeautifulSoup

from .config import AGRICHARTS_TARGETS, EMAIL_LOCATION_ALLOWLIST


SOY_BU_PER_MT = 36.7437
CORN_BU_PER_MT = 39.3683
WHEAT_BU_PER_MT = 36.7437

MONTH_MAP = {
    "Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
    "May": "May", "Jun": "June", "Jul": "July", "Aug": "August",
    "Sep": "September", "Sept": "September", "Oct": "October",
    "Nov": "November", "Dec": "December",
}
SHORT_MONTH_RX = re.compile(r"^\s*([A-Za-z]{3,4})[-\s](\d{2}|\d{4})\s*$")
CBOT_EIGHTHS_RX = re.compile(r"^[+-]?\d{1,4}-[0-7]$")
WANTED_HEADERS = (
    "Name", "Delivery", "Delivery End", "Futures Month",
    "Futures Price", "Change", "Basis", "Cash Price",
)


def add_mt_cash_price(df: pd.DataFrame) -> pd.DataFrame:
    """Add CAD/MT cash price derived from CAD/bushel and commodity."""
    out = df.copy()
    if "Bushel Cash Price" not in out.columns and "Cash Price" in out.columns:
        out = out.rename(columns={"Cash Price": "Bushel Cash Price"})
    if "Bushel Cash Price" not in out.columns:
        out["Bushel Cash Price"] = pd.NA
    price_bu = pd.to_numeric(
        out["Bushel Cash Price"].astype(str).str.replace(r"[^\d.]", "", regex=True),
        errors="coerce",
    )
    names = out.get("Name", pd.Series("", index=out.index)).astype(str)
    locations = out.get("Location", pd.Series("", index=out.index)).astype(str)
    is_soy = names.str.contains("soy", case=False, na=False) | locations.str.contains("soy", case=False, na=False)
    is_corn = names.str.contains("corn", case=False, na=False) | locations.str.contains("corn", case=False, na=False)
    is_wheat = names.str.contains("wheat", case=False, na=False) | locations.str.contains("wheat", case=False, na=False)
    mt_price = pd.Series(index=out.index, dtype="float64")
    mt_price.loc[is_soy] = price_bu.loc[is_soy] * SOY_BU_PER_MT
    mt_price.loc[is_corn] = price_bu.loc[is_corn] * CORN_BU_PER_MT
    mt_price.loc[is_wheat] = price_bu.loc[is_wheat] * WHEAT_BU_PER_MT
    if "MT Cash Price" in out.columns:
        out["MT Cash Price"] = mt_price.round(2)
    else:
        insert_at = list(out.columns).index("Bushel Cash Price") + 1
        out.insert(insert_at, "MT Cash Price", mt_price.round(2))
    return out


def norm_short_month(value: object) -> str:
    match = SHORT_MONTH_RX.match(str(value))
    if not match:
        return str(value)
    month, year = match.groups()
    year_int = int(year) + 2000 if int(year) < 100 else int(year)
    return f"{month[:3].title()} {year_int}"


def norm_full_month(value: object) -> str:
    match = SHORT_MONTH_RX.match(str(value))
    if not match:
        return str(value)
    month, year = match.groups()
    year_int = int(year) + 2000 if int(year) < 100 else int(year)
    return f"{MONTH_MAP.get(month[:3].title(), month[:3].title())} {year_int}"


def _format_cbot_eighths(cents_value: float, *, signed: bool) -> str:
    sign = ""
    if signed:
        sign = "+" if cents_value > 0 else "-" if cents_value < 0 else ""
    absolute = abs(cents_value)
    whole = int(absolute)
    fraction = round((absolute - whole) * 8)
    if fraction == 8:
        whole += 1
        fraction = 0
    return f"{sign}{whole}-{fraction}"


def normalize_futures_price(value: object) -> str:
    if pd.isna(value):
        return ""
    raw = str(value).strip()
    if not raw or raw.lower() == "nan":
        return ""
    if CBOT_EIGHTHS_RX.match(raw):
        return raw
    try:
        number = float(raw.replace(",", ""))
    except ValueError:
        return raw
    return "" if math.isnan(number) else _format_cbot_eighths(number * 100 if abs(number) < 50 else number, signed=False)


def normalize_change_value(value: object) -> str:
    if pd.isna(value):
        return ""
    raw = str(value).strip()
    if not raw or raw.lower() == "nan":
        return ""
    if CBOT_EIGHTHS_RX.match(raw):
        return raw if raw.startswith(("+", "-")) else f"+{raw}"
    try:
        number = float(raw.replace(",", ""))
    except ValueError:
        return raw
    return "" if math.isnan(number) else _format_cbot_eighths(number * 100 if abs(number) < 1 else number, signed=True)


def normalize_ingredion_change(value: object) -> str:
    """Ingredion reports price changes in cents; expose them as CAD/bu decimals."""
    if pd.isna(value):
        return ""
    raw = str(value).strip().replace(",", "")
    if not raw or raw.lower() == "nan":
        return ""
    try:
        number = float(raw)
    except ValueError:
        return raw
    if math.isnan(number):
        return ""
    return f"{number / 100:+.2f}"


def tidy_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [" ".join(str(item) for item in column if str(item) != "nan").strip() for column in out.columns]
    else:
        out.columns = [str(column).strip() for column in out.columns]
    for column in out.columns:
        if out[column].dtype == object:
            out[column] = out[column].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    return out


def score_headers(columns: Sequence[str]) -> int:
    lowered = [column.lower() for column in columns]
    return sum(1 for wanted in WANTED_HEADERS if any(wanted.lower() == column or wanted.lower() in column for column in lowered))


def pick_cash_table_html(page_html: str) -> Optional[str]:
    best_table = None
    best_score = -1
    for table in BeautifulSoup(page_html, "lxml").find_all("table"):
        headers = table.find_all("th")
        if not headers:
            first_row = table.find("tr")
            headers = first_row.find_all("td") if first_row else []
        score = score_headers([cell.get_text(" ", strip=True) for cell in headers])
        if score > best_score:
            best_table, best_score = table, score
    return str(best_table) if best_table else None


def drop_spacer_rows(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().fillna("")
    for column in WANTED_HEADERS:
        if column not in out:
            out[column] = ""
        out[column] = out[column].astype(str).str.strip()
    out = out[out["Name"].str.lower() != "name"]
    cash_ok = out["Cash Price"].str.match(re.compile(r"^\$?\s*\d"), na=False)
    futures_ok = out["Futures Price"].str.match(re.compile(r"^[+-]?\d{1,4}-[0-7]$"), na=False)
    out = out[(out["Name"].str.len() > 0) & (cash_ok | futures_ok)].copy()
    blank = (out[list(WANTED_HEADERS)] == "").all(axis=1)
    return out.loc[~blank].reset_index(drop=True)


def extract_table_to_df(table_html: str) -> pd.DataFrame:
    parsed = tidy_df(pd.read_html(io.StringIO(table_html))[0])
    if "Name" in parsed:
        parsed = parsed[parsed["Name"].astype(str).str.lower() != "name"]
    columns: dict[str, object] = {}
    for wanted in WANTED_HEADERS:
        match = next((column for column in parsed.columns if wanted.lower() == column.lower() or wanted.lower() in column.lower()), None)
        columns[wanted] = parsed[match] if match else [""] * len(parsed)
    out = pd.DataFrame(columns)
    out["Delivery"] = out["Delivery"].map(norm_short_month)
    out["Delivery End"] = out["Delivery End"].map(norm_short_month)
    out["Futures Month"] = out["Futures Month"].map(norm_full_month)
    out["Futures Price"] = out["Futures Price"].map(normalize_futures_price)
    out["Change"] = out["Change"].map(normalize_change_value)
    return drop_spacer_rows(out)


def filter_eastern_ontario_locations(df: pd.DataFrame) -> pd.DataFrame:
    if "Source" not in df.columns or "Location" not in df.columns:
        return df
    keep = pd.Series(True, index=df.index)
    source_values = df["Source"].astype(str).str.strip().str.lower()
    locations = df["Location"].astype(str).str.strip().str.lower()
    for source, allowed in EMAIL_LOCATION_ALLOWLIST.items():
        source_match = source_values.eq(source)
        location_match = pd.Series(False, index=df.index)
        for value in allowed:
            location_match |= locations.str.contains(re.escape(value), regex=True, na=False)
        keep &= ~source_match | location_match
    removed = int((~keep).sum())
    if removed:
        print(f"[INFO] Removed {removed} out-of-area or malformed email bid rows")
    return df.loc[keep].reset_index(drop=True)


def normalize_agricharts_basis(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Source" not in out.columns or "Basis" not in out.columns:
        return out
    source = out["Source"].astype(str).str.strip().str.lower()
    basis = pd.to_numeric(out["Basis"], errors="coerce")
    cents_mask = source.eq("agricharts") & basis.abs().ge(10)
    basis.loc[cents_mask] = basis.loc[cents_mask] / 100
    out["Basis"] = basis
    return out


_MON_TO_NUM = {name: number for number, names in enumerate(
    (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
     ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
     ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december")), 1
) for name in names}
_MONTH_KEY_RX = re.compile(r"^\s*([A-Za-z]+)[\s\-]+(\d{2,4})\s*$")


def month_to_key(value: object) -> str:
    raw = str(value).strip()
    match = _MONTH_KEY_RX.match(raw)
    if not match:
        return raw.lower()
    month, year = match.groups()
    year_int = int(year) + 2000 if int(year) < 100 else int(year)
    month_int = _MON_TO_NUM.get(month.lower(), _MON_TO_NUM.get(month[:3].lower()))
    return f"{year_int:04d}-{month_int:02d}" if month_int else raw.lower()


def month_sort_key(value: object) -> pd.Timestamp:
    key = month_to_key(value)
    return pd.Timestamp(f"{key}-01") if re.fullmatch(r"\d{4}-\d{2}", key) else pd.Timestamp.max


def sort_output_rows(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    order = {target["name"]: index for index, target in enumerate(AGRICHARTS_TARGETS)}
    out["__location_order"] = out.get("Location", pd.Series("", index=out.index)).map(order).fillna(len(order))
    out["__delivery_sort"] = out.get("Delivery", pd.Series("", index=out.index)).map(month_sort_key)
    out["__delivery_end_sort"] = out.get("Delivery End", pd.Series("", index=out.index)).map(month_sort_key)
    out["__futures_month_sort"] = out.get("Futures Month", pd.Series("", index=out.index)).map(month_sort_key)
    out = out.sort_values(by=["__location_order", "__delivery_sort", "__delivery_end_sort", "__futures_month_sort", "Name"], kind="stable")
    return out.drop(columns=["__location_order", "__delivery_sort", "__delivery_end_sort", "__futures_month_sort"])


def excel_protect(value: object) -> object:
    return f"'{value}" if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@") else value


def build_history_key(df: pd.DataFrame) -> pd.Series:
    defaults = pd.Series("", index=df.index)
    source = df.get("Source", pd.Series("AgriCharts", index=df.index)).astype(str).str.strip().str.lower()
    location = df.get("Location", defaults).astype(str).str.strip().str.lower()
    name = df.get("Name", defaults).astype(str).str.strip().str.lower()
    delivery = df.get("Delivery", defaults).map(month_to_key)
    delivery_end = df.get("Delivery End", defaults).map(month_to_key)
    futures = df.get("Futures Month", defaults).map(month_to_key)
    return source + "|" + location + "|" + name + "|" + delivery + "|" + delivery_end + "|" + futures


def find_previous_output_file(output_dir: Path, fetch_date: str) -> Optional[Path]:
    current = date.fromisoformat(fetch_date)
    best: tuple[date, Path] | None = None
    for path in output_dir.glob("EasternOntario_CashBids_*.csv"):
        match = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", path.name)
        if not match:
            continue
        candidate_date = date.fromisoformat(match.group(1))
        if candidate_date < current and (best is None or candidate_date > best[0]):
            best = (candidate_date, path)
    return best[1] if best else None


def add_basis_change_column(today_df: pd.DataFrame, previous_csv_path: Path) -> pd.DataFrame:
    out = today_df.copy()
    basis_today = pd.to_numeric(out.get("Basis", pd.Series(dtype="object")), errors="coerce")
    previous = pd.read_csv(previous_csv_path, dtype=str)
    for column in ("Source", "Location", "Name", "Delivery", "Delivery End", "Futures Month", "Basis"):
        if column not in previous:
            previous[column] = "AgriCharts" if column == "Source" else ""
    previous = normalize_agricharts_basis(previous)
    previous["Basis_num"] = pd.to_numeric(previous["Basis"], errors="coerce")
    previous_basis = pd.DataFrame({"key": build_history_key(previous), "basis": previous["Basis_num"]}).groupby("key", sort=False)["basis"].last()
    basis_change = build_history_key(out).map(previous_basis.to_dict())
    basis_change = basis_today - basis_change
    insert_at = out.columns.get_loc("Basis") + 1 if "Basis" in out else len(out.columns)
    if "Basis Change" in out:
        out = out.drop(columns=["Basis Change"])
    out.insert(insert_at, "Basis Change", basis_change)
    previous_us = pd.to_numeric(previous.get("US Basis (USD/bu)", pd.Series(index=previous.index)), errors="coerce")
    today_us = pd.to_numeric(out.get("US Basis (USD/bu)", pd.Series(index=out.index)), errors="coerce")
    previous_us_basis = pd.DataFrame({"key": build_history_key(previous), "basis": previous_us}).groupby("key", sort=False)["basis"].last()
    us_change = today_us - build_history_key(out).map(previous_us_basis.to_dict())
    us_insert_at = out.columns.get_loc("US Basis (USD/bu)") + 1 if "US Basis (USD/bu)" in out else len(out.columns)
    if "US Basis Change" in out:
        out = out.drop(columns=["US Basis Change"])
    out.insert(us_insert_at, "US Basis Change", us_change)
    return out
