"""Pure calculation tests. They run without Django:  python -m unittest billing.test_calc"""
import unittest
from decimal import Decimal as Dc

from billing.calc import (
    D, amount_in_words, compute_invoice, compute_line, compute_line_from_amount, is_valid_gstin, rate_summary, split_gst,
)


class LineTests(unittest.TestCase):
    def test_exclusive_intra(self):
        l = compute_line("2", "1000", "0", "18", inclusive=False, intra=True)
        self.assertEqual(l["taxable"], Dc("2000.00"))
        self.assertEqual(l["cgst"], Dc("180.00"))
        self.assertEqual(l["sgst"], Dc("180.00"))
        self.assertEqual(l["igst"], Dc("0.00"))
        self.assertEqual(l["total"], Dc("2360.00"))

    def test_exclusive_inter(self):
        l = compute_line("1", "1000", "0", "18", inclusive=False, intra=False)
        self.assertEqual(l["igst"], Dc("180.00"))
        self.assertEqual(l["cgst"], Dc("0.00"))
        self.assertEqual(l["total"], Dc("1180.00"))

    def test_inclusive_total_stays_exact(self):
        l = compute_line("1", "118", "0", "18", inclusive=True, intra=True)
        self.assertEqual(l["total"], Dc("118.00"))
        self.assertEqual(l["taxable"], Dc("100.00"))
        self.assertEqual(l["gst"], Dc("18.00"))
        self.assertEqual(l["taxable"] + l["gst"], l["total"])

    def test_inclusive_awkward_amount_still_adds_up(self):
        l = compute_line("3", "99.99", "0", "5", inclusive=True, intra=True)
        self.assertEqual(l["taxable"] + l["gst"], l["total"])
        self.assertEqual(l["cgst"] + l["sgst"], l["gst"])

    def test_discount(self):
        l = compute_line("10", "100", "10", "18", inclusive=False, intra=False)
        self.assertEqual(l["taxable"], Dc("900.00"))
        self.assertEqual(l["igst"], Dc("162.00"))

    def test_odd_gst_split_cgst_plus_sgst_equals_gst(self):
        l = compute_line("1", "0.30", "0", "5", inclusive=False, intra=True)  # gst = 0.015 -> 0.02
        self.assertEqual(l["cgst"] + l["sgst"], l["gst"])

    def test_zero_gst(self):
        l = compute_line("5", "20", "0", "0", inclusive=False, intra=True)
        self.assertEqual(l["gst"], Dc("0.00"))
        self.assertEqual(l["total"], Dc("100.00"))


class InvoiceTests(unittest.TestCase):
    def test_totals_and_round_off(self):
        items = [
            {"qty": "1", "rate": "100.50", "discount_pct": "0", "gst_rate": "18"},
            {"qty": "2", "rate": "250", "discount_pct": "0", "gst_rate": "5"},
        ]
        inv = compute_invoice(items, inclusive=False, intra=True)
        self.assertEqual(inv["taxable"], Dc("600.50"))
        # gst: 18.09 + 25.00 = 43.09 ; exact total 643.59 -> 644
        self.assertEqual(inv["gst_total"], Dc("43.09"))
        self.assertEqual(inv["total"], Dc("644"))
        self.assertEqual(inv["round_off"], Dc("0.41"))
        self.assertEqual(inv["taxable"] + inv["gst_total"] + inv["round_off"], inv["total"])
        self.assertEqual(inv["cgst"] + inv["sgst"], inv["gst_total"])

    def test_blank_rows_are_zero(self):
        inv = compute_invoice([{}, {"qty": "", "rate": ""}], inclusive=False, intra=True)
        self.assertEqual(inv["total"], Dc("0"))
        self.assertEqual(len(inv["lines"]), 2)

    def test_mode_switch_same_rate_different_total(self):
        item = [{"qty": "1", "rate": "1000", "gst_rate": "18"}]
        excl = compute_invoice(item, inclusive=False, intra=True)
        incl = compute_invoice(item, inclusive=True, intra=True)
        self.assertEqual(excl["total"], Dc("1180"))
        self.assertEqual(incl["total"], Dc("1000"))


