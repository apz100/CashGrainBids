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


# --- bushel → metric tonne conversion factors
SOY_BU_PER_MT   = 36.7437   # 1 metric tonne soybeans ≈ 36.7437 bu
CORN_BU_PER_MT  = 39.3683   # 1 metric tonne corn     ≈ 39.3683 bu
WHEAT_BU_PER_MT = 36.7437   # 1 metric tonne wheat    ≈ 36.7437 bu

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
    """Key = Location|Name|DeliveryKey|DeliveryEndKey|FutMonKey"""
    loc = df.get("Location", "").astype(str).str.strip().str.lower()
    nam = df.get("Name", "").astype(str).str.strip().str.lower()
    d1  = df.get("Delivery", "").apply(_month_to_key)
    d2  = df.get("Delivery End", "").apply(_month_to_key)
    fm  = df.get("Futures Month", "").apply(_month_to_key)
    return loc + "|" + nam + "|" + d1 + "|" + d2 + "|" + fm

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
        context = browser.new_context(
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

                df.insert(0, "Location", name)
                df = add_mt_cash_price(df)

                rows.append(df)
                print(f"[OK] {name}: {len(df)} rows")
            except Exception as e:
                print(f"[ERR] {name}: {e}")
            time.sleep(0.5)

        context.close()
        browser.close()

    if not rows:
        print("No data collected.")
        return None

    # IMPORTANT: don't fillna("") yet; we need numeric Basis for diff calc
    out = pd.concat(rows, ignore_index=True)

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
        "Location", "Name", "Delivery", "Delivery End", "Futures Month",
        "Futures Price", "Change", "Basis", "Basis Change", "Bushel Cash Price", "MT Cash Price"
    ]
    out = out[[c for c in base_cols if c in out.columns]]

    # Now it's safe to stringify empties for the CSV
    out = out.fillna("")

    # Prevent Excel from evaluating the Change strings like "+9-6" or "-0-2"
    if "Change" in out.columns:
        out["Change"] = out["Change"].astype(str).map(excel_protect)

    out.to_csv(out_path, index=False, header=True, quoting=csv.QUOTE_MINIMAL, encoding="utf-8")
    print(f"Wrote {len(out)} rows to {out_path}")
    try:
        print(out.head(12).to_string(index=False))
    except Exception:
        pass
    return out_path
if __name__ == "__main__":
    main()


