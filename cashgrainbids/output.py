"""Stable daily CSV/XLSX output writer."""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from .config import OUTPUT_COLUMNS
from .processing import excel_protect


def format_output(df: pd.DataFrame) -> pd.DataFrame:
    """Return the exact public CSV schema with consistently formatted values."""
    out = df[[column for column in OUTPUT_COLUMNS if column in df.columns]].copy().fillna("")
    for column in ("Basis", "Basis Change", "US Basis (USD/bu)", "US Basis Change", "Bushel Cash Price", "MT Cash Price"):
        if column not in out:
            continue
        numeric = pd.to_numeric(
            out[column].astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce"
        ).round(2)
        out[column] = numeric.map(lambda value: f"{value:.2f}" if pd.notna(value) else "")
    if "Bushel Cash Price" in out:
        out["Bushel Cash Price"] = out["Bushel Cash Price"].map(lambda value: f"${value}" if value else "")
    if "Change" in out:
        out["Change"] = out["Change"].astype(str).map(excel_protect)
    return out


def write_daily_outputs(df: pd.DataFrame, csv_path: Path) -> tuple[Path, Path]:
    """Write the CSV plus formatted Excel workbook and return both paths."""
    out = format_output(df)
    out.to_csv(csv_path, index=False, header=True, quoting=csv.QUOTE_MINIMAL, encoding="utf-8")
    xlsx_path = csv_path.with_suffix(".xlsx")
    excel_out = out.copy()
    for column in ("Basis", "Basis Change", "US Basis (USD/bu)", "US Basis Change", "Bushel Cash Price", "MT Cash Price"):
        if column in excel_out:
            excel_out[column] = pd.to_numeric(
                excel_out[column].astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce"
            )
    sheet_names = {
        "AgriCharts": "AgriCharts", "Greenfield": "Greenfield", "Ingredion": "Ingredion",
        "Great Lakes Grain": "Great Lakes", "Andersons email bids": "Andersons Email",
        "MacEwen email bids": "MacEwen Email", "Bunge email bids": "Bunge Email",
        "Richard email bids": "Richard Email",
        "Ceresco bids": "Ceresco",
    }
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        excel_out.to_excel(writer, index=False, sheet_name="Cash Bids")
        for source, source_df in excel_out.groupby("Source", sort=False):
            # Keep the full public schema on every source sheet, including a
            # blank US-basis column when that source lacks enough inputs.
            source_df.to_excel(
                writer, index=False, sheet_name=sheet_names.get(str(source), str(source)[:31])
            )
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            header_map = {cell.value: cell.column for cell in worksheet[1]}
            for column in ("Basis", "Basis Change", "US Basis (USD/bu)", "US Basis Change", "MT Cash Price"):
                if column in header_map:
                    for cells in worksheet.iter_cols(min_col=header_map[column], max_col=header_map[column], min_row=2):
                        for cell in cells:
                            cell.number_format = "0.00"
            if "Bushel Cash Price" in header_map:
                for cells in worksheet.iter_cols(
                    min_col=header_map["Bushel Cash Price"], max_col=header_map["Bushel Cash Price"], min_row=2
                ):
                    for cell in cells:
                        cell.number_format = "$0.00"
    return csv_path, xlsx_path