class AmountModeTests(unittest.TestCase):
    def test_amount_gives_taxable_gst_and_rate(self):
        l = compute_line_from_amount("1", "1180", "18", intra=True)
        self.assertEqual(l["total"], Dc("1180.00"))
        self.assertEqual(l["taxable"], Dc("1000.00"))
        self.assertEqual(l["gst"], Dc("180.00"))
        self.assertEqual((l["cgst"], l["sgst"]), (Dc("90.00"), Dc("90.00")))
        self.assertEqual(l["rate"], Dc("1000.0000"))

    def test_rate_is_taxable_divided_by_qty(self):
        l = compute_line_from_amount("4", "1180", "18", intra=False)
        self.assertEqual(l["rate"], Dc("250.0000"))
        self.assertEqual(l["igst"], Dc("180.00"))

    def test_awkward_amount_still_adds_up(self):
        l = compute_line_from_amount("3", "100", "18", intra=True)
        self.assertEqual(l["total"], Dc("100.00"))
        self.assertEqual(l["taxable"], Dc("84.75"))
        self.assertEqual(l["gst"], Dc("15.25"))
        self.assertEqual(l["taxable"] + l["gst"], l["total"])
        self.assertEqual(l["cgst"] + l["sgst"], l["gst"])
        self.assertEqual(l["rate"], Dc("28.2500"))

    def test_blank_or_zero_qty_counts_as_one(self):
        self.assertEqual(compute_line_from_amount("", "118", "18", True)["rate"], Dc("100.0000"))
        self.assertEqual(compute_line_from_amount("0", "118", "18", True)["rate"], Dc("100.0000"))

    def test_blank_amount_is_zero(self):
        l = compute_line_from_amount("2", "", "18", True)
        self.assertEqual((l["total"], l["taxable"], l["gst"], l["rate"]), (Dc("0.00"), Dc("0.00"), Dc("0.00"), Dc("0.0000")))

    def test_zero_gst(self):
        l = compute_line_from_amount("2", "500", "0", True)
        self.assertEqual((l["taxable"], l["gst"], l["rate"]), (Dc("500.00"), Dc("0.00"), Dc("250.0000")))

    def test_invoice_total_is_sum_of_amounts(self):
        items = [
            {"qty": "1", "amount": "1180", "gst_rate": "18"},
            {"qty": "2", "amount": "525", "gst_rate": "5"},
            {},
        ]
        inv = compute_invoice(items, inclusive=False, intra=True, amount_mode=True)
        self.assertEqual(inv["total"], Dc("1705"))
        self.assertEqual(inv["round_off"], Dc("0.00"))
        self.assertEqual(inv["taxable"], Dc("1000.00") + Dc("500.00"))
        self.assertEqual(inv["gst_total"], Dc("180.00") + Dc("25.00"))
        self.assertEqual(len(inv["lines"]), 3)
        self.assertEqual(inv["cgst"] + inv["sgst"], inv["gst_total"])

    def test_paise_amounts_are_rounded_off_to_rupee(self):
        inv = compute_invoice([{"qty": "1", "amount": "100.40", "gst_rate": "18"}], False, True, amount_mode=True)
        self.assertEqual(inv["total"], Dc("100"))
        self.assertEqual(inv["round_off"], Dc("-0.40"))


