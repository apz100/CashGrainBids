# cash_bids_via_playwright.py
# Renders each AgriCharts page in headless Chromium and exports:
# Name | Delivery | Delivery End | Futures Month | Futures Price | Change | Basis | (Bushel Cash Price | MT Cash Price)
# + Location
# Writes daily CSV under the folder next to this script.

from pathlib import Path
from datetime import datetime
import math
import re, csv, io, time, os
from typing import List, Dict, Optional

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import datetime as _dt
import re as _re

try:
    from email_bid_sources import collect_outlook_bid_rows
except Exception:
    collect_outlook_bid_rows = None


# --- bushel → metric tonne conversion factors
SOY_BU_PER_MT   = 36.7437   # 1 metric tonne soybeans ≈ 36.7437 bu
CORN_BU_PER_MT  = 39.3683   # 1 metric tonne corn     ≈ 39.3683 bu
WHEAT_BU_PER_MT = 36.7437   # 1 metric tonne wheat    ≈ 36.7437 bu

PROJECT_DIR = Path(__file__).resolve().parent
INGREDION_URL = "https://ag.ingredion.com/cash-bids"
GREENFIELD_URL = "https://ggi.marketplace.barchart.com/cash-bids"
GREAT_LAKES_URL = "https://www.greatlakesgrain.com/cash-bids"
INGREDION_STORAGE_STATE = PROJECT_DIR / "ingredion_storage_state.json"

def add_mt_cash_price(df: pd.DataFrame) -> pd.DataFrame:
    """Rename Cash Price → Bushel Cash Price, then insert MT Cash Price right after."""
    out = df.copy()

    # ensure the bushel column name
    if "Bushel Cash Price" not in out.columns and "Cash Price" in out.columns:
        out = out.rename(columns={"Cash Price": "Bushel Cash Price"})

    # robust numeric parse from strings like "$13.24"
    raw = (
        out["Bushel Cash Price"]
        .astype(str)
        .str.replace(r"[^\d.]", "", regex=True)   # keep only digits and dot
    )
    price_bu = pd.to_numeric(raw, errors="coerce")  # -> float with NaN instead of pd.NA

    # detect commodity from Name or Location
    is_soy  = out.get("Name", "").astype(str).str.contains("soy",  case=False, na=False) \
            | out.get("Location", "").astype(str).str.contains("soy",  case=False, na=False)
    is_corn = out.get("Name", "").astype(str).str.contains("corn", case=False, na=False) \
            | out.get("Location", "").astype(str).str.contains("corn", case=False, na=False)
    is_wheat = out.get("Name", "").astype(str).str.contains("wheat", case=False, na=False) \
             | out.get("Location", "").astype(str).str.contains("wheat", case=False, na=False)

    # compute MT price (float column default NaN)
    mt_price = pd.Series(index=out.index, dtype="float64")
    mt_price.loc[is_soy]   = price_bu.loc[is_soy]   * SOY_BU_PER_MT
    mt_price.loc[is_corn]  = price_bu.loc[is_corn]  * CORN_BU_PER_MT
    mt_price.loc[is_wheat] = price_bu.loc[is_wheat] * WHEAT_BU_PER_MT

    # insert right after Bushel Cash Price
    insert_at = list(out.columns).index("Bushel Cash Price") + 1
    out.insert(insert_at, "MT Cash Price", mt_price.round(2))

    return out


# ---------- YOUR LOCATIONS ----------
TARGETS: List[Dict] = [
    {"name": "Brinston Corn",         "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=3614"},
    {"name": "Brinston Soybeans",     "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=3615"},
    {"name": "Brinston Wheat",        "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=79461"},
    {"name": "Cardinal Corn",         "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=4193"},
    {"name": "Chesterville Corn",     "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=3371"},
    {"name": "Chesterville Soybeans", "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=3382"},
    {"name": "Dalkeith Corn",         "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85515"},
    {"name": "Dalkeith Soybeans",     "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85516"},
    {"name": "Dalkeith Wheat",        "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85517"},
    {"name": "Johnstown Corn",        "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=7568"},
    {"name": "Kars Corn",             "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=62198"},
    {"name": "Kars Soybeans",         "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=62199"},
    {"name": "Lansdowne Corn",        "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85846"},
    {"name": "Lansdowne Soybeans",    "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85847"},
    {"name": "Lansdowne Wheat",       "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=85845"},
    {"name": "North Gower Corn",      "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=2640"},
    {"name": "North Gower Soybeans",  "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=2642"},
    {"name": "North Gower Wheat",     "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=2641"},
    {"name": "Prescott Corn",         "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=64539"},
    {"name": "Prescott Soybeans",     "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=27183"},
    {"name": "Prescott Wheat",        "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=4427"},
    {"name": "Vankleek Hill Corn",    "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=73813"},
    {"name": "Vankleek Hill Soybeans","url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=73814"},
    {"name": "Winchester Corn",       "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=1965"},
    {"name": "Winchester Soybeans",   "url": "https://fmn1.agricharts.com/markets/cash.php?location_filter=1992"},
]

