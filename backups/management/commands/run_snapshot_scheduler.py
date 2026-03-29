from django.core.management.base import BaseCommand

from backups.services.snapshots import run_due_snapshots, run_scheduler_loop


class Command(BaseCommand):
    help = "Run a long-lived scheduler loop that creates due snapshots"

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval-seconds",
            type=int,
            default=60,
            help="How often to check for due snapshots",
        )
        parser.add_argument(
            "--run-once",
            action="store_true",
            help="Run a single scheduling pass and exit",
        )

    def handle(self, *args, **options):
        interval_seconds = max(options["interval_seconds"], 5)
        if options["run_once"]:
            created = run_due_snapshots()
            self.stdout.write(self.style.SUCCESS(f"Created {len(created)} snapshot(s)"))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting scheduler loop, checking for due snapshots every {interval_seconds}s"
            )
        )
        run_scheduler_loop(interval_seconds=interval_seconds)
