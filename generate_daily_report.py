"""Create a daily HTML/PDF cash-bid report and optionally copy it to Drive.

The report is intentionally generated from the already-written CSV so a
reporting problem cannot alter or re-scrape prices.  Google Drive export uses
the local Google Drive Desktop sync folder; no Google credentials are stored
in this project.
"""

from __future__ import annotations

import html
import os
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "EasternOntarioBids"
REPORT_DIR = OUTPUT_DIR / "Reports"


def classify_row(row: pd.Series) -> str:
    source = str(row.get("Source", "")).lower()
    location = f"{row.get('Location', '')} {row.get('Name', '')}".lower()
    if "agricharts" in source:
        return "Direct Ship Competitor" if "prescott" in location else "Elevator"
    if "greenfield" in source or "ingredion" in source:
        return "Processor"
    if any(value in source for value in ("richard", "bunge")):
        return "Exporter"
    if "anderson" in source or "macewen" in source:
        return "Direct Ship Competitor"
    if "great lakes" in source:
        return "Direct Ship Competitor" if any(
            value in location for value in ("port", "sorel", "direct")
        ) else "Elevator"
    if "broadgrain" in source:
        return "Direct Ship Competitor" if any(
            value in location for value in ("port", "sorel", "terminal")
        ) else "Elevator"
    return "Unclassified"


def _money(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
        errors="coerce",
    )


def _table(frame: pd.DataFrame, columns: list[str], limit: int = 40) -> str:
    if frame.empty:
        return '<p class="muted">No rows available.</p>'
    view = frame.head(limit).copy()
    for col in columns:
        if col not in view:
            view[col] = ""
    view = view[columns]
    return view.to_html(index=False, classes="data", na_rep="", escape=True)


def build_html(frame: pd.DataFrame, report_date: str) -> str:
    frame = frame.copy()
    frame["Category"] = frame.apply(classify_row, axis=1)
    frame["_cash"] = _money(frame.get("Bushel Cash Price", pd.Series("", index=frame.index)))
    frame["_basis_change"] = _money(frame.get("Basis Change", pd.Series("", index=frame.index)))
    frame["Commodity"] = frame.get("Name", "").astype(str)
    frame["Delivery"] = frame.get("Delivery", "").astype(str)

    source_counts = frame.groupby(["Category", "Source"], dropna=False).size().reset_index(name="Rows")
    category_counts = frame["Category"].value_counts().rename_axis("Category").reset_index(name="Rows")
    changed = frame[frame["_basis_change"].notna() & frame["_basis_change"].ne(0)].copy()
    changed["Basis Change"] = changed["_basis_change"].map(lambda x: f"{x:.2f}")
    best = frame[frame["_cash"].notna()].sort_values("_cash", ascending=False)
    best = best.drop_duplicates(["Commodity", "Delivery"], keep="first")
    best["Cash Price"] = best["_cash"].map(lambda x: f"${x:.2f}")

    summary = pd.DataFrame([
        {"Metric": "Rows collected", "Value": len(frame)},
        {"Metric": "Sources", "Value": frame["Source"].nunique()},
        {"Metric": "Categories", "Value": frame["Category"].nunique()},
        {"Metric": "Rows with basis change", "Value": len(changed)},
    ])

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
@page {{ size: Letter landscape; margin: 0.45in; }}
body {{ font-family: Arial, sans-serif; color: #172033; font-size: 10px; }}
h1 {{ color: #174a7e; margin: 0 0 3px; font-size: 23px; }}
h2 {{ color: #174a7e; border-bottom: 2px solid #8eb7d9; padding-bottom: 3px; margin: 16px 0 5px; }}
.subtitle {{ color: #566273; margin-bottom: 12px; }}
.grid {{ display: flex; gap: 10px; }}
.card {{ flex: 1; border: 1px solid #cbd5e1; padding: 7px; }}
.data {{ border-collapse: collapse; width: 100%; margin-top: 4px; }}
.data th {{ background: #174a7e; color: white; padding: 4px; text-align: left; }}
.data td {{ border-bottom: 1px solid #dbe2ea; padding: 3px 4px; }}
.data tr:nth-child(even) {{ background: #f3f7fb; }}
.muted {{ color: #687386; }}
.pagebreak {{ break-before: page; }}
</style></head><body>
<h1>Eastern Ontario Cash Bids</h1>
<div class="subtitle">Daily report for {html.escape(report_date)} &nbsp; | &nbsp; Generated {datetime.now():%Y-%m-%d %H:%M}</div>
<div class="grid"><div class="card"><h2>Summary</h2>{_table(summary, ['Metric', 'Value'])}</div>
<div class="card"><h2>Rows by category</h2>{_table(category_counts, ['Category', 'Rows'])}</div></div>
<h2>Sources collected</h2>{_table(source_counts, ['Category', 'Source', 'Rows'])}
<h2>Highest available cash bids by commodity and delivery</h2>{_table(best, ['Category', 'Source', 'Location', 'Commodity', 'Delivery', 'Cash Price'])}
<h2 class="pagebreak">Basis changes</h2>{_table(changed, ['Category', 'Source', 'Location', 'Commodity', 'Delivery', 'Basis', 'Basis Change'])}
</body></html>"""


def latest_csv() -> Path | None:
    candidates = sorted(OUTPUT_DIR.glob("EasternOntario_CashBids_*.csv"), reverse=True)
    return candidates[0] if candidates else None


def export_to_drive(files: list[Path], report_date: str) -> Path | None:
    drive_root = os.environ.get("CASH_BIDS_GOOGLE_DRIVE_DIR", "").strip()
    if not drive_root:
        print("[INFO] Google Drive export skipped: CASH_BIDS_GOOGLE_DRIVE_DIR is not set")
        return None
    target = Path(drive_root) / "CashGrainBids" / report_date
    target.mkdir(parents=True, exist_ok=True)
    for source in files:
        shutil.copy2(source, target / source.name)
    print(f"[OK] Copied {len(files)} report files to {target}")
    return target


def main() -> int:
    csv_path = latest_csv()
    if csv_path is None:
        print(f"[ERR] No daily CSV found in {OUTPUT_DIR}")
        return 1
    report_date = csv_path.stem.rsplit("_", 1)[-1]
    frame = pd.read_csv(csv_path, dtype=str).fillna("")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = REPORT_DIR / f"EasternOntario_CashBids_Report_{report_date}.html"
    pdf_path = REPORT_DIR / f"EasternOntario_CashBids_Report_{report_date}.pdf"
    content = build_html(frame, report_date)
    html_path.write_text(content, encoding="utf-8")
    browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(content, wait_until="load")
        page.pdf(path=str(pdf_path), format="Letter", landscape=True, print_background=True)
        browser.close()
    print(f"[OK] Wrote report: {pdf_path}")
    files = [csv_path, csv_path.with_suffix(".xlsx"), html_path, pdf_path]
    export_to_drive([path for path in files if path.is_file()], report_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