# ---------- ROBUST OUTPUT DIR ----------
CANDIDATES = [Path(__file__).resolve().parent / "EasternOntarioBids"]

# Email bid sheets often contain several Ontario regions. Keep only the
# locations that are useful for the Eastern Ontario comparison. Web sources
# are already explicitly configured above and are not filtered here.
EMAIL_LOCATION_ALLOWLIST = {
    "andersons email bids": ("johnstown", "prescott", "picton terminal"),
    "macewen email bids": ("prescott/cardinal/johnstown", "port prescott"),
}

OUTPUT_DIR = None
last_err = None
for d in CANDIDATES:
    try:
        d.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR = d
        break
    except Exception as e:
        last_err = e
if OUTPUT_DIR is None:
    raise RuntimeError(f"Could not create any output directory from {CANDIDATES}: {last_err}")

# ---------- NORMALIZATION ----------
MONTH_MAP = {
    "Jan":"January", "Feb":"February", "Mar":"March", "Apr":"April", "May":"May", "Jun":"June",
    "Jul":"July", "Aug":"August", "Sep":"September", "Sept":"September", "Oct":"October",
    "Nov":"November", "Dec":"December"
}
SHORT_MONTH_RX = re.compile(r"^\s*([A-Za-z]{3,4})[-\s](\d{2}|\d{4})\s*$")

def norm_short_month(s: str) -> str:
    m = SHORT_MONTH_RX.match(str(s))
    if not m: return str(s)
    mon, yy = m.groups()
    mon3 = mon[:3].title()
    yyyy = int(yy) + 2000 if int(yy) < 100 else int(yy)
    return f"{mon3} {yyyy}"

def norm_full_month(s: str) -> str:
    m = SHORT_MONTH_RX.match(str(s))
    if not m: return str(s)
    mon, yy = m.groups()
    mon3 = mon[:3].title()
    full = MONTH_MAP.get(mon3, mon3)
    yyyy = int(yy) + 2000 if int(yy) < 100 else int(yy)
    return f"{full} {yyyy}"

CBOT_EIGHTHS_RX = re.compile(r"^[+-]?\d{1,4}-[0-7]$")


def _format_cbot_eighths(cents_value: float, *, signed: bool) -> str:
    sign = ""
    if signed:
        if cents_value > 0:
            sign = "+"
        elif cents_value < 0:
            sign = "-"
    abs_value = abs(cents_value)
    whole = int(abs_value)
    frac = round((abs_value - whole) * 8)
    if frac == 8:
        whole += 1
        frac = 0
    return f"{sign}{whole}-{frac}"


def normalize_futures_price(s: str) -> str:
    if pd.isna(s):
        return ""
    raw = str(s).strip()
    if not raw or raw.lower() == "nan":
        return ""
    if CBOT_EIGHTHS_RX.match(raw):
        return raw
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return raw
    if math.isnan(value):
        return ""
    cents_value = value * 100 if abs(value) < 50 else value
    return _format_cbot_eighths(cents_value, signed=False)


def normalize_change_value(s: str) -> str:
    if pd.isna(s):
        return ""
    raw = str(s).strip()
    if not raw or raw.lower() == "nan":
        return ""
    if CBOT_EIGHTHS_RX.match(raw):
        return raw if raw.startswith(("+", "-")) else "+" + raw
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return raw
    if math.isnan(value):
        return ""
    cents_value = value * 100 if abs(value) < 1 else value
    return _format_cbot_eighths(cents_value, signed=True)


def month_sort_key(s: str) -> pd.Timestamp:
    key = _month_to_key(s)
    if re.fullmatch(r"\d{4}-\d{2}", key):
        return pd.Timestamp(f"{key}-01")
    return pd.Timestamp.max


