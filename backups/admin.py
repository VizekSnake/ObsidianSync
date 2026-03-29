import json

from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpRequest
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse, reverse_lazy
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import action, display
from unfold.enums import ActionVariant
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from backups.models import BackupSnapshot, DocumentRevision, Vault, VaultDocument
from backups.services.history import build_revision_diff
from backups.services.revisions import (
    checkout_branch_head,
    create_branch_from_revision,
    merge_revision_to_branch,
    restore_revision_to_branch,
)
from backups.services.snapshots import create_snapshot

admin.site.site_header = "ObsidianSync Admin"
admin.site.site_title = "ObsidianSync"
admin.site.index_title = "Vaults, snapshoty i rewizje"

admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


@admin.register(Vault)
class VaultAdmin(ModelAdmin):
    list_display = (
        "vault_identity",
        "source_path",
        "snapshot_interval_minutes",
        "retention_snapshots",
        "is_active",
        "last_snapshot_status",
    )
    list_filter = ("is_active",)
    search_fields = ("name", "source_path")
    readonly_fields = ("last_successful_snapshot",)
    list_fullwidth = False
    warn_unsaved_form = True
    actions_row = ["run_snapshot_action"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "slug",
                    "source_path",
                    "is_active",
                    "last_successful_snapshot",
                )
            },
        ),
        (
            "Snapshot policy",
            {"fields": ("snapshot_interval_minutes", "retention_snapshots", "exclude_patterns")},
        ),
    )

    @display(description=_("Vault"), header=True)
    def vault_identity(self, obj: Vault):
        return [
            obj.name,
            obj.source_path,
            obj.name[:2].upper(),
        ]

    @display(
        description=_("Last snapshot"),
        label={
            BackupSnapshot.Status.SUCCESS: "success",
            BackupSnapshot.Status.RUNNING: "info",
            BackupSnapshot.Status.PENDING: "warning",
            BackupSnapshot.Status.FAILED: "danger",
            None: "warning",
        },
    )
    def last_snapshot_status(self, obj: Vault):
        snapshot = obj.last_successful_snapshot or obj.snapshots.first()
        if snapshot is None:
            return None, _("No snapshots")
        return snapshot.status, snapshot.get_status_display()

    @action(
        description=_("Run snapshot"),
        permissions=["run_snapshot_action"],
        url_path="run-snapshot",
        variant=ActionVariant.PRIMARY,
    )
    def run_snapshot_action(self, request: HttpRequest, object_id: int):
        vault = Vault.objects.get(pk=object_id)
        try:
            snapshot = create_snapshot(vault)
        except Exception as exc:
            self.message_user(
                request,
                _("Snapshot failed for %(vault)s: %(error)s")
                % {"vault": vault.name, "error": exc},
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                _("Snapshot %(snapshot)s created for %(vault)s")
                % {"snapshot": snapshot.pk, "vault": vault.name},
                level=messages.SUCCESS,
            )
        return redirect(reverse_lazy("admin:backups_vault_changelist"))

    def has_run_snapshot_action_permission(self, request: HttpRequest):
        return request.user.is_staff


@admin.register(BackupSnapshot)
class BackupSnapshotAdmin(ModelAdmin):
    list_display = (
        "snapshot_identity",
        "status_badge",
        "trigger_badge",
        "created_at",
        "file_count",
        "total_bytes",
    )
    list_filter = ("status", "trigger", "vault")
    search_fields = ("vault__name", "snapshot_path", "notes")
    readonly_fields = ("manifest",)
    list_fullwidth = False
    warn_unsaved_form = True

    @display(description=_("Snapshot"), header=True)
    def snapshot_identity(self, obj: BackupSnapshot):
        return [
            obj.vault.name,
            obj.snapshot_path or _("Pending path"),
            f"#{obj.pk}",
        ]

    @display(
        description=_("Status"),
        ordering="status",
        label={
            BackupSnapshot.Status.SUCCESS: "success",
            BackupSnapshot.Status.RUNNING: "info",
            BackupSnapshot.Status.PENDING: "warning",
            BackupSnapshot.Status.FAILED: "danger",
        },
    )
    def status_badge(self, obj: BackupSnapshot):
        return obj.status, obj.get_status_display()

    @display(
        description=_("Trigger"),
        ordering="trigger",
        label={
            BackupSnapshot.Trigger.MANUAL: "info",
            BackupSnapshot.Trigger.SCHEDULED: "success",
            BackupSnapshot.Trigger.WEBHOOK: "warning",
        },
    )
    def trigger_badge(self, obj: BackupSnapshot):
        return obj.trigger, obj.get_trigger_display()


