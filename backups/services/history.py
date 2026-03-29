from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

from backups.models import DocumentRevision


@dataclass(slots=True)
class RevisionDiff:
    current: DocumentRevision
    previous: DocumentRevision | None
    diff: str
    current_content: str
    previous_content: str
    is_binary: bool = False


def build_revision_diff(revision: DocumentRevision) -> RevisionDiff:
    previous = (
        revision.document.revisions.filter(revision_index__lt=revision.revision_index)
        .order_by("-revision_index")
        .first()
    )

    current_content, current_binary = _read_content(Path(revision.content_path))
    previous_content = ""
    previous_binary = False

    if previous:
        previous_content, previous_binary = _read_content(Path(previous.content_path))

    is_binary = current_binary or previous_binary
    diff = ""
    if not is_binary:
        diff = "\n".join(
            unified_diff(
                previous_content.splitlines(),
                current_content.splitlines(),
                fromfile=previous.display_label if previous else "empty",
                tofile=revision.display_label,
                lineterm="",
            )
        )

    return RevisionDiff(
        current=revision,
        previous=previous,
        diff=diff,
        current_content=current_content,
        previous_content=previous_content,
        is_binary=is_binary,
    )


def build_diff_summary(previous_path: Path | None, current_path: Path) -> str:
    current_content, current_binary = _read_content(current_path)

    if previous_path is None:
        return "Initial revision"

    previous_content, previous_binary = _read_content(previous_path)

    if current_binary or previous_binary:
        return "Binary content changed"

    previous_lines = previous_content.splitlines()
    current_lines = current_content.splitlines()
    diff_lines = list(
        unified_diff(
            previous_lines,
            current_lines,
            fromfile=previous_path.name,
            tofile=current_path.name,
            lineterm="",
        )
    )

    if not diff_lines:
        return "No textual changes detected"

    additions = sum(
        1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
    )
    deletions = sum(
        1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
    )
    preview = [
        line
        for line in diff_lines
        if line.startswith("@@") or (line.startswith("+") and not line.startswith("+++")) or (line.startswith("-") and not line.startswith("---"))
    ][:8]
    summary_header = f"+{additions} -{deletions}"

    if not preview:
        return summary_header

    return f"{summary_header}\n" + "\n".join(preview)


def _read_content(file_path: Path) -> tuple[str, bool]:
    try:
        return file_path.read_text(encoding="utf-8"), False
    except UnicodeDecodeError:
        return "[binary content omitted]", True
    except FileNotFoundError:
        return "[snapshot file missing]", False
