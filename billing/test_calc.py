"""Pure calculation tests. They run without Django:  python -m unittest billing.test_calc"""
import unittest
from decimal import Decimal as Dc

from billing.calc import D, amount_in_words, compute_invoice, compute_line, compute_line_from_amount, is_valid_gstin


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


if __name__ == "__main__":
    unittest.main()
