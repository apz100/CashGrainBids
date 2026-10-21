"""Readers for recurring cash-bid emails in classic Outlook.

The email formats are intentionally handled separately from the web scrapers:
they are publisher-specific and may change independently.
"""

from __future__ import annotations

import io
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


MONTHS = {
    "F": "January", "G": "February", "H": "March", "J": "April",
    "K": "May", "M": "June", "N": "July", "Q": "August",
    "U": "September", "V": "October", "X": "November", "Z": "December",
}
MONTH_RE = re.compile(r"^(?:[A-Za-z]{3,9}[- ]\d{2,4}|HARVEST(?:[- ]\d{2,4})?|NOV[- ]DEC[- ]\d{4})$", re.I)
NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")
TARGET_OUTLOOK_ADDRESS = "adam@northgowergrains.com"


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def _email_quote_date(item: Any) -> str:
    """Return the date the bid entered Outlook for display and stale checks."""
    value = getattr(item, "ReceivedTime", None) or getattr(item, "SentOn", None)
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return _text(value)[:10]


def _number(value: Any) -> float:
    match = NUMBER_RE.search(_text(value).replace(",", ""))
    return float(match.group()) if match else float("nan")


def _us_basis_per_bushel(value: Any) -> float:
    """Parse verified USD/bu basis, rejecting values outside its valid range."""
    number = _number(value)
    return number if pd.notna(number) and abs(number) <= 2 else float("nan")


def _month(value: Any) -> str:
    raw = _text(value)
    harvest = re.match(r"^(?:r[ée]coltes/)?harvest[- ]?(\d{2,4})$", raw, re.I)
    if harvest:
        year = int(harvest.group(1))
        return f"Harvest {2000 + year if year < 100 else year}"
    delivery_range = re.match(r"^([A-Za-z]{3,9})-([A-Za-z]{3,9})\s*-?(\d{2,4})$", raw)
    if delivery_range:
        start, end, year = delivery_range.groups()
        year_int = int(year)
        return f"{start[:3].title()}-{end[:3].title()} {2000 + year_int if year_int < 100 else year_int}"
    match = re.match(r"^([A-Za-z]{3,9})[- ](\d{2,4})$", raw)
    if not match:
        return raw
    year = int(match.group(2))
    if year < 100:
        year += 2000
    return f"{match.group(1)[:3].title()} {year}"


def _future_month(code: Any) -> str:
    raw = _text(code).upper()
    match = re.search(r"([FGHJKMNQUVXZ])(\d{1,2})$", raw)
    if not match:
        return raw
    year_text = match.group(2)
    year = 2020 + int(year_text) if len(year_text) == 1 else 2000 + int(year_text)
    return f"{MONTHS[match.group(1)]} {year}"


def _reverse_month(value: Any) -> str:
    raw = _text(value)
    match = re.match(r"^(\d{2})-([A-Za-z]{3,9})$", raw)
    if not match:
        return _month(raw)
    return _month(f"{match.group(2)}-{match.group(1)}")


def _row(source: str, location: str, name: str, delivery: Any, future: Any,
         futures_price: Any, basis: Any, bushel_price: Any, mt_price: Any = None,
         us_basis: Any = None) -> dict:
    if source == "Andersons email bids":
        location = _text(location).title()
    elif source == "MacEwen email bids":
        location_map = {
            "cobden": "MacEwen Cobden",
            "maxville": "MacEwen Maxville",
            "port prescott": "Port Prescott",
        }
        location = location_map.get(_text(location).lower(), _text(location))
    return {
        "Source": source,
        "Location": location,
        "Name": name,
        "Delivery": _month(delivery),
        "Delivery End": _month(delivery),
        "Futures Month": _future_month(future),
        "Futures Price": _text(futures_price),
        "Change": "",
        "Basis": _number(basis),
        "US Basis (USD/bu)": _us_basis_per_bushel(us_basis),
        "Bushel Cash Price": _number(bushel_price),
        "MT Cash Price": _number(mt_price),
    }


