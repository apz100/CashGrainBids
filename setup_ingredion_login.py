from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "ingredion_storage_state.json"
URL = "https://ag.ingredion.com/cash-bids"


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    print("A browser window is open. Log in to Ingredion and confirm that the Cardinal / CEY Dent table is visible.")
    input("When finished, return here and press Enter to save the session... ")
    context.storage_state(path=str(STATE_FILE))
    browser.close()

print(f"Saved Ingredion session to {STATE_FILE}")
