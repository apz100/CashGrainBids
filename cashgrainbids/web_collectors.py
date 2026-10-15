"""Website-specific Playwright collectors.

Each collector returns the common bid-data columns. The orchestrator owns the
browser lifecycle, retry policy, output, and reporting.
"""

from __future__ import annotations

import io
import re
import time
from typing import Optional

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .config import GREAT_LAKES_URL, GREENFIELD_URL, INGREDION_URL
from .processing import (
    CORN_BU_PER_MT,
    add_mt_cash_price,
    extract_table_to_df,
    norm_full_month,
    norm_short_month,
    normalize_change_value,
    normalize_ingredion_change,
    normalize_futures_price,
    pick_cash_table_html,
    tidy_df,
)


def scrape_agricharts(page, url: str) -> Optional[pd.DataFrame]:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)

    def extract(page_html: str) -> Optional[pd.DataFrame]:
        table_html = pick_cash_table_html(page_html)
        return extract_table_to_df(table_html) if table_html else None

    try:
        page.wait_for_selector("table", timeout=15000)
        frame = extract(page.content())
        if frame is not None and not frame.empty:
            return frame
    except PlaywrightTimeout:
        pass
    for frame_page in page.frames:
        try:
            frame_page.wait_for_selector("table", timeout=8000)
            frame = extract(frame_page.content())
            if frame is not None and not frame.empty:
                return frame
        except PlaywrightTimeout:
            continue
    return None


def _table_after_heading(page, heading: str, required_text: tuple[str, ...] = (), timeout: int = 15000):
    locator = page.get_by_text(heading, exact=True).first
    locator.wait_for(state="visible", timeout=timeout)
    tables = locator.locator("xpath=following::table")
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for index in range(tables.count()):
            table = tables.nth(index)
            if table.is_visible():
                text = table.inner_text(timeout=1000).lower()
                if all(required.lower() in text for required in required_text):
                    return table
        time.sleep(0.25)
    raise PlaywrightTimeout(f"Could not find table after {heading} with headers {required_text}")


def _parse_delivery_range(value: object) -> tuple[str, str]:
    parts = re.split(r"\s*-\s*", str(value), maxsplit=1)
    parsed: list[str] = []
    for part in parts[:2]:
        try:
            parsed.append(pd.to_datetime(part).strftime("%b %Y"))
        except Exception:
            parsed.append(str(part).strip())
    if len(parsed) == 1:
        parsed.append(parsed[0])
    return parsed[0], parsed[1]


def scrape_greenfield_johnstown(page) -> Optional[pd.DataFrame]:
    page.goto(GREENFIELD_URL, wait_until="domcontentloaded", timeout=45000)
    table = _table_after_heading(page, "JOHNSTOWN")
    dataframe = tidy_df(pd.read_html(io.StringIO(table.evaluate("el => el.outerHTML")))[0])
    rows: list[dict] = []
    for _, row in dataframe.iterrows():
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
    page.goto(INGREDION_URL, wait_until="domcontentloaded", timeout=45000)
    if page.locator("input[type='password']").count() > 0:
        print("[AUTH] Ingredion requires login; skipping Cardinal CEY Dent")
        return None
    section = page.get_by_text("CEY Dent", exact=True).first.locator(
        "xpath=ancestor::div[contains(@class, 'cbCommodity')]"
    )
    section.wait_for(state="visible", timeout=15000)
    row_locator = section.locator("ul[class*='fcControls1'], ul[class*='fcControls2']")
    rows: list[dict] = []
    for index in range(row_locator.count()):
        cells = [value.strip() for value in row_locator.nth(index).locator("li").all_inner_texts()]
        if len(cells) < 7:
            continue
        delivery, bid, basis, futures, change, futures_month, _last_trade = cells[:7]
        mt_price = pd.to_numeric(bid.replace(",", ""), errors="coerce")
        basis_mt = pd.to_numeric(basis.replace(",", ""), errors="coerce")
        rows.append({
            "Source": "Ingredion",
            "Location": "Ingredion Cardinal CEY Dent",
            "Name": "Corn",
            "Delivery": norm_short_month(delivery),
            "Delivery End": norm_short_month(delivery),
            "Futures Month": norm_full_month(futures_month.replace(" Corn", "")),
            "Futures Price": normalize_futures_price(re.sub(r"[sS]$", "", futures.strip())),
            "Change": normalize_ingredion_change(change),
            "Basis": basis_mt / CORN_BU_PER_MT,
            "Bushel Cash Price": mt_price / CORN_BU_PER_MT,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return None
    out["Basis"] = pd.to_numeric(out["Basis"], errors="coerce")
    return add_mt_cash_price(out)


def _futures_month_from_dtn_symbol(symbol: object) -> str:
    raw = re.sub(r"[^A-Za-z0-9]", "", str(symbol)).upper()
    months = {
        "F": "January", "G": "February", "H": "March", "J": "April", "K": "May",
        "M": "June", "N": "July", "Q": "August", "U": "September", "V": "October",
        "X": "November", "Z": "December",
    }
    match = re.search(r"(\d)([FGHJKMNQUVXZ])$", raw)
    if not match:
        return str(symbol).strip()
    year_digit, month_code = match.groups()
    return f"{months[month_code]} {2020 + int(year_digit)}"


def _parse_visible_number(value: object) -> float:
    text = re.sub(r"<!--.*?-->", "", str(value), flags=re.S)
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text.replace(",", ""))
    return float(match.group()) if match else float("nan")


def scrape_great_lakes_embrun(page) -> Optional[pd.DataFrame]:
    frame = None
    last_error = None
    for attempt in range(1, 4):
        try:
            page.goto(GREAT_LAKES_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500 * attempt)
            frame = next((item for item in page.frames if "cashbids.greatlakesgrain.com" in item.url), None)
            if frame is not None:
                break
        except Exception as error:
            last_error = error
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
        f"https://cashbids.greatlakesgrain.com/index.cfm?show=11&mid=25&theLocation={location_id}&cmid=all&layout=19",
        wait_until="networkidle", timeout=60000,
    )
    commodities = ("Corn", "Soybeans", "SRW Wheat", "HR Spring Wheat", "HRW Wheat")
    tables = frame.locator("table[name='cashbids-data-table']")
    if tables.count() == 0:
        raise RuntimeError("Great Lakes Embrun page loaded, but no bid tables were found")
    rows: list[dict] = []
    for index in range(tables.count()):
        dataframe = tidy_df(pd.read_html(io.StringIO(tables.nth(index).evaluate("el => el.outerHTML")))[0])
        commodity = commodities[index] if index < len(commodities) else "Unknown"
        for _, row in dataframe.iterrows():
            delivery = norm_short_month(row.get("Delivery", ""))
            rows.append({
                "Source": "Great Lakes Grain",
                "Location": "Great Lakes Embrun Elevator",
                "Name": commodity,
                "Delivery": delivery,
                "Delivery End": delivery,
                "Futures Month": _futures_month_from_dtn_symbol(row.get("Futures Mon.", "")),
                "Futures Price": normalize_futures_price(str(row.get("Futures", "")).replace("'", "-")),
                "Change": normalize_change_value(str(row.get("Chg", "")).replace("'", "-")),
                "Basis": _parse_visible_number(row.get("Basis", "")),
                "Bushel Cash Price": _parse_visible_number(row.get("Cash Price", "")),
            })
    out = pd.DataFrame(rows)
    return add_mt_cash_price(out) if not out.empty else None
