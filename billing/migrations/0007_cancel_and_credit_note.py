from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0006_invoice_doc_type"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="invoice",
            options={"ordering": ["-date", "-id"], "permissions": [("cancel_invoice", "Can cancel invoices")]},
        ),
        migrations.AlterField(
            model_name="invoice",
            name="doc_type",
            field=models.CharField(
                choices=[
                    ("TAX", "Tax invoice"),
                    ("SUPPLY", "Bill of supply (no GST)"),
                    ("EST", "Estimate (no GST, not a tax document)"),
                    ("CN", "Credit note (return or correction)"),
                ],
                default="TAX",
                max_length=6,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="ref_no",
            field=models.CharField(blank=True, max_length=40, verbose_name="Against invoice no."),
        ),
        migrations.AddField(
            model_name="invoice",
            name="ref_date",
            field=models.DateField(blank=True, null=True, verbose_name="Against invoice date"),
        ),
        migrations.AddField(
            model_name="invoice",
            name="status",
            field=models.CharField(
                choices=[("ACTIVE", "Active"), ("CANCELLED", "Cancelled")], default="ACTIVE", max_length=10
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="cancelled_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invoice",
            name="cancel_reason",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
