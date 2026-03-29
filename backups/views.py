from django.db.models import Count, Sum
from django.http import HttpRequest

from backups.models import BackupSnapshot, Vault, VaultDocument


def admin_dashboard_callback(request: HttpRequest, context: dict) -> dict:
    vaults = Vault.objects.annotate(
        snapshot_total=Count("snapshots"),
        document_total=Count("documents"),
    ).order_by("name")
    snapshots = BackupSnapshot.objects.select_related("vault").order_by("-created_at")[:8]
    context.update(
        {
            "dashboard_metrics": {
                "vaults": vaults.count(),
                "snapshots": BackupSnapshot.objects.count(),
                "documents": VaultDocument.objects.count(),
                "bytes": BackupSnapshot.objects.aggregate(total=Sum("total_bytes"))["total"] or 0,
            },
            "dashboard_vaults": vaults[:6],
            "dashboard_snapshots": snapshots,
            "dashboard_failed_snapshots": BackupSnapshot.objects.filter(
                status=BackupSnapshot.Status.FAILED
            ).count(),
        }
    )
    return context
