import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from backups.models import BackupSnapshot, DocumentRevision, Vault, VaultDocument
from backups.services.history import build_diff_summary

DEFAULT_EXCLUDES = {
    ".DS_Store",
    ".git",
    ".obsidian/workspace.json",
    ".obsidian/workspace-mobile.json",
    ".trash",
}


@dataclass(slots=True)
class SnapshotStats:
    file_count: int = 0
    total_bytes: int = 0


def create_snapshot(vault: Vault, trigger: str = BackupSnapshot.Trigger.MANUAL) -> BackupSnapshot:
    snapshot = BackupSnapshot.objects.create(
        vault=vault,
        trigger=trigger,
        status=BackupSnapshot.Status.RUNNING,
        started_at=timezone.now(),
    )

    try:
        stats, snapshot_dir = _copy_vault(vault, snapshot)
        _refresh_documents(vault, snapshot, snapshot_dir)
        snapshot.status = BackupSnapshot.Status.SUCCESS
        snapshot.finished_at = timezone.now()
        snapshot.snapshot_path = str(snapshot_dir)
        snapshot.file_count = stats.file_count
        snapshot.total_bytes = stats.total_bytes
        snapshot.manifest = {
            "source_path": vault.source_path,
            "snapshot_path": str(snapshot_dir),
            "exclude_patterns": sorted(DEFAULT_EXCLUDES | set(vault.exclude_patterns)),
        }
        snapshot.save(
            update_fields=[
                "status",
                "finished_at",
                "snapshot_path",
                "file_count",
                "total_bytes",
                "manifest",
                "updated_at",
            ]
        )
        _prune_old_snapshots(vault)
    except Exception as exc:
        snapshot.status = BackupSnapshot.Status.FAILED
        snapshot.finished_at = timezone.now()
        snapshot.notes = str(exc)
        snapshot.save(update_fields=["status", "finished_at", "notes", "updated_at"])
        raise

    return snapshot


def run_due_snapshots() -> list[BackupSnapshot]:
    created: list[BackupSnapshot] = []
    now = timezone.now()

    for vault in Vault.objects.filter(is_active=True):
        last_snapshot = vault.snapshots.filter(status=BackupSnapshot.Status.SUCCESS).first()
        if last_snapshot is None:
            created.append(create_snapshot(vault, BackupSnapshot.Trigger.SCHEDULED))
            continue

        age_minutes = (now - last_snapshot.created_at).total_seconds() / 60
        if age_minutes >= vault.snapshot_interval_minutes:
            created.append(create_snapshot(vault, BackupSnapshot.Trigger.SCHEDULED))

    return created


def run_scheduler_loop(interval_seconds: int = 60) -> None:
    while True:
        run_due_snapshots()
        time.sleep(interval_seconds)


def _copy_vault(vault: Vault, snapshot: BackupSnapshot) -> tuple[SnapshotStats, Path]:
    source_root = Path(vault.source_path).expanduser().resolve()
    if not source_root.exists() or not source_root.is_dir():
        raise FileNotFoundError(f"Vault path does not exist: {source_root}")

    timestamp = timezone.localtime(snapshot.created_at).strftime("%Y%m%d-%H%M%S-%f")
    snapshot_dir = Path(settings.BACKUP_STORAGE_ROOT) / vault.slug / f"{timestamp}-s{snapshot.pk}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    stats = SnapshotStats()
    excludes = DEFAULT_EXCLUDES | set(vault.exclude_patterns)

    for file_path in source_root.rglob("*"):
        if file_path.is_dir():
            continue

        relative_path = file_path.relative_to(source_root).as_posix()
        if _is_excluded(relative_path, excludes):
            continue

        target_path = snapshot_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target_path)
        stats.file_count += 1
        stats.total_bytes += file_path.stat().st_size

    return stats, snapshot_dir


def _refresh_documents(vault: Vault, snapshot: BackupSnapshot, snapshot_dir: Path) -> None:
    known_paths: set[str] = set()

    with transaction.atomic():
        for file_path in snapshot_dir.rglob("*"):
            if file_path.is_dir():
                continue

            relative_path = file_path.relative_to(snapshot_dir).as_posix()
            known_paths.add(relative_path)
            checksum = _sha256(file_path)
            document, _ = VaultDocument.objects.get_or_create(
                vault=vault,
                relative_path=relative_path,
                defaults={
                    "active_branch": "main",
                    "latest_checksum": checksum,
                    "last_snapshot": snapshot,
                },
            )

            previous_revision = (
                document.revisions.filter(branch_name=document.active_branch)
                .order_by("-revision_index")
                .first()
            )
            changed = checksum != document.latest_checksum
            document.latest_checksum = checksum
            document.last_snapshot = snapshot
            document.is_deleted = False
            document.save(
                update_fields=[
                    "latest_checksum",
                    "last_snapshot",
                    "is_deleted",
                    "updated_at",
                ]
            )

            if changed or document.revisions.count() == 0:
                latest_revision = document.revisions.order_by("-revision_index").first()
                revision_index = (latest_revision.revision_index if latest_revision else 0) + 1
                previous_path = (
                    Path(previous_revision.content_path)
                    if previous_revision and previous_revision.content_path
                    else None
                )
                DocumentRevision.objects.create(
                    document=document,
                    snapshot=snapshot,
                    parent_revision=previous_revision,
                    branch_name=document.active_branch,
                    revision_index=revision_index,
                    checksum=checksum,
                    content_path=str(file_path),
                    diff_summary=build_diff_summary(previous_path, file_path),
                    metadata={"size": file_path.stat().st_size},
                )

        VaultDocument.objects.filter(vault=vault).exclude(relative_path__in=known_paths).update(is_deleted=True)


def _prune_old_snapshots(vault: Vault) -> None:
    snapshots = list(vault.snapshots.filter(status=BackupSnapshot.Status.SUCCESS))
    stale = snapshots[vault.retention_snapshots :]

    for snapshot in stale:
        if snapshot.snapshot_path:
            shutil.rmtree(snapshot.snapshot_path, ignore_errors=True)
        snapshot.delete()


def _is_excluded(relative_path: str, excludes: set[str]) -> bool:
    for excluded in excludes:
        cleaned = excluded.strip("/")
        if relative_path == cleaned or relative_path.startswith(f"{cleaned}/"):
            return True
    return False


def _sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
