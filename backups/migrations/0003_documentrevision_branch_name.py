from django.db import migrations, models


def populate_branch_names(apps, schema_editor):
    DocumentRevision = apps.get_model("backups", "DocumentRevision")
    DocumentRevision.objects.filter(branch_name="").update(branch_name="main")


class Migration(migrations.Migration):
    dependencies = [
        ("backups", "0002_documentrevision_parent_revision"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentrevision",
            name="branch_name",
            field=models.CharField(default="main", max_length=80),
        ),
        migrations.RunPython(populate_branch_names, migrations.RunPython.noop),
    ]
