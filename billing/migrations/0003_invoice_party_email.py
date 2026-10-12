from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0002_invoice_price_mode_amount"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="party_email",
            field=models.EmailField(blank=True, default="", max_length=254),
            preserve_default=False,
        ),
    ]
