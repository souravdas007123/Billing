import re

from django.conf import settings
from django.db import models
from django.utils import timezone

# GST state codes (name -> code)
STATE_CODES = {
    "Jammu and Kashmir": "01", "Himachal Pradesh": "02", "Punjab": "03", "Chandigarh": "04",
    "Uttarakhand": "05", "Haryana": "06", "Delhi": "07", "Rajasthan": "08", "Uttar Pradesh": "09",
    "Bihar": "10", "Sikkim": "11", "Arunachal Pradesh": "12", "Nagaland": "13", "Manipur": "14",
    "Mizoram": "15", "Tripura": "16", "Meghalaya": "17", "Assam": "18", "West Bengal": "19",
    "Jharkhand": "20", "Odisha": "21", "Chhattisgarh": "22", "Madhya Pradesh": "23", "Gujarat": "24",
    "Dadra and Nagar Haveli and Daman and Diu": "26", "Maharashtra": "27", "Karnataka": "29",
    "Goa": "30", "Lakshadweep": "31", "Kerala": "32", "Tamil Nadu": "33", "Puducherry": "34",
    "Andaman and Nicobar Islands": "35", "Telangana": "36", "Andhra Pradesh": "37", "Ladakh": "38",
}
STATE_CHOICES = [(name, name) for name in STATE_CODES]
CODE_TO_STATE = {code: name for name, code in STATE_CODES.items()}

PRICE_MODES = [("EXCL", "GST Excluding"), ("INCL", "GST Including")]


def state_from_gstin(gstin):
    g = (gstin or "").strip()
    return CODE_TO_STATE.get(g[:2], "") if len(g) >= 2 else ""


class Firm(models.Model):
    """Your own company details (a single record). Fill it in from the admin site."""

    name = models.CharField(max_length=200, default="My Company")
    address = models.TextField(blank=True)
    gstin = models.CharField("GSTIN", max_length=15, blank=True)
    state = models.CharField(max_length=60, choices=STATE_CHOICES, default="West Bengal")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    bank_details = models.TextField(blank=True, help_text="Printed at the bottom of the invoice")
    terms = models.TextField(blank=True, help_text="Terms & conditions")
    invoice_prefix = models.CharField(max_length=20, default="INV")

    class Meta:
        verbose_name = "Firm"

    def __str__(self):
        return self.name

    @classmethod
    def get(cls):
        return cls.objects.first() or cls.objects.create()


class Party(models.Model):
    name = models.CharField(max_length=200, unique=True)
    address = models.TextField(blank=True)
    gstin = models.CharField("GSTIN", max_length=15, blank=True)
    state = models.CharField(max_length=60, choices=STATE_CHOICES, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Parties"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.gstin = (self.gstin or "").strip().upper()
        if self.gstin and not self.state:
            self.state = state_from_gstin(self.gstin)
        super().save(*args, **kwargs)


class Product(models.Model):
    """Optional item master: typing a description fills in the HSN, unit, rate and GST automatically."""

    name = models.CharField(max_length=300, unique=True)
    hsn = models.CharField("HSN/SAC", max_length=12, blank=True)
    unit = models.CharField(max_length=20, default="Nos")
    rate = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=settings.DEFAULT_GST_RATE)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def financial_year_label(d):
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


class Invoice(models.Model):
    invoice_no = models.CharField(max_length=40, unique=True)
    date = models.DateField(default=timezone.localdate)
    party = models.ForeignKey(Party, null=True, blank=True, on_delete=models.SET_NULL)

    # Party details are stored on the invoice as a snapshot, so editing a party later does not change old invoices.
    party_name = models.CharField(max_length=200)
    party_address = models.TextField(blank=True)
    party_gstin = models.CharField(max_length=15, blank=True)
    party_state = models.CharField(max_length=60, blank=True)
    party_phone = models.CharField(max_length=40, blank=True)

    place_of_supply = models.CharField(max_length=60, blank=True)
    price_mode = models.CharField(max_length=4, choices=PRICE_MODES, default="EXCL")
    is_intra_state = models.BooleanField(default=True)

    taxable_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cgst = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sgst = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    igst = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    round_off = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.invoice_no} - {self.party_name}"

    @property
    def gst_total(self):
        return self.cgst + self.sgst + self.igst

    @classmethod
    def next_number(cls, prefix, on_date=None):
        """Next number, e.g. PREFIX/26-27/0001. The series restarts each financial year (April to March)."""
        on_date = on_date or timezone.localdate()
        series = f"{prefix}/{financial_year_label(on_date)}/"
        last = 0
        for no in cls.objects.filter(invoice_no__startswith=series).values_list("invoice_no", flat=True):
            m = re.search(r"(\d+)$", no)
            if m:
                last = max(last, int(m.group(1)))
        return f"{series}{last + 1:04d}"


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, related_name="items", on_delete=models.CASCADE)
    sr = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=300)
    hsn = models.CharField(max_length=12, blank=True)
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.CharField(max_length=20, blank=True)
    rate = models.DecimalField(max_digits=14, decimal_places=4)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    taxable = models.DecimalField(max_digits=14, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=14, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["sr"]

    def __str__(self):
        return f"{self.invoice.invoice_no} #{self.sr} {self.description}"
