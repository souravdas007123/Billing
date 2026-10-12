from django.contrib import admin

from .models import Firm, Invoice, InvoiceItem, Party, Product


@admin.register(Firm)
class FirmAdmin(admin.ModelAdmin):
    list_display = ("name", "gstin", "state", "invoice_prefix")


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ("name", "gstin", "state", "phone", "email")
    search_fields = ("name", "gstin", "phone", "email")


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
    list_display = ("invoice_no", "date", "party_name", "total")
    search_fields = ("invoice_no", "party_name", "party_gstin")
    date_hierarchy = "date"
    inlines = [InvoiceItemInline]
    # Invoices are created and edited only on the billing screen, so the totals always follow the server's rules.
    readonly_fields = [f.name for f in Invoice._meta.fields]

    def has_add_permission(self, request):
        return False
