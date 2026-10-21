"""Daily collection orchestration; intentionally small and source-agnostic."""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright

from email_bid_sources import collect_outlook_bid_rows
from ceresco_bids import collect_ceresco_bids

from .config import AGRICHARTS_TARGETS, FX_DIR, INGREDION_STORAGE_STATE, OUTPUT_DIR
from .fx_rates import add_us_basis_from_spot
from .output import write_daily_outputs
from .processing import (
    add_basis_change_column,
    add_mt_cash_price,
    filter_eastern_ontario_locations,
    find_previous_output_file,
    normalize_agricharts_basis,
    sort_output_rows,
)
from .web_collectors import (
    scrape_agricharts,
    scrape_greenfield_johnstown,
    scrape_great_lakes_embrun,
    scrape_ingredion_cardinal_cey_dent,
)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fetch_date = datetime.now().strftime("%Y-%m-%d")
    run_period = "AM" if datetime.now().hour < 12 else "PM"
    run_tag = f"{fetch_date}_{run_period}"
    csv_path = OUTPUT_DIR / f"EasternOntario_CashBids_{run_tag}.csv"
    rows: list[pd.DataFrame] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context_kwargs = {"storage_state": str(INGREDION_STORAGE_STATE)} if INGREDION_STORAGE_STATE.is_file() else {}
        context = browser.new_context(
            **context_kwargs,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari",
        )
        page = context.new_page()
        for target in AGRICHARTS_TARGETS:
            try:
                frame = scrape_agricharts(page, target["url"])
                if frame is None or frame.empty:
                    print(f"[WARN] {target['name']}: no rendered bids table found")
                else:
                    frame.insert(0, "Source", "AgriCharts")
                    frame.insert(1, "Location", target["name"])
                    frame["Quote Date"] = fetch_date
                    rows.append(add_mt_cash_price(frame))
                    print(f"[OK] {target['name']}: {len(frame)} rows")
            except Exception as error:
                print(f"[ERR] {target['name']}: {error}")
            time.sleep(0.5)
        for source_name, collector in (
            ("Greenfield Johnstown Corn", scrape_greenfield_johnstown),
            ("Ingredion Cardinal CEY Dent", scrape_ingredion_cardinal_cey_dent),
            ("Great Lakes Embrun Elevator", scrape_great_lakes_embrun),
        ):
            try:
                frame = collector(page)
                if frame is None or frame.empty:
                    print(f"[WARN] {source_name}: no data collected")
                else:
                    if "Quote Date" not in frame:
                        frame["Quote Date"] = fetch_date
                    rows.append(frame)
                    print(f"[OK] {source_name}: {len(frame)} rows")
            except Exception as error:
                print(f"[ERR] {source_name}: {error}")
            time.sleep(0.5)
        context.close()
        browser.close()

    try:
        email_rows = collect_outlook_bid_rows(OUTPUT_DIR.parent)
        if email_rows is not None and not email_rows.empty:
            rows.append(email_rows)
            print(f"[OK] Outlook email bids: {len(email_rows)} rows")
    except Exception as error:
        print(f"[ERR] Outlook email bids: {error}")

    ceresco_rows = collect_ceresco_bids()
    rows.append(ceresco_rows)
    print(f"[OK] Ceresco manual bids: {len(ceresco_rows)} rows; quote date not supplied")

    if not rows:
        print("No data collected.")
        return 1
    out = normalize_agricharts_basis(pd.concat(rows, ignore_index=True))
    out = filter_eastern_ontario_locations(out)
    out = add_us_basis_from_spot(out, fetch_date, FX_DIR)
    previous = find_previous_output_file(OUTPUT_DIR, fetch_date)
    if previous is not None:
        out = add_basis_change_column(out, previous)
    elif "Basis" in out:
        out.insert(out.columns.get_loc("Basis") + 1, "Basis Change", pd.NA)
    else:
        out["Basis Change"] = pd.NA
    if "US Basis Change" not in out:
        us_insert_at = out.columns.get_loc("US Basis (USD/bu)") + 1 if "US Basis (USD/bu)" in out else len(out.columns)
        out.insert(us_insert_at, "US Basis Change", pd.NA)
    out = sort_output_rows(out).reset_index(drop=True)
    csv_path, xlsx_path = write_daily_outputs(out, csv_path)
    print(f"Wrote {len(out)} rows to {csv_path}")
    print(f"Wrote formatted Excel workbook to {xlsx_path}")
    try:
        print(out.head(12).to_string(index=False))
    except Exception:
        pass
    return 0