def sort_output_rows(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    location_order = {name: idx for idx, name in enumerate(t["name"] for t in TARGETS)}
    out["__location_order"] = out.get("Location", "").map(location_order).fillna(len(location_order))
    out["__delivery_sort"] = out.get("Delivery", "").apply(month_sort_key)
    out["__delivery_end_sort"] = out.get("Delivery End", "").apply(month_sort_key)
    out["__futures_month_sort"] = out.get("Futures Month", "").apply(month_sort_key)
    out = out.sort_values(
        by=["__location_order", "__delivery_sort", "__delivery_end_sort", "__futures_month_sort", "Name"],
        kind="stable",
    )
    return out.drop(columns=["__location_order", "__delivery_sort", "__delivery_end_sort", "__futures_month_sort"])

# ---------- TABLE PICKING ----------
WANTED_HEADERS = [
    "Name", "Delivery", "Delivery End", "Futures Month",
    "Futures Price", "Change", "Basis", "Cash Price"
]

def tidy_df(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join([str(x) for x in t if str(x) != "nan"]).strip() for t in df.columns]
    else:
        df.columns = [str(c).strip() for c in df.columns]
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    return df

def score_headers(cols: List[str]) -> int:
    low = [c.lower() for c in cols]
    need = [h.lower() for h in WANTED_HEADERS]
    return sum(1 for h in need if any(h == c or h in c for c in low))

def pick_cash_table_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "lxml")
    best_tbl = None
    best_score = -1
    for tbl in soup.find_all("table"):
        hdr_cells = tbl.find_all("th")
        if not hdr_cells:
            first_tr = tbl.find("tr")
            hdr_cells = first_tr.find_all("td") if first_tr else []
        hdrs = [c.get_text(" ", strip=True) for c in hdr_cells]
        sc = score_headers(hdrs)
        if sc > best_score:
            best_tbl, best_score = tbl, sc
    return str(best_tbl) if best_tbl else None

# ---------- NEW: DROP SPACER/BLANK ROWS ----------
def drop_spacer_rows(out: pd.DataFrame) -> pd.DataFrame:
    """
    Remove spacer/header-echo rows. Keep rows that have a Name and at least one price.
    """
    out = out.copy().fillna("")
    # Ensure all target cols exist
    for c in WANTED_HEADERS:
        if c not in out.columns:
            out[c] = ""
    # Whitespace normalize
    for c in WANTED_HEADERS:
        out[c] = out[c].astype(str).str.strip()
    # Drop header echoes (e.g., Name == 'Name')
    out = out[out["Name"].str.lower() != "name"]
    # “Has price” signals
    rx_cash = re.compile(r"^\$?\s*\d")            # "$13.24" or "13.24"
    rx_frac = re.compile(r"^[+-]?\d{1,4}-[0-7]$") # "1025-0", "-6-2", etc.
    cash_ok = out["Cash Price"].str.match(rx_cash, na=False)
    fut_ok  = out["Futures Price"].str.match(rx_frac, na=False)
    # Keep: Name present AND (some price present)
    name_ok = out["Name"].str.len() > 0
    keep = name_ok & (cash_ok | fut_ok)
    out = out[keep].copy()
    # Final guard: drop rows where all 9 fields are empty
    all_blank = (out[[c for c in WANTED_HEADERS if c in out.columns]] == "").all(axis=1)
    out = out[~all_blank]
    return out.reset_index(drop=True)

def extract_table_to_df(table_html: str) -> pd.DataFrame:
    dfs = pd.read_html(io.StringIO(table_html))
    df = tidy_df(dfs[0])
    if "Name" in df.columns:
        df = df[df["Name"].astype(str).str.lower() != "name"]  # small safety
    cols = {}
    for want in WANTED_HEADERS:
        match = None
        for c in df.columns:
            if want.lower() == c.lower() or want.lower() in c.lower():
                match = c
                break
        cols[want] = df[match] if match else [""] * len(df)
    out = pd.DataFrame(cols)
    if "Delivery" in out.columns:
        out["Delivery"] = out["Delivery"].apply(norm_short_month)
    if "Delivery End" in out.columns:
        out["Delivery End"] = out["Delivery End"].apply(norm_short_month)
    if "Futures Month" in out.columns:
        out["Futures Month"] = out["Futures Month"].apply(norm_full_month)
    if "Futures Price" in out.columns:
        out["Futures Price"] = out["Futures Price"].apply(normalize_futures_price)
    if "Change" in out.columns:
        out["Change"] = out["Change"].apply(normalize_change_value)
    # NEW: remove spacer/blank rows
    out = drop_spacer_rows(out)
    return out


