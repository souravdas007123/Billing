from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0005_invoice_draft_has_no_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="doc_type",
            field=models.CharField(
                choices=[
                    ("TAX", "Tax invoice"),
                    ("SUPPLY", "Bill of supply (no GST)"),
                    ("EST", "Estimate (no GST, not a tax document)"),
                ],
                default="TAX",
                max_length=6,
            ),
        ),
    ]
