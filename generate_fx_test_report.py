"""Generate a non-destructive report using the current FX calculation code."""

from pathlib import Path

import pandas as pd

from cashgrainbids.config import FX_DIR, OUTPUT_DIR, REPORT_DIR
from cashgrainbids.fixed_report import build_fixed_pdf, build_net_all_commercial_pdf
from cashgrainbids.fx_rates import add_us_basis_from_spot, add_wanna_make_it_nearby_basis
from email_bid_sources import parse_broadgrain_ocr, parse_wanna_make_it_nearby_futures


def main() -> int:
    csv_path = sorted(OUTPUT_DIR.glob("EasternOntario_CashBids_*.csv"), reverse=True)[0]
    report_date = csv_path.stem.removeprefix("EasternOntario_CashBids_")
    fetch_date = report_date[:10]
    frame = pd.read_csv(csv_path, dtype=str).fillna("")
    # Test the email-stated futures path using the latest saved WMI email.
    # The normal collector will populate this metadata on the next full run.
    email_path = Path("logs") / "wanna_make_it_latest_email.html"
    if email_path.exists():
        email_futures = parse_wanna_make_it_nearby_futures(email_path.read_text(encoding="utf-8", errors="ignore"))
        wmi = frame["Source"].astype(str).str.contains("wanna make it", case=False, na=False)
        for commodity, value in email_futures.items():
            mask = wmi & frame["Name"].astype(str).str.fullmatch(commodity, case=False, na=False)
            frame.loc[mask, "Email Futures Price"] = value
    # Include the latest saved BroadGrain OCR text in this non-destructive
    # report test so newly fixed SRW parsing can be reviewed immediately.
    broadgrain_texts = sorted(Path("logs").glob("broadgrain_*_image*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)
    if broadgrain_texts:
        wheat_rows = parse_broadgrain_ocr(broadgrain_texts[0].read_text(encoding="utf-8", errors="ignore"))
        wheat_rows = wheat_rows[wheat_rows["Name"].astype(str).str.contains("Wheat", case=False, na=False)]
        if not wheat_rows.empty:
            wheat_rows["Quote Date"] = fetch_date
            frame = pd.concat([frame, wheat_rows], ignore_index=True)
    frame = add_wanna_make_it_nearby_basis(frame, fetch_date)
    frame = add_us_basis_from_spot(frame, fetch_date, FX_DIR)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    elevator_pdf = REPORT_DIR / f"EasternOntario_CashBids_Report_{report_date}_FX_TEST.pdf"
    commercial_pdf = REPORT_DIR / f"EasternOntario_Commercial_Buyers_{report_date}_FX_TEST.pdf"
    suffix = 2
    while elevator_pdf.exists() or commercial_pdf.exists():
        elevator_pdf = REPORT_DIR / f"EasternOntario_CashBids_Report_{report_date}_FX_TEST_{suffix}.pdf"
        commercial_pdf = REPORT_DIR / f"EasternOntario_Commercial_Buyers_{report_date}_AM_FX_TEST_{suffix}.pdf"
        suffix += 1
    build_fixed_pdf(frame, report_date, elevator_pdf)
    build_net_all_commercial_pdf(frame, report_date, commercial_pdf)
    print(f"US-basis rows after recalculation: {frame['US Basis (USD/bu)'].notna().sum()}")
    print(f"Wrote: {elevator_pdf}")
    print(f"Wrote: {commercial_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
