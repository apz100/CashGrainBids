from pathlib import Path
import io
import re

import pandas as pd
import win32com.client
from email_bid_sources import _matches_email_source


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

SOURCE_PATTERNS = {
    "broadgrain": ("bid sheet",),
    "macewen": ("morning report",),
    "andersons": ("snapshot of andersons",),
    "andrea": ("richardson.ca",),
    "richard": ("pandh.ca",),
}


def connect_outlook():
    try:
        return win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception:
        return win32com.client.GetActiveObject("Outlook.Application").GetNamespace("MAPI")


namespace = connect_outlook()
inbox = namespace.GetDefaultFolder(6)
items = inbox.Items
items.Sort("[ReceivedTime]", True)
matches = {name: None for name in SOURCE_PATTERNS}

for index in range(1, min(items.Count, 3000) + 1):
    item = items.Item(index)
    for source in SOURCE_PATTERNS:
        if matches[source] is None and _matches_email_source(item, source):
            matches[source] = item
    if all(matches.values()):
        break

for source, item in matches.items():
    if item is None:
        print(f"{source}: no matching email found")
        continue

    html = str(getattr(item, "HTMLBody", "") or "")
    html_path = LOG_DIR / f"{source}_latest_email.html"
    summary_path = LOG_DIR / f"{source}_email_tables.txt"
    html_path.write_text(html, encoding="utf-8")

    lines = [
        f"Source: {source}",
        f"Subject: {getattr(item, 'Subject', '')}",
        f"Sender: {getattr(item, 'SenderEmailAddress', '')}",
        f"Sender name: {getattr(item, 'SenderName', '')}",
        f"Received: {getattr(item, 'ReceivedTime', '')}",
        f"HTML length: {len(html)}",
    ]
    try:
        tables = pd.read_html(io.StringIO(html))
        lines.append(f"Tables: {len(tables)}")
        for table_index, table in enumerate(tables):
            lines.append(
                f"TABLE {table_index}: shape={table.shape} columns={list(table.columns)!r}"
            )
            lines.append(table.head(5).to_string(index=False))
    except Exception as exc:
        lines.append(f"Could not parse HTML tables: {exc!r}")

    summary_path.write_text("\n\n".join(lines), encoding="utf-8")
    print(f"{source}: {getattr(item, 'Subject', '')}")
    print(f"  HTML: {html_path}")
    print(f"  Summary: {summary_path}")
