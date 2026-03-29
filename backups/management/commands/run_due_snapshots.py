from django.core.management.base import BaseCommand

from backups.services.snapshots import run_due_snapshots


class Command(BaseCommand):
    help = "Create scheduled snapshots for all active vaults that are due"

    def handle(self, *args, **options):
        created = run_due_snapshots()
        self.stdout.write(self.style.SUCCESS(f"Created {len(created)} snapshot(s)"))
