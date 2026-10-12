"""Tests of the dashboard numbers (no Django needed): python -m unittest billing.test_reports"""
import datetime
import unittest
from decimal import Decimal as D

from .reports import build_report, fy_label, fy_months, fy_start_year, inr


def inv(date, party, taxable, cgst="0", sgst="0", igst="0", round_off="0", total=None, intra=None, gstin="", doc_type="TAX"):
    taxable, cgst, sgst, igst, round_off = (D(x) for x in (taxable, cgst, sgst, igst, round_off))
    return {
        "date": date, "party_name": party, "party_gstin": gstin, "doc_type": doc_type, "is_intra_state": (not igst) if intra is None else intra,
        "taxable_value": taxable, "cgst": cgst, "sgst": sgst, "igst": igst, "round_off": round_off,
        "total": D(total) if total is not None else taxable + cgst + sgst + igst + round_off,
    }


class FinancialYearTests(unittest.TestCase):
    def test_year_runs_april_to_march(self):
        self.assertEqual(fy_start_year(datetime.date(2027, 3, 31)), 2026)
        self.assertEqual(fy_start_year(datetime.date(2027, 4, 1)), 2027)
        self.assertEqual(fy_label(2026), "2026-27")
        self.assertEqual(fy_label(2099), "2099-00")
        months = fy_months(2026)
        self.assertEqual((months[0], months[8], months[9], months[11]), ((2026, 4), (2026, 12), (2027, 1), (2027, 3)))


class ReportTests(unittest.TestCase):
    TODAY = datetime.date(2026, 10, 12)

    def report(self, invoices, items=()):
        return build_report(invoices, items, 2026, self.TODAY)

    def test_bills_are_grouped_by_invoice_month(self):
        r = self.report([
            inv(datetime.date(2026, 4, 1), "A", "1000", "90", "90"),
            inv(datetime.date(2026, 4, 30), "A", "500", "45", "45"),
            inv(datetime.date(2027, 3, 31), "B", "200", igst="36"),
        ])
        apr, mar = r["months"][0], r["months"][-1]
        self.assertEqual((apr["bills"], apr["taxable"], apr["cgst"], apr["sgst"], apr["gst"], apr["total"]),
                         (2, D("1500"), D("135"), D("135"), D("270"), D("1770")))
        self.assertEqual((mar["bills"], mar["igst"], mar["gst"], mar["total"]), (1, D("36"), D("36"), D("236")))

    def test_totals_equal_the_sum_of_months(self):
        r = self.report([inv(datetime.date(2026, m, 5), "A", "100", "9", "9", round_off="0.40") for m in (4, 5, 9, 12)])
        t = r["totals"]
        self.assertEqual(t["bills"], 4)
        for k in ("taxable", "cgst", "sgst", "igst", "gst", "round_off", "total"):
            self.assertEqual(t[k], sum(m[k] for m in r["months"]), k)
        self.assertEqual(t["taxable"] + t["gst"] + t["round_off"], t["total"])

    def test_bills_outside_the_year_are_ignored(self):
        r = self.report([inv(datetime.date(2026, 3, 31), "A", "100"), inv(datetime.date(2027, 4, 1), "A", "100")])
        self.assertEqual(r["totals"]["bills"], 0)
        self.assertEqual((r["average_bill"], r["best_month"], r["parties"]), (D("0"), "", []))

    def test_future_months_are_marked(self):
        r = self.report([])
        flags = [m["is_future"] for m in r["months"]]
        self.assertEqual(flags, [False] * 7 + [True] * 5)  # Apr..Oct are not in the future on 12-Oct-2026

    def test_bar_heights_are_relative_to_the_best_month(self):
        r = self.report([inv(datetime.date(2026, 4, 2), "A", "1000"), inv(datetime.date(2026, 5, 2), "A", "250")])
        self.assertEqual([round(m["bar_pct"]) for m in r["months"][:3]], [100, 25, 0])
        self.assertEqual(r["best_month"], "Apr 2026")

    def test_top_parties_merge_spelling_case_and_are_sorted(self):
        rows = [inv(datetime.date(2026, 5, 1), "Alpha Traders", "100"), inv(datetime.date(2026, 6, 1), " alpha traders ", "100"),
                inv(datetime.date(2026, 6, 2), "Beta", "300")]
        r = self.report(rows + [inv(datetime.date(2026, 7, i + 1), f"P{i}", "1") for i in range(6)])
        names = [p["name"] for p in r["parties"]]
        self.assertEqual(len(names), 5)
        self.assertEqual(names[:2], ["Beta", "Alpha Traders"])
        self.assertEqual(r["parties"][1]["bills"], 2)
        self.assertAlmostEqual(r["parties"][0]["share"], 300 / 506 * 100, places=6)

    def test_rate_wise_split(self):
        items = [{"gst_rate": D("18"), "taxable": D("100"), "gst_amount": D("18")},
                 {"gst_rate": D("5"), "taxable": D("200"), "gst_amount": D("10")},
                 {"gst_rate": D("18"), "taxable": D("50"), "gst_amount": D("9")}]
        r = self.report([], items)
        self.assertEqual([(x["rate"], x["taxable"], x["gst"]) for x in r["rates"]],
                         [(D("5"), D("200"), D("10")), (D("18"), D("150"), D("27"))])

    def test_same_state_and_other_state_split_uses_the_bill_flag(self):
        r = self.report([inv(datetime.date(2026, 5, 1), "A", "100", "9", "9"),
                         inv(datetime.date(2026, 5, 2), "B", "100", igst="18"),
                         inv(datetime.date(2026, 5, 3), "C", "100", intra=False)])  # a zero-GST bill to another state
        self.assertEqual((r["intra"]["bills"], r["inter"]["bills"], r["inter"]["taxable"]), (1, 2, D("200")))

    def test_average_bill(self):
        r = self.report([inv(datetime.date(2026, 5, 1), "A", "100"), inv(datetime.date(2026, 5, 2), "A", "201")])
        self.assertEqual(r["average_bill"], D("150.50"))

    def test_registered_vs_unregistered_and_by_type(self):
        r = self.report([
            inv(datetime.date(2026, 5, 1), "A", "100", "9", "9", gstin="19AAAAA0000A1Z5"),
            inv(datetime.date(2026, 5, 2), "B", "200", "18", "18"),                        # no GSTIN: B2C
            inv(datetime.date(2026, 5, 3), "C", "50", doc_type="SUPPLY"),                  # bill of supply, no GST
        ])
        self.assertEqual((r["registered"]["bills"], r["registered"]["taxable"]), (1, D("100")))
        self.assertEqual((r["unregistered"]["bills"], r["unregistered"]["taxable"], r["unregistered"]["total"]), (2, D("250"), D("286")))
        self.assertEqual((r["by_type"]["TAX"]["bills"], r["by_type"]["SUPPLY"]["bills"], r["by_type"]["SUPPLY"]["total"]), (2, 1, D("50")))
        self.assertEqual(r["totals"]["bills"], 3)  # all of them count as sales


class IndianGroupingTests(unittest.TestCase):
    def test_grouping(self):
        self.assertEqual(inr(0), "0.00")
        self.assertEqual(inr("999.5"), "999.50")
        self.assertEqual(inr(1000), "1,000.00")
        self.assertEqual(inr(123456), "1,23,456.00")
        self.assertEqual(inr(D("12345678.9")), "1,23,45,678.90")
        self.assertEqual(inr(D("-100000")), "-1,00,000.00")
        self.assertEqual(inr(None), "0.00")


if __name__ == "__main__":
    unittest.main()