class HelperTests(unittest.TestCase):
    def test_D_cleans_input(self):
        self.assertEqual(D("1,234.50"), Dc("1234.50"))
        self.assertEqual(D("₹ 99"), Dc("99"))
        self.assertEqual(D("18%"), Dc("18"))
        self.assertEqual(D("abc"), Dc("0"))
        self.assertEqual(D(""), Dc("0"))
        self.assertEqual(D(None), Dc("0"))
        self.assertEqual(D("NaN"), Dc("0"))
        self.assertEqual(D("Infinity"), Dc("0"))

    def test_words(self):
        self.assertEqual(amount_in_words(0), "Rupees Zero Only")
        self.assertEqual(amount_in_words(1180), "Rupees One Thousand One Hundred Eighty Only")
        self.assertEqual(amount_in_words(125000), "Rupees One Lakh Twenty Five Thousand Only")
        self.assertEqual(amount_in_words(12345678), "Rupees One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight Only")
        self.assertEqual(amount_in_words("10.50"), "Rupees Ten and Fifty Paise Only")

    def test_gstin_checksum(self):
        self.assertTrue(is_valid_gstin("27AAPFU0939F1ZV"))
        self.assertFalse(is_valid_gstin("27AAPFU0939F1ZA"))  # wrong check digit
        self.assertFalse(is_valid_gstin("27AAPFU0939F1Z"))  # too short
        self.assertFalse(is_valid_gstin(""))


class RateSummaryTests(unittest.TestCase):
    ITEMS = [
        {"qty": "1", "rate": "1000", "gst_rate": "18"},
        {"qty": "1", "rate": "500", "gst_rate": "12"},
        {"qty": "3", "rate": "33.33", "gst_rate": "18"},
        {},  # blank line
    ]

    def test_groups_by_rate_and_matches_the_invoice_totals(self):
        for intra in (True, False):
            for inclusive in (False, True):
                r = compute_invoice(self.ITEMS, inclusive, intra)
                s = r["summary"]
                self.assertEqual([x["rate"] for x in s], [Dc("12"), Dc("18")])
                for k in ("taxable", "cgst", "sgst", "igst"):
                    self.assertEqual(sum(x[k] for x in s), r[k], (k, intra, inclusive))
                self.assertEqual(sum(x["gst"] for x in s), r["gst_total"])
                for x in s:
                    self.assertEqual(x["cgst"] + x["sgst"] + x["igst"], x["gst"])

    def test_example_from_the_docs(self):
        s = compute_invoice(self.ITEMS[:2], False, True)["summary"]
        self.assertEqual((s[0]["taxable"], s[0]["cgst"], s[0]["sgst"]), (Dc("500.00"), Dc("30.00"), Dc("30.00")))
        self.assertEqual((s[1]["taxable"], s[1]["cgst"], s[1]["sgst"]), (Dc("1000.00"), Dc("90.00"), Dc("90.00")))

    def test_inter_state_uses_igst_only(self):
        s = compute_invoice(self.ITEMS[:2], False, False)["summary"]
        self.assertEqual([(x["cgst"], x["sgst"], x["igst"]) for x in s], [(0, 0, Dc("60.00")), (0, 0, Dc("180.00"))])

    def test_same_rate_written_differently_is_one_group(self):
        r = compute_invoice([{"qty": "1", "rate": "100", "gst_rate": "18"}, {"qty": "1", "rate": "100", "gst_rate": "18.0"}], False, True)
        self.assertEqual(len(r["summary"]), 1)

    def test_odd_paise_split_never_loses_a_paisa(self):
        self.assertEqual(split_gst(Dc("0.05"), True), (Dc("0.03"), Dc("0.02"), Dc("0.00")))  # 0.025 rounds up for CGST
        c, sg, i = split_gst(Dc("0.03"), True)
        self.assertEqual(c + sg, Dc("0.03"))

    def test_summary_rebuilt_from_stored_lines_equals_the_live_one(self):
        r = compute_invoice(self.ITEMS, False, True)
        stored = []
        for it, line in zip(self.ITEMS, r["lines"]):
            c, sg, i = split_gst(line["gst"], True)
            stored.append((it.get("gst_rate"), {"taxable": line["taxable"], "gst": line["gst"], "cgst": c, "sgst": sg, "igst": i}))
        self.assertEqual(rate_summary(stored), r["summary"])

    def test_all_blank_gives_empty_summary(self):
        self.assertEqual(compute_invoice([{}, {}], False, True)["summary"], [])


if __name__ == "__main__":
    unittest.main()
