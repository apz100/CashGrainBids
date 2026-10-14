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

When classic Outlook is installed and signed in, the daily run also checks the
Inbox for the newest recurring MacEwen, Andersons, Richard, and Bunge bid
emails and adds their rows to the CSV and Excel files. Bunge is matched by
sender (`jose.borunda@bunge.com`) rather than subject and its text basis rows
are recorded without inventing cash prices. BroadGrain bid sheets are embedded images, so
the run saves their inline image attachment under `logs/` for OCR processing;
it does not guess prices from an image. The scheduled task must run while the
Windows user is signed in and Outlook is available. Email errors do not stop
the website bids from being written.

BroadGrain OCR also requires the Tesseract OCR application installed on
Windows. `Pillow` and `pytesseract` are included in the Python requirements;
the first OCR test saves recognized text under `logs/` for verification rather
than importing unverified prices into the workbook.

## Regression tests

Before relying on a code change, run:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

These tests cover AgriCharts basis conversion, basis-change calculation from
older CSV files, and the Eastern Ontario email-location filter.

Email results are recorded in both the normal `logs/run_YYYY-MM-DD_HHmm.log`
file and `logs/email_pull_YYYY-MM-DD.txt`. Look for `[SUCCESS]`, `[NO MATCH]`,
`[FAILURE]`, or `[OCR REVIEW ONLY]` beside each email source.
