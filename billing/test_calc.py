"""Pure calculation tests. Django ke bina bhi chalte hain:  python -m unittest billing.test_calc"""
import unittest
from decimal import Decimal as Dc

from billing.calc import D, amount_in_words, compute_invoice, compute_line, is_valid_gstin


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
        self.assertFalse(is_valid_gstin("27AAPFU0939F1ZA"))  # galat check digit
        self.assertFalse(is_valid_gstin("27AAPFU0939F1Z"))  # chhota
        self.assertFalse(is_valid_gstin(""))


if __name__ == "__main__":
    unittest.main()
