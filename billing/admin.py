from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from .importer import MAX_BYTES, SAMPLE_CSV, ImportFileError, build_parties, read_csv_text, read_table
from .models import STATE_CODES, AuditLog, Firm, Invoice, InvoiceItem, Party, Product


@admin.register(Firm)
class FirmAdmin(admin.ModelAdmin):
    list_display = ("name", "gstin", "state", "invoice_prefix")


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ("name", "gstin", "state", "phone", "email")
    search_fields = ("name", "gstin", "phone", "email")
    change_list_template = "admin/billing/party/change_list.html"  # adds the "Import parties" button

    # ---- import parties from a file or from rows pasted out of Excel ----
    def get_urls(self):
        mine = [
            path("import/", self.admin_site.admin_view(self.import_view), name="billing_party_import"),
            path("import/sample/", self.admin_site.admin_view(self.import_sample), name="billing_party_import_sample"),
        ]
        return mine + super().get_urls()  # ours first, so "import/" is not taken for an object id

    def _import_context(self, request, **extra):
        return {**self.admin_site.each_context(request), "opts": self.model._meta, "title": "Import parties", **extra}

    def import_sample(self, request):
        response = HttpResponse(SAMPLE_CSV, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="parties-sample.csv"'
        return response

    def import_view(self, request):
        if not (self.has_add_permission(request) and self.has_change_permission(request)):
            raise PermissionDenied
        page = "admin/billing/party/import.html"
        if request.method != "POST":
            return TemplateResponse(request, page, self._import_context(request, mode="skip"))
        if "confirm" in request.POST:
            return self._import_confirm(request)

        mode = "update" if request.POST.get("mode") == "update" else "skip"
        upload, pasted = request.FILES.get("file"), request.POST.get("pasted", "")
        try:
            if upload:
                table = read_table(upload.name, upload.read(MAX_BYTES + 1))
            elif pasted.strip():
                table = read_csv_text(pasted)
            else:
                raise ImportFileError("Choose a file, or paste the rows you copied from Excel.")
            parties, _ = build_parties(table, STATE_CODES)
        except ImportFileError as exc:
            return TemplateResponse(request, page, self._import_context(request, mode=mode, error=str(exc)))

        existing = {name.lower() for name in Party.objects.values_list("name", flat=True)}
        counts = {"new": 0, "exists": 0, "error": 0}
        for p in parties:
            p["status"] = "error" if p["error"] else ("exists" if p["name"].lower() in existing else "new")
            counts[p["status"]] += 1
        request.session["party_import"] = {"mode": mode, "parties": [p for p in parties if not p["error"]]}
        return TemplateResponse(
            request, page,
            self._import_context(request, mode=mode, preview=True, parties=parties[:300], total=len(parties), counts=counts,
                                 warned=sum(1 for p in parties if p["warnings"])),
        )

    def _import_confirm(self, request):
        data = request.session.pop("party_import", None)
        changelist = reverse("admin:billing_party_changelist")
        if not data:
            self.message_user(request, "The import session has expired. Please upload the file again.", messages.ERROR)
            return redirect(reverse("admin:billing_party_import"))
        created = updated = skipped = 0
        with transaction.atomic():
            by_name = {p.name.lower(): p for p in Party.objects.all()}
            for row in data["parties"]:
                party = by_name.get(row["name"].lower())
                if party is None:
                    party = Party(name=row["name"], address=row["address"], gstin=row["gstin"], state=row["state"],
                                  phone=row["phone"], email=row["email"])
                    party.save()
                    by_name[row["name"].lower()] = party
                    created += 1
                elif data["mode"] == "update":
                    for field in ("address", "gstin", "state", "phone", "email"):
                        if row[field]:  # a blank cell never wipes out what is already saved
                            setattr(party, field, row[field])
                    party.save()
                    updated += 1
                else:
                    skipped += 1
        from . import audit
        audit.record(request, "Imported parties", "", f"{created} added, {updated} updated, {skipped} skipped")
        self.message_user(
            request, f"Import finished: {created} added, {updated} updated, {skipped} skipped (already existed).", messages.SUCCESS
        )
        return redirect(changelist)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "hsn", "unit", "rate", "gst_rate")
    search_fields = ("name", "hsn")


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in InvoiceItem._meta.fields if f.name != "invoice"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_no", "doc_type", "date", "party_name", "total", "submitted_on", "status")
    list_filter = ("doc_type", "status")
    actions = None  # no bulk delete
    search_fields = ("invoice_no", "party_name", "party_gstin")
    date_hierarchy = "date"
    inlines = [InvoiceItemInline]
    # Invoices are created and edited only on the billing screen, so the totals always follow the server's rules.
    readonly_fields = [f.name for f in Invoice._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # A numbered bill can never be deleted (that would leave a hole in the series): cancel it on the billing screen.
        if obj is not None and obj.invoice_no:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """A read-only history of who created, edited, submitted, cancelled or deleted what."""
    list_display = ("at", "user_name", "action", "doc_no", "detail")
    list_filter = ("action", "user_name")
    search_fields = ("doc_no", "detail", "user_name")
    date_hierarchy = "at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
