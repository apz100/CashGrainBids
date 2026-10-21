"""HTML/PDF reporting and Google Drive Desktop export."""

from __future__ import annotations

import html
import os
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

from .classification import classify_bid
from .config import OUTPUT_DIR, REPORT_DIR
from .fixed_report import build_fixed_pdf, build_net_all_commercial_pdf


def _money(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce"
    )


def _table(frame: pd.DataFrame, columns: list[str], limit: int = 40) -> str:
    if frame.empty:
        return '<p class="muted">No rows available.</p>'
    view = frame.head(limit).copy()
    for column in columns:
        if column not in view:
            view[column] = ""
    return view[columns].to_html(index=False, classes="data", na_rep="", escape=True)


def build_html(frame: pd.DataFrame, report_date: str) -> str:
    """Build a three-page elevator basis market-position report."""
    frame = frame.copy()
    frame["Category"] = frame.apply(classify_bid, axis=1)
    frame["_cash"] = _money(frame.get("Bushel Cash Price", pd.Series("", index=frame.index)))
    frame["_mt"] = _money(frame.get("MT Cash Price", pd.Series("", index=frame.index)))
    frame["_basis"] = _money(frame.get("Basis", pd.Series("", index=frame.index)))
    frame["_change"] = _money(frame.get("Basis Change", pd.Series("", index=frame.index)))
    elevators = frame[frame["Category"].eq("Elevator")].copy()
    elevators["_rank"] = elevators.groupby(["Name", "Delivery"], dropna=False)["_cash"].rank(method="min", ascending=False)

    def fmt(value, prefix=""):
        return "" if pd.isna(value) else f"{prefix}{float(value):.2f}"

    def commodity_table(name, color="#e7f0d2"):
        data = elevators[elevators["Name"].str.contains(name, case=False, na=False)].copy()
        if data.empty:
            return '<div class="empty">No bids reported.</div>'
        data["Location"] = data["Location"].str.replace(f" {name}", "", regex=False)
        data["Bid"] = data["_cash"].map(lambda x: fmt(x, "$"))
        data["CAD/MT"] = data["_mt"].map(lambda x: fmt(x, "$"))
        data["Basis"] = data["_basis"].map(fmt)
        data["Change"] = data["_change"].map(lambda x: fmt(x, "+"))
        data["Rank"] = data["_rank"].map(lambda x: "" if pd.isna(x) else str(int(x)))
        data = data.sort_values(["Delivery", "_rank", "Location"], kind="stable")
        parts = ['<table class="market"><thead><tr><th>Delivery</th><th>Location</th><th>CAD Basis</th><th>Cash/Bu</th><th>CAD/MT</th><th>Change</th><th>Rank</th></tr></thead><tbody>']
        for location, group in data.groupby("Location", sort=False):
            parts.append(f'<tr class="location"><td colspan="7">{html.escape(str(location))}</td></tr>')
            for _, row in group.iterrows():
                rank_class = "best" if row["_rank"] == 1 else ""
                parts.append(
                    f'<tr class="{rank_class}"><td>{html.escape(str(row["Delivery"]))}</td>'
                    f'<td>{html.escape(str(location))}</td><td>{fmt(row["_basis"])}</td>'
                    f'<td>{fmt(row["_cash"], "$")}</td><td>{fmt(row["_mt"], "$")}</td>'
                    f'<td>{fmt(row["_change"], "+")}</td><td>{"" if pd.isna(row["_rank"]) else int(row["_rank"])}</td></tr>'
                )
        parts.append('</tbody></table>')
        table = "".join(parts)
        return f'<div class="commodity" style="--commodity:{color}"><div class="commodity-title">{html.escape(name.upper())}</div>{table}</div>'

    def commodity_section(name, color):
        return commodity_table(name, color)

    changed = elevators[elevators["_change"].notna() & elevators["_change"].ne(0)].copy()
    if not changed.empty:
        changed["Location"] = changed["Location"].str.replace(r"\s+(Corn|Soybeans|Wheat)$", "", regex=True)
        changed["Change"] = changed["_change"].map(lambda x: fmt(x, "+"))
        changes_html = changed[["Name", "Delivery", "Location", "Change"]].sort_values(["Name", "Delivery"]).to_html(index=False, classes="market", na_rep="", escape=True)
    else:
        changes_html = '<div class="empty">No comparable CAD basis changes.</div>'

    missing = elevators[elevators[["_cash", "_basis"]].isna().any(axis=1)]
    warning = f'<div class="warning">Data warning: {len(missing)} elevator rows have missing cash or basis values.</div>' if not missing.empty else ''
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
@page {{ size: Letter landscape; margin: 0.35in; }} body {{ font-family: Arial, sans-serif; color: #152238; font-size: 9px; }}
.header {{ background:#214f82; color:#fff; padding:12px 16px; border-bottom:7px solid #f3d21b; }}
h1 {{ margin:0; font-size:25px; letter-spacing:.3px; }} .subtitle {{ margin-top:4px; font-size:11px; }}
.intro {{ background:#e9f1d4; border:1px solid #9cae72; padding:7px 10px; margin-top:8px; }}
.commodity {{ margin:8px 0 12px; border:1px solid #263b52; }} .commodity-title {{ background:var(--commodity); font-size:15px; font-weight:bold; padding:5px 8px; border-bottom:2px solid #263b52; }}
.market {{ border-collapse:collapse; width:100%; table-layout:fixed; }} .market th {{ background:#214f82; color:#fff; padding:4px; text-align:center; font-size:9px; }}
.market td {{ border:1px solid #9aa6b5; padding:3px 4px; text-align:right; }} .market td:first-child,.market td:nth-child(2) {{ text-align:left; }}
.market tr:nth-child(even) {{ background:#f1f4f7; }} .market tr:first-child td {{ border-top:0; }}
.market .location td {{ background:#d6e5b6; font-weight:bold; text-align:left; color:#1c2c1b; }} .market .best td {{ background:#fff36a; font-weight:bold; }}
.pagebreak {{ break-before:page; }} .warning {{ background:#fff0c2; border:1px solid #bf8b00; padding:6px; margin:8px 0; }}
.empty {{ border:1px solid #aaa; padding:8px; color:#777; }} .footer {{ margin-top:8px; color:#596575; font-size:8px; }}
</style></head><body>
<div class="header"><h1>North Gower Grains</h1><div class="subtitle">Eastern Ontario Elevator Basis Market Position | {html.escape(report_date)} | Generated {datetime.now():%Y-%m-%d %H:%M}</div></div>
<div class="intro"><b>Purpose:</b> comparison of elevator bids available to Eastern Ontario producers. Basis and cash values are shown in CAD; Rank 1 is the strongest available elevator bid for the delivery.</div>
{warning}{commodity_section('Corn', '#f7cfae')}{commodity_section('Soybeans', '#dce9b8')}
<div class="footer">Sources: AgriCharts and configured elevator sources. Commercial buyers and direct-ship competitors are excluded from elevator rankings.</div>
<div class="pagebreak"><div class="header"><h1>North Gower Grains</h1><div class="subtitle">Elevator Basis Market Position - Wheat</div></div>{commodity_section('SRW', '#e8b7b7')}{commodity_section('HRW', '#e8b7b7')}{commodity_section('HRS', '#e8b7b7')}{commodity_section('Wheat', '#e8b7b7')}</div>
<div class="pagebreak"><div class="header"><h1>North Gower Grains</h1><div class="subtitle">Daily Changes and Data Notes | {html.escape(report_date)}</div></div>
<div class="commodity" style="--commodity:#f4df20"><div class="commodity-title">CAD BASIS MOVEMENT</div>{changes_html}</div>
<h2>Report notes</h2><div class="intro">Basis Change is the CAD basis movement versus the most recent prior daily file. USD basis changes are retained in the workbook and will be added to this page once the elevator report layout is finalized.</div>
<div class="footer">This report is generated from the preserved daily CSV. Blank values indicate that the source did not provide a comparable quote.</div></div>
</body></html>"""


def latest_csv() -> Path | None:
    candidates = sorted(OUTPUT_DIR.glob("EasternOntario_CashBids_*.csv"), reverse=True)
    return candidates[0] if candidates else None


def export_to_drive(files: list[Path], report_date: str) -> Path | None:
    """Copy output to an already-synchronized Google Drive Desktop folder."""
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
    stem_parts = csv_path.stem.split("_")
    report_date = "_".join(stem_parts[-2:]) if stem_parts[-1] in {"AM", "PM"} else stem_parts[-1]
    frame = pd.read_csv(csv_path, dtype=str).fillna("")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = REPORT_DIR / f"EasternOntario_CashBids_Report_{report_date}.html"
    pdf_path = REPORT_DIR / f"EasternOntario_CashBids_Report_{report_date}.pdf"
    commercial_pdf_path = REPORT_DIR / f"EasternOntario_Commercial_Buyers_{report_date}.pdf"
    content = build_html(frame, report_date)
    html_path.write_text(content, encoding="utf-8")
    build_fixed_pdf(frame, report_date, pdf_path)
    build_net_all_commercial_pdf(frame, report_date, commercial_pdf_path)
    print(f"[OK] Wrote report: {pdf_path}")
    files = [csv_path, csv_path.with_suffix(".xlsx"), html_path, pdf_path, commercial_pdf_path]
    export_to_drive([path for path in files if path.is_file()], report_date)
    return 0