def filter_eastern_ontario_locations(df: pd.DataFrame) -> pd.DataFrame:
    """Remove out-of-area email locations and known parser artifacts."""
    if "Source" not in df.columns or "Location" not in df.columns:
        return df
    keep = pd.Series(True, index=df.index)
    for source, allowed in EMAIL_LOCATION_ALLOWLIST.items():
        source_mask = df["Source"].astype(str).str.strip().str.lower().eq(source)
        location = df["Location"].astype(str).str.strip().str.lower()
        source_keep = pd.Series(False, index=df.index)
        for value in allowed:
            source_keep |= location.str.contains(re.escape(value), regex=True, na=False)
        keep &= ~source_mask | source_keep
    removed = int((~keep).sum())
    if removed:
        print(f"[INFO] Removed {removed} out-of-area or malformed email bid rows")
    return df.loc[keep].reset_index(drop=True)


def normalize_agricharts_basis(df: pd.DataFrame) -> pd.DataFrame:
    """AgriCharts publishes basis in cents; normalize 165 to CAD/bu 1.65."""
    out = df.copy()
    if "Source" not in out.columns or "Basis" not in out.columns:
        return out
    source = out["Source"].astype(str).str.strip().str.lower()
    basis = pd.to_numeric(out["Basis"], errors="coerce")
    cents_mask = source.eq("agricharts") & basis.abs().ge(10)
    # Replace the whole column with a numeric series. Previous CSVs are read
    # with string dtype, and assigning floats into a pandas string extension
    # column raises a TypeError on newer pandas versions.
    basis.loc[cents_mask] = basis.loc[cents_mask] / 100
    out["Basis"] = basis
    return out

# ---------- BROWSER SCRAPE ----------
def scrape_one(page, url: str) -> Optional[pd.DataFrame]:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)

    def try_extract_from_html(html: str) -> Optional[pd.DataFrame]:
        tbl_html = pick_cash_table_html(html)
        if not tbl_html:
            return None
        return extract_table_to_df(tbl_html)

    # Try main page
    try:
        page.wait_for_selector("table", timeout=15000)
        html = page.content()
        df = try_extract_from_html(html)
        if df is not None and len(df):
            return df
    except PWTimeout:
        pass

    # Try iframes
    for fr in page.frames:
        try:
            fr.wait_for_selector("table", timeout=8000)
            html = fr.content()
            df = try_extract_from_html(html)
            if df is not None and len(df):
                return df
        except PWTimeout:
            continue

    return None


def _table_after_heading(page, heading: str, required_text: tuple[str, ...] = (), timeout: int = 15000):
    """Return the first following table containing the required header text."""
    locator = page.get_by_text(heading, exact=True).first
    locator.wait_for(state="visible", timeout=timeout)
    tables = locator.locator("xpath=following::table")
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for idx in range(tables.count()):
            table = tables.nth(idx)
            if not table.is_visible():
                continue
            text = table.inner_text(timeout=1000).lower()
            if all(required.lower() in text for required in required_text):
                return table
        time.sleep(0.25)
    raise PWTimeout(f"Could not find table after {heading} with headers {required_text}")


def _parse_delivery_range(value: str) -> tuple[str, str]:
    """Convert 11/01/26 - 11/30/26 into normalized delivery fields."""
    parts = re.split(r"\s*-\s*", str(value), maxsplit=1)
    parsed = []
    for part in parts[:2]:
        try:
            parsed.append(pd.to_datetime(part).strftime("%b %Y"))
        except Exception:
            parsed.append(str(part).strip())
    if len(parsed) == 1:
        parsed.append(parsed[0])
    return parsed[0], parsed[1]