@admin.register(VaultDocument)
class VaultDocumentAdmin(ModelAdmin):
    list_display = (
        "document_identity",
        "active_branch",
        "latest_checksum",
        "deleted_badge",
        "graph_link",
        "updated_at",
    )
    list_filter = ("vault", "is_deleted")
    search_fields = ("relative_path",)
    list_fullwidth = False
    readonly_fields = ("active_branch", "graph_link", "revision_tree")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "vault",
                    "relative_path",
                    "active_branch",
                    "latest_checksum",
                    "last_snapshot",
                    "is_deleted",
                    "graph_link",
                )
            },
        ),
        (
            "Revision graph",
            {
                "fields": ("revision_tree",),
            },
        ),
    )

    @display(description=_("Document"), header=True)
    def document_identity(self, obj: VaultDocument):
        return [
            obj.relative_path,
            obj.vault.name,
        ]

    @display(
        description=_("Deleted"),
        boolean=True,
    )
    def deleted_badge(self, obj: VaultDocument):
        return obj.is_deleted

    @display(description=_("Graph"))
    def graph_link(self, obj: VaultDocument):
        url = reverse_lazy("admin:backups_vaultdocument_graph", args=[obj.pk])
        return format_html('<a href="{}">Open revision graph</a>', url)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/graph/",
                self.admin_site.admin_view(self.revision_graph_view),
                name="backups_vaultdocument_graph",
            )
        ]
        return custom_urls + urls

    def revision_graph_view(self, request: HttpRequest, object_id: str):
        document = self.get_object(request, object_id)
        if document is None:
            return redirect(reverse_lazy("admin:backups_vaultdocument_changelist"))

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": document,
            "title": _("Revision graph"),
            "document": document,
            "graph_payload": json.dumps(self._graph_payload(document), cls=DjangoJSONEncoder),
        }
        return TemplateResponse(
            request,
            "admin/backups/revision_graph.html",
            context,
        )

    @display(description=_("Revision tree"))
    def revision_tree(self, obj: VaultDocument):
        revisions = list(obj.revisions.select_related("snapshot").order_by("-revision_index"))
        if not revisions:
            return _("No revisions yet.")

        lane_palette = [
            "rgb(var(--color-primary-600))",
            "rgb(var(--color-info-600))",
            "rgb(var(--color-success-600))",
            "rgb(var(--color-warning-600))",
            "rgb(var(--color-red-600))",
            "rgb(var(--color-purple-600))",
        ]
        lane_map: dict[str, int] = {}
        nodes = []
        total = len(revisions)
        for index, revision in enumerate(revisions):
            lane = lane_map.setdefault(revision.branch_name, len(lane_map))
            lane_color = lane_palette[lane % len(lane_palette)]
            summary = revision.diff_summary or _("No summary")
            preview = "<br>".join(summary.splitlines()[:4])
            snapshot_label = f"#{revision.snapshot_id}" if revision.snapshot_id else _("No snapshot")
            revision_url = reverse_lazy("admin:backups_documentrevision_change", args=[revision.pk])
            node_color = lane_color
            if summary == "Initial revision":
                node_color = lane_color
            elif "Binary" in summary:
                node_color = "var(--color-warning-600)"
            elif summary.startswith("+0 -0") or summary == "No textual changes detected":
                node_color = "var(--color-base-500)"
            lane_left = 16 + (lane * 18)
            connector = "" if index == total - 1 else f'<div style="position:absolute; left:{lane_left}px; top:22px; bottom:-14px; width:2px; background:{lane_color}; opacity:.45;"></div>'
            parent_label = f"r{revision.parent_revision.revision_index}" if revision.parent_revision_id else "root"
            parent_connector = ""
            if revision.parent_revision_id:
                parent_lane = lane_map.setdefault(
                    revision.parent_revision.branch_name,
                    len(lane_map),
                )
                parent_left = 12 + (parent_lane * 18)
                if parent_left != lane_left:
                    left = min(parent_left, lane_left)
                    width = abs(parent_left - lane_left)
                    parent_connector = (
                        f'<div style="position:absolute; left:{left}px; top:8px; width:{width}px; height:2px; '
                        f'background:{lane_color}; opacity:.45;"></div>'
                    )
            nodes.append(
                f"""
                <div style="position:relative; display:grid; grid-template-columns:96px minmax(0,1fr); gap:14px; padding:0 0 16px;">
                  <div style="position:relative; min-height:22px;">
                    {parent_connector}
                    <div style="position:absolute; left:{lane_left}px; top:2px; width:10px; height:10px; border-radius:5px; background:{node_color}; box-shadow:0 0 0 3px color-mix(in srgb, {node_color} 14%, transparent);"></div>
                    {connector}
                    <div style="position:absolute; left:50px; top:0; font-size:11px; color:var(--color-base-500); font-weight:600; white-space:nowrap;">{revision.branch_name}</div>
                  </div>
                  <div style="border:1px solid var(--color-base-200); border-radius:6px; padding:12px 14px; background:var(--color-base-50); box-shadow:0 1px 2px rgba(15,23,42,.04);">
                    <div style="display:flex; justify-content:space-between; gap:12px; align-items:start; flex-wrap:wrap;">
                      <strong style="font-size:13px; line-height:1.4;"><a href="{revision_url}">{revision.display_label}</a></strong>
                      <span style="font-size:11px; color:var(--color-base-500); white-space:nowrap;">{snapshot_label}</span>
                    </div>
                    <div style="margin-top:8px; display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
                      <span style="font-size:11px; padding:3px 8px; border-radius:6px; background:color-mix(in srgb, {lane_color} 12%, transparent); color:{lane_color}; border:1px solid color-mix(in srgb, {lane_color} 18%, transparent);">{revision.branch_name}</span>
                      <span style="font-size:11px; padding:3px 8px; border-radius:6px; background:var(--color-base-100); color:var(--color-base-700); border:1px solid var(--color-base-200);">parent {parent_label}</span>
                      <span style="font-size:11px; padding:3px 8px; border-radius:6px; background:var(--color-base-100); color:var(--color-base-500); border:1px solid var(--color-base-200);">r{revision.revision_index}</span>
                    </div>
                    <div style="margin-top:8px; font-size:11px; color:var(--color-base-500); font-family:ui-monospace, SFMono-Regular, Menlo, monospace; overflow:hidden; text-overflow:ellipsis;">{revision.checksum}</div>
                    <div style="margin-top:10px; font-size:12px; line-height:1.55; color:var(--color-base-700);">{preview}</div>
                  </div>
                </div>
                """
            )

        return format_html(
            """
            <div style="display:grid; gap:8px; padding:6px 0;">
              <div>{}</div>
              <div style="font-size:12px;"><a href="{}">Open full revision graph</a></div>
            </div>
            """,
            format_html("".join(nodes[:6])),
            reverse_lazy("admin:backups_vaultdocument_graph", args=[obj.pk]),
        )

    def _graph_payload(self, obj: VaultDocument):
        revisions = list(obj.revisions.select_related("snapshot", "parent_revision").order_by("-revision_index"))
        revision_by_id = {revision.pk: revision for revision in revisions}
        lane_map: dict[str, int] = {}
        nodes = []
        for revision in revisions:
            lane = lane_map.setdefault(revision.branch_name, len(lane_map))
            parent_lane = None
            if revision.parent_revision_id:
                parent_lane = lane_map.setdefault(
                    revision.parent_revision.branch_name,
                    len(lane_map),
                )
            merge_parent_id = revision.metadata.get("merge_parent_revision_id")
            merge_parent = revision_by_id.get(merge_parent_id)
            merge_parent_lane = None
            if merge_parent is not None:
                merge_parent_lane = lane_map.setdefault(
                    merge_parent.branch_name,
                    len(lane_map),
                )
            nodes.append(
                {
                    "id": revision.pk,
                    "label": str(revision.display_label),
                    "branch": str(revision.branch_name),
                    "lane": lane,
                    "parent_id": revision.parent_revision_id,
                    "parent_lane": parent_lane,
                    "parent_label": f"r{revision.parent_revision.revision_index}"
                    if revision.parent_revision_id
                    else "root",
                    "snapshot": revision.snapshot_id,
                    "revision_index": revision.revision_index,
                    "summary": str(revision.diff_summary or "No summary"),
                    "checksum": str(revision.checksum),
                    "url": reverse("admin:backups_documentrevision_change", args=[revision.pk]),
                    "created_at": revision.created_at.isoformat(),
                    "operation": str(revision.metadata.get("operation", "snapshot")),
                    "merge_parent_id": merge_parent_id,
                    "merge_parent_lane": merge_parent_lane,
                    "merge_parent_label": f"r{merge_parent.revision_index}" if merge_parent is not None else None,
                    "merge_source_branch": str(revision.metadata.get("source_branch_name", "")),
                    "is_binary": "Binary" in (revision.diff_summary or ""),
                    "is_initial": revision.diff_summary == "Initial revision",
                }
            )
        return {
            "document": {
                "path": str(obj.relative_path),
                "vault": str(obj.vault.name),
                "active_branch": str(obj.active_branch),
            },
            "branches": sorted({str(revision.branch_name) for revision in revisions}),
            "nodes": nodes,
        }


