from django.db import migrations, models


def mark_existing_invoices_submitted(apps, schema_editor):
    """Bills made before this feature existed were already handed over, so they are not shown as pending."""
    Invoice = apps.get_model("billing", "Invoice")
    Invoice.objects.update(submitted_on=models.F("date"))


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0003_invoice_party_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="submitted_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(mark_existing_invoices_submitted, migrations.RunPython.noop),
    ]
