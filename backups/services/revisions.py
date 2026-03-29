from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from backups.models import DocumentRevision
from backups.services.history import build_diff_summary


def create_branch_from_revision(
    revision: DocumentRevision,
    branch_name: str | None = None,
) -> DocumentRevision:
    target_branch = branch_name or _generated_branch_name(revision, prefix="branch")
    restored_path = _copy_revision_content(revision, target_branch)
    checksum = _sha256(restored_path)

    branched_revision = DocumentRevision.objects.create(
        document=revision.document,
        snapshot=None,
        parent_revision=revision,
        branch_name=target_branch,
        revision_index=_next_revision_index(revision),
        checksum=checksum,
        content_path=str(restored_path),
        diff_summary=f"Branch created from r{revision.revision_index} on {target_branch}",
        metadata={
            "operation": "branch_create",
            "source_revision_id": revision.pk,
            "branch_name": target_branch,
        },
    )
    _apply_revision_to_live_document(branched_revision)
    return branched_revision


def restore_revision_to_branch(
    revision: DocumentRevision,
    branch_name: str = "main",
) -> DocumentRevision:
    parent = (
        revision.document.revisions.filter(branch_name=branch_name)
        .order_by("-revision_index")
        .first()
    )
    restored_path = _copy_revision_content(revision, branch_name)
    checksum = _sha256(restored_path)
    previous_path = Path(parent.content_path) if parent and parent.content_path else None
    diff_summary = build_diff_summary(previous_path, restored_path)
    if diff_summary:
        diff_summary = f"Restored to {branch_name}\n{diff_summary}"
    else:
        diff_summary = f"Restored to {branch_name}"

    restored_revision = DocumentRevision.objects.create(
        document=revision.document,
        snapshot=None,
        parent_revision=parent or revision,
        branch_name=branch_name,
        revision_index=_next_revision_index(revision),
        checksum=checksum,
        content_path=str(restored_path),
        diff_summary=diff_summary,
        metadata={
            "operation": "restore",
            "source_revision_id": revision.pk,
            "branch_name": branch_name,
        },
    )
    _apply_revision_to_live_document(restored_revision)
    return restored_revision


def merge_revision_to_branch(
    revision: DocumentRevision,
    branch_name: str = "main",
) -> DocumentRevision:
    target_head = (
        revision.document.revisions.filter(branch_name=branch_name)
        .order_by("-revision_index")
        .first()
    )
    if target_head and target_head.pk == revision.pk:
        raise ValueError(f"Revision r{revision.revision_index} is already the head of {branch_name}.")

    merged_path = _copy_revision_content(revision, branch_name)
    checksum = _sha256(merged_path)
    previous_path = Path(target_head.content_path) if target_head and target_head.content_path else None
    diff_summary = build_diff_summary(previous_path, merged_path)
    if diff_summary:
        diff_summary = (
            f"Merged {revision.branch_name} r{revision.revision_index} into {branch_name}\n{diff_summary}"
        )
    else:
        diff_summary = f"Merged {revision.branch_name} r{revision.revision_index} into {branch_name}"

    merged_revision = DocumentRevision.objects.create(
        document=revision.document,
        snapshot=None,
        parent_revision=target_head or revision,
        branch_name=branch_name,
        revision_index=_next_revision_index(revision),
        checksum=checksum,
        content_path=str(merged_path),
        diff_summary=diff_summary,
        metadata={
            "operation": "merge",
            "source_revision_id": revision.pk,
            "source_branch_name": revision.branch_name,
            "target_branch_name": branch_name,
            "merge_parent_revision_id": revision.pk,
        },
    )
    _apply_revision_to_live_document(merged_revision)
    return merged_revision


def checkout_branch_head(document_revision: DocumentRevision, branch_name: str = "main") -> DocumentRevision:
    branch_head = (
        document_revision.document.revisions.filter(branch_name=branch_name)
        .order_by("-revision_index")
        .first()
    )
    if branch_head is None:
        raise ValueError(f"Branch {branch_name} has no revisions for this document.")

    _apply_revision_to_live_document(branch_head)
    return branch_head


def _generated_branch_name(revision: DocumentRevision, prefix: str) -> str:
    timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    return slugify(f"{prefix}-r{revision.revision_index}-{timestamp}")


def _apply_revision_to_live_document(revision: DocumentRevision) -> Path:
    source_path = Path(revision.content_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Revision content missing: {source_path}")

    live_path = Path(revision.document.vault.source_path) / revision.document.relative_path
    live_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, live_path)

    revision.document.latest_checksum = revision.checksum
    revision.document.active_branch = revision.branch_name
    revision.document.is_deleted = False
    revision.document.save(update_fields=["latest_checksum", "active_branch", "is_deleted", "updated_at"])
    return live_path


def _copy_revision_content(revision: DocumentRevision, branch_name: str) -> Path:
    source_path = Path(revision.content_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Revision content missing: {source_path}")

    suffix = source_path.suffix
    filename = (
        f"{timezone.now().strftime('%Y%m%d-%H%M%S')}-r{revision.revision_index}{suffix}"
        if suffix
        else f"{timezone.now().strftime('%Y%m%d-%H%M%S')}-r{revision.revision_index}"
    )
    target_dir = (
        Path(settings.BACKUP_STORAGE_ROOT)
        / "branches"
        / revision.document.vault.slug
        / str(revision.document_id)
        / slugify(branch_name)
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    shutil.copy2(source_path, target_path)
    return target_path


def _next_revision_index(revision: DocumentRevision) -> int:
    latest = revision.document.revisions.order_by("-revision_index").first()
    return (latest.revision_index if latest else 0) + 1


def _sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
