import django.db.models.deletion
from django.db import migrations, models


def link_existing_revisions(apps, schema_editor):
    DocumentRevision = apps.get_model("backups", "DocumentRevision")

    for revision in DocumentRevision.objects.order_by("document_id", "revision_index"):
        parent = (
            DocumentRevision.objects.filter(
                document_id=revision.document_id,
                revision_index__lt=revision.revision_index,
            )
            .order_by("-revision_index")
            .first()
        )
        if parent:
            revision.parent_revision_id = parent.id
            revision.save(update_fields=["parent_revision"])


class Migration(migrations.Migration):
    dependencies = [
        ("backups", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentrevision",
            name="parent_revision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="children",
                to="backups.documentrevision",
            ),
        ),
        migrations.RunPython(link_existing_revisions, migrations.RunPython.noop),
    ]