def parse_andersons(html: str) -> pd.DataFrame:
    """Parse Andersons' six-column commodity bid sheet."""
    rows: list[dict] = []
    for table in pd.read_html(io.StringIO(html)):
        if table.shape[1] < 6:
            continue
        commodity = ""
        location = ""
        for values in table.fillna("").astype(str).values.tolist():
            cells = [_text(v) for v in values]
            first = cells[0]
            lower = first.lower()
            if lower in {"corn", "soybeans", "soybeans / soya", "wheat"}:
                commodity = "Soybeans" if "soy" in lower else first.title()
                location = ""
                continue
            if lower in {"ship mo", "ship month"}:
                continue
            if first and all(cell == first for cell in cells) and not MONTH_RE.match(first):
                location = first
                continue
            if not commodity or not location or not re.match(r"^[A-Za-z]{3,9}[- ]\d{2,4}$", first):
                continue
            rows.append(_row(
                "Andersons email bids", location, commodity, first, cells[1],
                cells[2], cells[3], cells[4], cells[5],
            ))
    return pd.DataFrame(rows)


def parse_macewen(html: str) -> pd.DataFrame:
    """Parse MacEwen's Ontario/Quebec bid tables, including MT-only prices."""
    rows: list[dict] = []
    for table in pd.read_html(io.StringIO(html)):
        if table.shape[1] < 3:
            continue
        commodity = ""
        locations: dict[int, str] = {}
        for values in table.fillna("").astype(str).values.tolist():
            cells = [_text(v) for v in values]
            first = cells[0]
            lower = first.lower()
            if "corn" in lower:
                commodity = "Corn"
                locations = {}
                continue
            if "soybean" in lower:
                commodity = "Soybeans"
                locations = {}
                continue
            if "wheat" in lower:
                commodity = "Wheat"
                locations = {}
                continue
            if not commodity:
                continue
            if re.match(r"^(?:[A-Za-z]{3,9}[- ]\d{2,4}|HARVEST(?:[- ]\d{2,4})?|NOV[- ]DEC[- ]\d{4})$", first, re.I):
                for col in range(1, len(cells)):
                    value = _number(cells[col])
                    if pd.isna(value):
                        continue
                    location = locations.get(col, f"Column {col}")
                    factor = 39.3683 if commodity == "Corn" else 36.7437
                    rows.append(_row(
                        "MacEwen email bids", location, commodity, first, "", "", "", value / factor, value
                    ))
                continue
            # Header rows contain location names. Keep only useful, non-price labels.
            row_text = " ".join(cells).lower()
            if any(token in row_text for token in ("maxville", "prescott", "cardinal", "johnstown", "cobden", "montreal")):
                for col in range(1, len(cells)):
                    if cells[col] and not cells[col].startswith("$"):
                        locations[col] = cells[col]
    return pd.DataFrame(rows)


def parse_richard(html: str) -> pd.DataFrame:
    """Parse Richard Kricsfalusy's HTML bid tables (no OCR required)."""
    rows: list[dict] = []
    for table in pd.read_html(io.StringIO(html)):
        if table.empty:
            continue
        table = table.fillna("").astype(str)
        location = ""
        commodity = ""
        for values in table.values.tolist():
            cells = [_text(value) for value in values]
            row_text = " ".join(cells).lower()
            if "bean" in row_text:
                commodity = "Soybeans"
            elif "corn" in row_text:
                commodity = "Corn"
            for candidate in ("Prescott", "Picton", "DLVD Johnstown/Cardinal"):
                if candidate.lower() in row_text:
                    location = candidate
            if not commodity or not location or len(cells) < 9:
                continue
            if not re.match(r"^\d{2}-[A-Za-z]{3,9}$", cells[0]):
                continue
            # Month, CME Price, Fut.Month, US Basis, FX, FX.Month,
            # CAD Basis, CAD/BU, CAD/MT, USD Basis (BU).
            if len(cells) < 10:
                continue
            rows.append(_row(
                "Richard email bids", location, commodity, _reverse_month(cells[0]),
                cells[5], cells[1], cells[6], cells[7], cells[8],
            ))
    return pd.DataFrame(rows)


