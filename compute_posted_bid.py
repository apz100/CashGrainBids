# compute_posted_bid.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import re
import pandas as pd
import os
from datetime import datetime


BU_PER_MT = {
    "corn": 39.368,      # bu per metric tonne
    "soybeans": 36.744,  # bu per metric tonne
    "wheat": 36.743,     # if you add wheat later
}


@dataclass
class BidParams:
    # Positioning vs market
    target_discount_cad_mt: float = 7.5   # aim: avg - 7.5
    discount_min_cad_mt: float = 5.0
    discount_max_cad_mt: float = 10.0

    # Anchor construction
    trim_percent: float = 0.20            # trimmed mean (drop top/bottom 20%)

    # Risk/margin clamps (optional but recommended)
        # Optional absolute floor/ceiling clamps in CAD/MT (independent of FX)
    min_posted_bid_cad_mt: Optional[float] = None  # e.g. don't go below 250
    max_posted_bid_cad_mt: Optional[float] = None  # e.g. don't go above 400


    # Rate limiting (optional)
    max_move_up_cad_mt: float = 3.0
    max_move_down_cad_mt: float = 5.0

    # Data filters
    max_bid_age_minutes: Optional[int] = None  # not used unless your CSV has timestamps


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _parse_cbot_price(price_str: str) -> float:
    """
    Parses CBOT-style strings like '425-4' into cents/bu as a float.
    Convention: the suffix is eighths of a cent.
      425-4 -> 425 + 4/8 = 425.5 cents/bu
      1061-2 -> 1061.25 cents/bu
    """
    if price_str is None or str(price_str).strip() == "":
        raise ValueError("Empty Futures Price")
    s = str(price_str).strip()
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", s)
    if not m:
        raise ValueError(f"Unrecognized Futures Price format: {price_str!r}")
    whole = float(m.group(1))
    frac = float(m.group(2)) if m.group(2) is not None else 0.0
    return whole + frac / 8.0  # cents/bu

def _futures_to_usd_per_bu(fut_price: str | float | int) -> float:
    """
    Returns futures price in USD/bu from common formats:
      - '425-6' (cents/bu CBOT)
      - '425.75' (cents/bu)
      - '4.2575' (USD/bu)
      - '$4.25' (USD/bu)
    """
    if fut_price is None:
        raise ValueError("Empty futures price")

    s = str(fut_price).strip().replace("$", "").replace(",", "")
    if s == "":
        raise ValueError("Empty futures price")

    # CBOT style: 425-6 => cents/bu
    try:
        cents = _parse_cbot_price(s)
        return cents / 100.0
    except Exception:
        pass

    # Decimal style
    v = float(s)

    # Heuristic:
    # If v is small (< 50), treat as USD/bu (e.g., 4.25)
    # If v is large (>= 50), treat as cents/bu (e.g., 425.75)
    if v < 50:
        return v
    else:
        return v / 100.0

