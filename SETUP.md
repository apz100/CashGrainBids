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

The project currently only writes the local cash-bids CSV. Derks-price calculation and Google Sheets upload are disabled.