def parse_bunge(text: str) -> pd.DataFrame:
    """Parse Bunge's plain-text basis email.

    Bunge emails may have arbitrary subjects, but the body consistently uses
    sections such as ``Soybeans BCC``, ``Soybeans MTL`` and ``Corn MTL``.
    These messages provide a basis and futures contract, rather than a cash
    price, so the cash-price fields intentionally remain blank.
    """
    rows: list[dict] = []
    commodity = ""
    location = ""
    section_re = re.compile(r"\b(soybeans?|corn)\s+(bcc|mtl)\b", re.I)
    bid_re = re.compile(
        r"^\s*([A-Za-z]{3,9}-\d{2})(?:\s+\d{1,2}-\d{1,2}(?:st|nd|rd|th)?\.?)?\s*:?\s*"
        r"([+-]?\d+(?:\.\d+)?)\s*([A-Z]{1,3}\d{2})\b",
        re.I,
    )
    for raw_line in re.sub(r"<[^>]+>", "\n", str(text)).splitlines():
        line = _text(raw_line).replace("•", "")
        if not line:
            continue
        section = section_re.search(line)
        if section:
            commodity = "Soybeans" if section.group(1).lower().startswith("soy") else "Corn"
            location = section.group(2).upper()
            continue
        match = bid_re.match(line)
        if not match or not commodity or not location:
            continue
        delivery, basis, futures_code = match.groups()
        # Bunge quotes its cash basis against CME in USD/bushel, not a CAD
        # basis. Keep the general CAD Basis column blank so it is never
        # compared directly with Canadian-dollar basis values.
        rows.append(_row(
            "Bunge email bids", f"Bunge {location}", commodity, delivery,
            futures_code, "", "", "", "", us_basis=basis,
        ))
    return pd.DataFrame(rows)