def scrape_greenfield_johnstown(page) -> Optional[pd.DataFrame]:
    """Scrape only the Johnstown Corn table from Greenfield/Barchart."""
    page.goto(GREENFIELD_URL, wait_until="domcontentloaded", timeout=45000)
    table = _table_after_heading(page, "JOHNSTOWN")
    df = tidy_df(pd.read_html(io.StringIO(table.evaluate("el => el.outerHTML")))[0])
    df.columns = [str(c).strip() for c in df.columns]

    rows = []
    for _, row in df.iterrows():
        delivery, delivery_end = _parse_delivery_range(row.get("Delivery", ""))
        rows.append({
            "Source": "Greenfield",
            "Location": "Greenfield Johnstown Corn",
            "Name": "Corn",
            "Delivery": delivery,
            "Delivery End": delivery_end,
            "Futures Month": norm_full_month(row.get("Futures Month", "")),
            "Futures Price": normalize_futures_price(row.get("Futures Price", "")),
            "Change": normalize_change_value(row.get("Change", "")),
            "Basis": row.get("Basis", ""),
            "Bushel Cash Price": row.get("Price", ""),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return None
    out["Bushel Cash Price"] = pd.to_numeric(out["Bushel Cash Price"], errors="coerce")
    out["Basis"] = pd.to_numeric(out["Basis"], errors="coerce")
    return add_mt_cash_price(out)


def scrape_ingredion_cardinal_cey_dent(page) -> Optional[pd.DataFrame]:
    """Scrape only Ingredion's Cardinal / CEY Dent table."""
    page.goto(INGREDION_URL, wait_until="domcontentloaded", timeout=45000)
    if page.locator("input[type='password']").count() > 0:
        print("[AUTH] Ingredion requires login; skipping Cardinal CEY Dent")
        return None

    section = page.get_by_text("CEY Dent", exact=True).first.locator(
        "xpath=ancestor::div[contains(@class, 'cbCommodity')]"
    )
    section.wait_for(state="visible", timeout=15000)
    row_locator = section.locator("ul[class*='fcControls1'], ul[class*='fcControls2']")
    rows = []
    for idx in range(row_locator.count()):
        cells = [value.strip() for value in row_locator.nth(idx).locator("li").all_inner_texts()]
        if len(cells) < 7:
            continue
        delivery, bid, basis, futures, change, futures_month, _last_trade = cells[:7]
        mt_price = pd.to_numeric(bid.replace(",", ""), errors="coerce")
        basis_mt = pd.to_numeric(basis.replace(",", ""), errors="coerce")
        bu_price = mt_price / CORN_BU_PER_MT
        basis_bu = basis_mt / CORN_BU_PER_MT
        rows.append({
            "Source": "Ingredion",
            "Location": "Ingredion Cardinal CEY Dent",
            "Name": "Corn",
            "Delivery": norm_short_month(delivery),
            "Delivery End": norm_short_month(delivery),
            "Futures Month": norm_full_month(futures_month.replace(" Corn", "")),
            "Futures Price": normalize_futures_price(re.sub(r"[sS]$", "", futures.strip())),
            "Change": normalize_change_value(change),
            # Ingredion reports Bid and Basis in CAD/MT; normalize Basis to CAD/bu.
            "Basis": basis_bu,
            "Bushel Cash Price": bu_price,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return None
    out["Basis"] = pd.to_numeric(out["Basis"], errors="coerce")
    return add_mt_cash_price(out)


def _futures_month_from_dtn_symbol(symbol: str) -> str:
    """Convert DTN symbols such as @C6Z or @MW7U to a futures month."""
    raw = re.sub(r"[^A-Za-z0-9]", "", str(symbol)).upper()
    month_codes = {
        "F": "January", "G": "February", "H": "March", "J": "April",
        "K": "May", "M": "June", "N": "July", "Q": "August",
        "U": "September", "V": "October", "X": "November", "Z": "December",
    }
    match = re.search(r"(\d)([FGHJKMNQUVXZ])$", raw)
    if not match:
        return str(symbol).strip()
    year_digit, month_code = match.groups()
    year = 2020 + int(year_digit)
    return f"{month_codes[month_code]} {year}"


def _parse_visible_number(value: object) -> float:
    """Parse a displayed number while ignoring hidden HTML comments."""
    text = re.sub(r"<!--.*?-->", "", str(value), flags=re.S)
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text.replace(",", ""))
    return float(match.group()) if match else float("nan")


def scrape_great_lakes_embrun(page) -> Optional[pd.DataFrame]:
    """Scrape all visible elevator bids for Embrun from Great Lakes Grain."""
    frame = None
    last_error = None
    for attempt in range(1, 4):
        try:
            page.goto(GREAT_LAKES_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500 * attempt)
            frame = next(
                (fr for fr in page.frames if "cashbids.greatlakesgrain.com" in fr.url),
                None,
            )
            if frame is not None:
                break
        except Exception as exc:
            last_error = exc
        if attempt < 3:
            print(f"[WARN] Great Lakes frame not ready; retrying ({attempt}/3)")
    if frame is None:
        detail = f": {last_error}" if last_error else ""
        raise RuntimeError(f"Great Lakes cash-bids frame was not found after 3 attempts{detail}")

    location = frame.locator("select[name='Location']").first
    location.wait_for(state="visible", timeout=15000)
    location.select_option(label="Embrun Elevator")
    frame.wait_for_timeout(1500)
    location_id = location.input_value()
    frame.goto(
        f"https://cashbids.greatlakesgrain.com/index.cfm?show=11&mid=25"
        f"&theLocation={location_id}&cmid=all&layout=19",
        wait_until="networkidle",
        timeout=60000,
    )

    commodity_names = ["Corn", "Soybeans", "SRW Wheat", "HR Spring Wheat", "HRW Wheat"]
    tables = frame.locator("table[name='cashbids-data-table']")
    if tables.count() == 0:
        raise RuntimeError("Great Lakes Embrun page loaded, but no bid tables were found")
    rows = []
    for idx in range(tables.count()):
        table_html = tables.nth(idx).evaluate("el => el.outerHTML")
        df = tidy_df(pd.read_html(io.StringIO(table_html))[0])
        commodity = commodity_names[idx] if idx < len(commodity_names) else "Unknown"
        for _, row in df.iterrows():
            delivery = norm_short_month(row.get("Delivery", ""))
            rows.append({
                "Source": "Great Lakes Grain",
                "Location": "Great Lakes Embrun Elevator",
                "Name": commodity,
                "Delivery": delivery,
                "Delivery End": delivery,
                "Futures Month": _futures_month_from_dtn_symbol(row.get("Futures Mon.", "")),
                "Futures Price": normalize_futures_price(
                    str(row.get("Futures", "")).replace("'", "-")
                ),
                "Change": normalize_change_value(
                    str(row.get("Chg", "")).replace("'", "-")
                ),
                "Basis": _parse_visible_number(row.get("Basis", "")),
                "Bushel Cash Price": _parse_visible_number(row.get("Cash Price", "")),
            })

    out = pd.DataFrame(rows)
    if out.empty:
        return None
    return add_mt_cash_price(out)

def excel_protect(s: str) -> str:
    if isinstance(s, str) and s and s[0] in ("=", "+", "-", "@"):
        return "'" + s  # Excel treats this as literal text, not a formula
    return s

# ---------- BASIS CHANGE HELPERS ----------
# Month maps to build a robust YYYY-MM key from various formats
_MON_TO_NUM = {
    "jan":1,"january":1, "feb":2,"february":2, "mar":3,"march":3, "apr":4,"april":4,
    "may":5, "jun":6,"june":6, "jul":7,"july":7, "aug":8,"august":8,
    "sep":9,"sept":9,"september":9, "oct":10,"october":10, "nov":11,"november":11, "dec":12,"december":12
}
_RX_MON_ANY = _re.compile(r"^\s*([A-Za-z]+)[\s\-]+(\d{2,4})\s*$")

def _month_to_key(s: str) -> str:
    """
    Normalize 'Sep-25', 'Sep 2025', or 'September 2025' -> '2025-09'.
    If not parseable, returns stripped lowercased string.
    """
    s = str(s).strip()
    m = _RX_MON_ANY.match(s)
    if not m:
        parts = s.replace(",", " ").replace("  ", " ").split()
        if len(parts) == 2 and parts[0].isalpha() and parts[1].isdigit():
            mon = parts[0].lower()
            yr  = int(parts[1])
            yr  = 2000 + yr if yr < 100 else yr
            mm  = _MON_TO_NUM.get(mon, None)
            if mm:
                return f"{yr:04d}-{mm:02d}"
        return s.lower()
    mon, yy = m.groups()
    yr = int(yy)
    yr = 2000 + yr if yr < 100 else yr
    mm = _MON_TO_NUM.get(mon.lower(), _MON_TO_NUM.get(mon[:3].lower(), None))
    return f"{yr:04d}-{mm:02d}" if mm else s.lower()

def _build_key(df: pd.DataFrame) -> pd.Series:
    """Key = Source|Location|Name|DeliveryKey|DeliveryEndKey|FutMonKey"""
    source = df.get("Source", pd.Series("AgriCharts", index=df.index)).astype(str).str.strip().str.lower()
    loc = df.get("Location", "").astype(str).str.strip().str.lower()
    nam = df.get("Name", "").astype(str).str.strip().str.lower()
    d1  = df.get("Delivery", "").apply(_month_to_key)
    d2  = df.get("Delivery End", "").apply(_month_to_key)
    fm  = df.get("Futures Month", "").apply(_month_to_key)
    return source + "|" + loc + "|" + nam + "|" + d1 + "|" + d2 + "|" + fm

def _find_prev_output_file(fetch_date: str) -> Optional[Path]:
    """
    Return the most recent prior *_YYYY-MM-DD.csv in OUTPUT_DIR with a date < fetch_date.
    Accepts either 'cash_bids_raw_*.csv' or 'EasternOntario_CashBids_*.csv'.
    """
    current = _dt.date.fromisoformat(fetch_date)
    best = None
    for p in OUTPUT_DIR.glob("*.csv"):
        m = _re.search(r"(?:cash_bids_raw|EasternOntario_CashBids)_(\d{4}-\d{2}-\d{2})\.csv$", p.name)
        if not m:
            continue
        d = _dt.date.fromisoformat(m.group(1))
        if d < current and (best is None or d > best[0]):
            best = (d, p)
    return best[1] if best else None

def add_basis_change_column(today_df: pd.DataFrame, prev_csv_path: Path) -> pd.DataFrame:
    """
    Compute 'Basis Change' = today's Basis - previous day's Basis (aligned by key)
    and insert it immediately after the Basis column.

    This version makes the previous-day key index UNIQUE before mapping,
    so .map() won't raise InvalidIndexError when there are duplicate keys.
    """
    out = today_df.copy()

    # Today's numeric basis
    basis_today = pd.to_numeric(out.get("Basis", pd.Series(dtype="object")), errors="coerce")

    # Load previous CSV (as strings), ensure columns exist
    prev = pd.read_csv(prev_csv_path, dtype=str)
    for c in ["Location", "Name", "Delivery", "Delivery End", "Futures Month", "Basis"]:
        if c not in prev.columns:
            prev[c] = ""
    if "Source" not in prev.columns:
        prev["Source"] = "AgriCharts"

    # Older files may contain AgriCharts basis as whole cents (165). Bring
    # them to the same CAD/bu scale as today's normalized values.
    prev = normalize_agricharts_basis(prev)

    # Numeric previous basis
    prev["Basis_num"] = pd.to_numeric(prev["Basis"], errors="coerce")

    # Build comparable keys for today and previous
    key_today = _build_key(out)
    key_prev  = _build_key(prev)

    # --- Make previous keys UNIQUE before mapping ---
    # Policy: if duplicates exist, keep the LAST occurrence (most recent row in file).
    prev_unique = (
        pd.DataFrame({"key": key_prev, "basis": prev["Basis_num"]})
        .groupby("key", sort=False, as_index=True)["basis"]
        .last()               # collapse duplicates
    )

    # Optional: quick debug if you want to know duplicates existed
    # dupes = pd.Series(key_prev).value_counts()
    # if (dupes > 1).any():
    #     print(f"[INFO] previous-day duplicate keys: {(dupes > 1).sum()}")

    # Align previous basis to today's rows
    aligned_prev = key_today.map(prev_unique.to_dict())

    # Compute change
    basis_change = basis_today - aligned_prev  # NaN where no match

    # Insert column right after 'Basis'
    insert_at = out.columns.get_loc("Basis") + 1 if "Basis" in out.columns else len(out.columns)
    out.insert(insert_at, "Basis Change", basis_change)

    return out

def main():
    now = datetime.now()
    fetch_date = now.strftime("%Y-%m-%d")
    fetch_ts = now.isoformat(timespec="seconds")
    out_path = OUTPUT_DIR / f"EasternOntario_CashBids_{fetch_date}.csv"

    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context_kwargs = {}
        if INGREDION_STORAGE_STATE.is_file():
            context_kwargs["storage_state"] = str(INGREDION_STORAGE_STATE)
        context = browser.new_context(
            **context_kwargs,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari"
        )
        page = context.new_page()

        for t in TARGETS:
            name, url = t["name"], t["url"]
            try:
                df = scrape_one(page, url)
                if df is None or df.empty:
                    print(f"[WARN] {name}: no rendered bids table found")
                    continue

                df.insert(0, "Source", "AgriCharts")
                df.insert(1, "Location", name)
                df = add_mt_cash_price(df)

                rows.append(df)
                print(f"[OK] {name}: {len(df)} rows")
            except Exception as e:
                print(f"[ERR] {name}: {e}")
            time.sleep(0.5)

        for source_name, collector in [
            ("Greenfield Johnstown Corn", scrape_greenfield_johnstown),
            ("Ingredion Cardinal CEY Dent", scrape_ingredion_cardinal_cey_dent),
            ("Great Lakes Embrun Elevator", scrape_great_lakes_embrun),
        ]:
            try:
                df = collector(page)
                if df is None or df.empty:
                    print(f"[WARN] {source_name}: no data collected")
                    continue
                rows.append(df)
                print(f"[OK] {source_name}: {len(df)} rows")
            except Exception as e:
                print(f"[ERR] {source_name}: {e}")
            time.sleep(0.5)

        context.close()
        browser.close()

    # Classic Outlook runs in the signed-in Windows user's session. Email
    # failures are non-fatal so a missing Outlook profile cannot stop web bids.
    if collect_outlook_bid_rows is not None:
        try:
            email_rows = collect_outlook_bid_rows(PROJECT_DIR)
            if email_rows is not None and not email_rows.empty:
                rows.append(email_rows)
                print(f"[OK] Outlook email bids: {len(email_rows)} rows")
        except Exception as exc:
            print(f"[ERR] Outlook email bids: {exc}")

    if not rows:
        print("No data collected.")
        return 1

    # IMPORTANT: don't fillna("") yet; we need numeric Basis for diff calc
    out = pd.concat(rows, ignore_index=True)
    out = normalize_agricharts_basis(out)
    out = filter_eastern_ontario_locations(out)

    # Compare to the most recent prior CSV (if any) and add 'Basis Change'
    prev_path = _find_prev_output_file(fetch_date)
    if prev_path is not None:
        out = add_basis_change_column(out, prev_path)
    else:
        # no prior file: still add the column so the CSV schema is stable
        if "Basis" in out.columns:
            out.insert(out.columns.get_loc("Basis") + 1, "Basis Change", pd.NA)
        else:
            out["Basis Change"] = pd.NA

    out = sort_output_rows(out).reset_index(drop=True)

    # Final column order (no Settlement; include Basis Change and Bushel/MT)
    base_cols = [
        "Source", "Location", "Name", "Delivery", "Delivery End", "Futures Month",
        "Futures Price", "Change", "Basis", "Basis Change", "Bushel Cash Price", "MT Cash Price"
    ]
    out = out[[c for c in base_cols if c in out.columns]]

    # Now it's safe to stringify empties for the CSV
    out = out.fillna("")

    # Standardize numeric output to two decimal places.
    # Keep futures/change values in their existing CBOT eighths format.
    for col in ["Basis", "Basis Change", "Bushel Cash Price", "MT Cash Price"]:
        if col not in out.columns:
            continue
        numeric = pd.to_numeric(
            out[col].astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
            errors="coerce",
        ).round(2)
        out[col] = numeric.map(lambda value: f"{value:.2f}" if pd.notna(value) else "")

    if "Bushel Cash Price" in out.columns:
        out["Bushel Cash Price"] = out["Bushel Cash Price"].map(
            lambda value: f"${value}" if value else ""
        )

    # Prevent Excel from evaluating the Change strings like "+9-6" or "-0-2"
    if "Change" in out.columns:
        out["Change"] = out["Change"].astype(str).map(excel_protect)

    out.to_csv(out_path, index=False, header=True, quoting=csv.QUOTE_MINIMAL, encoding="utf-8")
    print(f"Wrote {len(out)} rows to {out_path}")

    # Also write a real Excel workbook so Excel preserves two-decimal display.
    xlsx_path = out_path.with_suffix(".xlsx")
    try:
        excel_out = out.copy()
        for col in ["Basis", "Basis Change", "Bushel Cash Price", "MT Cash Price"]:
            if col in excel_out.columns:
                excel_out[col] = pd.to_numeric(
                    excel_out[col].astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
                    errors="coerce",
                )

        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            excel_out.to_excel(writer, index=False, sheet_name="Cash Bids")
            sheet_names = {"AgriCharts": "AgriCharts", "Greenfield": "Greenfield",
                           "Ingredion": "Ingredion", "Great Lakes Grain": "Great Lakes",
                           "Andersons email bids": "Andersons Email",
                           "MacEwen email bids": "MacEwen Email"}
            for source, source_df in excel_out.groupby("Source", sort=False):
                sheet_name = sheet_names.get(str(source), str(source)[:31])
                source_df = source_df.dropna(axis=1, how="all")
                source_df.to_excel(writer, index=False, sheet_name=sheet_name)

            for worksheet in writer.book.worksheets:
                worksheet.freeze_panes = "A2"
                worksheet.auto_filter.ref = worksheet.dimensions
                header_map = {cell.value: cell.column for cell in worksheet[1]}
                for col in ["Basis", "Basis Change", "MT Cash Price"]:
                    if col in header_map:
                        for cell in worksheet.iter_cols(
                            min_col=header_map[col], max_col=header_map[col], min_row=2
                        ):
                            for value_cell in cell:
                                value_cell.number_format = "0.00"
                if "Bushel Cash Price" in header_map:
                    for cell in worksheet.iter_cols(
                        min_col=header_map["Bushel Cash Price"],
                        max_col=header_map["Bushel Cash Price"],
                        min_row=2,
                    ):
                        for value_cell in cell:
                            value_cell.number_format = "$0.00"

        print(f"Wrote formatted Excel workbook to {xlsx_path}")
    except Exception as e:
        print(f"[WARN] Could not write Excel workbook: {e}")

    try:
        print(out.head(12).to_string(index=False))
    except Exception:
        pass
    return 0
if __name__ == "__main__":
    raise SystemExit(main())


