import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="BackupSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "trigger",
                    models.CharField(
                        choices=[
                            ("manual", "Manual"),
                            ("scheduled", "Scheduled"),
                            ("webhook", "Webhook"),
                        ],
                        default="manual",
                        max_length=20,
                    ),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("snapshot_path", models.CharField(blank=True, max_length=500)),
                ("file_count", models.PositiveIntegerField(default=0)),
                ("total_bytes", models.BigIntegerField(default=0)),
                ("notes", models.TextField(blank=True)),
                ("manifest", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Vault",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120, unique=True)),
                ("slug", models.SlugField(blank=True, max_length=140, unique=True)),
                ("source_path", models.CharField(max_length=500)),
                ("is_active", models.BooleanField(default=True)),
                ("snapshot_interval_minutes", models.PositiveIntegerField(default=60)),
                ("retention_snapshots", models.PositiveIntegerField(default=48)),
                ("exclude_patterns", models.JSONField(blank=True, default=list)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="VaultDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("relative_path", models.CharField(max_length=500)),
                ("latest_checksum", models.CharField(blank=True, max_length=64)),
                ("is_deleted", models.BooleanField(default=False)),
                (
                    "vault",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="backups.vault"),
                ),
                (
                    "last_snapshot",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="documents",
                        to="backups.backupsnapshot",
                    ),
                ),
            ],
            options={"ordering": ["relative_path"], "unique_together": {("vault", "relative_path")}},
        ),
        migrations.AddField(
            model_name="backupsnapshot",
            name="vault",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="snapshots", to="backups.vault"),
        ),
        migrations.CreateModel(
            name="DocumentRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("revision_index", models.PositiveIntegerField()),
                ("checksum", models.CharField(max_length=64)),
                ("content_path", models.CharField(max_length=500)),
                ("diff_summary", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "document",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="revisions", to="backups.vaultdocument"),
                ),
                (
                    "snapshot",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="revisions",
                        to="backups.backupsnapshot",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"], "unique_together": {("document", "revision_index")}},
        ),
    ]
