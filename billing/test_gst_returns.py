import datetime
import unittest
from decimal import Decimal as D

from billing.gst_returns import b2b_rows, b2c_rows, hsn_rows, series_summary


def doc(no, t="TAX", status="ACTIVE"):
    return {"invoice_no": no, "doc_type": t, "status": status}


def inv(i, no, gstin="", t="TAX", intra=True, pos="West Bengal"):
    return {"id": i, "invoice_no": no, "date": datetime.date(2026, 10, i), "doc_type": t, "party_name": "P", "party_gstin": gstin,
            "place_of_supply": pos, "is_intra_state": intra, "total": D("118.00")}


def line(i, rate, taxable, gst, hsn="8471", qty="1", unit="Nos"):
    return {"invoice_id": i, "gst_rate": D(rate), "taxable": D(taxable), "gst_amount": D(gst), "hsn": hsn, "qty": D(qty), "unit": unit}


class SeriesTests(unittest.TestCase):
    def test_gap_and_cancelled(self):
        rows = series_summary([doc("INV/26-27/0001"), doc("INV/26-27/0002", status="CANCELLED"), doc("INV/26-27/0005"),
                               doc("CN/26-27/0001", "CN"), doc("EST/26-27/0001", "EST")])
        tax = rows[0]
        self.assertEqual((tax["label"], tax["first"], tax["last"], tax["count"]), ("Tax invoice", "INV/26-27/0001", "INV/26-27/0005", 3))
        self.assertEqual(tax["missing"], ["INV/26-27/0003", "INV/26-27/0004"])
        self.assertEqual(tax["cancelled"], ["INV/26-27/0002"])
        self.assertEqual([r["doc_type"] for r in rows], ["TAX", "CN", "EST"])
        self.assertEqual(rows[1]["missing"], [])

    def test_financial_years_are_separate_series(self):
        rows = series_summary([doc("INV/25-26/0009"), doc("INV/26-27/0001")])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["missing"] == [] for r in rows))

    def test_numbers_without_digits_are_ignored(self):
        self.assertEqual(series_summary([doc("MANUAL"), doc(None)]), [])


class ReturnTests(unittest.TestCase):
    def setUp(self):
        self.invs = [inv(1, "INV/1", gstin="19AAAAA0000A1Z5"), inv(2, "INV/2"), inv(3, "CN/1", t="CN"),
                     inv(4, "INV/4", gstin="27AAAAA0000A1Z5", intra=False, pos="Maharashtra"), inv(5, "BOS/1", t="SUPPLY")]
        self.items = [line(1, "18", "100.00", "18.00"), line(1, "12", "50.00", "6.00"), line(2, "18", "200.00", "36.00"),
                      line(3, "18", "100.00", "18.00"), line(4, "18", "10.00", "1.80"), line(5, "0", "40.00", "0.00", hsn="")]

    def test_b2b_is_registered_only_and_rate_wise(self):
        rows = b2b_rows(self.invs, self.items)
        self.assertEqual([(r["invoice_no"], r["rate"]) for r in rows], [("INV/1", D("12")), ("INV/1", D("18")), ("INV/4", D("18"))])
        r = rows[1]
        self.assertEqual((r["taxable"], r["cgst"], r["sgst"], r["igst"]), (D("100.00"), D("9.00"), D("9.00"), D("0.00")))
        self.assertEqual(rows[2]["igst"], D("1.80"))
        self.assertEqual(rows[2]["place_of_supply"], "Maharashtra")

    def test_b2c_subtracts_credit_notes(self):
        rows = b2c_rows(self.invs, self.items)
        self.assertEqual(len(rows), 1)
        r = rows[0]  # INV/2 (200) minus CN/1 (100); the CN has no GSTIN so it is B2C
        self.assertEqual((r["taxable"], r["cgst"], r["sgst"]), (D("100.00"), D("9.00"), D("9.00")))

    def test_odd_paisa_is_split_equally(self):
        rows = b2b_rows([inv(1, "INV/1", gstin="X")], [line(1, "18", "10.00", "1.80"), line(1, "18", "10.00", "1.80")])
        self.assertEqual((rows[0]["cgst"], rows[0]["sgst"]), (D("1.80"), D("1.80")))

    def test_hsn_summary(self):
        rows = hsn_rows(self.invs, self.items)
        by = {(r["hsn"], r["rate"]): r for r in rows}
        self.assertEqual(by[("8471", D("18"))]["taxable"], D("210.00"))  # 100 + 200 - 100 + 10
        self.assertEqual(by[("8471", D("18"))]["qty"], D("2"))
        self.assertIn(("(blank)", D("0")), by)

    def test_estimates_are_left_out(self):
        invs = self.invs + [inv(6, "EST/1", t="EST")]
        rows = hsn_rows(invs, self.items + [line(6, "18", "999.00", "0.00")])
        self.assertEqual(sum(r["taxable"] for r in rows), D("300.00"))


if __name__ == "__main__":
    unittest.main()
