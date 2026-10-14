from pathlib import Path
import io

import pandas as pd
import win32com.client


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
HTML_OUT = LOG_DIR / "broadgrain_latest_email.html"
SUMMARY_OUT = LOG_DIR / "broadgrain_email_tables.txt"


def connect_outlook():
    try:
        return win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception:
        return win32com.client.GetActiveObject("Outlook.Application").GetNamespace("MAPI")


namespace = connect_outlook()
inbox = namespace.GetDefaultFolder(6)
items = inbox.Items
items.Sort("[ReceivedTime]", True)

match = None
for index in range(1, min(items.Count, 2000) + 1):
    item = items.Item(index)
    subject = str(getattr(item, "Subject", "") or "")
    sender = str(getattr(item, "SenderEmailAddress", "") or "")
    sender_name = str(getattr(item, "SenderName", "") or "")
    if "bid sheet" in subject.lower() and (
        "broadgrain" in sender.lower() or "dylan" in sender_name.lower()
    ):
        match = item
        break

if match is None:
    raise SystemExit("No matching BroadGrain email was found in the Inbox.")

html = str(getattr(match, "HTMLBody", "") or "")
HTML_OUT.write_text(html, encoding="utf-8")

lines = [
    f"Subject: {getattr(match, 'Subject', '')}",
    f"Sender: {getattr(match, 'SenderEmailAddress', '')}",
    f"Received: {getattr(match, 'ReceivedTime', '')}",
    f"HTML length: {len(html)}",
]

try:
    tables = pd.read_html(io.StringIO(html))
    lines.append(f"Tables: {len(tables)}")
    for index, table in enumerate(tables):
        lines.append(f"TABLE {index}: shape={table.shape} columns={list(table.columns)!r}")
        lines.append(table.head(3).to_string(index=False))
except Exception as exc:
    lines.append(f"Could not parse HTML tables: {exc!r}")

SUMMARY_OUT.write_text("\n\n".join(lines), encoding="utf-8")
print("Matching email:", getattr(match, "Subject", ""))
print("Saved HTML:", HTML_OUT)
print("Saved table summary:", SUMMARY_OUT)
