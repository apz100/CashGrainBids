"""Daily CAD/USD spot rate collection and cached historical FX values."""

from __future__ import annotations

import json
import html
import re
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd


BOC_USDCAD_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json"
FRANKFURTER_USDCAD_URL = "https://api.frankfurter.app"
CME_CADUSD_QUOTES_URL = "https://www.cmegroup.com/markets/fx/g10/canadian-dollar/quotes"
FARMBUCKS_CADUSD_URL = "https://farmbucks.com/futures/currencies/canadian-dollar"
BARCHART_CADUSD_URL = "https://www.barchart.com/futures/quotes/D6%2A0/futures-prices"
TRADINGVIEW_CADUSD_URL = "https://www.tradingview.com/symbols/CME-6C1!/contracts/"


def load_forward_curve(cache_dir: Path) -> dict[str, tuple[float, str]]:
    """Load month-matched CME-style USD/CAD quotes from the local FX cache.

    CSV columns: Futures Month, USD/CAD, Quote Date. Quotes are USD per CAD.
    The file is deliberately an explicit input so a missing market quote can
    never be silently fabricated.
    """
    path = cache_dir / "FX_Forward_Rates.csv"
    if not path.is_file():
        return {}
    frame = pd.read_csv(path)
    required = {"Futures Month", "USD/CAD"}
    if not required.issubset(frame.columns):
        print(f"[WARN] Ignoring malformed FX forward curve: {path}")
        return {}
    result = {}
    for _, row in frame.iterrows():
        month = str(row["Futures Month"]).strip().lower()
        try:
            quote = float(row["USD/CAD"])
        except (TypeError, ValueError):
            continue
        if month and quote > 0:
            result[month] = (quote, str(row.get("Quote Date", "")))
    return result