def _configure_tesseract() -> None:
    """Point pytesseract at a known Windows installation when PATH is stale."""
    import pytesseract

    candidates = [
        os.environ.get("TESSERACT_CMD", ""),
        shutil.which("tesseract.exe") or "",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    executable = next((value for value in candidates if value and Path(value).is_file()), None)
    if executable is None:
        raise FileNotFoundError("Tesseract OCR is not installed")
    pytesseract.pytesseract.tesseract_cmd = str(executable)


def _ocr_image(image_path: Path, *, psm: int = 6, crop: tuple[float, float, float, float] | None = None,
               enhance: bool = True) -> str:
    """OCR one image, with upscaling and contrast for small email tables."""
    from PIL import Image, ImageEnhance, ImageOps
    import pytesseract

    _configure_tesseract()
    image = Image.open(image_path)
    if crop is not None:
        left, top, right, bottom = crop
        image = image.crop((
            int(left * image.width), int(top * image.height),
            int(right * image.width), int(bottom * image.height),
        ))
    if enhance:
        image = ImageOps.grayscale(image)
        image = image.resize((image.width * 2, image.height * 2))
        image = ImageEnhance.Contrast(image).enhance(2)
    return pytesseract.image_to_string(image, config=f"--psm {psm}")


def _save_ocr_text(text: str, image_path: Path, output_dir: Path, suffix: str = "") -> None:
    label = f"_{suffix}" if suffix else ""
    (output_dir / f"{image_path.stem}{label}.txt").write_text(text, encoding="utf-8")


def _row_from_mt(source: str, location: str, commodity: str, delivery: str,
                 futures_code: str, futures_price: str, basis: str, mt_price: str) -> dict | None:
    mt_value = _number(mt_price)
    basis_value = _number(basis)
    if pd.isna(mt_value) or pd.isna(basis_value):
        return None
    factor = 39.3683 if commodity == "Corn" else 36.7437
    return _row(
        source, location, commodity, delivery, futures_code, futures_price,
        basis_value, mt_value / factor, mt_value,
    )


_RICHARDSON_ROW_RE = re.compile(
    r"(?P<delivery>(?:r[ée]coltes/)?harvest[- ]?\d{2,4}|[a-z]{3,9}(?:-[a-z]{3,9})?[- ]?-?\d{2,4})\s+"
    r"(?P<usd>[+-]?\d+(?:\.\d+)?)\s+(?P<basis>\d+(?:\.\d+)?)\s+"
    r"(?P<contract>[a-z]{1,3}\d{1,2})\s+(?P<futures>\d+(?:\.\d+)?)\s+\$?\s*"
    r"(?P<mt>\d+(?:\.\d+)?)",
    re.I,
)


def _richardson_us_basis_by_delivery(text: str) -> dict[str, float]:
    """Read the USD/bu column from a sparse OCR pass without losing minus signs."""
    values: dict[str, float] = {}
    lines = [_text(line) for line in text.splitlines() if _text(line)]
    for index, line in enumerate(lines):
        if not MONTH_RE.match(line):
            continue
        for candidate in lines[index + 1:index + 4]:
            if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", candidate):
                us_basis = _us_basis_per_bushel(candidate)
                if pd.notna(us_basis):
                    values[_month(line)] = us_basis
                break
    return values


def _richardson_us_basis_sequence(text: str) -> list[float]:
    """Read sequential USD/bu values from a narrowly cropped table column."""
    values: list[float] = []
    for line in text.splitlines():
        match = NUMBER_RE.search(_text(line))
        if match:
            value = _us_basis_per_bushel(match.group())
            if pd.notna(value):
                values.append(value)
    return values


def _parse_richardson_ocr_region(
    text: str, commodity: str, location: str, us_basis_by_delivery: dict[str, float] | None = None,
    us_basis_sequence: list[float] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    sequence_index = 0
    for raw_line in text.splitlines():
        line = _text(raw_line).replace("$", " ").replace('"', " ").replace(" id ", " ")
        match = _RICHARDSON_ROW_RE.search(line)
        if not match:
            continue
        values = match.groupdict()
        row = _row_from_mt(
            "Richardson email bids", location, commodity, values["delivery"],
            values["contract"], values["futures"], values["basis"], values["mt"],
        )
        if row is not None:
            # The row OCR can lose a leading minus. A sparse OCR pass reads
            # the USD-basis column independently and is preferred when found.
            delivery_key = _month(values["delivery"])
            fallback = _us_basis_per_bushel(values["usd"])
            usd_basis = us_basis_by_delivery.get(delivery_key, fallback) if us_basis_by_delivery else fallback
            if us_basis_sequence and sequence_index < len(us_basis_sequence):
                usd_basis = us_basis_sequence[sequence_index]
            row["US Basis (USD/bu)"] = usd_basis
            rows.append(row)
            sequence_index += 1
    return rows


def parse_richardson_images(image_paths: list[Path], output_dir: Path) -> pd.DataFrame:
    """Parse Andrea Richardson's fixed four-panel price-grid attachment."""
    rows: list[dict] = []
    # The Richardson sheet is one landscape image with four stable panels.
    regions = (
        # The narrow Sorel soybean USD column preserves small leading minus
        # signs that full-table OCR can lose.
        ("Soybeans", "Richardson Sorel", (0.00, 0.17, 0.49, 0.62), "soy_sorel", (0.17, 0.17, 0.29, 0.62)),
        ("Soybeans", "Richardson Johnstown", (0.00, 0.69, 0.49, 0.99), "soy_johnstown", None),
        ("Corn", "Richardson Sorel", (0.50, 0.17, 1.00, 0.45), "corn_sorel", None),
        ("Corn", "Richardson Johnstown", (0.50, 0.60, 1.00, 0.92), "corn_johnstown", None),
    )
    for image_path in image_paths:
        try:
            from PIL import Image
            width, height = Image.open(image_path).size
            if width < 900 or width / max(height, 1) < 2.5:
                continue
            for commodity, location, crop, suffix, usd_crop in regions:
                text = _ocr_image(image_path, crop=crop)
                usd_column_text = _ocr_image(image_path, psm=11, crop=crop)
                _save_ocr_text(text, image_path, output_dir, suffix)
                _save_ocr_text(usd_column_text, image_path, output_dir, f"{suffix}_usd")
                usd_sequence: list[float] | None = None
                if usd_crop is not None:
                    usd_column_text = _ocr_image(image_path, psm=6, crop=usd_crop, enhance=True)
                    _save_ocr_text(usd_column_text, image_path, output_dir, f"{suffix}_usd_column")
                    usd_sequence = _richardson_us_basis_sequence(usd_column_text)
                rows.extend(_parse_richardson_ocr_region(
                    text, commodity, location,
                    _richardson_us_basis_by_delivery(_ocr_image(image_path, psm=11, crop=crop)),
                    usd_sequence,
                ))
        except Exception as exc:
            print(f"[WARN] Richardson OCR failed for {image_path.name}: {exc}")
    return pd.DataFrame(rows)


_PANDH_ROW_RE = re.compile(r"^\d{2}-[A-Za-z]{3,9}\b")
_PANDH_CAPTURE_RE = re.compile(
    r"^(?P<delivery>\d{2}-[A-Za-z]{3,9}).*?"
    r"(?P<futures>\d+\.\d+).*?"
    r"(?P<contract>z?[sc][a-z]{1,3}\d{2}).*?"
    r"(?P<us_basis_mt>-?\d+\.\d+).*?"
    r"(?P<fx>\d+\.\d+).*?"
    r"(?P<fx_month>ca[a-z0-9]*\d{1,2}).*?"
    r"(?P<basis>-?\d+\.\d+).*?"
    r"(?P<cash>\d+\.\d+).*?"
    r"(?P<mt>\d+\.\d+).*?"
    r"(?P<us_basis>[+-]?\d+(?:\.\d+)?)\s*$",
    re.I,
)


def parse_pandh_ocr(text: str, *, default_location: str = "", default_commodity: str = "") -> pd.DataFrame:
    """Parse a P&H OCR table with CAD basis, CAD/bu, and CAD/MT columns."""
    rows: list[dict] = []
    location = default_location
    for raw_line in text.splitlines():
        line = _text(raw_line)
        lower = line.lower()
        for candidate in ("Prescott", "Picton", "DLVD Johnstown/Cardinal"):
            if candidate.lower() in lower:
                location = candidate
        if not location or not _PANDH_ROW_RE.match(line):
            continue
        if "#value!" in lower:
            continue
        match = _PANDH_CAPTURE_RE.search(line.replace("|", " ").replace("_", " "))
        if not match:
            continue
        values = match.groupdict()
        commodity = "Soybeans" if "s" in values["contract"].lower() else "Corn"
        if default_commodity:
            commodity = default_commodity
        futures_price = values["futures"]
        futures_number = _number(futures_price)
        # Grid lines can be read as a leading "1" on P&H corn futures
        # (14.8275 instead of 4.8275). Corn futures are otherwise below $10.
        if commodity == "Corn" and 10 <= futures_number < 20:
            futures_price = f"{futures_number - 10:.4f}"
        row = _row(
            "P&H email bids", location, commodity, _reverse_month(values["delivery"]),
            values["contract"], futures_price, values["basis"], values["cash"], values["mt"],
            us_basis=values["us_basis"],
        )
        if not pd.isna(row["Basis"]) and not pd.isna(row["Bushel Cash Price"]):
            rows.append(row)
    return pd.DataFrame(rows)


def parse_pandh_images(image_paths: list[Path], output_dir: Path) -> pd.DataFrame:
    """OCR P&H inline table images and parse only complete, numeric bid rows."""
    frames: list[pd.DataFrame] = []
    for image_path in image_paths:
        try:
            # P&H uses tiny bordered tables. Its original pixels preserve the
            # grid layout better than the enlarged/contrast-enhanced variant.
            text = _ocr_image(image_path, psm=4, enhance=False)
            _save_ocr_text(text, image_path, output_dir)
            filename = image_path.name.lower()
            # P&H's message has one inline table per image. The corn Picton
            # image starts directly with bid rows, so retain its known panel
            # identity even when its location heading is cropped off.
            defaults = (
                ("Picton", "Corn") if "image004" in filename else
                ("DLVD Johnstown/Cardinal", "Corn") if "image005" in filename else
                ("", "")
            )
            frame = parse_pandh_ocr(text, default_location=defaults[0], default_commodity=defaults[1])
            if not frame.empty:
                frames.append(frame)
        except Exception as exc:
            print(f"[WARN] P&H OCR failed for {image_path.name}: {exc}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


_BROADGRAIN_ROW_RE = re.compile(
    r"(?P<delivery>[A-Za-z]{3,9}-\d{2}|Harvest-?\d{2})\s+\$?\s*"
    r"(?P<basis>[+-]?\d+(?:\.\d+)?)\s+(?P<futures>\d+(?:\.\d+)?)\s+"
    r"(?P<contract>[A-Za-z]{1,3}\d{1,2})\s+\$?\s*(?P<cash>\d+(?:\.\d+)?)\s+\$?\s*"
    r"(?P<mt>\d+(?:\.\d+)?)",
    re.I,
)


def _ocr_futures(value: str) -> str:
    number = _number(value)
    if pd.isna(number):
        return ""
    if number >= 100:
        number /= 10000
    return f"{number:.4f}"


def parse_broadgrain_ocr(text: str) -> pd.DataFrame:
    """Parse BroadGrain's OCR text, favoring the printed CAD/MT price."""
    rows: list[dict] = []
    commodity = ""
    location = "BroadGrain Brinston"
    for raw_line in text.splitlines():
        line = _text(raw_line).replace("$", " ").replace("Â§", " ").replace("§", " ")
        lower = line.lower()
        if "corn" in lower and not lower.startswith("unconfirmed"):
            commodity = "Corn"
        elif "soybean" in lower:
            commodity = "Soybeans"
        elif "wheat - srw" in lower:
            commodity = "SRW Wheat"
        elif "wheat - hrw" in lower:
            commodity = "HRW Wheat"
        elif "wheat - hrs" in lower:
            commodity = "HRS Wheat"
        match = _BROADGRAIN_ROW_RE.search(line)
        location_context = line[:match.start()] if match else line
        location_match = re.search(
            r"(?:del\s*-?\s*)([A-Za-z]+(?:[ /.-][A-Za-z]+)*)", line, re.I
        )
        if match:
            location_match = re.search(
                r"(?:del\s*-?\s*)([A-Za-z]+(?:[ /.-][A-Za-z]+)*)", location_context, re.I
            )
        if location_match:
            location_name = re.sub(
                r"\s+(?:[A-Za-z]{3,9}-\d{2}|Harvest-?\d{2})$", "", location_match.group(1).strip(), flags=re.I
            )
            location_name = re.sub(
                r"\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$", "", location_name, flags=re.I
            )
            location = f"BroadGrain {location_name.title()}"
        elif "brinston" in lower:
            location = "BroadGrain Brinston"
        if not match or not commodity:
            continue
        values = match.groupdict()
        contract = values["contract"].upper()
        row_commodity = (
            "Soybeans" if contract.startswith("S") else
            "Corn" if contract.startswith("C") else
            "SRW Wheat" if contract.startswith("W") else commodity
        )
        row = _row_from_mt(
            "BroadGrain email bids", location, row_commodity, values["delivery"],
            values["contract"], _ocr_futures(values["futures"]), values["basis"], values["mt"],
        )
        if row is not None:
            rows.append(row)
    return pd.DataFrame(rows)


def parse_broadgrain_images(image_paths: list[Path], output_dir: Path) -> pd.DataFrame:
    """OCR BroadGrain bid-sheet images and parse complete printed bid rows."""
    frames: list[pd.DataFrame] = []
    for image_path in image_paths:
        try:
            text = _ocr_image(image_path)
            _save_ocr_text(text, image_path, output_dir)
            frame = parse_broadgrain_ocr(text)
            if not frame.empty:
                frames.append(frame)
        except Exception as exc:
            print(f"[WARN] BroadGrain OCR failed for {image_path.name}: {exc}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _save_inline_attachments(item: Any, output_dir: Path, prefix: str = "broadgrain") -> list[Path]:
    """Save inline Outlook attachments so BroadGrain's image sheet is available."""
    saved: list[Path] = []
    attachments = getattr(item, "Attachments", None)
    if attachments is None:
        return saved
    for index in range(1, attachments.Count + 1):
        attachment = attachments.Item(index)
        name = _text(getattr(attachment, "FileName", "attachment")) or "attachment"
        target = output_dir / f"{prefix}_{index}_{Path(name).name}"
        try:
            attachment.SaveAsFile(str(target))
            saved.append(target)
        except Exception:
            continue
    return saved


def _matches_email_source(item: Any, source: str) -> bool:
    """Identify forwarded/renamed bid emails using subject, sender, and body."""
    subject = _text(getattr(item, "Subject", "")).lower()
    sender = _text(getattr(item, "SenderEmailAddress", "")).lower()
    body = _text(getattr(item, "Body", "")).lower()
    html = _text(getattr(item, "HTMLBody", "")).lower()
    searchable = f"{subject} {sender} {body} {html}"
    if source == "macewen":
        return "morning report" in subject or "macewen" in searchable
    if source == "andersons":
        return (
            "anderson" in subject
            or ("anderson" in searchable and (
                "cad basis" in searchable
                or "producer commodity bid sheet" in searchable
            ))
        )
    if source == "broadgrain":
        # Dylan Stewart is the actual BroadGrain sender. Do not mistake an
        # internal "neighbours' bids" summary for his original bid sheet.
        return ("dylan stewart" in searchable or "dylan.stewart" in searchable) and "broadgrain" in searchable
    if source == "richardson":
        return (
            "andrea.baronmancera@richardson.ca" in searchable
            or "andrea baron" in searchable
        )
    if source == "pandh":
        return (
            "rkricsfalusy@pandh.ca" in searchable
            or "richard kricsfalusy" in searchable
        )
    if source == "bunge":
        # The sender is the stable identifier; Bunge changes subjects such as
        # "bunge bids - corn/soy" and "Bunge BIDS MTL/BCC".
        return "jose.borunda@bunge.com" in searchable
    return False


def _all_inbox_folders(namespace: Any) -> list[Any]:
    """Return Inbox folders from every Outlook mailbox/store."""
    inboxes: list[Any] = []
    seen: set[str] = set()

    def visit(folder: Any) -> None:
        try:
            name = _text(getattr(folder, "Name", ""))
            entry_id = _text(getattr(folder, "EntryID", ""))
            key = entry_id or f"{name}:{id(folder)}"
            if key in seen:
                return
            seen.add(key)
            if name.lower() in {"inbox", "bids"}:
                inboxes.append(folder)
            children = getattr(folder, "Folders", None)
            if children is not None:
                for index in range(1, children.Count + 1):
                    visit(children.Item(index))
        except Exception:
            return

    # Prefer the user's named delivery store. GetDefaultFolder(6) can point
    # at a different default account when Outlook has multiple mailboxes.
    try:
        accounts = getattr(namespace, "Accounts", None)
        if accounts is None:
            accounts = namespace.Application.Session.Accounts
        for index in range(1, accounts.Count + 1):
            account = accounts.Item(index)
            address = _text(getattr(account, "SmtpAddress", "")).lower()
            if address == TARGET_OUTLOOK_ADDRESS:
                visit(account.DeliveryStore.GetDefaultFolder(6))
    except Exception:
        pass

    # Include the normal default Inbox, then search other stores as fallback.
    try:
        visit(namespace.GetDefaultFolder(6))
    except Exception:
        pass
    try:
        for index in range(1, namespace.Folders.Count + 1):
            visit(namespace.Folders.Item(index))
    except Exception:
        pass
    return inboxes


def collect_outlook_bid_rows(project_dir: Path) -> pd.DataFrame:
    """Read the newest matching classic-Outlook email from each configured source."""
    log_dir = project_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    status_lines = [f"Email pull started: {datetime.now().isoformat(timespec='seconds')}"]
    try:
        import win32com.client
        namespace = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception as exc:
        message = f"[FAILURE] Outlook unavailable: {exc}"
        print(message)
        status_lines.append(message)
        (log_dir / f"email_pull_{datetime.now():%Y-%m-%d}.txt").write_text(
            "\n".join(status_lines) + "\n", encoding="utf-8"
        )
        return pd.DataFrame()

    patterns = {
        "broadgrain": ("bid sheet",),
        "macewen": ("morning report",),
        "andersons": ("snapshot of andersons",),
        "richardson": ("richardson.ca",),
        "pandh": ("pandh.ca",),
        "bunge": ("jose.borunda@bunge.com",),
    }
    found: dict[str, Any] = {}
    inboxes = _all_inbox_folders(namespace)
    status_lines.append(
        f"Target Outlook account: {TARGET_OUTLOOK_ADDRESS}; mail folders scanned: {len(inboxes)}"
    )
    for inbox in inboxes:
        try:
            parent = _text(getattr(getattr(inbox, "Parent", None), "Name", ""))
            name = _text(getattr(inbox, "Name", "Inbox"))
            status_lines.append(f"Mail folder: {parent} / {name}")
        except Exception:
            pass
    for inbox in inboxes:
        items = inbox.Items
        items.Sort("[ReceivedTime]", True)
        for index in range(1, min(items.Count, 3000) + 1):
            item = items.Item(index)
            for source in patterns:
                if source not in found and _matches_email_source(item, source):
                    found[source] = item
            if len(found) == len(patterns):
                break
        if len(found) == len(patterns):
            break

    frames: list[pd.DataFrame] = []
    for source, item in found.items():
        html = _text(getattr(item, "HTMLBody", ""))
        (log_dir / f"{source}_latest_email.html").write_text(html, encoding="utf-8")
        subject = _text(getattr(item, "Subject", ""))
        received = _text(getattr(item, "ReceivedTime", ""))
        status_lines.append(f"{source.title()} selected: {subject} | Received: {received}")
        if source in {"broadgrain", "richardson", "pandh"}:
            saved = _save_inline_attachments(item, log_dir, prefix=source)
            try:
                frame = {
                    "broadgrain": parse_broadgrain_images,
                    "richardson": parse_richardson_images,
                    "pandh": parse_pandh_images,
                }[source](saved, log_dir)
                labels = {
                    "broadgrain": "BroadGrain",
                    "richardson": "Richardson",
                    "pandh": "P&H",
                }
                if not frame.empty:
                    frame["Quote Date"] = _email_quote_date(item)
                    frames.append(frame)
                    message = f"[SUCCESS] {labels[source]} email bids (OCR): {len(frame)} rows from {len(saved)} image attachment(s)"
                else:
                    message = f"[FAILURE] {labels[source]} OCR found no complete parseable bid rows; saved {len(saved)} image attachment(s)"
                print(message)
                status_lines.append(message)
            except Exception as exc:
                message = f"[FAILURE] {source.title()} OCR: {exc}"
                print(message)
                status_lines.append(message)
            continue
        parser = {
            "macewen": parse_macewen,
            "andersons": parse_andersons,
            "bunge": lambda value: parse_bunge(
                getattr(item, "Body", "") or value
            ),
        }[source]
        try:
            frame = parser(html)
            if not frame.empty:
                frame["Quote Date"] = _email_quote_date(item)
                frames.append(frame)
                message = f"[SUCCESS] {source.title()} email bids: {len(frame)} rows"
                print(message)
                status_lines.append(message)
            else:
                message = f"[FAILURE] {source.title()} email contained no parseable bid rows"
                print(message)
                status_lines.append(message)
        except Exception as exc:
            message = f"[FAILURE] {source.title()} email parser: {exc}"
            print(message)
            status_lines.append(message)

    for source in patterns:
        if source not in found:
            message = f"[NO MATCH] {source.title()}: no matching Inbox email found"
            print(message)
            status_lines.append(message)

    status_lines.append(f"Email rows added: {sum(len(frame) for frame in frames)}")
    (log_dir / f"email_pull_{datetime.now():%Y-%m-%d}.txt").write_text(
        "\n".join(status_lines) + "\n", encoding="utf-8"
    )

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
