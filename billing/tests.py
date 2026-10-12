import datetime
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Firm, Invoice, Party


def payload(**over):
    base = {
        "invoice_no": "T-1", "date": "2026-10-12", "price_mode": "EXCL",
        "party_name": "Alpha Traders", "party_address": "Kolkata", "party_gstin": "",
        "party_state": "West Bengal", "party_phone": "", "party_email": "", "place_of_supply": "West Bengal", "notes": "",
        "items": [
            {"description": "Item", "hsn": "", "qty": "2", "unit": "Nos", "rate": "1000",
             "discount_pct": "", "gst_rate": "18"},
        ],
    }
    base.update(over)
    return base


class BillingViewTests(TestCase):
    def setUp(self):
        Firm.objects.create(name="My Firm", state="West Bengal", invoice_prefix="INV")
        get_user_model().objects.create_user("u", password="p")
        self.client.login(username="u", password="p")

    def save(self, data, url=None):
        return self.client.post(url or reverse("invoice_save"), json.dumps(data), content_type="application/json")

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("invoice_new")).status_code, 302)

    def test_pages_render(self):
        self.assertEqual(self.client.get(reverse("invoice_new")).status_code, 200)
        self.assertEqual(self.client.get(reverse("invoice_list")).status_code, 200)
        r = self.save(payload())
        inv_id = r.json()["id"]
        self.assertEqual(self.client.get(reverse("invoice_print", args=[inv_id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("invoice_edit", args=[inv_id])).status_code, 200)

    def test_save_intra_state(self):
        r = self.save(payload())
        self.assertEqual(r.status_code, 200, r.content)
        inv = Invoice.objects.get(invoice_no="T-1")
        self.assertEqual((inv.taxable_value, inv.cgst, inv.sgst, inv.igst, inv.total), (2000, 180, 180, 0, 2360))
        self.assertTrue(inv.is_intra_state)
        self.assertEqual(inv.items.count(), 1)
        self.assertTrue(Party.objects.filter(name="Alpha Traders").exists())  # a new party is saved automatically

    def test_save_inter_state_uses_igst(self):
        self.save(payload(party_state="Maharashtra", place_of_supply="Maharashtra"))
        inv = Invoice.objects.get(invoice_no="T-1")
        self.assertEqual((inv.cgst, inv.sgst, inv.igst), (0, 0, 360))

    def test_inclusive_mode(self):
        self.save(payload(price_mode="INCL"))
        inv = Invoice.objects.get(invoice_no="T-1")
        self.assertEqual(inv.total, 2000)
        self.assertEqual(inv.taxable_value + inv.gst_total + inv.round_off, inv.total)

    def test_duplicate_invoice_no_rejected(self):
        self.save(payload())
        r = self.save(payload())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_bad_rows_rejected(self):
        bad = payload(items=[{"description": "X", "qty": "0", "rate": "10", "gst_rate": "18"}])
        self.assertEqual(self.save(bad).status_code, 400)
        no_rate = payload(items=[{"description": "X", "qty": "1", "rate": "", "gst_rate": "18"}])
        self.assertEqual(self.save(no_rate).status_code, 400)
        bad_gst = payload(items=[{"description": "X", "qty": "1", "rate": "10", "gst_rate": "17"}])
        self.assertEqual(self.save(bad_gst).status_code, 400)
        self.assertEqual(self.save(payload(items=[])).status_code, 400)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_blank_rows_are_ignored(self):
        items = payload()["items"] + [{"description": "", "qty": "", "rate": "", "gst_rate": "18"}]
        self.assertEqual(self.save(payload(items=items)).status_code, 200)
        self.assertEqual(Invoice.objects.get().items.count(), 1)

    def test_update_replaces_items(self):
        inv_id = self.save(payload()).json()["id"]
        new_items = [{"description": "Other", "qty": "1", "rate": "500", "gst_rate": "5"}]
        r = self.save(payload(items=new_items, invoice_no="T-1-EDIT"), reverse("invoice_update", args=[inv_id]))
        self.assertEqual(r.status_code, 200, r.content)
        inv = Invoice.objects.get(pk=inv_id)
        self.assertEqual(inv.invoice_no, "T-1-EDIT")
        self.assertEqual([i.description for i in inv.items.all()], ["Other"])
        self.assertEqual(inv.total, 525)

    def test_live_calc_endpoint(self):
        body = {"price_mode": "EXCL", "place_of_supply": "West Bengal",
                "items": [{"qty": "1", "rate": "100", "gst_rate": "18"}, {}]}
        r = self.client.post(reverse("calc_api"), json.dumps(body), content_type="application/json")
        data = r.json()
        self.assertEqual(data["total"], "118.00")
        self.assertEqual(len(data["lines"]), 2)


    def test_amount_mode_derives_rate_taxable_and_gst(self):
        items = [{"description": "Pen", "qty": "4", "amount": "1180", "gst_rate": "18"}]
        r = self.save(payload(price_mode="AMT", items=items))
        self.assertEqual(r.status_code, 200, r.content)
        inv = Invoice.objects.get(invoice_no="T-1")
        self.assertEqual(inv.price_mode, "AMT")
        self.assertEqual((inv.taxable_value, inv.cgst, inv.sgst, inv.igst, inv.total), (1000, 90, 90, 0, 1180))
        item = inv.items.get()
        self.assertEqual((item.rate, item.taxable, item.gst_amount, item.line_total), (250, 1000, 180, 1180))

    def test_amount_mode_blank_quantity_counts_as_one(self):
        items = [{"description": "Pen", "qty": "", "amount": "118", "gst_rate": "18"}]
        self.assertEqual(self.save(payload(price_mode="AMT", items=items)).status_code, 200)
        item = Invoice.objects.get().items.get()
        self.assertEqual((item.qty, item.rate), (1, 100))

    def test_amount_mode_rejects_missing_or_zero_amount(self):
        for amount in ("", "0", "-5"):
            items = [{"description": "Pen", "qty": "1", "amount": amount, "gst_rate": "18"}]
            self.assertEqual(self.save(payload(price_mode="AMT", items=items)).status_code, 400, amount)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_amount_mode_invoice_reopens_and_can_be_updated(self):
        items = [{"description": "Pen", "qty": "4", "amount": "1180", "gst_rate": "18"}]
        inv_id = self.save(payload(price_mode="AMT", items=items)).json()["id"]
        self.assertEqual(self.client.get(reverse("invoice_edit", args=[inv_id])).status_code, 200)
        items = [{"description": "Pen", "qty": "2", "amount": "236", "gst_rate": "18"}]
        r = self.save(payload(price_mode="AMT", items=items), reverse("invoice_update", args=[inv_id]))
        self.assertEqual(r.status_code, 200, r.content)
        inv = Invoice.objects.get(pk=inv_id)
        self.assertEqual((inv.total, inv.items.get().rate), (236, 100))

    def test_live_calc_amount_mode(self):
        body = {"price_mode": "AMT", "place_of_supply": "West Bengal",
                "items": [{"qty": "4", "amount": "1180", "gst_rate": "18"}]}
        data = self.client.post(reverse("calc_api"), json.dumps(body), content_type="application/json").json()
        line = data["lines"][0]
        self.assertEqual((line["rate"], line["taxable"], line["gst"], line["total"]), ("250.00", "1000.00", "180.00", "1180.00"))
        self.assertEqual(data["total"], "1180.00")


    def test_party_email_is_saved_on_invoice_and_new_party(self):
        r = self.save(payload(party_email="accounts@alpha.example"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Invoice.objects.get().party_email, "accounts@alpha.example")
        self.assertEqual(Party.objects.get(name="Alpha Traders").email, "accounts@alpha.example")

    def test_invalid_party_email_rejected(self):
        for bad in ("not-an-email", "a@b", "a b@c.com"):
            self.assertEqual(self.save(payload(party_email=bad)).status_code, 400, bad)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_party_email_shown_on_print_and_edit_pages(self):
        inv_id = self.save(payload(party_email="accounts@alpha.example")).json()["id"]
        self.assertContains(self.client.get(reverse("invoice_print", args=[inv_id])), "accounts@alpha.example")
        self.assertContains(self.client.get(reverse("invoice_edit", args=[inv_id])), "accounts@alpha.example")


    def test_editing_keeps_the_original_submitted_date(self):
        inv_id = self.save(payload()).json()["id"]
        original = Invoice.objects.get(pk=inv_id).submitted_on
        Invoice.objects.filter(pk=inv_id).update(submitted_on=datetime.date(2026, 9, 1))
        self.save(payload(), reverse("invoice_update", args=[inv_id]))
        self.assertEqual(Invoice.objects.get(pk=inv_id).submitted_on, datetime.date(2026, 9, 1))
        self.assertNotEqual(original, datetime.date(2026, 9, 1))

    def test_submit_requires_post_and_ignores_offsite_redirects(self):
        inv_id = self.save(payload(submitted=False)).json()["id"]
        url = reverse("invoice_submit", args=[inv_id])
        self.assertEqual(self.client.get(url).status_code, 405)
        r = self.client.post(url, {"next": "https://evil.example/"})
        self.assertEqual(r["Location"], reverse("invoice_list"))

    def test_check_number_reports_duplicates(self):
        inv_id = self.save(payload()).json()["id"]
        url = reverse("check_number")
        self.assertTrue(self.client.get(url, {"no": "T-1"}).json()["exists"])
        self.assertFalse(self.client.get(url, {"no": "T-9"}).json()["exists"])
        self.assertFalse(self.client.get(url, {"no": "T-1", "exclude": inv_id}).json()["exists"])

    def test_form_shows_the_last_invoice(self):
        self.assertIsNone(self.client.get(reverse("invoice_new")).context["init"]["last_invoice"])
        self.save(payload(invoice_no="T-1"))
        self.save(payload(invoice_no="T-2"))
        self.assertEqual(self.client.get(reverse("invoice_new")).context["init"]["last_invoice"]["no"], "T-2")


    def test_submitted_bill_gets_a_number_and_a_draft_does_not(self):
        self.save(payload(invoice_no="T-1"))
        self.assertIsNotNone(Invoice.objects.get(invoice_no="T-1").submitted_on)
        r = self.save(payload(invoice_no="IGNORED-9", submitted=False))
        self.assertEqual(r.status_code, 200, r.content)
        draft = Invoice.objects.get(pk=r.json()["id"])
        self.assertIsNone(draft.invoice_no)  # a typed number is ignored for a draft
        self.assertIsNone(draft.submitted_on)

    def test_drafts_do_not_use_up_numbers(self):
        first = self.save(payload(invoice_no="")).json()["id"]
        self.save(payload(party_name="Beta", submitted=False))
        self.save(payload(party_name="Gamma", submitted=False))
        second = self.save(payload(invoice_no="")).json()["id"]
        self.assertEqual(Invoice.objects.get(pk=first).invoice_no, "INV/26-27/0001")
        self.assertEqual(Invoice.objects.get(pk=second).invoice_no, "INV/26-27/0002")  # no gap

    def test_submitting_a_draft_gives_it_the_next_number(self):
        draft_id = self.save(payload(submitted=False)).json()["id"]
        self.save(payload(invoice_no=""))  # INV/26-27/0001
        url = reverse("invoice_submit", args=[draft_id])
        r = self.client.post(url, {"next": reverse("invoice_list")})
        self.assertEqual(r.status_code, 302)
        draft = Invoice.objects.get(pk=draft_id)
        self.assertEqual(draft.invoice_no, "INV/26-27/0002")
        self.assertIsNotNone(draft.submitted_on)
        self.assertGreaterEqual(draft.date, datetime.date(2026, 10, 12))  # a past date becomes the day of issue
        self.client.post(url, {"next": reverse("invoice_list")})
        self.assertEqual(Invoice.objects.get(pk=draft_id).invoice_no, "INV/26-27/0002")  # submitting twice changes nothing

    def test_editing_a_draft_and_submitting_it_assigns_a_number(self):
        draft_id = self.save(payload(submitted=False)).json()["id"]
        r = self.save(payload(invoice_no="", submitted=True), reverse("invoice_update", args=[draft_id]))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Invoice.objects.get(pk=draft_id).invoice_no, "INV/26-27/0001")

    def test_submitted_bill_cannot_go_back_to_draft(self):
        inv_id = self.save(payload(invoice_no="T-1")).json()["id"]
        r = self.save(payload(invoice_no="T-1", submitted=False), reverse("invoice_update", args=[inv_id]))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Invoice.objects.get(pk=inv_id).invoice_no, "T-1")

    def test_submit_requires_post_and_ignores_offsite_redirects(self):
        inv_id = self.save(payload(submitted=False)).json()["id"]
        url = reverse("invoice_submit", args=[inv_id])
        self.assertEqual(self.client.get(url).status_code, 405)
        r = self.client.post(url, {"next": "https://evil.example/"})
        self.assertEqual(r["Location"], reverse("invoice_list"))

    def test_list_filters_by_status_and_shows_counts(self):
        self.save(payload(invoice_no="T-1"))
        draft_id = self.save(payload(submitted=False)).json()["id"]
        r = self.client.get(reverse("invoice_list"), {"status": "pending"})
        self.assertEqual([i.pk for i in r.context["invoices"]], [draft_id])
        self.assertEqual(dict(r.context["counts"]), {"all": 2, "pending": 1, "submitted": 1})
        r = self.client.get(reverse("invoice_list"), {"status": "submitted"})
        self.assertEqual([i.invoice_no for i in r.context["invoices"]], ["T-1"])

    def test_draft_print_page_shows_the_draft_banner(self):
        draft_id = self.save(payload(submitted=False)).json()["id"]
        self.assertContains(self.client.get(reverse("invoice_print", args=[draft_id])), "DRAFT")
        issued_id = self.save(payload(invoice_no="T-5")).json()["id"]
        self.assertNotContains(self.client.get(reverse("invoice_print", args=[issued_id])), "not a valid tax invoice")

    def test_last_invoice_hint_ignores_drafts(self):
        self.save(payload(invoice_no="T-1"))
        self.save(payload(submitted=False))
        self.assertEqual(self.client.get(reverse("invoice_new")).context["init"]["last_invoice"]["no"], "T-1")


    def test_dashboard_counts_submitted_bills_only(self):
        self.save(payload(invoice_no="T-1"))                      # 2000 + 360 GST = 2360, October 2026
        self.save(payload(party_name="Beta", submitted=False))    # a draft: not in any figure
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        totals = r.context["report"]["totals"]
        self.assertEqual((totals["bills"], totals["taxable"], totals["gst"], totals["total"]), (1, 2000, 360, 2360))
        self.assertEqual((r.context["draft_count"], r.context["fy"]), (1, 2026))
        self.assertContains(r, "23,60.00".replace("23,60", "2,360"))

    def test_dashboard_year_filter_and_bad_values(self):
        self.save(payload(invoice_no="T-1"))
        self.assertEqual(self.client.get(reverse("dashboard"), {"fy": "2025"}).context["report"]["totals"]["bills"], 0)
        self.assertEqual(self.client.get(reverse("dashboard"), {"fy": "abc"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard"), {"fy": "99999"}).context["fy"], 2026)

    def test_dashboard_csv_export(self):
        self.save(payload(invoice_no="T-1"))
        r = self.client.get(reverse("dashboard_export"), {"fy": "2026"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        body = r.content.decode("utf-8-sig").splitlines()
        self.assertEqual(body[0].split(",")[0], "Month")
        self.assertEqual(len(body), 14)  # header + 12 months + total
        self.assertTrue(body[-1].startswith("Total,1,2000"))

    def test_dashboard_needs_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        self.assertEqual(self.client.get(reverse("dashboard_export")).status_code, 302)


    def test_print_page_shows_rate_wise_tax_summary_only_for_mixed_rates(self):
        mixed = payload(items=[
            {"description": "A", "qty": "1", "rate": "1000", "gst_rate": "18"},
            {"description": "B", "qty": "1", "rate": "500", "gst_rate": "12"},
        ])
        inv_id = self.save(mixed).json()["id"]
        r = self.client.get(reverse("invoice_print", args=[inv_id]))
        rows = r.context["summary"]
        self.assertEqual([(x["taxable"], x["cgst"], x["sgst"]) for x in rows], [(500, 30, 30), (1000, 90, 90)])
        self.assertContains(r, "Total GST")
        single = self.save(payload(invoice_no="T-2")).json()["id"]
        self.assertNotContains(self.client.get(reverse("invoice_print", args=[single])), "Total GST")

    def test_live_calc_returns_the_summary(self):
        body = {"price_mode": "EXCL", "place_of_supply": "West Bengal",
                "items": [{"qty": "1", "rate": "1000", "gst_rate": "18"}, {"qty": "1", "rate": "500", "gst_rate": "12"}]}
        data = self.client.post(reverse("calc_api"), json.dumps(body), content_type="application/json").json()
        self.assertEqual([(x["rate"], x["cgst"], x["sgst"]) for x in data["summary"]], [("12", "30.00", "30.00"), ("18", "90.00", "90.00")])


    def test_form_offers_the_unit_list_and_print_shows_dash_and_percent(self):
        self.assertIn("Kg", self.client.get(reverse("invoice_new")).context["init"]["units"])
        inv_id = self.save(payload()).json()["id"]
        html = self.client.get(reverse("invoice_print", args=[inv_id])).content.decode()
        self.assertIn("18%", html)       # GST rate with its % sign
        self.assertIn(">-</td>", html)   # no discount -> a hyphen


class InvoiceNumberTests(TestCase):
    def test_series_increments_and_resets_each_financial_year(self):
        self.assertEqual(Invoice.next_number("INV", datetime.date(2026, 10, 12)), "INV/26-27/0001")
        Invoice.objects.create(invoice_no="INV/26-27/0005", party_name="A")
        self.assertEqual(Invoice.next_number("INV", datetime.date(2026, 10, 12)), "INV/26-27/0006")
        self.assertEqual(Invoice.next_number("INV", datetime.date(2027, 3, 31)), "INV/26-27/0006")
        self.assertEqual(Invoice.next_number("INV", datetime.date(2027, 4, 1)), "INV/27-28/0001")

    def test_manual_numbers_outside_series_do_not_break_it(self):
        Invoice.objects.create(invoice_no="CUSTOM-9", party_name="A")
        self.assertEqual(Invoice.next_number("INV", datetime.date(2026, 10, 12)), "INV/26-27/0001")
