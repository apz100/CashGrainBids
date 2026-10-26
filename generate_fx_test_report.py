"""Generate a non-destructive report using the current FX calculation code."""

from pathlib import Path

import pandas as pd

from cashgrainbids.config import FX_DIR, OUTPUT_DIR, REPORT_DIR
from cashgrainbids.fixed_report import build_fixed_pdf, build_net_all_commercial_pdf
from cashgrainbids.fx_rates import add_us_basis_from_spot, add_wanna_make_it_nearby_basis


def main() -> int:
    csv_path = sorted(OUTPUT_DIR.glob("EasternOntario_CashBids_*.csv"), reverse=True)[0]
    report_date = csv_path.stem.removeprefix("EasternOntario_CashBids_")
    fetch_date = report_date[:10]
    frame = pd.read_csv(csv_path, dtype=str).fillna("")
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
