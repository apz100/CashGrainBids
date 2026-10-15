# CashGrainBids setup

## First run on a new Windows computer

1. Install Python 3 for Windows and enable **Add python.exe to PATH**.
2. Open PowerShell in this folder.
3. Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup_new_computer.ps1
.\run_cash_bids.ps1
```

The collector writes CSV files and logs under this project folder. To install the daily scheduled task, run PowerShell as Administrator and execute:

```powershell
.\cash_bids_runner.ps1
```

The project writes the local cash-bids CSV, formatted Excel workbook, and a daily HTML/PDF report under `EasternOntarioBids\Reports`. Derks-price calculation and Google Sheets upload are disabled.

## Google Drive export

For unattended export, install Google Drive for Desktop and set
`CASH_BIDS_GOOGLE_DRIVE_DIR` to the local folder that synchronizes to the
desired Drive folder. The daily runner copies the CSV, Excel workbook, HTML
report, and PDF into a dated `CashGrainBids\YYYY-MM-DD` subfolder. If the
variable is not set, local report generation still works and Drive export is
logged as skipped.

The synchronized-folder path varies by Google account and Drive for Desktop
configuration. Set it for the Windows user running the scheduled task, for
example:

```powershell
[Environment]::SetEnvironmentVariable('CASH_BIDS_GOOGLE_DRIVE_DIR', "$env:USERPROFILE\Google Drive", 'User')
```

ChatGPT's Google Drive app can then find files that the connected Google
account is permitted to access, but the connection itself is not a replacement
for the local scheduled export.

## Additional sources

The collector also checks Greenfield Johnstown Corn, Ingredion Cardinal CEY Dent, and Great Lakes Grain's Embrun Elevator. Great Lakes elevator bids are read from an embedded frame after selecting Embrun; its offer-centre login is not required for those elevator bids. Greenfield is attempted as a public page. Ingredion requires an authenticated session:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup_ingredion_login.ps1
```

Log in in the browser window that opens, verify that the Cardinal / CEY Dent table is visible, then return to PowerShell and press Enter. The session is saved locally in `ingredion_storage_state.json` and is excluded from Git. The daily scheduled task reuses that session.

## Outlook bid emails

When classic Outlook is installed and signed in, the daily run scans the Inbox
and its subfolders for the newest recurring bid emails from MacEwen, Andersons,
BroadGrain, Richardson, P&H, and Bunge, then adds validated rows to the CSV and
Excel files. Sender matching is deliberate: Dylan Stewart is BroadGrain,
Andrea Baron Mancera is Richardson, Richard Kricsfalusy is P&H, and Bunge is
matched by `jose.borunda@bunge.com` rather than subject.

BroadGrain, Richardson, and P&H send their bid tables as inline images rather
than usable HTML tables. Their image attachments are therefore read with OCR.
Only complete rows with the expected numeric values are imported; unclear,
partial, and error rows are left out instead of being guessed. The raw OCR text
and source images are retained under `logs/` for review. The scheduled task
must run while the Windows user is signed in and classic Outlook is available.
An email-source failure does not stop website bids from being written.

This OCR path requires the Tesseract OCR application installed on Windows.
`Pillow` and `pytesseract` are included in the Python requirements. Confirm
each source using `logs/email_pull_YYYY-MM-DD.txt`: `[SUCCESS]` includes the
number of imported rows, while `[FAILURE]` explains why no rows were added.

`Basis` is the source's CAD basis when supplied. `US Basis (USD/bu)` is a
separate column for exporter and processor comparisons: it is read directly
from Richardson and P&H sheets and from Bunge's USD basis email. Sources that
do not provide a USD basis or the FX value required to calculate one are left
blank rather than converted with an assumption.

The daily run also retrieves the Bank of Canada `FXUSDCAD` spot observation,
caches it under `EasternOntarioBids/FX/`, converts it to CADUSD, and calculates
USD basis for BroadGrain, Andersons, MacEwen, Ingredion, and Greenfield when
both CAD cash and futures values are present. The public workbook keeps only
the `US Basis (USD/bu)` result; FX details remain internal. Printed USD basis
values are preserved. Values outside the valid +/-2.00 USD/bu range are
rejected and logged. MacEwen's current email format supplies MT cash and a
delivery month but no futures price, so its USD basis remains blank until a
matching futures value is added.

## Regression tests

Before relying on a code change, run:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

These tests cover AgriCharts basis conversion, basis-change calculation from
older CSV files, and the Eastern Ontario email-location filter.

Email results are recorded in both the normal `logs/run_YYYY-MM-DD_HHmm.log`
file and `logs/email_pull_YYYY-MM-DD.txt`. Look for `[SUCCESS]`, `[NO MATCH]`,
or `[FAILURE]` beside each email source.

## Project structure

The scheduled task still starts `cash_bids_via_playwright_UPDATED.py`; it is
now a compatibility entry point only. The application code is organized under
`cashgrainbids`:

- `config.py` — source URLs, AgriCharts locations, output paths, and email
  location rules.
- `processing.py` — shared cleaning, basis conversion, validation, sorting,
  and prior-day basis comparison.
- `web_collectors.py` — the website-specific Greenfield, Ingredion, Great
  Lakes, and AgriCharts collectors.
- `output.py` — standard CSV and Excel workbook writing.
- `classification.py` — elevator, processor, exporter, and direct-ship
  competitor categorization.
- `reporting.py` — PDF/HTML report generation and Google Drive Desktop export.
- `pipeline.py` — the small orchestration layer that runs the daily flow.

Email parsing remains in `email_bid_sources.py` because each company has its
own email format. Add a new website collector in `web_collectors.py`, a new
recurring email parser in `email_bid_sources.py`, and put locations or rules
in `config.py`. This keeps new sources from expanding the daily pipeline.
