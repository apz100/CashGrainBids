"""Daily CAD/USD spot rate collection and cached historical FX values."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd


BOC_USDCAD_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json"
FRANKFURTER_USDCAD_URL = "https://api.frankfurter.app"


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


def add_us_basis_from_spot(df: pd.DataFrame, fetch_date: str, cache_dir: Path) -> pd.DataFrame:
    """Calculate USD/bu basis for Canadian-cash-price sources with futures values."""
    out = df.copy()
    for column in ("FX Rate", "FX Type", "FX Quote Date", "USD Cash Price"):
        if column not in out:
            out[column] = pd.NA
    if "US Basis (USD/bu)" not in out:
        out["US Basis (USD/bu)"] = pd.NA
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
    usdcad_rates = months.map(lambda month: forward_curve.get(month, (spot_usdcad, spot_quote_date)))
    cadusd = usdcad_rates.map(lambda pair: 1 / pair[0] if pair[0] else float("nan"))
    calculated = cash_bu * cadusd - futures
    eligible = target & cash_bu.notna() & futures.notna() & out["US Basis (USD/bu)"].isna()
    matched_forward = months.isin(forward_curve)
    out.loc[eligible, "FX Rate"] = cadusd[eligible]
    out.loc[eligible, "FX Type"] = matched_forward[eligible].map({True: "Forward Futures", False: "Spot"})
    out.loc[eligible, "FX Quote Date"] = usdcad_rates[eligible].map(lambda pair: pair[1])
    out.loc[eligible, "USD Cash Price"] = cash_bu[eligible] * cadusd
    out.loc[eligible, "US Basis (USD/bu)"] = calculated[eligible].where(calculated[eligible].abs() <= 2)
    for source, source_rows in out.loc[target].groupby("Source", dropna=False):
        calculated_count = int(source_rows["US Basis (USD/bu)"].notna().sum())
        print(f"[INFO] {source}: {calculated_count} USD-basis rows available")
    return out
