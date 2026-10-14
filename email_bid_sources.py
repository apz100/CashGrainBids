"""Readers for recurring cash-bid emails in classic Outlook.

The email formats are intentionally handled separately from the web scrapers:
they are publisher-specific and may change independently.
"""

from __future__ import annotations

import io
import re
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


def _number(value: Any) -> float:
    match = NUMBER_RE.search(_text(value).replace(",", ""))
    return float(match.group()) if match else float("nan")


def _month(value: Any) -> str:
    raw = _text(value)
    match = re.match(r"^([A-Za-z]{3,9})[- ](\d{2,4})$", raw)
    if not match:
        return raw
    year = int(match.group(2))
    if year < 100:
        year += 2000
    return f"{match.group(1)[:3].title()} {year}"


def _future_month(code: Any) -> str:
    raw = _text(code).upper()
    match = re.search(r"([FGHJKMNQUVXZ])(\d{2})$", raw)
    if not match:
        return raw
    return f"{MONTHS[match.group(1)]} {2000 + int(match.group(2))}"


def _reverse_month(value: Any) -> str:
    raw = _text(value)
    match = re.match(r"^(\d{2})-([A-Za-z]{3,9})$", raw)
    if not match:
        return _month(raw)
    return _month(f"{match.group(2)}-{match.group(1)}")


def _row(source: str, location: str, name: str, delivery: Any, future: Any,
         futures_price: Any, basis: Any, bushel_price: Any, mt_price: Any = None) -> dict:
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
        rows.append(_row(
            "Bunge email bids", f"Bunge {location}", commodity, delivery,
            futures_code, "", basis, "", "",
        ))
    return pd.DataFrame(rows)


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
        return "bid sheet" in subject or "broadgrain" in searchable
    if source == "andrea":
        return (
            "andrea.baronmancera@richardson.ca" in searchable
            or "andrea baron" in searchable
        )
    if source == "richard":
        return (
            "rkricsfalusy@pandh.ca" in searchable
            or "richard kricsfalusy" in searchable
        )
    if source == "bunge":
        # The sender is the stable identifier; Bunge changes subjects such as
        # "bunge bids - corn/soy" and "Bunge BIDS MTL/BCC".
        return "jose.borunda@bunge.com" in searchable
    return False


def _ocr_broadgrain_images(image_paths: list[Path], output_dir: Path) -> None:
    """Run optional local OCR and save text for review; never invent bid rows."""
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        print("[WARN] BroadGrain OCR unavailable: install Pillow and pytesseract")
        return
    for image_path in image_paths:
        try:
            text = pytesseract.image_to_string(Image.open(image_path), config="--psm 6")
            text_path = output_dir / f"{image_path.stem}.txt"
            text_path.write_text(text, encoding="utf-8")
            print(f"[OK] BroadGrain OCR text saved: {text_path}")
        except Exception as exc:
            print(f"[WARN] BroadGrain OCR failed for {image_path.name}: {exc}")


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
        "andrea": ("richardson.ca",),
        "richard": ("pandh.ca",),
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
        if source in {"broadgrain", "andrea"}:
            saved = _save_inline_attachments(item, log_dir, prefix=source)
            _ocr_broadgrain_images(saved, log_dir)
            label = "BroadGrain" if source == "broadgrain" else "Andrea Richardson"
            message = f"[OCR REVIEW ONLY] {label}: matching email found; saved {len(saved)} image attachment(s)"
            print(message)
            status_lines.append(message)
            continue
        parser = {
            "macewen": parse_macewen,
            "andersons": parse_andersons,
            "richard": parse_richard,
            "bunge": lambda value: parse_bunge(
                getattr(item, "Body", "") or value
            ),
        }[source]
        try:
            frame = parser(html)
            if not frame.empty:
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