@admin.register(DocumentRevision)
class DocumentRevisionAdmin(ModelAdmin):
    list_display = (
        "revision_identity",
        "branch_badge",
        "revision_index",
        "parent_revision_link",
        "document_graph_link",
        "checksum",
        "created_at",
    )
    list_filter = ("document__vault",)
    search_fields = ("document__relative_path", "checksum")
    list_fullwidth = False
    readonly_fields = ("full_diff",)
    actions_row = [
        "create_branch_action",
        "checkout_branch_action",
        "checkout_main_head_action",
        "apply_revision_to_main_action",
        "merge_to_main_action",
    ]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "document",
                    "snapshot",
                    "branch_name",
                    "parent_revision",
                    "revision_index",
                    "checksum",
                    "content_path",
                    "diff_summary",
                    "metadata",
                )
            },
        ),
        (
            "Full diff",
            {
                "fields": ("full_diff",),
            },
        ),
    )

    @display(description=_("Revision"), header=True)
    def revision_identity(self, obj: DocumentRevision):
        return [
            obj.document.relative_path,
            obj.document.vault.name,
            f"r{obj.revision_index}",
        ]

    @display(description=_("Branch"))
    def branch_badge(self, obj: DocumentRevision):
        is_active = obj.document.active_branch == obj.branch_name
        tone = "rgb(var(--color-primary-600))" if is_active else "var(--color-base-600)"
        bg = "rgb(var(--color-primary-50))" if is_active else "var(--color-base-100)"
        active_badge = ""
        if is_active:
            active_badge = (
                '<span style="font-size:10px; padding:2px 6px; border-radius:999px; '
                'background:rgb(var(--color-success-100)); color:rgb(var(--color-success-700)); '
                'border:1px solid rgb(var(--color-success-200));">active</span>'
            )
        return format_html(
            '<div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">'
            '<span style="font-size:11px; padding:3px 8px; border-radius:6px; color:{}; background:{}; '
            'border:1px solid var(--color-base-200);">{}</span>{}</div>',
            tone,
            bg,
            obj.branch_name,
            format_html(active_badge) if active_badge else "",
        )

    @display(description=_("Parent"))
    def parent_revision_link(self, obj: DocumentRevision):
        if not obj.parent_revision_id:
            return _("Root")

        url = reverse_lazy("admin:backups_documentrevision_change", args=[obj.parent_revision_id])
        return format_html('<a href="{}">r{}</a>', url, obj.parent_revision.revision_index)

    @display(description=_("Graph"))
    def document_graph_link(self, obj: DocumentRevision):
        url = reverse_lazy("admin:backups_vaultdocument_graph", args=[obj.document_id])
        return format_html('<a href="{}">Open graph</a>', url)

    @display(description=_("Full diff"))
    def full_diff(self, obj: DocumentRevision):
        bundle = build_revision_diff(obj)
        if bundle.is_binary:
            return _("Binary content detected. Full text diff unavailable.")

        if not bundle.diff:
            return _("No textual changes detected.")

        return format_html(
            '<pre style="white-space:pre-wrap; overflow:auto; max-height:720px; padding:14px; border:1px solid var(--color-base-200); border-radius:6px; background:var(--color-base-50);">{}</pre>',
            bundle.diff,
        )

    @action(
        description=_("Create branch"),
        permissions=["create_branch_action"],
        url_path="create-branch",
        variant=ActionVariant.DEFAULT,
    )
    def create_branch_action(self, request: HttpRequest, object_id: int):
        revision = DocumentRevision.objects.select_related("document", "document__vault").get(pk=object_id)
        try:
            branched = create_branch_from_revision(revision)
        except Exception as exc:
            self.message_user(
                request,
                _("Branch creation failed for r%(revision)s: %(error)s")
                % {"revision": revision.revision_index, "error": exc},
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                _("Created branch %(branch)s from r%(revision)s")
                % {"branch": branched.branch_name, "revision": revision.revision_index},
                level=messages.SUCCESS,
            )
        return redirect(
            reverse_lazy("admin:backups_documentrevision_change", args=[object_id])
        )

    @action(
        description=_("Checkout this branch"),
        permissions=["checkout_branch_action"],
        url_path="checkout-branch",
        variant=ActionVariant.DEFAULT,
    )
    def checkout_branch_action(self, request: HttpRequest, object_id: int):
        revision = DocumentRevision.objects.select_related("document", "document__vault").get(pk=object_id)
        try:
            checked_out = checkout_branch_head(revision, branch_name=revision.branch_name)
        except Exception as exc:
            self.message_user(
                request,
                _("Checkout %(branch)s failed for %(document)s: %(error)s")
                % {
                    "branch": revision.branch_name,
                    "document": revision.document.relative_path,
                    "error": exc,
                },
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                _("Checked out %(branch)s at r%(revision)s to the live document")
                % {
                    "branch": checked_out.branch_name,
                    "revision": checked_out.revision_index,
                },
                level=messages.SUCCESS,
            )
        return redirect(
            reverse_lazy("admin:backups_documentrevision_change", args=[object_id])
        )

    @action(
        description=_("Checkout main head"),
        permissions=["checkout_main_head_action"],
        url_path="checkout-main-head",
        variant=ActionVariant.DEFAULT,
    )
    def checkout_main_head_action(self, request: HttpRequest, object_id: int):
        revision = DocumentRevision.objects.select_related("document", "document__vault").get(pk=object_id)
        try:
            checked_out = checkout_branch_head(revision, branch_name="main")
        except Exception as exc:
            self.message_user(
                request,
                _("Checkout main head failed for %(document)s: %(error)s")
                % {"document": revision.document.relative_path, "error": exc},
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                _("Checked out main head r%(revision)s to the live document")
                % {"revision": checked_out.revision_index},
                level=messages.SUCCESS,
            )
        return redirect(
            reverse_lazy("admin:backups_documentrevision_change", args=[object_id])
        )

    @action(
        description=_("Apply this revision to main"),
        permissions=["apply_revision_to_main_action"],
        url_path="apply-revision-to-main",
        variant=ActionVariant.PRIMARY,
    )
    def apply_revision_to_main_action(self, request: HttpRequest, object_id: int):
        revision = DocumentRevision.objects.select_related("document", "document__vault").get(pk=object_id)
        try:
            restored = restore_revision_to_branch(revision, branch_name="main")
        except Exception as exc:
            self.message_user(
                request,
                _("Applying revision r%(revision)s to main failed: %(error)s")
                % {"revision": revision.revision_index, "error": exc},
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                _("Applied r%(revision)s to %(branch)s as r%(new_revision)s")
                % {
                    "revision": revision.revision_index,
                    "branch": restored.branch_name,
                    "new_revision": restored.revision_index,
                },
                level=messages.SUCCESS,
            )
        return redirect(
            reverse_lazy("admin:backups_documentrevision_change", args=[object_id])
        )

    @action(
        description=_("Merge to main"),
        permissions=["merge_to_main_action"],
        url_path="merge-to-main",
        variant=ActionVariant.PRIMARY,
    )
    def merge_to_main_action(self, request: HttpRequest, object_id: int):
        revision = DocumentRevision.objects.select_related("document", "document__vault").get(pk=object_id)
        try:
            merged = merge_revision_to_branch(revision, branch_name="main")
        except Exception as exc:
            self.message_user(
                request,
                _("Merge failed for r%(revision)s: %(error)s")
                % {"revision": revision.revision_index, "error": exc},
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                _("Merged %(branch)s r%(revision)s into %(target)s as r%(new_revision)s")
                % {
                    "branch": revision.branch_name,
                    "revision": revision.revision_index,
                    "target": merged.branch_name,
                    "new_revision": merged.revision_index,
                },
                level=messages.SUCCESS,
            )
        return redirect(
            reverse_lazy("admin:backups_documentrevision_change", args=[object_id])
        )

    def has_create_branch_action_permission(self, request: HttpRequest):
        return request.user.is_staff

    def has_checkout_branch_action_permission(self, request: HttpRequest):
        return request.user.is_staff

    def has_checkout_main_head_action_permission(self, request: HttpRequest):
        return request.user.is_staff

    def has_apply_revision_to_main_action_permission(self, request: HttpRequest):
        return request.user.is_staff

    def has_merge_to_main_action_permission(self, request: HttpRequest):
        return request.user.is_staff
