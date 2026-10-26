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
    parse_wanna_make_it,
    parse_wanna_make_it_nearby_futures,
)
from cashgrainbids.classification import classify_bid
from cashgrainbids.config import AGRICHARTS_TARGETS
from cashgrainbids.fx_rates import add_us_basis_from_spot, add_wanna_make_it_nearby_basis
from basis_normalization import add_standardized_commercial_basis
from cashgrainbids.pricing_decisions import add_pricing_decision_columns
from cashgrainbids.fixed_report import _single_month_delivery_labels
from cashgrainbids.wmi_futures import verify_nearby_futures_price


class CashBidsRegressionTests(unittest.TestCase):
    def test_wmi_email_nearby_futures_values_are_parsed(self):
        text = "Nearby futures of corn trading at $4.52; soybeans at $12.35 and wheat is at $6.24 USD per bushel."
        self.assertEqual(parse_wanna_make_it_nearby_futures(text), {"Corn": 4.52, "Soybeans": 12.35, "SRW": 6.24})

    def test_wmi_futures_verification_accepts_unknown_delay(self):
        quotes = pd.DataFrame([
            {"Timestamp": "2026-10-22 09:53:00", "Contract": "SX26", "Price": 12.35},
            {"Timestamp": "2026-10-22 10:03:00", "Contract": "SF27", "Price": 12.44},
        ])
        result = verify_nearby_futures_price(
            12.35, pd.Timestamp("2026-10-22 10:03:00"), quotes
        )
        self.assertEqual(result["status"], "Verified")
        self.assertEqual(result["contract"], "SX26")
        self.assertEqual(result["delay_minutes"], 10)

    def test_wmi_futures_verification_flags_roll_ambiguity(self):
        quotes = pd.DataFrame([
            {"Timestamp": "2026-10-22 10:03:00", "Contract": "SX26", "Price": 12.35},
            {"Timestamp": "2026-10-22 09:53:00", "Contract": "SF27", "Price": 12.35},
        ])
        result = verify_nearby_futures_price(
            12.35, pd.Timestamp("2026-10-22 10:03:00"), quotes
        )
        self.assertEqual(result["status"], "Ambiguous contract/timing")
    def test_ngg_pricing_decision_layer_corn_and_soybeans(self):
        rows = [
            {"Source": "AgriCharts", "Location": "North Gower Corn", "Name": "Corn",
             "Delivery": "Dec 2026", "Delivery End": "Dec 2026", "Futures Month": "March 2027",
             "Futures Price": 5.00, "Basis": 1.00, "US Basis (USD/bu)": -0.10, "FX Rate": 0.72},
            {"Source": "AgriCharts", "Location": "Kars Corn", "Name": "Corn",
             "Delivery": "Dec 2026", "Delivery End": "Dec 2026", "Futures Month": "March 2027",
             "Futures Price": 5.00, "US Basis (USD/bu)": 0.10},
            {"Source": "AgriCharts", "Location": "Lansdowne Corn", "Name": "Corn",
             "Delivery": "Dec 2026", "Delivery End": "Dec 2026", "Futures Month": "March 2027",
             "Futures Price": 5.00, "US Basis (USD/bu)": 0.20},
            {"Source": "AgriCharts", "Location": "Vankleek Hill Corn", "Name": "Corn",
             "Delivery": "Dec 2026", "Delivery End": "Dec 2026", "Futures Month": "March 2027",
             "Futures Price": 5.00, "US Basis (USD/bu)": 0.15},
            {"Source": "AgriCharts", "Location": "North Gower Soybeans", "Name": "Soybeans",
             "Delivery": "Dec 2026", "Delivery End": "Dec 2026", "Futures Month": "January 2027",
             "Futures Price": 12.50, "Basis": 4.00, "US Basis (USD/bu)": -0.20, "FX Rate": 0.72},
            {"Source": "AgriCharts", "Location": "Kars Soybeans", "Name": "Soybeans",
             "Delivery": "Dec 2026", "Delivery End": "Dec 2026", "Futures Month": "January 2027",
             "Futures Price": 12.50, "US Basis (USD/bu)": -0.40},
            {"Source": "AgriCharts", "Location": "Lansdowne Soybeans", "Name": "Soybeans",
             "Delivery": "Dec 2026", "Delivery End": "Dec 2026", "Futures Month": "January 2027",
             "Futures Price": 12.50, "US Basis (USD/bu)": -0.30},
            {"Source": "AgriCharts", "Location": "Vankleek Hill Soybeans", "Name": "Soybeans",
             "Delivery": "Dec 2026", "Delivery End": "Dec 2026", "Futures Month": "January 2027",
             "Futures Price": 12.50, "US Basis (USD/bu)": -0.35},
        ]
        previous = pd.DataFrame([
            {"Source": "AgriCharts", "Location": "North Gower Corn", "Name": "Corn",
             "Delivery": "Dec 2026", "Delivery End": "Dec 2026", "Futures Month": "March 2027",
             "Basis": 1.10, "US Basis (USD/bu)": -0.20},
            {"Source": "AgriCharts", "Location": "North Gower Soybeans", "Name": "Soybeans",
             "Delivery": "Dec 2026", "Delivery End": "Dec 2026", "Futures Month": "January 2027",
             "Basis": 4.50, "US Basis (USD/bu)": -0.50},
        ])
        result = add_pricing_decision_columns(
            pd.DataFrame(rows), previous,
            ceilings={("Corn", "current"): 0.25, ("Soybeans", "current"): -0.20},
            premiums={"Corn": 0.05, "Soybeans": 0.05},
        )
        corn = result.iloc[0]
        soy = result.iloc[4]
        self.assertAlmostEqual(float(corn["FX Neutral CAD Basis"]), 1.6666667, places=5)
        self.assertAlmostEqual(float(corn["Competitor Benchmark US Basis"]), 0.15, places=5)
        self.assertAlmostEqual(float(corn["Competitive US Basis Target"]), 0.20, places=5)
        self.assertAlmostEqual(float(corn["Recommended Max CAD Basis"]), 2.2222222, places=5)
        self.assertAlmostEqual(float(soy["Competitor Benchmark US Basis"]), -0.35, places=5)
        self.assertAlmostEqual(float(soy["Competitive US Basis Target"]), -0.30, places=5)
        self.assertEqual(corn["Pricing Decision Status"], "Complete")
        self.assertEqual(soy["Pricing Decision Status"], "Complete")

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

    def test_basis_normalization_converts_to_majority_futures_month(self):
        frame = pd.DataFrame([
            {"Source": "AgriCharts", "Location": "North Gower Corn", "Name": "Corn", "Delivery": "Dec 2026", "Futures Month": "March 2027", "Futures Price": "5.00"},
            {"Source": "P&H email bids", "Location": "Picton", "Name": "Corn", "Delivery": "Dec 2026", "Futures Month": "December 2026", "Futures Price": "4.80", "US Basis (USD/bu)": 0.10},
            {"Source": "Greenfield", "Location": "Greenfield Johnstown Corn", "Name": "Corn", "Delivery": "Dec 2026", "Futures Month": "March 2027", "Futures Price": "5.00", "US Basis (USD/bu)": 0.12},
            {"Source": "Ingredion", "Location": "Ingredion Cardinal CEY Dent", "Name": "Corn", "Delivery": "Dec 2026", "Futures Month": "March 2027", "Futures Price": "5.00", "US Basis (USD/bu)": 0.14},
        ])
        result = add_standardized_commercial_basis(frame)
        self.assertEqual(result.loc[1, "Standard Futures Month"], "March 2027")
        self.assertAlmostEqual(float(result.loc[1, "Standardized US Basis (USD/bu)" ]), -0.10)

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

    def test_wanna_make_it_keeps_fob_farm_separate_from_delivered(self):
        frame = parse_wanna_make_it(
            "Corn\n"
            "Del Elevator\n$245.00 Harvest26\n"
            "FOB Farm\n$245.00 Harvest26\n$250.00 Dec26\n"
            "Del Johnstown\n$260.00 Harvest26\n"
            "Soybeans\nFOB Farm\n$593.00 Oct26\n"
        )
        self.assertEqual(len(frame), 4)
        self.assertEqual(frame["Bid Type"].tolist(), [
            "Delivered Elevator", "FOB Farm", "FOB Farm", "FOB Farm",
        ])
        self.assertEqual(frame.loc[2, "Delivery"], "Dec 2026")
        self.assertAlmostEqual(float(frame.loc[1, "MT Cash Price"]), 245.00)
        self.assertTrue(pd.isna(frame.loc[1, "Basis"]))
        self.assertTrue((frame["Location"] != "Wanna Make It Johnstown").all())

    def test_wanna_make_it_nearby_soybean_basis_uses_matching_futures(self):
        frame = pd.DataFrame([
            {"Source": "AgriCharts", "Name": "Soybeans", "Delivery": "Oct 2026",
             "Bid Type": "", "Futures Month": "November 2026", "Futures Price": "1256-4"},
            {"Source": "Wanna Make It email bids", "Name": "Soybeans", "Delivery": "Oct 2026",
             "Bid Type": "FOB Farm", "Futures Month": "", "Futures Price": "",
             "Bushel Cash Price": 593 / 36.7437},
        ])
        result = add_wanna_make_it_nearby_basis(frame, "2026-10-23")
        self.assertEqual(result.loc[1, "Futures Month"], "November 2026")
        self.assertAlmostEqual(float(result.loc[1, "Basis"]), (593 / 36.7437) - 12.5650, places=4)

    def test_wanna_make_it_nearby_corn_harvest_basis_uses_december_futures(self):
        frame = pd.DataFrame([
            {"Source": "AgriCharts", "Name": "Corn", "Delivery": "Oct 2026",
             "Bid Type": "", "Futures Month": "December 2026", "Futures Price": "452-2"},
            {"Source": "Wanna Make It email bids", "Name": "Corn", "Delivery": "Harvest 2026",
             "Bid Type": "FOB Farm", "Futures Month": "", "Futures Price": "",
             "Bushel Cash Price": 245 / 39.3683},
        ])
        result = add_wanna_make_it_nearby_basis(frame, "2026-10-23")
        self.assertEqual(result.loc[1, "Futures Month"], "December 2026")
        self.assertAlmostEqual(float(result.loc[1, "Basis"]), (245 / 39.3683) - 4.5225, places=4)

    def test_broadgrain_ocr_parser_keeps_multi_month_srw_rows(self):
        frame = parse_broadgrain_ocr(
            "Wheat - SRW\n"
            "Del - Johnstown July/Aug27 $ 1.87 7.1400 WN7 $ 9.01 $ 331.05\n"
            "Del - Picton July /Aug-27 $ 1.80 7.1400 WN7 $ 8.94 $ 328.48"
        )
        self.assertEqual(len(frame), 2)
        self.assertEqual(
            frame["Location"].tolist(),
            ["BroadGrain Johnstown", "BroadGrain Picton"],
        )
        self.assertTrue(frame["Name"].eq("SRW Wheat").all())

    def test_broadgrain_ocr_parser_handles_srw_ocr_punctuation(self):
        frame = parse_broadgrain_ocr(
            "Wheat - SRW\nMIN275FN/MAX2PPMVOM\n"
            "Del - Johnstown July/Aug27 $ 1.81 6.5300 WN7~ $ 8.34 $ 306.44\n"
            "Del - Picton July /Aug-27) $ 1.60 6.5300 WN7 $ 8.13 $ 298.72"
        )
        self.assertEqual(len(frame), 2)
        self.assertTrue(frame["Name"].eq("SRW Wheat").all())
        self.assertEqual(frame.loc[0, "Futures Month"], "July 2027")

    def test_report_splits_compact_broadgrain_month_range(self):
        self.assertEqual(
            _single_month_delivery_labels("July/Aug27"),
            ["Jul 2027", "Aug 2027"],
        )
        self.assertEqual(
            _single_month_delivery_labels("July /Aug-27"),
            ["Jul 2027", "Aug 2027"],
        )
        self.assertEqual(
            _single_month_delivery_labels("Dec 2026-Jan 2027"),
            ["Dec 2026", "Jan 2027"],
        )

    def test_bunge_parser_accepts_leading_decimal_basis(self):
        frame = parse_bunge("Corn MTL:\nFeb-27: +.45 CH27\n")
        self.assertEqual(len(frame), 1)
        self.assertAlmostEqual(float(frame.loc[0, "US Basis (USD/bu)"]), 0.45)

    def test_bunge_parser_reads_corn_from_html_body(self):
        frame = parse_bunge(
            "<p><b>Corn MTL:</b></p>"
            "<li>Jan-27: +0.40 CH27</li>"
            "<li>Feb-27: +.45CH27</li>"
        )
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["Location"].unique().tolist(), ["Bunge MTL"])
        self.assertEqual(frame["Name"].unique().tolist(), ["Corn"])
        self.assertAlmostEqual(float(frame.loc[1, "US Basis (USD/bu)"]), 0.45)

    def test_bunge_parser_keeps_html_date_range_row(self):
        frame = parse_bunge(
            "<p><b>Soybeans BCC:</b></p>"
            "<li>Nov-26 <u>21-30<sup>th</sup></u>: -0.10 SX26</li>"
        )
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.loc[0, "Delivery"], "Nov 2026")
        self.assertAlmostEqual(float(frame.loc[0, "US Basis (USD/bu)"]), -0.10)

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
            SenderName="George McAllister",
            Body="BroadGrain bid sheet summary", HTMLBody="",
        )
        dylan = SimpleNamespace(
            Subject="Bid Sheet", SenderEmailAddress="dylan.stewart@broadgrain.com",
            SenderName="Dylan Stewart",
            Body="BroadGrain Commodities", HTMLBody="",
        )
        self.assertFalse(_matches_email_source(summary, "broadgrain"))
        self.assertTrue(_matches_email_source(dylan, "broadgrain"))

    def test_broadgrain_forwarded_copy_is_excluded(self):
        forwarded = SimpleNamespace(
            Subject="FW: Bid Sheet Oct 22",
            SenderEmailAddress="george@example.com",
            SenderName="George McAllister",
            Body="Begin forwarded message Dylan Stewart BroadGrain Commodities",
            HTMLBody="Dylan Stewart dylan.stewart@broadgrain.com BroadGrain",
        )
        self.assertFalse(_matches_email_source(forwarded, "broadgrain"))

    def test_email_quote_date_uses_original_received_date(self):
        from email_bid_sources import _email_quote_date

        item = SimpleNamespace(
            ReceivedTime="2026-10-09 11:33:15",
            SentOn="2026-10-22 10:00:00",
        )
        self.assertEqual(_email_quote_date(item), "2026-10-09")

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
        self.assertAlmostEqual(float(result.loc[0, "US Basis (USD/bu)"]), -1.875, places=5)
        self.assertEqual(result.loc[0, "FX Type"], "Forward Futures")

    def test_cme_cadusd_quote_parser_uses_actual_contract_price(self):
        from cashgrainbids.fx_rates import parse_cme_cadusd_rows

        result = parse_cme_cadusd_rows(
            ["DEC 2026 6CZ6 opt 0.7107 +0.0021 0.7086"],
            "2026-10-22T16:00:00-04:00",
        )
        self.assertEqual(result.loc[0, "Futures Month"], "December 2026")
        self.assertAlmostEqual(float(result.loc[0, "USD/CAD"]), 0.7107)

    def test_farmbucks_cadusd_fallback_parser_uses_contract_chain(self):
        from cashgrainbids.fx_rates import parse_farmbucks_cadusd_text

        result = parse_farmbucks_cadusd_text(
            "6CZ26 Dec 2026 $0.7137 +0.0002 6CK27 May 2027 $0.7187 +0.0003",
            "2026-10-22T16:00:00-04:00",
        )
        self.assertEqual(result["Futures Month"].tolist(), ["December 2026", "May 2027"])
        self.assertAlmostEqual(float(result.loc[1, "USD/CAD"]), 0.7187)

    def test_barchart_cadusd_parser_reads_contract_last_price(self):
        from cashgrainbids.fx_rates import parse_barchart_cadusd_text

        result = parse_barchart_cadusd_text(
            "Canadian Dollar D6Z26 Quote Overview Last Price | 0.71370 "
            "Canadian Dollar D6K27 Quote Overview Last Price | 0.71870",
            "2026-10-22T16:00:00-04:00",
        )
        self.assertEqual(result["Futures Month"].tolist(), ["December 2026", "May 2027"])
        self.assertAlmostEqual(float(result.loc[0, "USD/CAD"]), 0.7137)

    def test_tradingview_cadusd_parser_reads_full_contract_chain(self):
        from cashgrainbids.fx_rates import parse_tradingview_cadusd_text

        result = parse_tradingview_cadusd_text(
            "6CX2026 Canadian Dollar Futures (Nov 2026) 0.71260 6CZ2026 Canadian Dollar Futures (Dec 2026) 0.71360 6CH2027 Canadian Dollar Futures (Mar 2027) 0.71660",
            "2026-10-22T16:00:00-04:00",
        )
        self.assertEqual(result["Futures Month"].tolist(), ["November 2026", "December 2026", "March 2027"])
        self.assertAlmostEqual(float(result.loc[2, "USD/CAD"]), 0.7166)

    def test_manual_quote_date_registry_fills_only_blank_dates(self):
        from cashgrainbids.manual_dates import apply_manual_quote_dates

        registry = Path(tempfile.mkdtemp()) / "manual_quote_dates.json"
        registry.write_text(
            '{"entries":[{"source":"Ceresco bids","location":"Montreal*","quote_date":"2026-10-20"}]}',
            encoding="utf-8",
        )
        frame = pd.DataFrame([
            {"Source": "Ceresco bids", "Location": "Montreal, QC", "Quote Date": ""},
            {"Source": "Ceresco bids", "Location": "Montreal, QC", "Quote Date": "2026-10-21"},
        ])
        result = apply_manual_quote_dates(frame, registry)
        self.assertEqual(result.loc[0, "Quote Date"], "2026-10-20")
        self.assertEqual(result.loc[1, "Quote Date"], "2026-10-21")

    def test_deferred_fx_does_not_fall_back_to_spot(self):
        cache = Path(tempfile.mkdtemp())
        (cache / "FX_Forward_Rates.csv").write_text(
            "Futures Month,USD/CAD,Quote Date\nMarch 2027,0.7500,2026-10-22\n",
            encoding="utf-8",
        )
        frame = pd.DataFrame([{
            "Source": "BroadGrain email bids", "Name": "Corn",
            "Futures Month": "December 2026", "Bushel Cash Price": 6.00,
            "Futures Price": 5.00,
        }])
        with patch("cashgrainbids.fx_rates.get_usdcad_spot", return_value=(1.40, "2026-10-22")):
            result = add_us_basis_from_spot(frame, "2026-10-22", cache)
        self.assertTrue(pd.isna(result.loc[0, "US Basis (USD/bu)"]))
        self.assertTrue(pd.isna(result.loc[0, "FX Rate"]))

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
