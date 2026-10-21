"""Add recoverable quote dates to historical daily CSV snapshots.

Original CSV files are never overwritten. Dates for email sources come from
the saved Outlook pull logs; website rows use the daily snapshot date.
"""
from __future__ import annotations

import re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "EasternOntarioBids"
OUTPUT_DIR = INPUT_DIR / "BackfilledDates"
LOG_DIR = ROOT / "logs"

SOURCE_KEYS = {
    "andersons email bids": "Andersons",
    "broadgrain email bids": "Broadgrain",
    "macewen email bids": "Macewen",
    "richard email bids": "Richard",
    "richardson email bids": "Richardson",
    "p&h email bids": "Pandh",
    "bunge email bids": "Bunge",
}


def load_log_dates() -> dict[tuple[str, str], str]:
    dates: dict[tuple[str, str], str] = {}
    for path in LOG_DIR.glob("email_pull_*.txt"):
        run_date = path.stem.removeprefix("email_pull_")
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = re.match(r"([^ ]+) selected:.*?Received:\s*(\d{4}-\d{2}-\d{2})", line)
            if match:
                dates[(run_date, match.group(1).lower())] = match.group(2)
    return dates


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_dates = load_log_dates()
    count = 0
    for path in sorted(INPUT_DIR.glob("EasternOntario_CashBids_*.csv")):
        if " - Copy" in path.stem:
            continue
        report_date = path.stem.rsplit("_", 1)[-1]
        frame = pd.read_csv(path)
        if "Source" not in frame.columns:
            print(f"Skipped {path.name}: no Source column")
            continue
        dates = []
        for source in frame["Source"].astype(str):
            key = SOURCE_KEYS.get(source.lower())
            dates.append(log_dates.get((report_date, key.lower()), report_date) if key else report_date)
        frame["Quote Date"] = dates
        out = OUTPUT_DIR / path.name
        frame.to_csv(out, index=False)
        count += 1
    print(f"Backfilled {count} CSV snapshots to {OUTPUT_DIR}")
    print("Rows without a saved email-log match use the snapshot date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
