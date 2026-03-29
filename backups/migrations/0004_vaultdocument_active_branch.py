from django.db import migrations, models


def populate_active_branch(apps, schema_editor):
    VaultDocument = apps.get_model("backups", "VaultDocument")
    VaultDocument.objects.filter(active_branch="").update(active_branch="main")


class Migration(migrations.Migration):
    dependencies = [
        ("backups", "0003_documentrevision_branch_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="vaultdocument",
            name="active_branch",
            field=models.CharField(default="main", max_length=80),
        ),
        migrations.RunPython(populate_active_branch, migrations.RunPython.noop),
    ]
