"""Fixed-layout NGG basis report modeled on the supplied market-position PDFs."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re
import pandas as pd
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

PAGE = (1008, 612)
NAVY = (0.09, 0.20, 0.30)
GOLD = (0.79, 0.56, 0.07)
PALE_BLUE = (0.91, 0.93, 0.94)
PALE_YELLOW = (1.0, 0.95, 0.79)
WHITE = (1, 1, 1)
TEXT = NAVY


def _num(value):
    try:
        number = float(str(value).replace("$", "").replace(",", ""))
        return None if pd.isna(number) else number
    except (TypeError, ValueError):
        return None


def _money(value):
    n = _num(value)
    return "" if n is None else f"${n:.2f}"


def _basis(value):
    n = _num(value)
    return "" if n is None else f"{n:+.2f}"


def _futures_symbol(commodity, futures_month):
    """Convert a full futures month to the compact CME symbol used in reports."""
    match = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})", str(futures_month), re.I)
    if not match:
        return str(futures_month)
    month = match.group(1).lower()
    year = match.group(2)[-2:]
    codes = {
        "corn": {"march": "H", "may": "K", "july": "N", "september": "U", "december": "Z"},
        "soybeans": {"january": "F", "march": "H", "may": "K", "july": "N", "august": "Q", "september": "U", "november": "X"},
        "srw": {"march": "H", "may": "K", "july": "N", "september": "U", "december": "Z"},
        "hrw": {"march": "H", "may": "K", "july": "N", "september": "U", "december": "Z"},
        "hrs": {"march": "H", "may": "K", "july": "N", "september": "U", "december": "Z"},
    }
    code = codes.get(str(commodity).lower(), {}).get(month)
    return f"{code}{year}" if code else str(futures_month)


def _delivery_sort_key(value):
    """Sort delivery labels chronologically, including harvest and ranges."""
    text = str(value).strip()
    lower = text.lower()
    year_match = re.search(r"(20\d{2}|\d{2})", text)
    year = int(year_match.group(1)) if year_match else 9999
    if year < 100:
        year += 2000
    month_codes = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    month_match = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
        lower,
    )
    month = month_codes.get(month_match.group(1), 99) if month_match else 99
    harvest = 0 if "harvest" in lower else 1
    return year, harvest, month, lower


def _single_month_delivery_labels(value):
    """Expand multi-month buyer labels into single-month report rows."""
    text = str(value).strip()
    lower = text.lower().replace("–", "-").replace("—", "-")
    year_match = re.search(r"(20\d{2}|\d{2})", text)
    if not year_match:
        return [text]
    year = int(year_match.group(1))
    if year < 100:
        year += 2000
    month_codes = {
        "jan": "Jan", "january": "Jan", "feb": "Feb", "february": "Feb",
        "mar": "Mar", "march": "Mar", "apr": "Apr", "april": "Apr",
        "may": "May", "jun": "Jun", "june": "Jun", "jul": "Jul",
        "july": "Jul", "aug": "Aug", "august": "Aug", "sep": "Sep",
        "sept": "Sep", "september": "Sep", "oct": "Oct", "october": "Oct",
        "nov": "Nov", "november": "Nov", "dec": "Dec", "december": "Dec",
    }
    month_pattern = (
        r"(?<![a-z])(january|jan|february|feb|march|mar|april|apr|may|"
        r"june|jun|july|jul|august|aug|september|sept|sep|october|oct|"
        r"november|nov|december|dec)"
        r"(?=(?:\d{2,4}\b|[\s./-]|$))"
    )
    month_matches = list(re.finditer(month_pattern, lower, re.I))
    month_tokens = [match.group(1) for match in month_matches]
    shorthand = re.search(r"\b([JFMASOND]{2,4})[- ]?\d{2,4}\b", text, re.I)
    shorthand_map = {
        "jfm": ["Jan", "Feb", "Mar"], "am": ["Apr", "May"],
        "mj": ["May", "Jun"], "jas": ["Jul", "Aug", "Sep"],
        "ond": ["Oct", "Nov", "Dec"],
    }
    if shorthand and shorthand.group(1).lower() in shorthand_map:
        return [f"{month} {year}" for month in shorthand_map[shorthand.group(1).lower()]]
    labels = []
    for index, match in enumerate(month_matches):
        segment_end = month_matches[index + 1].start() if index + 1 < len(month_matches) else len(text)
        segment = text[match.end():segment_end]
        segment_year = re.search(r"(20\d{2}|\d{2})", segment)
        label_year = int(segment_year.group(1)) if segment_year else year
        if label_year < 100:
            label_year += 2000
        labels.append(f"{month_codes[match.group(1).lower()]} {label_year}")
    return list(dict.fromkeys(labels)) if len(labels) > 1 else [text]


def _text(c, x, y, text, size=10, bold=False, color=TEXT):
    c.setFillColorRGB(*color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, str(text))


def _center(c, x, y, width, text, size=10, bold=False, color=TEXT):
    font = "Helvetica-Bold" if bold else "Helvetica"
    c.setFont(font, size)
    c.setFillColorRGB(*color)
    c.drawString(x + (width - stringWidth(str(text), font, size)) / 2, y, str(text))


def _panel_header(c, x, y, width, title, subtitle=""):
    c.setFillColorRGB(*NAVY); c.rect(x, y, width, 38, fill=1, stroke=0)
    _text(c, x + 11, y + 21, title, 17, True, WHITE)
    if subtitle:
        _text(c, x + width - stringWidth(subtitle, "Helvetica-Bold", 10) - 10, y + 23, subtitle, 10, True, WHITE)


def _table(c, x, y, width, rows, title, color):
    _panel_header(c, x, y, width, title)
    y -= 31
    headers = ("#", "Location", "Basis", "$/bu", "$/MT")
    widths = (30, 210, 86, 78, 75)
    c.setFillColorRGB(*PALE_BLUE); c.rect(x, y, width, 25, fill=1, stroke=0)
    cursor = x
    for h, w in zip(headers, widths):
        _center(c, cursor, y + 8, w, h, 10, True); cursor += w
    y -= 25
    for idx, row in enumerate(rows[:10], 1):
        c.setFillColorRGB(*(WHITE if idx % 2 else color)); c.rect(x, y, width, 28, fill=1, stroke=0)
        c.setStrokeColorRGB(0.83, 0.87, 0.90); c.setLineWidth(.4); c.line(x, y, x + width, y)
        vals = (idx, row["Location"], _basis(row.get("Basis")), _money(row.get("Bushel Cash Price")), _money(row.get("MT Cash Price")))
        cursor = x
        for val, w in zip(vals, widths):
            _center(c, cursor, y + 8, w, val, 10 if idx > 1 else 10, idx == 1 and False)
            cursor += w
        y -= 28
    return y


def _draw_market_panel(c, x, y, width, commodity, subset, crop_label, crop_color):
    subset = subset.copy()
    subset["_cash"] = subset.get("Bushel Cash Price", pd.Series(index=subset.index)).map(_num)
    farm_reference = subset[subset.get("Bid Type", pd.Series("", index=subset.index)).astype(str).str.lower().eq("fob farm")].copy()
    ranked_subset = subset[~subset.index.isin(farm_reference.index)].copy()
    if commodity in {"Corn", "Soybeans"} and not farm_reference.empty:
        ranked_subset = pd.concat([ranked_subset, farm_reference], ignore_index=True)
        farm_reference = farm_reference.iloc[0:0]
    # Rank and display locations from highest cash price to lowest.
    ranked_subset = ranked_subset.sort_values(["_cash", "Delivery"], ascending=[False, True])
    ng = ranked_subset[ranked_subset["Location"].astype(str).str.contains("North Gower", case=False, na=False)]
    ng_value = ng["_cash"].max() if not ng.empty else None
    rank = int((ranked_subset["_cash"] > ng_value).sum() + 1) if ng_value is not None else "-"
    _panel_header(c, x, y, width, crop_label, f"NGG {_money(ng_value)} | RANK {rank}/{len(ranked_subset)}")
    y -= 31
    c.setFillColorRGB(*crop_color); c.rect(x, y, width, 26, fill=1, stroke=0)
    _text(c, x + 10, y + 8, commodity.upper(), 12, True)
    y -= 26
    headers = ("#", "Location", "Basis", "$/bu", "$/MT")
    widths = (30, 210, 86, 78, 75)
    c.setFillColorRGB(*PALE_BLUE); c.rect(x, y, width, 25, fill=1, stroke=0)
    cursor = x
    for h, w in zip(headers, widths):
        _center(c, cursor, y + 8, w, h, 10, True); cursor += w
    y -= 25
    locations = []
    display_names = {
        "Great Lakes Embrun Elevator": "Embrun Co-op",
        "Vankleek Hill": "Vankleek Hill (Wilsons)",
        "Chesterville": "Chesterville (Vanden Bosch)",
        "Kars": "Kars (Tara Farms)",
        "Brinston": "Brinston (Broadgrain)",
        "Lansdowne": "Lansdowne (Seed Solutions)",
        "Wanna Make It Elevator": "Wanna Make It (Elevator)",
        "Wanna Make It Farm": "Wanna Make It (FOB Farm)",
    }
    for location, group in ranked_subset.groupby("Location", sort=False):
        label = str(location).replace(f" {commodity}", "")
        label = label.replace(" Wheat", "") if commodity in {"SRW", "HRW", "HRS"} else label
        locations.append((display_names.get(label, label), group))
    locations.sort(key=lambda item: item[1]["_cash"].max() if item[1]["_cash"].notna().any() else float("-inf"), reverse=True)
    for location_number, (location, group) in enumerate(locations[:8], 1):
        if y < 40: break
        c.setFillColorRGB(*(1, 1, 1) if len(locations) % 2 else PALE_YELLOW); c.rect(x, y, width, 26, fill=1, stroke=0)
        c.setStrokeColorRGB(0.83, 0.87, 0.90); c.line(x, y, x + width, y)
        row = group.iloc[0]
        vals = (location_number, location, _basis(row.get("Basis")), _money(row.get("Bushel Cash Price")), _money(row.get("MT Cash Price")))
        cursor = x
        for val, w in zip(vals, widths):
            _center(c, cursor, y + 8, w, val, 10, False); cursor += w
        y -= 26
    if not farm_reference.empty and y >= 40:
        row = farm_reference.sort_values("Delivery", key=lambda values: values.map(_delivery_sort_key)).iloc[0]
        c.setFillColorRGB(*(0.91, 0.96, 0.84)); c.rect(x, y, width, 26, fill=1, stroke=0)
        c.setStrokeColorRGB(0.83, 0.87, 0.90); c.line(x, y, x + width, y)
        vals = ("", "Wanna Make It (FOB Farm)", _basis(row.get("Basis")), _money(row.get("Bushel Cash Price")), _money(row.get("MT Cash Price")))
        cursor = x
        for val, w in zip(vals, widths):
            _center(c, cursor, y + 8, w, val, 9, False); cursor += w
        y -= 26
    return y


def build_fixed_pdf(frame: pd.DataFrame, report_date: str, output_path: Path) -> Path:
    frame = frame.copy()
    raw_frame = frame.copy()
    report_date_text = str(report_date)[:10]
    try:
        report_dt = datetime.strptime(report_date_text, "%Y-%m-%d")
    except ValueError:
        report_dt = datetime.now()
    report_year = str(report_dt.year)
    nearby_month = report_dt.strftime("%b")
    frame["Category"] = frame.apply(
        lambda r: (
            "Elevator"
            if (
                (
                    "agricharts" in str(r.get("Source", "")).lower()
                    or "great lakes" in str(r.get("Source", "")).lower()
                    or "wanna make it" in str(r.get("Source", "")).lower()
                )
                and "prescott" not in str(r.get("Location", "")).lower()
                and "fob farm" not in str(r.get("Bid Type", "")).lower()
                and not (
                    "wanna make it" in str(r.get("Source", "")).lower()
                    and str(r.get("Location", "")).strip().lower() != "wanna make it elevator"
                )
            )
            else "Other"
        ),
        axis=1,
    )
    frame = frame[frame["Category"].eq("Elevator")]
    excluded = frame["Location"].astype(str).str.contains("Johnstown|Cardinal", case=False, na=False)
    excluded = excluded | frame["Location"].astype(str).str.contains("Dalkeith", case=False, na=False)
    frame = frame[~excluded]
    frame["_cash"] = frame.get("Bushel Cash Price", pd.Series(index=frame.index)).map(_num)
    frame = frame.sort_values(["Name", "Delivery", "_cash"], ascending=[True, True, False])
    canvas = Canvas(str(output_path), pagesize=PAGE)
    width, height = PAGE
    frame["_type"] = frame["Name"].astype(str).map(lambda value: "SRW" if "SRW" in value.upper() else "HRW" if "HRW" in value.upper() else "HRS" if "HRS" in value.upper() or "SPRING" in value.upper() else "Corn" if "CORN" in value.upper() else "Soybeans" if "SOY" in value.upper() else "Other")
    pages = [("Corn", PALE_YELLOW, [("Corn", PALE_YELLOW), ("Corn", PALE_YELLOW)]), ("Soybeans", (0.86, 0.92, 0.72), [("Soybeans", (0.86, 0.92, 0.72)), ("Soybeans", (0.86, 0.92, 0.72))]), ("Wheat", (0.95, 0.84, 0.84), [("SRW", (0.95, 0.84, 0.84)), ("HRW", (0.95, 0.84, 0.84)), ("HRS", (0.95, 0.84, 0.84))])]
    for page, (commodity, color, panel_types) in enumerate(pages):
        _text(canvas, 16, 581, f"NORTH GOWER GRAINS - {commodity.upper()} BASIS MARKET POSITION", 24, True)
        _text(canvas, 897, 593, report_date, 10, False, (0.35, 0.42, 0.48))
        canvas.setStrokeColorRGB(*GOLD); canvas.setLineWidth(2); canvas.line(16, 555, 992, 555)
        _text(canvas, 16, 565, "Competitor elevator bids ranked separately from potential resale destinations. Basis shown in $/bu.", 10, False, (0.35, 0.42, 0.48))
        if commodity == "Wheat":
            for panel_index, (panel_type, panel_color) in enumerate(panel_types):
                subset = frame[frame["_type"].eq(panel_type)]
                old_mask = subset["Name"].astype(str).str.contains("old crop", case=False, na=False) | subset["Delivery"].astype(str).str.contains("2026", na=False)
                old, new = subset[old_mask], subset[~old_mask]
                row_y = 504 - panel_index * 165
                _draw_market_panel(canvas, 16, row_y, 479, panel_type, old, f"2026 NEW CROP - {panel_type}", panel_color)
                _draw_market_panel(canvas, 513, row_y, 479, panel_type, new, f"2027 NEW CROP - {panel_type}", panel_color)
        else:
          for panel_index, (panel_type, panel_color) in enumerate(panel_types):
            col = panel_index % 2
            x = 16 + col * 497
            if panel_type == "HRW/HRS":
                subset = frame[frame["_type"].isin(["HRW", "HRS"])]
            else:
                subset = frame[frame["_type"].eq(panel_type)]
            old_mask = subset["Name"].astype(str).str.contains("old crop", case=False, na=False) | subset["Delivery"].astype(str).str.contains("2026", na=False)
            old = subset[old_mask]
            new = subset[~old_mask]
            if panel_type in {"Corn", "Soybeans"} and col == 0:
                nearby_labels = [f"{nearby_month} {report_year}"]
                if panel_type == "Corn":
                    nearby_labels.append(f"Harvest {report_year}")
                nearby_pattern = "|".join(re.escape(label) for label in nearby_labels)
                wmi_nearby_elevator = raw_frame[
                    raw_frame["Source"].astype(str).str.contains("wanna make it", case=False, na=False)
                    & raw_frame["Name"].astype(str).str.fullmatch(panel_type, case=False, na=False)
                    & raw_frame["Location"].astype(str).str.lower().eq("wanna make it elevator")
                    & raw_frame["Delivery"].astype(str).str.contains(nearby_pattern, case=False, na=False, regex=True)
                ]
                farm = raw_frame[
                    raw_frame["Source"].astype(str).str.contains("wanna make it", case=False, na=False)
                    & raw_frame["Name"].astype(str).str.contains(panel_type, case=False, na=False)
                    & raw_frame.get("Bid Type", pd.Series("", index=raw_frame.index)).astype(str).str.lower().eq("fob farm")
                    & raw_frame["Delivery"].astype(str).str.contains(report_year, na=False)
                ].copy()
                if not farm.empty and wmi_nearby_elevator.empty:
                    old = pd.concat([old, farm.sort_values("Delivery", key=lambda values: values.map(_delivery_sort_key)).head(1)], ignore_index=True)
            chosen = old if col == 0 else new
            _draw_market_panel(canvas, x, 504, 479, panel_type, chosen, ("2026 NEW CROP - " if col == 0 else "2027 NEW CROP - ") + panel_type.upper(), panel_color)
        canvas.setFillColorRGB(*PALE_BLUE); canvas.rect(16, 11, 976, 27, fill=1, stroke=0)
        _text(canvas, 24, 20, "NGG report | Blank values indicate missing or non-comparable source data.", 8, False, (0.35, 0.42, 0.48))
        canvas.showPage()
    canvas.save()
    return output_path


def build_commercial_pdf(frame: pd.DataFrame, report_date: str, output_path: Path) -> Path:
    """Build delivery-period commercial-buyer tables for resale analysis."""
    frame = frame.copy()
    source = frame["Source"].astype(str).str.lower()
    allowed = source.str.contains("greenfield|ingredion|bunge|richard|p&h|pandh", regex=True, na=False)
    frame = frame[allowed].copy()
    frame["_cash"] = frame.get("Bushel Cash Price", pd.Series(index=frame.index)).map(_num)
    frame["_type"] = frame["Name"].astype(str).map(lambda value: "SRW" if "SRW" in value.upper() else "HRW" if "HRW" in value.upper() else "HRS" if "HRS" in value.upper() or "SPRING" in value.upper() else "Corn" if "CORN" in value.upper() else "Soybeans" if "SOY" in value.upper() else "Other")
    frame["_rank"] = frame.groupby(["_type", "Delivery", "Futures Month"], dropna=False)["_cash"].rank(method="min", ascending=False)

    def commercial_table(subset, title, color):
        if subset.empty:
            return
        _panel_header(canvas, 16, y_pos, 976, title)
        yy = y_pos - 31
        headers = ("Delivery", "Buyer / Destination", "Futures", "CAD Basis", "USD Basis", "CAD/bu", "CAD/MT", "Rank")
        widths = (105, 230, 95, 83, 83, 80, 85, 55)
        canvas.setFillColorRGB(*color); canvas.rect(16, yy, 976, 24, fill=1, stroke=0)
        cursor = 16
        for header, col_width in zip(headers, widths):
            _center(canvas, cursor, yy + 7, col_width, header, 9, True); cursor += col_width
        yy -= 24
        subset = subset.sort_values(["Delivery", "_cash"], ascending=[True, False])
        for i, (_, row) in enumerate(subset.iterrows()):
            if yy < 45: break
            canvas.setFillColorRGB(*(WHITE if i % 2 == 0 else PALE_YELLOW)); canvas.rect(16, yy, 976, 23, fill=1, stroke=0)
            source = str(row.get("Source", "")).replace(" email bids", "").replace(" Email Bids", "")
            buyer = f"{source} / {row.get('Location', '')}"
            vals = (row.get("Delivery", ""), buyer, row.get("Futures Month", ""), _basis(row.get("Basis")), _basis(row.get("US Basis (USD/bu)")), _money(row.get("Bushel Cash Price")), _money(row.get("MT Cash Price")), "" if pd.isna(row.get("_rank")) else int(row.get("_rank")))
            cursor = 16
            for val, col_width in zip(vals, widths):
                _center(canvas, cursor, yy + 7, col_width, val, 8.5, False); cursor += col_width
            yy -= 23
    canvas = Canvas(str(output_path), pagesize=PAGE)
    pages = [("Corn", PALE_YELLOW), ("Soybeans", (0.86, 0.92, 0.72)), ("Wheat", (0.95, 0.84, 0.84))]
    for commodity, color in pages:
        _text(canvas, 16, 581, f"NORTH GOWER GRAINS - {commodity.upper()} COMMERCIAL BUYER POSITION", 23, True)
        _text(canvas, 897, 593, report_date, 10, False, (0.35, 0.42, 0.48))
        canvas.setStrokeColorRGB(*GOLD); canvas.setLineWidth(2); canvas.line(16, 555, 992, 555)
        _text(canvas, 16, 565, "Commercial buyers ranked separately from elevator and direct-ship competitor bids.", 10, False, (0.35, 0.42, 0.48))
        subset = frame[frame["_type"].isin(["SRW", "HRW", "HRS"] if commodity == "Wheat" else [commodity])]
        y_pos = 504
        if commodity == "Wheat":
            for kind in ("SRW", "HRW", "HRS"):
                y_pos = 504 - (0 if kind == "SRW" else 165 if kind == "HRW" else 330)
                commercial_table(subset[subset["_type"].eq(kind)], f"{kind} DELIVERY PERIODS", color)
        else:
            commercial_table(subset, f"{commodity.upper()} DELIVERY PERIODS", color)
        canvas.setFillColorRGB(*PALE_BLUE); canvas.rect(16, 11, 976, 27, fill=1, stroke=0)
        _text(canvas, 24, 20, "Commercial buyer report | Blank values indicate missing or non-comparable source data.", 8, False, (0.35, 0.42, 0.48))
        canvas.showPage()
    canvas.save()
    return output_path


def build_net_all_commercial_pdf(frame: pd.DataFrame, report_date: str, output_path: Path) -> Path:
    """Render a Net_All-style buyer matrix: deliveries as rows, buyers as columns."""
    frame = frame.copy()
    source = frame["Source"].astype(str).str.lower()
    frame = frame[source.str.contains("greenfield|ingredion|bunge|richard|p&h|pandh|anderson|broadgrain|macewen|ceresco", regex=True, na=False)].copy()
    frame["_type"] = frame["Name"].astype(str).map(lambda value: "SRW" if "SRW" in value.upper() else "HRW" if "HRW" in value.upper() else "HRS" if "HRS" in value.upper() or "SPRING" in value.upper() else "Corn" if "CORN" in value.upper() else "Soybeans" if "SOY" in value.upper() else "Other")
    expanded_rows = []
    for _, original in frame.iterrows():
        for label in _single_month_delivery_labels(original.get("Delivery", "")):
            row = original.copy()
            row["_report_delivery"] = label
            expanded_rows.append(row)
    frame = pd.DataFrame(expanded_rows) if expanded_rows else frame.assign(_report_delivery=frame["Delivery"])
    frame["_cash"] = frame.get("Bushel Cash Price", pd.Series(index=frame.index)).map(_num)
    buyers = [
        ("Greenfield", "J-town", "greenfield", "johnstown"),
        ("Richardson", "J-town", "richard", "johnstown"),
        ("P & H", "J-town/Cardinal", r"p\s*&\s*h|pandh|parrish", "johnstown|cardinal|prescott|picton"),
        ("Andersons", "J-town", "anderson", "johnstown"),
        ("BroadGrain", "J-town/Picton", "broadgrain", "johnstown|picton"),
        ("Ingredion", "Cardinal", "ingredion", "cardinal"),
        ("Richardson", "Sorel", "richard", "sorel"),
        # Keep Bunge's Montreal and BCC destinations separate.  BCC rows
        # must not populate the Montreal column when Montreal has no quote.
        ("Bunge", "Montreal", "bunge", r"^Bunge\s+MTL$"),
        ("Bunge", "BCC", "bunge", r"^Bunge\s+BCC$"),
        ("Ceresco", "Best available", "ceresco", "contrecoeur|contrecœur|montreal|montréal|varennes|saint-hyacinthe|johnstown"),
    ]
    c = Canvas(str(output_path), pagesize=(792, 612))

    def matrix(kind, y, color, fallback_date, delivery_subset=None):
        rows = frame[frame["_type"].eq(kind)].copy()
        if rows.empty: return
        # Bunge's BCC destination is a soybean outlet in the current source
        # data. Do not display an empty BCC corn column.
        active_buyers = [
            buyer for buyer in buyers
            if not (kind == "Corn" and buyer[0] == "Bunge" and buyer[1] == "BCC")
        ]
        deliveries = sorted(rows["_report_delivery"].dropna().drop_duplicates(), key=_delivery_sort_key)
        if delivery_subset is not None:
            deliveries = list(delivery_subset)
        x0, total = 16, 760
        delivery_w = 66
        col_w = (total - delivery_w) / len(active_buyers)
        c.setFillColorRGB(*NAVY); c.setStrokeColorRGB(*NAVY); c.rect(x0, y, total, 34, fill=1, stroke=1)
        _text(c, x0 + 8, y + 11, kind.upper(), 14, True, WHITE)
        y -= 25
        c.setFillColorRGB(*NAVY); c.setStrokeColorRGB(*NAVY); c.setLineWidth(.5); c.rect(x0, y, total, 27, fill=1, stroke=1)
        _center(c, x0, y + 9, delivery_w, "Delivery", 7.5, True, WHITE)
        for i, (buyer, dest, _, _) in enumerate(active_buyers):
            c.line(x0 + delivery_w + i * col_w, y, x0 + delivery_w + i * col_w, y + 27)
            source_rx, location_rx = active_buyers[i][2], active_buyers[i][3]
            quote_date = fallback_date
            if "Quote Date" in rows.columns:
                date_mask = rows["Source"].astype(str).str.contains(source_rx, case=False, regex=True, na=False) & rows["Location"].astype(str).str.contains(location_rx, case=False, regex=True, na=False)
                dates = pd.to_datetime(rows.loc[date_mask, "Quote Date"], errors="coerce").dropna()
                if not dates.empty:
                    quote_date = dates.max().strftime("%Y-%m-%d")
            _center(c, x0 + delivery_w + i * col_w, y + 16, col_w, buyer, 6.6, True, WHITE)
            _center(c, x0 + delivery_w + i * col_w, y + 9, col_w, dest, 6.0, True, WHITE)
            _center(c, x0 + delivery_w + i * col_w, y + 2, col_w, f"Bid {quote_date}", 5.2, False, WHITE)
        y -= 27
        for idx, delivery in enumerate(deliveries):
            if y < 42:
                break
            c.setFillColorRGB(*WHITE); c.setStrokeColorRGB(0.55, 0.62, 0.68); c.setLineWidth(.35); c.rect(x0, y, total, 22, fill=1, stroke=1)
            c.line(x0 + delivery_w, y, x0 + delivery_w, y + 22)
            for i in range(1, len(active_buyers)):
                c.line(x0 + delivery_w + i * col_w, y, x0 + delivery_w + i * col_w, y + 22)
            _center(c, x0, y + 7, delivery_w, delivery, 7.2, True)
            matches = []
            for _, _, source_rx, location_rx in active_buyers:
                mask = (
                    rows["_report_delivery"].eq(delivery)
                    & rows["Source"].astype(str).str.contains(source_rx, case=False, regex=True, na=False)
                    & rows["Location"].astype(str).str.contains(location_rx, case=False, regex=True, na=False)
                )
                found = rows[mask].copy()
                # Ceresco has several destinations but only one matrix column;
                # choose the strongest available basis and retain the location
                # in the cell text below.
                if source_rx == "ceresco" and not found.empty:
                    found["_basis_rank"] = pd.to_numeric(found["US Basis (USD/bu)"], errors="coerce")
                    found = found.sort_values("_basis_rank", ascending=False)
                    top_basis = found.iloc[0]["_basis_rank"]
                    same_basis = found[found["_basis_rank"].eq(top_basis)]
                    if len(same_basis) > 1:
                        row = found.iloc[0].copy()
                        short_locations = [
                            str(value).replace(", QC", "").replace(", ON", "")
                            for value in same_basis["Location"]
                        ]
                        row["Location"] = "/".join(dict.fromkeys(short_locations))
                        found = pd.DataFrame([row])
                else:
                    found = found.sort_values("_cash", ascending=False)
                matches.append(found.iloc[0] if not found.empty else None)
            # Rank only against quotes using the same futures reference month.
            # A March delivery priced against CH27 must not compete directly
            # with a March delivery priced against CK27.
            basis_groups = {}
            for i, row in enumerate(matches):
                if row is None:
                    continue
                basis = _num(row.get("Standardized US Basis (USD/bu)"))
                if basis is None:
                    basis = _num(row.get("US Basis (USD/bu)"))
                if basis is None:
                    basis = _num(row.get("Basis"))
                if basis is not None:
                    futures_key = _futures_symbol(kind, row.get("Futures Month", ""))
                    basis_groups.setdefault(futures_key, {})[i] = basis
            for i, row in enumerate(matches):
                if row is None:
                    value = "-"
                else:
                    # This report is the commercial-buyer comparison.  Its
                    # cells are USD-basis economics only; never fall back to
                    # the source's CAD basis when FX is missing.
                    display_basis = row.get("Standardized US Basis (USD/bu)")
                    if _num(display_basis) is None:
                        display_basis = row.get("US Basis (USD/bu)")
                    value = _basis(display_basis)
                    if value and value != "-":
                        display_month = row.get("Standard Futures Month")
                        if not str(display_month).strip() or str(display_month).lower() == "nan":
                            display_month = row.get("Futures Month", "")
                        value = f"{value} {_futures_symbol(kind, display_month)}".strip()
                        if str(row.get("Source", "")).lower() == "ceresco bids":
                            location = str(row.get("Location", "")).replace(", QC", "").replace(", ON", "")
                            location = location.replace("Varennes", "VAR").replace("Saint-Hyacinthe", "St-Hy")
                            location = location.replace("Montréal", "MTL").replace("Montreal", "MTL")
                            location = location.replace("Contrecoeur", "CC").replace("Contrecœur", "CC")
                            location = re.sub(r"\s*/\s*", "/", location)
                            value = f"{value} ({location})"
                    futures_key = _futures_symbol(kind, row.get("Futures Month", ""))
                    ranked = sorted(basis_groups.get(futures_key, {}), key=lambda index: basis_groups[futures_key][index], reverse=True)
                    if ranked and i == ranked[0]:
                        c.setFillColorRGB(0.67, 0.86, 0.38); c.rect(x0 + delivery_w + i * col_w, y, col_w, 22, fill=1, stroke=1)
                    elif len(ranked) > 1 and i == ranked[1]:
                        c.setFillColorRGB(1.0, 0.95, 0.35); c.rect(x0 + delivery_w + i * col_w, y, col_w, 22, fill=1, stroke=1)
                _center(c, x0 + delivery_w + i * col_w, y + 7, col_w, value, 6.8, False)
            y -= 22

    def footer():
        c.setFillColorRGB(*PALE_BLUE); c.rect(16, 12, 760, 22, fill=1, stroke=0)
        _text(c, 22, 19, "Net basis shown where available; blank cells mean no comparable buyer quote.", 7.5, False, (0.35, 0.42, 0.48))

    def render_kind_pages(kind, color, title):
        deliveries = sorted(
            frame.loc[frame["_type"].eq(kind), "_report_delivery"].dropna().drop_duplicates(),
            key=_delivery_sort_key,
        )
        # The matrix has room for 20 rows per landscape page. Split rather
        # than silently dropping later delivery periods.
        chunks = [deliveries[index:index + 20] for index in range(0, len(deliveries), 20)]
        if not chunks:
            chunks = [[]]
        for chunk_number, chunk in enumerate(chunks, 1):
            suffix = f" ({chunk_number}/{len(chunks)})" if len(chunks) > 1 else ""
            _text(c, 16, 581, f"{title}{suffix}", 17.5, True)
            _text(c, 16, 562, f"Commercial resale buyer offers | {report_date}", 8.5, False, (0.33, 0.38, 0.42))
            c.setStrokeColorRGB(*GOLD); c.setLineWidth(1.5); c.line(16, 555, 776, 555)
            if chunk:
                matrix(kind, 520, color, report_date, chunk)
            else:
                c.setFillColorRGB(*NAVY); c.rect(16, 486, 760, 34, fill=1, stroke=1)
                _text(c, 24, 497, kind.upper(), 14, True, WHITE)
                c.setFillColorRGB(*WHITE); c.setStrokeColorRGB(0.55, 0.62, 0.68)
                c.rect(16, 430, 760, 44, fill=1, stroke=1)
                _center(c, 16, 448, 760, "No commercial buyer bids available for this class.", 11, False)
            footer()
            c.showPage()

    render_kind_pages("Corn", PALE_YELLOW, "NGG Corn U.S. Basis Matrix")
    render_kind_pages("Soybeans", (0.86, 0.95, 0.84), "NGG Soybeans U.S. Basis Matrix")
    render_kind_pages("SRW", (0.95, 0.84, 0.84), "NGG SRW Wheat U.S. Basis Matrix")
    if frame["_type"].eq("HRW").any():
        render_kind_pages("HRW", (0.82, 0.88, 0.95), "NGG HRW Wheat U.S. Basis Matrix")
    if frame["_type"].eq("HRS").any():
        render_kind_pages("HRS", (0.87, 0.82, 0.92), "NGG HRS Wheat U.S. Basis Matrix")
    c.save(); return output_path
