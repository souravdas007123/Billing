from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0008_auditlog"),
    ]

    operations = [
        migrations.AddIndex(model_name="invoice", index=models.Index(fields=["date"], name="inv_date_idx")),
        migrations.AddIndex(model_name="invoice", index=models.Index(fields=["doc_type", "date"], name="inv_type_date_idx")),
        migrations.AddIndex(model_name="invoice", index=models.Index(fields=["party_name"], name="inv_party_idx")),
        migrations.AddIndex(model_name="invoice", index=models.Index(fields=["status"], name="inv_status_idx")),
        migrations.AddIndex(model_name="invoice", index=models.Index(fields=["submitted_on"], name="inv_submitted_idx")),
    ]
