import datetime
import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import AuditLog, Firm, Invoice, Party


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
        self.assertEqual(self.client.get(reverse("invoice_new")).context["init"]["last_invoices"]["TAX"]["no"], "T-2")


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
        self.assertEqual(self.client.get(reverse("invoice_new")).context["init"]["last_invoices"]["TAX"]["no"], "T-1")


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
        lines = r.context["items"]  # every line carries its own CGST and SGST that add up to the line's GST
        self.assertEqual([(l["cgst"], l["sgst"]) for l in lines], [(90, 90), (30, 30)])
        self.assertTrue(all(l["cgst"] + l["sgst"] == l["gst_amount"] for l in lines))
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
        self.assertIn("9%", html)        # CGST and SGST rates, each with its % sign
        self.assertIn(">-</td>", html)   # no discount -> a hyphen


    # ---- document types ----
    def test_bill_of_supply_charges_no_gst_and_has_its_own_series(self):
        r = self.save(payload(invoice_no="", doc_type="SUPPLY"))  # the payload still says 18% - it must be ignored
        self.assertEqual(r.status_code, 200, r.content)
        inv = Invoice.objects.get(pk=r.json()["id"])
        self.assertEqual((inv.doc_type, inv.invoice_no), ("SUPPLY", "BOS/26-27/0001"))
        self.assertEqual((inv.taxable_value, inv.cgst, inv.sgst, inv.igst, inv.total), (2000, 0, 0, 0, 2000))
        self.assertEqual(set(inv.items.values_list("gst_rate", flat=True)), {0})
        tax = Invoice.objects.get(pk=self.save(payload(invoice_no="")).json()["id"])
        self.assertEqual(tax.invoice_no, "INV/26-27/0001")  # the tax series is untouched

    def test_estimate_has_its_own_series_and_is_not_in_the_dashboard(self):
        est = Invoice.objects.get(pk=self.save(payload(invoice_no="", doc_type="EST")).json()["id"])
        self.assertEqual(est.invoice_no, "EST/26-27/0001")
        self.save(payload(invoice_no="", doc_type="SUPPLY", party_name="Beta"))
        self.save(payload(invoice_no=""))
        report = self.client.get(reverse("dashboard")).context["report"]
        self.assertEqual(report["totals"]["bills"], 2)                      # the estimate is left out
        self.assertEqual((report["by_type"]["TAX"]["bills"], report["by_type"]["SUPPLY"]["bills"]), (1, 1))
        self.assertEqual((report["registered"]["bills"], report["unregistered"]["bills"]), (0, 2))

    def test_type_cannot_change_after_a_number_is_given_but_a_draft_can_change(self):
        issued = self.save(payload(invoice_no="T-1")).json()["id"]
        r = self.save(payload(invoice_no="T-1", doc_type="EST"), reverse("invoice_update", args=[issued]))
        self.assertEqual(r.status_code, 400)
        draft = self.save(payload(submitted=False)).json()["id"]
        self.save(payload(invoice_no="", doc_type="SUPPLY"), reverse("invoice_update", args=[draft]))
        self.assertEqual(Invoice.objects.get(pk=draft).invoice_no, "BOS/26-27/0001")

    def test_submitting_a_draft_uses_its_types_series(self):
        draft = self.save(payload(submitted=False, doc_type="EST")).json()["id"]
        self.client.post(reverse("invoice_submit", args=[draft]), {"next": "/"})
        self.assertEqual(Invoice.objects.get(pk=draft).invoice_no, "EST/26-27/0001")

    def test_live_calc_ignores_gst_for_a_non_tax_bill(self):
        body = {"price_mode": "EXCL", "place_of_supply": "West Bengal", "doc_type": "SUPPLY",
                "items": [{"qty": "1", "rate": "100", "gst_rate": "18"}]}
        data = self.client.post(reverse("calc_api"), json.dumps(body), content_type="application/json").json()
        self.assertEqual((data["total"], data["gst_total"], data["summary"][0]["rate"]), ("100.00", "0.00", "0"))

    def test_print_titles_and_unregistered_label(self):
        tax = self.save(payload(invoice_no="T-1")).json()["id"]
        html = self.client.get(reverse("invoice_print", args=[tax])).content.decode()
        self.assertIn("TAX INVOICE", html)
        self.assertIn("GSTIN: Unregistered", html)
        sup = self.save(payload(invoice_no="", doc_type="SUPPLY")).json()["id"]
        html = self.client.get(reverse("invoice_print", args=[sup])).content.decode()
        self.assertIn("BILL OF SUPPLY", html)
        self.assertNotIn("CGST", html)
        est = self.save(payload(invoice_no="", doc_type="EST")).json()["id"]
        self.assertContains(self.client.get(reverse("invoice_print", args=[est])), "not a tax invoice")

    # ---------- cancel, credit note, copy ----------
    def issue(self, **over):
        r = self.save(payload(invoice_no="", submitted=True, **over))
        self.assertEqual(r.status_code, 200, r.content)
        return Invoice.objects.get(pk=r.json()["id"])

    def test_cancel_needs_permission_and_reason(self):
        inv = self.issue()
        url = reverse("invoice_cancel", args=[inv.pk])
        self.assertEqual(self.client.post(url, {"reason": "wrong party"}).status_code, 403)
        get_user_model().objects.filter(username="u").update(is_superuser=True)
        self.client.post(url, {"reason": ""})
        inv.refresh_from_db()
        self.assertFalse(inv.is_cancelled)
        self.client.post(url, {"reason": "wrong party"})
        inv.refresh_from_db()
        self.assertTrue(inv.is_cancelled)
        self.assertEqual(inv.cancel_reason, "wrong party")
        # a cancelled bill cannot be edited and its number is not reused
        r = self.save(payload(invoice_no=inv.invoice_no), reverse("invoice_update", args=[inv.pk]))
        self.assertEqual(r.status_code, 400)
        self.assertNotEqual(self.issue().invoice_no, inv.invoice_no)

    def test_draft_can_be_deleted_numbered_cannot(self):
        draft = Invoice.objects.get(pk=self.save(payload(submitted=False)).json()["id"])
        self.client.post(reverse("invoice_delete_draft", args=[draft.pk]))
        self.assertFalse(Invoice.objects.filter(pk=draft.pk).exists())
        inv = self.issue()
        self.client.post(reverse("invoice_delete_draft", args=[inv.pk]))
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())

    def test_credit_note_needs_reference_and_has_own_series(self):
        inv = self.issue()
        self.assertEqual(self.save(payload(invoice_no="", doc_type="CN")).status_code, 400)
        cn = self.issue(doc_type="CN", ref_no=inv.invoice_no, ref_date="2026-10-12")
        self.assertTrue(cn.invoice_no.startswith("CN/"))
        self.assertEqual(cn.ref_no, inv.invoice_no)
        self.assertEqual(self.client.get(reverse("invoice_print", args=[cn.pk])).status_code, 200)

    def test_credit_note_is_deducted_on_dashboard(self):
        self.issue()
        self.issue(doc_type="CN", ref_no="X/1", ref_date="2026-10-12")
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["report"]["totals"]["total"], 0)

    def test_copy_estimate_to_tax_invoice(self):
        est = self.issue(doc_type="EST")
        r = self.client.get(reverse("invoice_new") + f"?copy={est.pk}&as=TAX")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["init"]["invoice"]["doc_type"], "TAX")
        self.assertTrue(r.context["init"]["invoice"]["notice"])

    # ---------- GST reports and party statement ----------
    def test_gst_reports_and_exports(self):
        self.issue(party_gstin="19AAACG1234A1Z5")
        self.issue()
        r = self.client.get(reverse("gst_reports"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context["has_gap"])
        self.assertEqual((r.context["b2b_count"], r.context["b2c_count"]), (1, 1))
        for kind in ("b2b", "b2c", "hsn", "series"):
            resp = self.client.get(reverse("gst_export", args=[kind]) + "?month=2026-10")
            self.assertEqual(resp.status_code, 200, kind)
            self.assertIn("text/csv", resp["Content-Type"])
        b2b = self.client.get(reverse("gst_export", args=["b2b"])).content.decode("utf-8-sig").splitlines()
        self.assertEqual(len(b2b), 2)
        self.assertIn("19AAACG1234A1Z5", b2b[1])
        self.assertEqual(self.client.get(reverse("gst_export", args=["nope"])).status_code, 404)

    def test_gst_reports_show_gap(self):
        self.issue()
        self.issue(invoice_no="INV/26-27/0009")
        self.assertTrue(self.client.get(reverse("gst_reports")).context["has_gap"])

    def test_party_statement(self):
        self.issue()
        self.issue(doc_type="CN", ref_no="X", ref_date="2026-10-12")
        r = self.client.get(reverse("party_statement") + "?party=alpha traders&fy=2026")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["rows"]), 2)
        self.assertEqual(r.context["total"], 0)
        csv_resp = self.client.get(reverse("party_statement") + "?party=Alpha Traders&fy=2026&csv=1")
        self.assertIn("text/csv", csv_resp["Content-Type"])
        self.assertEqual(self.client.get(reverse("party_statement")).status_code, 200)

    def test_audit_log_records_actions(self):
        inv = self.issue()
        get_user_model().objects.filter(username="u").update(is_superuser=True)
        self.client.post(reverse("invoice_cancel", args=[inv.pk]), {"reason": "typo"})
        actions = list(AuditLog.objects.order_by("id").values_list("action", "doc_no", "user_name"))
        self.assertEqual(actions[0][0], "Created")
        self.assertEqual(actions[-1], ("Cancelled", inv.invoice_no, "u"))

    def test_backup_download_is_superuser_only(self):
        self.assertEqual(self.client.get(reverse("backup_download")).status_code, 403)

    def test_list_filters_and_pages(self):
        for i in range(52):
            self.issue(party_name=f"Party {i:02d}")
        self.issue(doc_type="EST", party_name="Quote Co")
        r = self.client.get(reverse("invoice_list"))
        self.assertEqual(len(r.context["invoices"]), 50)
        self.assertEqual(r.context["pg"].paginator.num_pages, 2)
        self.assertEqual(len(self.client.get(reverse("invoice_list") + "?page=2").context["invoices"]), 3)
        self.assertEqual(len(self.client.get(reverse("invoice_list") + "?type=EST").context["invoices"]), 1)
        self.assertEqual(len(self.client.get(reverse("invoice_list") + "?from=2030-01-01").context["invoices"]), 0)
        self.assertEqual(len(self.client.get(reverse("invoice_list") + "?q=Party 07").context["invoices"]), 1)
        self.assertEqual(self.client.get(reverse("invoice_list") + "?from=junk&type=zzz&page=99").status_code, 200)

    def test_share_links_and_upi_on_print_page(self):
        Firm.objects.update(upi_id="shop@okaxis")
        inv = self.issue(party_phone="9876543210", party_email="a@b.com")
        r = self.client.get(reverse("invoice_print", args=[inv.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("https://wa.me/919876543210?text=", r.context["share"]["whatsapp"])
        self.assertTrue(r.context["share"]["email"].startswith("mailto:a%40b.com"))
        draft = Invoice.objects.get(pk=self.save(payload(submitted=False)).json()["id"])
        r = self.client.get(reverse("invoice_print", args=[draft.pk]))
        self.assertIsNone(r.context["share"])
        self.assertEqual(r.context["upi_qr"], "")  # no payment QR on a draft

    def test_firm_image_needs_a_file(self):
        self.assertEqual(self.client.get(reverse("firm_image", args=["logo"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("firm_image", args=["other"])).status_code, 404)

    def test_firm_upi_id_is_validated(self):
        from django.core.exceptions import ValidationError
        firm = Firm.objects.first()
        firm.upi_id = "not a upi id"
        with self.assertRaises(ValidationError):
            firm.clean()


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


class PartyImportTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser("root", password="p")
        self.client.login(username="root", password="p")
        self.url = reverse("admin:billing_party_import")

    def upload(self, text, **extra):
        return self.client.post(self.url, {"file": SimpleUploadedFile("parties.csv", text.encode()), **extra})

    def test_admin_list_has_the_import_button(self):
        self.assertContains(self.client.get(reverse("admin:billing_party_changelist")), "Import parties")
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:billing_party_import_sample")).status_code, 200)

    def test_upload_preview_then_confirm(self):
        r = self.upload("name,gstin,phone\nAlpha,19AABAB6861E1ZS,111\nBeta,,222\n,,333\n")
        self.assertEqual(r.context["counts"], {"new": 2, "exists": 0, "error": 1})
        self.assertEqual(Party.objects.count(), 0)  # nothing is saved before the confirmation
        r = self.client.post(self.url, {"confirm": "1"}, follow=True)
        self.assertEqual(Party.objects.count(), 2)
        self.assertEqual(Party.objects.get(name="Alpha").state, "West Bengal")  # taken from the GSTIN
        self.assertContains(r, "2 added")

    def test_existing_parties_are_skipped_or_updated_without_erasing(self):
        Party.objects.create(name="Alpha", phone="111", email="a@x.com")
        self.upload("name,phone,email\nalpha,999,\n")
        self.client.post(self.url, {"confirm": "1"})
        self.assertEqual(Party.objects.get(name="Alpha").phone, "111")  # skipped
        self.upload("name,phone,email\nalpha,999,\n", mode="update")
        self.client.post(self.url, {"confirm": "1"})
        a = Party.objects.get(name="Alpha")
        self.assertEqual((a.phone, a.email), ("999", "a@x.com"))        # the empty email did not erase the saved one
        self.assertEqual(Party.objects.count(), 1)

    def test_pasted_rows_and_errors(self):
        r = self.client.post(self.url, {"pasted": "name\tphone\nGamma\t5\n"})
        self.assertEqual(r.context["counts"]["new"], 1)
        r = self.upload("foo,bar\n1,2\n")
        self.assertIn("name", r.context["error"])
        self.assertEqual(self.client.post(self.url, {"confirm": "1"}, follow=True).status_code, 200)  # no preview: back to the form

    def test_import_needs_a_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