def parse_cme_cadusd_rows(rows: list[str], quote_date: str) -> pd.DataFrame:
    """Parse rendered CME 6C quote rows into the local forward-curve schema."""
    month_codes = {"F": "January", "G": "February", "H": "March", "J": "April",
                   "K": "May", "M": "June", "N": "July", "Q": "August",
                   "U": "September", "V": "October", "X": "November", "Z": "December"}
    records = []
    row_re = re.compile(r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(20\d{2})\b.*?\b(6C([FGHJKMNQUVXZ])(\d{1,2}))\b", re.I)
    number_re = re.compile(r"(?<![A-Z])(?:0\.)?\d{1,4}(?:\.\d+)?")
    for raw in rows:
        text = " ".join(str(raw).split())
        match = row_re.search(text)
        if not match:
            continue
        month_name = month_codes[match.group(4).upper()]
        year_digit = int(match.group(5))
        year = 2020 + year_digit if year_digit < 10 else 2000 + year_digit
        decimals = [float(value) for value in number_re.findall(text[match.end():]) if 0.5 <= float(value) <= 1.5]
        if not decimals:
            continue
        records.append({"Futures Month": f"{month_name} {year}", "USD/CAD": decimals[0], "Quote Date": quote_date})
    return pd.DataFrame(records).drop_duplicates("Futures Month")


def collect_cme_cadusd_forward_curve(page, cache_dir: Path) -> Path | None:
    """Collect public delayed CME 6C quotes and cache them for this run."""
    try:
        # CME can keep the document request open while its quote widgets load;
        # commit plus a short render wait is more reliable than waiting for
        # DOMContentLoaded.
        page.goto(CME_CADUSD_QUOTES_URL, wait_until="commit", timeout=30_000)
        page.wait_for_timeout(3_000)
        rows = page.locator("tr").all_inner_texts()
        quote_date = datetime.now().astimezone().isoformat(timespec="seconds")
        curve = parse_cme_cadusd_rows(rows, quote_date)
        if curve.empty:
            print("[WARN] CME CAD/USD page returned no parseable 6C quotes")
            return None
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / "FX_Forward_Rates.csv"
        curve.to_csv(path, index=False)
        print(f"[OK] CME CAD/USD forward curve: {len(curve)} contracts -> {path}")
        return path
    except Exception as exc:
        print(f"[WARN] CME CAD/USD quote collection failed: {exc}")
        return None


def parse_farmbucks_cadusd_text(text: str, quote_date: str) -> pd.DataFrame:
    """Parse Farmbucks' public 6C futures chain as a CME fallback."""
    month_codes = {"F": "January", "G": "February", "H": "March", "J": "April",
                   "K": "May", "M": "June", "N": "July", "Q": "August",
                   "U": "September", "V": "October", "X": "November", "Z": "December"}
    records = []
    # The chain places the delivery label between the contract code and the
    # price: ``6CX26 Nov 2026 $0.7142``. Stop before the next contract code so
    # the first four-decimal value belongs to the current row.
    pattern = re.compile(
        r"\b6C([FGHJKMNQUVXZ])(\d{2})\b(?:(?!\b6C).){0,120}?\$?(0\.\d{4})\b",
        re.I | re.S,
    )
    for match in pattern.finditer(text):
        code, year_text, value = match.groups()
        year = 2000 + int(year_text)
        records.append({
            "Futures Month": f"{month_codes[code]} {year}",
            "USD/CAD": float(value),
            "Quote Date": quote_date,
        })
    return pd.DataFrame(records).drop_duplicates("Futures Month")


def collect_farmbucks_cadusd_forward_curve(page, cache_dir: Path, output_name: str = "FX_Forward_Rates.csv") -> Path | None:
    """Collect the public delayed 6C contract chain without browser dependence."""
    quote_date = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        request = Request(FARMBUCKS_CADUSD_URL, headers={"User-Agent": "CashGrainBids/1.0"})
        with urlopen(request, timeout=20) as response:
            source = response.read().decode("utf-8", errors="replace")
        page_text = html.unescape(re.sub(r"<[^>]+>", " ", source))
        curve = parse_farmbucks_cadusd_text(page_text, quote_date)
        if curve.empty:
            # Some deployments populate the chain client-side; retain the
            # browser path as a secondary method before declaring failure.
            page.goto(FARMBUCKS_CADUSD_URL, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(1_500)
            curve = parse_farmbucks_cadusd_text(page.locator("body").inner_text(), quote_date)
        if curve.empty:
            print("[WARN] Farmbucks CAD/USD page returned no parseable 6C quotes")
            return None
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / output_name
        curve.to_csv(path, index=False)
        print(f"[OK] Farmbucks CAD/USD fallback: {len(curve)} contracts -> {path}")
        return path
    except Exception as exc:
        print(f"[WARN] Farmbucks CAD/USD HTTP request failed: {exc}")
        try:
            page.goto(FARMBUCKS_CADUSD_URL, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(1_500)
            curve = parse_farmbucks_cadusd_text(page.locator("body").inner_text(), quote_date)
            if not curve.empty:
                cache_dir.mkdir(parents=True, exist_ok=True)
                path = cache_dir / output_name
                curve.to_csv(path, index=False)
                print(f"[OK] Farmbucks CAD/USD browser fallback: {len(curve)} contracts -> {path}")
                return path
        except Exception as browser_exc:
            print(f"[WARN] Farmbucks CAD/USD browser fallback failed: {browser_exc}")
        return None


def parse_barchart_cadusd_text(text: str, quote_date: str) -> pd.DataFrame:
    """Parse Barchart's public Canadian-dollar futures price table."""
    month_codes = {"F": "January", "G": "February", "H": "March", "J": "April",
                   "K": "May", "M": "June", "N": "July", "Q": "August",
                   "U": "September", "V": "October", "X": "November", "Z": "December"}
    records = []
    pattern = re.compile(
        r"\bD6([FGHJKMNQUVXZ])(\d{2})\b.{0,240}?(?:Last Price|Last)\s*[:|]?\s*\$?([01]\.\d{4,5})",
        re.I | re.S,
    )
    for match in pattern.finditer(text):
        code, year_text, value = match.groups()
        records.append({
            "Futures Month": f"{month_codes[code]} {2000 + int(year_text)}",
            "USD/CAD": float(value),
            "Quote Date": quote_date,
        })
    return pd.DataFrame(records).drop_duplicates("Futures Month")


def collect_barchart_cadusd_forward_curve(page, cache_dir: Path) -> Path | None:
    """Second public fallback for the CME 6C futures curve."""
    try:
        page.goto(BARCHART_CADUSD_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2_000)
        quote_date = datetime.now().astimezone().isoformat(timespec="seconds")
        curve = parse_barchart_cadusd_text(page.locator("body").inner_text(), quote_date)
        if curve.empty:
            print("[WARN] Barchart CAD/USD page returned no parseable 6C quotes")
            return None
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / "FX_Forward_Rates.csv"
        curve.to_csv(path, index=False)
        print(f"[OK] Barchart CAD/USD fallback: {len(curve)} contracts -> {path}")
        return path
    except Exception as exc:
        print(f"[WARN] Barchart CAD/USD fallback failed: {exc}")
        return None


def parse_tradingview_cadusd_text(text: str, quote_date: str) -> pd.DataFrame:
    """Parse TradingView's individual-contract 6C chain."""
    month_codes = {"F": "January", "G": "February", "H": "March", "J": "April",
                   "K": "May", "M": "June", "N": "July", "Q": "August",
                   "U": "September", "V": "October", "X": "November", "Z": "December"}
    records = []
    pattern = re.compile(
        r"\b6C([FGHJKMNQUVXZ])(20\d{2})\b[\s\S]{0,180}?\b(0\.\d{4,5})\b",
        re.I,
    )
    for match in pattern.finditer(text):
        code, year_text, value = match.groups()
        records.append({
            "Futures Month": f"{month_codes[code.upper()]} {year_text}",
            "USD/CAD": float(value),
            "Quote Date": quote_date,
        })
    return pd.DataFrame(records).drop_duplicates("Futures Month")


def collect_tradingview_cadusd_forward_curve(
    page, cache_dir: Path, output_name: str = "FX_Forward_Rates_TradingView.csv"
) -> Path | None:
    """Collect TradingView's full delayed 6C contract chain."""
    try:
        page.goto(TRADINGVIEW_CADUSD_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2_000)
        quote_date = datetime.now().astimezone().isoformat(timespec="seconds")
        curve = parse_tradingview_cadusd_text(page.locator("body").inner_text(), quote_date)
        if curve.empty:
            print("[WARN] TradingView CAD/USD page returned no parseable 6C contracts")
            return None
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / output_name
        curve.to_csv(path, index=False)
        print(f"[OK] TradingView CAD/USD forward curve: {len(curve)} contracts -> {path}")
        return path
    except Exception as exc:
        print(f"[WARN] TradingView CAD/USD collection failed: {exc}")
        return None


def crosscheck_forward_curves(primary_path: Path, secondary_path: Path, log_path: Path) -> None:
    """Log contract-level differences without changing the selected curve."""
    primary = pd.read_csv(primary_path).rename(columns={"USD/CAD": "Primary USD/CAD"})
    secondary = pd.read_csv(secondary_path).rename(columns={"USD/CAD": "Secondary USD/CAD"})
    merged = primary.merge(secondary, on="Futures Month", how="outer", suffixes=("", " Secondary"))
    merged["Difference"] = merged["Primary USD/CAD"] - merged["Secondary USD/CAD"]
    merged["Both Present"] = merged["Primary USD/CAD"].notna() & merged["Secondary USD/CAD"].notna()
    merged["Match"] = merged["Both Present"] & merged["Difference"].abs().le(0.0002)
    merged.to_csv(log_path, index=False)
    mismatches = int((merged["Both Present"] & ~merged["Match"]).sum())
    missing = int((~merged["Both Present"]).sum())
    compared = int(merged["Both Present"].sum())
    print(f"[INFO] FX cross-check: {compared} shared contracts, {mismatches} mismatches, {missing} source-only contracts")


def _json_get(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "CashGrainBids/1.0"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def get_usdcad_spot(fetch_date: str, cache_dir: Path) -> tuple[float, str] | None:
    """Return CAD per USD for the requested date, using the latest prior BOC value."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"FX_Rates_{fetch_date}.json"
    try:
        payload = _json_get(f"{BOC_USDCAD_URL}?start_date={fetch_date}&end_date={fetch_date}")
        observations = payload.get("observations", [])
        if observations:
            value = observations[-1].get("FXUSDCAD", {}).get("v")
            if value not in (None, ""):
                result = {"requested_date": fetch_date, "quote_date": observations[-1]["d"], "usdcad": float(value), "source": BOC_USDCAD_URL}
                cache_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
                return result["usdcad"], result["quote_date"]
    except Exception as exc:
        print(f"[WARN] Bank of Canada FX request failed: {exc}")
    try:
        payload = _json_get(f"{FRANKFURTER_USDCAD_URL}/{fetch_date}?from=USD&to=CAD")
        value = payload.get("rates", {}).get("CAD")
        quote_date = str(payload.get("date", fetch_date))
        if value not in (None, ""):
            result = {"requested_date": fetch_date, "quote_date": quote_date, "usdcad": float(value), "source": FRANKFURTER_USDCAD_URL}
            cache_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print("[INFO] Using Frankfurter FX fallback")
            return result["usdcad"], result["quote_date"]
    except Exception as exc:
        print(f"[WARN] Frankfurter FX fallback failed: {exc}")
    if cache_path.is_file():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("usdcad") and cached.get("quote_date"):
            return float(cached["usdcad"]), str(cached["quote_date"])
    return None


def _futures_number(value: object) -> float:
    raw = str(value).strip().replace("'", "-")
    if "-" in raw:
        whole, eighths = raw.rsplit("-", 1)
        try:
            return (float(whole) + float(eighths) / 8) / 100
        except ValueError:
            return float("nan")
    try:
        return float(raw)
    except ValueError:
        return float("nan")


def add_wanna_make_it_nearby_basis(df: pd.DataFrame, fetch_date: str) -> pd.DataFrame:
    """Derive nearby corn/soybean basis from flat CAD/MT quotes.

    The source prints CAD/MT, while the standard elevator comparison uses
    CAD/bu minus the matching CBOT futures price. Convert the nearby WMI
    elevator quote when it exists, and the nearby FOB Farm quote as a
    fallback. Deferred FOB Farm rows remain raw reference prices until their
    own comparison rules are defined.
    """
    out = df.copy()
    required = {"Source", "Name", "Delivery", "Bid Type", "Bushel Cash Price"}
    if not required.issubset(out.columns):
        return out
    try:
        current = datetime.strptime(fetch_date, "%Y-%m-%d")
    except ValueError:
        return out
    nearby_delivery = current.strftime("%b %Y")
    source_mask = out["Source"].astype(str).str.lower().eq("agricharts")
    wmi_mask = out["Source"].astype(str).str.lower().eq("wanna make it email bids")
    out["Futures Month"] = out["Futures Month"].astype(object)
    out["Futures Price"] = out["Futures Price"].astype(object)
    out["Basis"] = out["Basis"].astype(object) if "Basis" in out.columns else pd.Series(pd.NA, index=out.index, dtype=object)
    for commodity in ("Soybeans", "Corn"):
        commodity_ref = out[source_mask & out["Name"].astype(str).str.fullmatch(commodity, case=False, na=False)]
        ref_delivery = commodity_ref["Delivery"].astype(str).str.contains(
            rf"(?:{re.escape(nearby_delivery)}|Harvest\s+{current.year})", case=False, na=False
        )
        references = commodity_ref[ref_delivery & commodity_ref["Futures Month"].astype(str).ne("")]
        if references.empty:
            continue
        future_month = str(references.iloc[0]["Futures Month"])
        future_values = references["Futures Price"].map(_futures_number).dropna()
        if future_values.empty:
            continue
        future_price = float(future_values.iloc[0])
        if commodity == "Corn":
            nearby_mask = out["Delivery"].astype(str).str.contains(
                rf"(?:{re.escape(nearby_delivery)}|Harvest\s+{current.year})", case=False, na=False
            )
        else:
            nearby_mask = out["Delivery"].astype(str).eq(nearby_delivery)
        target = wmi_mask & out["Name"].astype(str).str.fullmatch(commodity, case=False, na=False) & nearby_mask
        if not target.any():
            continue
        out.loc[target, "Futures Month"] = future_month
        out.loc[target, "Futures Price"] = f"{future_price:.4f}"
        cash_bu = pd.to_numeric(
            out.loc[target, "Bushel Cash Price"].astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
            errors="coerce",
        )
        out.loc[target, "Basis"] = cash_bu - future_price
    return out


def _month_key(value: object) -> tuple[int, int] | None:
    """Return (year, month) for a normalized futures month label."""
    match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
        str(value),
        re.I,
    )
    if not match:
        return None
    month = datetime.strptime(match.group(1), "%B").month
    return int(match.group(2)), month


def _uses_spot_for_month(value: object, fetch_date: str) -> bool:
    """Spot FX is valid for the current/next calendar month only."""
    key = _month_key(value)
    if key is None:
        # Rows without a futures month retain the existing spot behavior.
        return True
    try:
        current = datetime.strptime(fetch_date, "%Y-%m-%d")
    except ValueError:
        return False
    current_key = (current.year, current.month)
    next_key = (current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1)
    return key in {current_key, next_key}


def add_us_basis_from_spot(df: pd.DataFrame, fetch_date: str, cache_dir: Path) -> pd.DataFrame:
    """Calculate USD/bu basis for Canadian-cash-price sources with futures values."""
    out = df.copy()
    for column in ("FX Rate", "FX Type", "FX Quote Date", "USD Cash Price"):
        if column not in out:
            out[column] = pd.NA
        else:
            # Report inputs may be loaded with dtype=str. Keep these output
            # columns assignable when numeric recalculation is requested.
            out[column] = out[column].astype(object)
    if "US Basis (USD/bu)" not in out:
        out["US Basis (USD/bu)"] = pd.NA
    else:
        out["US Basis (USD/bu)"] = out["US Basis (USD/bu)"].astype(object)
    spot_result = get_usdcad_spot(fetch_date, cache_dir)
    forward_curve = load_forward_curve(cache_dir)
    if spot_result is None and not forward_curve:
        print("[WARN] No CAD/USD spot or forward rate available; USD basis calculations skipped")
        return out
    spot_usdcad, spot_quote_date = spot_result or (None, None)
    # All AgriCharts quotes already have CAD cash and futures values, so they
    # are eligible too. Other sources are opt-in because their quote units
    # and destinations vary.
    source_names = out["Source"].astype(str).str.lower()
    target = source_names.eq("agricharts") | source_names.isin({
        "broadgrain email bids", "andersons email bids", "macewen email bids", "ingredion", "greenfield",
    })
    cash_bu = pd.to_numeric(out.get("Bushel Cash Price", pd.Series(index=out.index)), errors="coerce")
    mt_cash = pd.to_numeric(out.get("MT Cash Price", pd.Series(index=out.index)), errors="coerce")
    names = out.get("Name", pd.Series("", index=out.index)).astype(str).str.lower()
    factor = names.map(lambda value: 39.3683 if "corn" in value else 36.7437 if value else float("nan"))
    cash_bu = cash_bu.fillna(mt_cash / factor)
    futures = out.get("Futures Price", pd.Series(index=out.index)).map(_futures_number)
    months = out.get("Futures Month", pd.Series("", index=out.index)).astype(str).str.lower()
    # Do not silently use spot FX for deferred deliveries.  That would make
    # the displayed USD basis look precise while using the wrong economics.
    def rate_for_month(month: str):
        if month in forward_curve:
            # Forward curve values are USD per CAD already (for example
            # 0.7158), so do not invert them.
            return forward_curve[month]
        # Preserve the established pipeline behavior if CME is temporarily
        # unreachable and no forward curve exists at all.  This is explicitly
        # labeled as spot fallback; it is never presented as a forward quote.
        if not forward_curve and spot_usdcad is not None:
            return (1 / spot_usdcad, spot_quote_date)
        if _uses_spot_for_month(month, fetch_date):
            return ((1 / spot_usdcad) if spot_usdcad else float("nan"), spot_quote_date)
        return (float("nan"), "")

    usdcad_rates = months.map(rate_for_month)
    usd_per_cad = usdcad_rates.map(lambda pair: pair[0] if pair[0] else float("nan"))
    calculated = cash_bu * usd_per_cad - futures
    # CSV/report inputs commonly represent missing numeric values as empty
    # strings. Treat both blanks and NaN as missing so recalculation fills them.
    existing_us_basis = pd.to_numeric(out["US Basis (USD/bu)"], errors="coerce")
    eligible = target & cash_bu.notna() & futures.notna() & existing_us_basis.isna()
    matched_forward = months.isin(forward_curve)
    out.loc[eligible, "FX Rate"] = usd_per_cad[eligible]
    fx_labels = matched_forward[eligible].map({True: "Forward Futures", False: "Spot"})
    if not forward_curve:
        fallback_deferred = (~matched_forward & ~months.map(lambda month: _uses_spot_for_month(month, fetch_date)))[eligible]
        fx_labels = fx_labels.mask(fallback_deferred, "Spot (Forward unavailable)")
    out.loc[eligible, "FX Type"] = fx_labels
    out.loc[eligible, "FX Quote Date"] = usdcad_rates[eligible].map(lambda pair: pair[1])
    out.loc[eligible, "USD Cash Price"] = cash_bu[eligible] * usd_per_cad[eligible]
    out.loc[eligible, "US Basis (USD/bu)"] = calculated[eligible].where(calculated[eligible].abs() <= 2)
    for source, source_rows in out.loc[target].groupby("Source", dropna=False):
        calculated_count = int(source_rows["US Basis (USD/bu)"].notna().sum())
        print(f"[INFO] {source}: {calculated_count} USD-basis rows available")
    deferred_missing = eligible & ~matched_forward & ~months.map(lambda month: _uses_spot_for_month(month, fetch_date))
    if deferred_missing.any():
        count = int(deferred_missing.sum())
        print(f"[WARN] {count} deferred quote(s) lack a matching forward CADUSD rate; USD basis left blank")
    return out
