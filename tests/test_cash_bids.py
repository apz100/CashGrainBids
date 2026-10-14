import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from cash_bids_via_playwright_UPDATED import (
    add_basis_change_column,
    filter_eastern_ontario_locations,
    normalize_agricharts_basis,
)
from email_bid_sources import _matches_email_source, parse_bunge


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
        self.assertAlmostEqual(float(frame.loc[0, "Basis"]), -0.10)
        self.assertEqual(frame.loc[2, "Futures Month"], "March 2027")


if __name__ == "__main__":
    unittest.main()
