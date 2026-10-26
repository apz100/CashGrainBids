"""Quickly refresh the CAD/USD futures curve without running all scrapers."""

from playwright.sync_api import sync_playwright
import shutil

from cashgrainbids.config import FX_DIR
from cashgrainbids.fx_rates import (
    collect_farmbucks_cadusd_forward_curve,
    collect_tradingview_cadusd_forward_curve,
    crosscheck_forward_curves,
)


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        tv_path = collect_tradingview_cadusd_forward_curve(page, FX_DIR)
        farm_path = collect_farmbucks_cadusd_forward_curve(
            page, FX_DIR, output_name="FX_Forward_Rates_Farmbucks.csv"
        )
        path = tv_path or farm_path
        if tv_path is not None:
            shutil.copyfile(tv_path, FX_DIR / "FX_Forward_Rates.csv")
            if farm_path is not None:
                crosscheck_forward_curves(
                    FX_DIR / "FX_Forward_Rates.csv", farm_path,
                    FX_DIR / "FX_Crosscheck_manual.csv",
                )
        elif farm_path is not None:
            shutil.copyfile(farm_path, FX_DIR / "FX_Forward_Rates.csv")
        browser.close()
    return 0 if path is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
