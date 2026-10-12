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