def _trimmed_mean(values: pd.Series, trim: float) -> float:
    vals = values.dropna().astype(float).sort_values().to_list()
    n = len(vals)
    if n == 0:
        raise ValueError("No competitor MT Cash Price values after filtering.")
    if n < 5 or trim <= 0:
        return sum(vals) / n

    k = int(n * trim)
    # ensure we don't trim everything
    if 2 * k >= n:
        k = max(0, (n - 1) // 2)

    trimmed = vals[k:n - k]
    return sum(trimmed) / len(trimmed)


def compute_posted_bid_from_cashbids_csv(
    csv_path: str | Path,
    *,
    commodity: str,
    delivery: Optional[str] = None,      # matches 'Delivery' column (exact string)
    futures_month: Optional[str] = None, # matches 'Futures Month' column (exact string)
    params: BidParams = BidParams(),
    last_bid_cad_mt: Optional[float] = None,
    output_csv: Optional[str | Path] = None,
    exclude_locations: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """
    FX-free posted bid:
      anchor = trimmed_mean(competitors MT Cash Price in CAD/MT)
      posted = anchor - clamp(discount, min, max)
      optional rate limiting vs last_bid

    Uses ONLY 'MT Cash Price' from your existing CSV.
    """

    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path)

    commodity_norm = commodity.strip().lower()
    if commodity_norm not in BU_PER_MT:
        raise ValueError(f"Unsupported commodity {commodity!r}. Supported: {list(BU_PER_MT.keys())}")

    # Filter by commodity
    df_f = df[df["Name"].astype(str).str.strip().str.lower() == commodity_norm].copy()

    # Filter by delivery bucket if provided
    if delivery is not None:
        df_f = df_f[df_f["Delivery"].astype(str).str.strip() == delivery]

    # Filter by futures month label if provided
    if futures_month is not None:
        df_f = df_f[df_f["Futures Month"].astype(str).str.strip() == futures_month]
        
        # Exclude certain locations from competitor set (case-insensitive exact match)
    if exclude_locations:
        excl = {str(x).strip().lower() for x in exclude_locations}
        df_f = df_f[~df_f["Location"].astype(str).str.strip().str.lower().isin(excl)].copy()


    if df_f.empty:
        raise ValueError(
            "No rows after filtering. Check commodity/delivery/futures_month values "
            f"against the CSV. Got commodity={commodity!r}, delivery={delivery!r}, futures_month={futures_month!r}"
        )

    # Helper: pick a representative non-empty string value (mode preferred)
    def _rep(col: str) -> str:
        if col not in df_f.columns:
            return ""
        s = df_f[col].dropna().astype(str).str.strip()
        s = s[s != ""]
        if s.empty:
            return ""
        try:
            return s.mode().iloc[0]
        except Exception:
            return s.iloc[0]

    # Market anchor based on competitor MT cash prices (CAD/MT)
    comp_prices = pd.to_numeric(df_f["MT Cash Price"], errors="coerce")
    anchor_cad_mt = _trimmed_mean(comp_prices, params.trim_percent)


    # Apply desired discount band (5–10 under avg)
    discount = _clamp(params.target_discount_cad_mt, params.discount_min_cad_mt, params.discount_max_cad_mt)
    bid_raw_cad_mt = anchor_cad_mt - discount

    bid_clamped_cad_mt = float(bid_raw_cad_mt)

    # Rate limit vs last bid (optional)
    if last_bid_cad_mt is not None:
        lo = last_bid_cad_mt - params.max_move_down_cad_mt
        hi = last_bid_cad_mt + params.max_move_up_cad_mt
        bid_clamped_cad_mt = _clamp(bid_clamped_cad_mt, lo, hi)

    bu_per_mt = BU_PER_MT[commodity_norm]
    posted_bid_cad_bu = bid_clamped_cad_mt / bu_per_mt
    
    # --- BASIS (AS REQUESTED: CAD cash minus USD futures, no FX) ---


    # --- Final pricing outputs ---
    # Representative fields pulled from the competitor rows so Wix file contains
    # Delivery, Delivery End, Futures Month, Futures Price, Change, and Basis.
    rep_location = _rep("Location")
    rep_delivery = _rep("Delivery")
    rep_futures_month = _rep("Futures Month") or (futures_month or "")
    rep_fut_price = _rep("Futures Price")
    rep_change = _rep("Change")
    
    basis_cad_bu = ""

    try:
        fut_usd_bu = _futures_to_usd_per_bu(rep_fut_price)  # tolerant parse -> USD/bu
        basis_cad_bu = round(float(posted_bid_cad_bu) - float(fut_usd_bu), 2)
    except Exception:
        basis_cad_bu = ""

    result = {
        "Location": rep_location,
        "Name": commodity_norm.upper(),
        "Delivery": rep_delivery,
        "Futures Month": rep_futures_month,

        "Futures Price": rep_fut_price,
        "Change": rep_change,
        "Basis (CAD/BU)": basis_cad_bu,

        "Bushel Cash Price": round(float(posted_bid_cad_bu), 2),
        "MT Cash Price": round(float(bid_clamped_cad_mt), 2),
    }

    if output_csv is not None:
        out_path = Path(output_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([result]).to_csv(out_path, index=False)

    return result



# -----------------------
# Example usage
# -----------------------

# -----------------------
# Example usage
# -----------------------
if __name__ == "__main__":
    bids_dir = Path(r"\\DERKS-SERVER\Current\Adam\Code\CashGrainBids\EasternOntarioBids")
    src = max(bids_dir.glob("EasternOntario_CashBids_*.csv"), key=lambda p: p.stat().st_mtime)
    out_dir = Path(r"\\DERKS-SERVER\Current\Adam\Code\CashGrainBids\PostedBids")
    out_dir.mkdir(parents=True, exist_ok=True)

    params = BidParams(
        target_discount_cad_mt=10.0,
        discount_min_cad_mt=7.5,
        discount_max_cad_mt=12.5,
        trim_percent=0.20,
        min_posted_bid_cad_mt=None,
        max_posted_bid_cad_mt=None,
        max_move_up_cad_mt=3.0,
        max_move_down_cad_mt=10.0,
    )

    # Read source file once
    df_src = pd.read_csv(src)

    # Take first 4 rows (these define your 4 posted-bid lines)
    df_first4 = df_src.iloc[:4].copy()

    results = []
    for _, row in df_first4.iterrows():
        res = compute_posted_bid_from_cashbids_csv(
            src,
            commodity=str(row["Name"]).strip(),                 # "Corn" / "Soybeans"
            delivery=str(row["Delivery"]).strip(),              # column C
            futures_month=str(row["Futures Month"]).strip(),    # column E
            params=params,
            exclude_locations=None,
        )
        results.append(res)

    # ============================
    # PUBLIC OUTPUT (WIX + SHEETS)
    # ============================

    SERVICE_ACCOUNT_JSON = "C:\secrets\google\derks-elevator-bids-2c0a610dd373.json"  # <-- your real path
    SHEET_ID = "1u6sqQdT0r6rgrUR-Fg-D6brK3K7GcbC3lZ2TbS6GWUo"                       # <-- from the sheet URL
    TAB_NAME = "WIX_BIDS"                                          # <-- exact tab name

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build Wix table directly from the 4 computed results
    wix_rows = []
    for r in results:
        wix_rows.append({
            "Commodity": str(r.get("Name", "")).title(),
            "Delivery": r.get("Delivery", ""),
            "Futures Month": r.get("Futures Month", ""),
            "Futures Price": r.get("Futures Price", ""),
            "Change": r.get("Change", ""),
            "Basis (CAD/BU)": r.get("Basis (CAD/BU)", ""),
            "Cash Price (Bushels)": r.get("Bushel Cash Price", ""),
            "Cash Price (Tonnes)": r.get("MT Cash Price", ""),
            "Notes": r.get("Notes", "")
        })


    df_wix = pd.DataFrame(wix_rows)

    df_wix = pd.DataFrame(wix_rows)
    df_wix["Cash Price (Tonnes)"] = df_wix["Cash Price (Tonnes)"].round(2)

    # Write CSV for Wix
    df_wix.to_csv(out_dir / "WIX_BIDS_latest.csv", index=False)
    print(f"Wrote {out_dir / 'WIX_BIDS_latest.csv'}")

    try:
        import gspread
        from google.oauth2.service_account import Credentials
        from gspread_dataframe import set_with_dataframe

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON, scopes=scopes)
        gc = gspread.authorize(creds)

        sh = gc.open_by_key(SHEET_ID)

        # Create the tab if it doesn't exist
        try:
            ws = sh.worksheet(TAB_NAME)
        except Exception:
            ws = sh.add_worksheet(title=TAB_NAME, rows="200", cols="20")

        # Keep headers (row 1) untouched:
        ws.batch_clear(["A2:Z"])  # clears data only

        # Write data starting on row 2, no headers
        set_with_dataframe(
            ws,
            df_wix,
            include_index=False,
            include_column_header=False,
            row=2,
            col=1,
            resize=False
        )

        print(f"Google Sheets updated: sheet={SHEET_ID} tab={TAB_NAME}")

    except Exception as e:
        print("Google Sheets update FAILED:", repr(e))

