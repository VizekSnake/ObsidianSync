from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Vault(TimestampedModel):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    source_path = models.CharField(max_length=500)
    is_active = models.BooleanField(default=True)
    snapshot_interval_minutes = models.PositiveIntegerField(default=60)
    retention_snapshots = models.PositiveIntegerField(default=48)
    exclude_patterns = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def clean(self) -> None:
        super().clean()
        source_root = Path(self.source_path).expanduser()
        if not source_root.exists():
            raise ValidationError(
                {
                    "source_path": (
                        "Vault path does not exist inside the current runtime. "
                        "If you use Docker, mount the host directory and use the container path, "
                        'for example "/vaults/MyVault".'
                    )
                }
            )

        if not source_root.is_dir():
            raise ValidationError({"source_path": "Vault path must point to a directory."})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name

    @property
    def last_successful_snapshot(self):
        return self.snapshots.filter(status=BackupSnapshot.Status.SUCCESS).first()


class BackupSnapshot(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    class Trigger(models.TextChoices):
        MANUAL = "manual", "Manual"
        SCHEDULED = "scheduled", "Scheduled"
        WEBHOOK = "webhook", "Webhook"

    vault = models.ForeignKey(Vault, on_delete=models.CASCADE, related_name="snapshots")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    trigger = models.CharField(max_length=20, choices=Trigger.choices, default=Trigger.MANUAL)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    snapshot_path = models.CharField(max_length=500, blank=True)
    file_count = models.PositiveIntegerField(default=0)
    total_bytes = models.BigIntegerField(default=0)
    notes = models.TextField(blank=True)
    manifest = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.vault.name} @ {self.created_at:%Y-%m-%d %H:%M}"


class VaultDocument(TimestampedModel):
    vault = models.ForeignKey(Vault, on_delete=models.CASCADE, related_name="documents")
    relative_path = models.CharField(max_length=500)
    active_branch = models.CharField(max_length=80, default="main")
    latest_checksum = models.CharField(max_length=64, blank=True)
    last_snapshot = models.ForeignKey(
        BackupSnapshot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    is_deleted = models.BooleanField(default=False)

    class Meta:
        unique_together = ("vault", "relative_path")
        ordering = ["relative_path"]

    def __str__(self) -> str:
        return self.relative_path


class DocumentRevision(TimestampedModel):
    document = models.ForeignKey(VaultDocument, on_delete=models.CASCADE, related_name="revisions")
    snapshot = models.ForeignKey(
        BackupSnapshot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revisions",
    )
    parent_revision = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    branch_name = models.CharField(max_length=80, default="main")
    revision_index = models.PositiveIntegerField()
    checksum = models.CharField(max_length=64)
    content_path = models.CharField(max_length=500)
    diff_summary = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("document", "revision_index")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.document.relative_path} r{self.revision_index}"

    @property
    def display_label(self) -> str:
        return f"r{self.revision_index} ({self.created_at:%Y-%m-%d %H:%M})"
