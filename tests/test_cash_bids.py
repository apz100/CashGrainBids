import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from cash_bids_via_playwright_UPDATED import (
    add_basis_change_column,
    filter_eastern_ontario_locations,
    normalize_agricharts_basis,
)
from email_bid_sources import (
    _matches_email_source,
    _parse_richardson_ocr_region,
    _richardson_us_basis_by_delivery,
    _richardson_us_basis_sequence,
    parse_broadgrain_ocr,
    parse_bunge,
    parse_pandh_ocr,
)
from cashgrainbids.classification import classify_bid
from cashgrainbids.config import AGRICHARTS_TARGETS
from cashgrainbids.fx_rates import add_us_basis_from_spot


class CashBidsRegressionTests(unittest.TestCase):
    def test_agricharts_basis_cents_are_converted(self):
        frame = pd.DataFrame({
            "Source": pd.Series(["AgriCharts", "Greenfield"], dtype="string"),
            "Basis": pd.Series(["165", "2.16"], dtype="string"),
        })
        result = normalize_agricharts_basis(frame)
        self.assertAlmostEqual(result.loc[0, "Basis"], 1.65)
        self.assertAlmostEqual(result.loc[1, "Basis"], 2.16)

    def test_basis_change_handles_old_string_csv(self):
        today = pd.DataFrame([{
            "Source": "AgriCharts", "Location": "Brinston Corn", "Name": "Corn",
            "Delivery": "Oct 2026", "Delivery End": "Oct 2026",
            "Futures Month": "December 2026", "Basis": 1.65,
        }])
        previous = today.copy()
        previous["Basis"] = "165.00"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "EasternOntario_CashBids_2026-10-11.csv"
            previous.to_csv(path, index=False)
            result = add_basis_change_column(today, path)
        self.assertAlmostEqual(float(result.loc[0, "Basis Change"]), 0.0)

    def test_email_location_filter_removes_unwanted_locations(self):
        frame = pd.DataFrame([
            {"Source": "Andersons email bids", "Location": "Johnstown"},
            {"Source": "Andersons email bids", "Location": "Havelock"},
            {"Source": "MacEwen email bids", "Location": "Prescott/Cardinal/Johnstown"},
            {"Source": "MacEwen email bids", "Location": "MacEwen Cobden"},
            {"Source": "AgriCharts", "Location": "Brinston Corn"},
        ])
        result = filter_eastern_ontario_locations(frame)
        self.assertEqual(result["Location"].tolist(), [
            "Johnstown", "Prescott/Cardinal/Johnstown", "Brinston Corn"
        ])

    def test_andersons_match_uses_html_body(self):
        item = SimpleNamespace(
            Subject="FW: Daily grain values",
            SenderEmailAddress="exchange@example.com",
            Body="",
            HTMLBody="Andersons Canada Producer Commodity Bid Sheet CAD Basis",
        )
        self.assertTrue(_matches_email_source(item, "andersons"))

    def test_bunge_matches_sender_without_subject_keyword(self):
        item = SimpleNamespace(
            Subject="Updated market information",
            SenderEmailAddress="jose.borunda@bunge.com",
            Body="Soybeans BCC:\n• Nov-26 21-30th: -0.10 SX26\n\nCorn MTL:\n• Jan-27: +0.40 CH27",
            HTMLBody="",
        )
        self.assertTrue(_matches_email_source(item, "bunge"))

    def test_bunge_parser_reads_basis_sections(self):
        frame = parse_bunge(
            "Soybeans BCC:\n"
            "• Nov-26 21-30th: -0.10 SX26\n"
            "• Dec-26: -0.10 SF27\n\n"
            "Corn MTL:\n"
            "• Jan-27: +0.40 CH27\n"
        )
        self.assertEqual(len(frame), 3)
        self.assertEqual(frame.loc[0, "Location"], "Bunge BCC")
        self.assertEqual(frame.loc[0, "Name"], "Soybeans")
        self.assertTrue(pd.isna(frame.loc[0, "Basis"]))
        self.assertAlmostEqual(float(frame.loc[0, "US Basis (USD/bu)"]), -0.10)
        self.assertEqual(frame.loc[2, "Futures Month"], "March 2027")

    def test_broadgrain_ocr_parser_uses_mt_price_for_cash_bid(self):
        frame = parse_broadgrain_ocr(
            "CORN Sep-26 $ 1.65 4.7900 CZ6 $ 6.44 $ 253.53\n"
            "Soybeans Harvest-27 $ 3.70 12.5200 SX7 $ 16.22 $ 595.98"
        )
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame.loc[0, "Location"], "BroadGrain Brinston")
        self.assertEqual(frame.loc[1, "Name"], "Soybeans")
        self.assertAlmostEqual(float(frame.loc[0, "MT Cash Price"]), 253.53)

    def test_richardson_ocr_parser_reads_corn_panel(self):
        usd_basis = _richardson_us_basis_by_delivery(
            "Harvest 26\n-0.60\n4.58\n"
            "Nov-26\n-0.40\n4.84\n"
            "Dec-26\n-0.45\n4.77\n"
            "Harvest 27\n-0.55\n4.18\n"
        )
        self.assertAlmostEqual(usd_basis["Dec 2026"], -0.45)
        self.assertEqual(
            _richardson_us_basis_sequence("-0.50 4.73\n-0.05 5.34\n-0.23 4.63"),
            [-0.50, -0.05, -0.23],
        )
        rows = _parse_richardson_ocr_region(
            "Dec-2026 0.40 2.63 H27 4.9225 $297.35\n"
            "Jan-Feb -27 0.40 2.61 H27 4.9225 $296.49",
            "Corn", "Richardson Sorel",
        )
        frame = pd.DataFrame(rows)
        self.assertEqual(frame["Delivery"].tolist(), ["Dec 2026", "Jan-Feb 2027"])
        self.assertAlmostEqual(float(frame.loc[0, "Basis"]), 2.63)
        self.assertAlmostEqual(float(frame.loc[0, "US Basis (USD/bu)"]), 0.40)

    def test_pandh_ocr_parser_reads_complete_numeric_row(self):
        frame = parse_pandh_ocr(
            "Prescott\n"
            "26-Oct 12.8275 ZSEX26 -25.72 0.7058 CA6Z26 4.36 17.18 631.36 -0.7"
        )
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.loc[0, "Source"], "P&H email bids")
        self.assertEqual(frame.loc[0, "Name"], "Soybeans")
        self.assertAlmostEqual(float(frame.loc[0, "MT Cash Price"]), 631.36)
        self.assertAlmostEqual(float(frame.loc[0, "US Basis (USD/bu)"]), -0.70)

    def test_broadgrain_match_requires_dylan_not_internal_summary(self):
        summary = SimpleNamespace(
            Subject="Neighbours' bids", SenderEmailAddress="internal@example.com",
            Body="BroadGrain bid sheet summary", HTMLBody="",
        )
        dylan = SimpleNamespace(
            Subject="Bid Sheet", SenderEmailAddress="dylan.stewart@broadgrain.com",
            Body="BroadGrain Commodities", HTMLBody="",
        )
        self.assertFalse(_matches_email_source(summary, "broadgrain"))
        self.assertTrue(_matches_email_source(dylan, "broadgrain"))

    def test_business_categories_follow_source_and_location_rules(self):
        self.assertEqual(classify_bid({"Source": "AgriCharts", "Location": "Brinston Corn"}), "Elevator")
        self.assertEqual(classify_bid({"Source": "AgriCharts", "Location": "Prescott Corn"}), "Direct Ship Competitor")
        self.assertEqual(classify_bid({"Source": "Greenfield", "Location": "Johnstown"}), "Processor")
        self.assertEqual(classify_bid({"Source": "Bunge email bids", "Location": "Bunge MTL"}), "Exporter")
        self.assertEqual(classify_bid({"Source": "Great Lakes Grain", "Location": "Great Lakes Embrun Elevator"}), "Elevator")

    def test_agricharts_configuration_contains_dalkeith_targets(self):
        target_names = {target["name"] for target in AGRICHARTS_TARGETS}
        self.assertTrue({"Dalkeith Corn", "Dalkeith Soybeans", "Dalkeith Wheat"}.issubset(target_names))

    def test_spot_fx_calculates_us_basis_without_overwriting_printed_basis(self):
        frame = pd.DataFrame([
            {"Source": "Greenfield", "Name": "Corn", "Bushel Cash Price": 7.00, "Futures Price": 4.80},
            {"Source": "Richardson email bids", "Name": "Corn", "Bushel Cash Price": 7.00, "Futures Price": 4.80, "US Basis (USD/bu)": 0.15},
        ])
        with patch("cashgrainbids.fx_rates.get_usdcad_spot", return_value=(1.40, "2026-10-15")):
            result = add_us_basis_from_spot(frame, "2026-10-15", Path(tempfile.mkdtemp()))
        self.assertAlmostEqual(float(result.loc[0, "US Basis (USD/bu)"]), 0.20)
        self.assertEqual(result.loc[0, "FX Type"], "Spot")
        self.assertAlmostEqual(float(result.loc[1, "US Basis (USD/bu)"]), 0.15)

    def test_forward_fx_matches_grain_futures_month(self):
        cache = Path(tempfile.mkdtemp())
        (cache / "FX_Forward_Rates.csv").write_text(
            "Futures Month,USD/CAD,Quote Date\nMarch 2027,0.7500,2026-10-15\n",
            encoding="utf-8",
        )
        frame = pd.DataFrame([{
            "Source": "Greenfield", "Name": "Corn", "Futures Month": "March 2027",
            "Bushel Cash Price": 3.90, "Futures Price": 4.80,
        }])
        with patch("cashgrainbids.fx_rates.get_usdcad_spot", return_value=(1.40, "2026-10-15")):
            result = add_us_basis_from_spot(frame, "2026-10-15", cache)
        self.assertAlmostEqual(float(result.loc[0, "US Basis (USD/bu)"]), 0.40, places=5)
        self.assertEqual(result.loc[0, "FX Type"], "Forward Futures")

    def test_basis_change_calculates_cad_and_usd(self):
        previous = Path(tempfile.mkdtemp()) / "previous.csv"
        pd.DataFrame([{
            "Source": "AgriCharts", "Location": "Dalkeith Corn", "Name": "Corn",
            "Delivery": "December 2026", "Delivery End": "December 2026",
            "Futures Month": "December 2026", "Basis": 1.00, "US Basis (USD/bu)": -0.20,
        }]).to_csv(previous, index=False)
        today = pd.DataFrame([{
            "Source": "AgriCharts", "Location": "Dalkeith Corn", "Name": "Corn",
            "Delivery": "December 2026", "Delivery End": "December 2026",
            "Futures Month": "December 2026", "Basis": 1.25, "US Basis (USD/bu)": -0.05,
        }])
        result = add_basis_change_column(today, previous)
        self.assertAlmostEqual(float(result.loc[0, "Basis Change"]), 0.25)
        self.assertAlmostEqual(float(result.loc[0, "US Basis Change"]), 0.15)


if __name__ == "__main__":
    unittest.main()
