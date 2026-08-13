"""
Attachment processing (Phase 32) - analyse uploaded/pasted files.

When a user attaches an image or document to a chat message, JARVIS reads
it *before* sending the message so the reply can be about the file:

* images   -> ``analyze_image`` (vision model) when a GOOGLE_API_KEY is
  configured, otherwise a textual note that the image was attached.
* documents -> ``read_document`` text extraction; the raw text is injected
  into the user message so the same-turn reply can answer from the file.

``build_user_message(attachments, user_text)`` returns the exact user
message that should reach the brain: the user's own words plus a compact
"<file_name>: <extracted>" context block for every attachment.
"""

from __future__ import annotations

from pathlib import Path

from tools.base import ToolError

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
_DOC_EXTS = (
    ".txt", ".md", ".log", ".csv", ".json", ".ini", ".yaml", ".yml",
    ".pdf", ".docx", ".xlsx", ".pptx",
)
# Guard against a huge document flooding the model context.
_MAX_DOC_CHARS = 4000


def classify(path: str | Path) -> str:
    """Return 'image', 'document' or 'other' for a file path."""
    ext = Path(str(path)).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _DOC_EXTS:
        return "document"
    return "other"


def _analyze_image(path: Path, question: str) -> str:
    from tools.vision import AnalyzeImageTool  # noqa: PLC0415

    try:
        answer = AnalyzeImageTool().execute(
            {"path": str(path), "question": question}
        )
    except ToolError as exc:
        # Vision not configured (no GOOGLE_API_KEY) or the model refused.
        return str(exc)
    return answer


def _read_document(path: Path) -> str:
    from tools.documents import ReadDocumentTool, _MAX_LIMIT_CHARS  # noqa: PLC0415

    try:
        text = ReadDocumentTool().execute(
            {"path": str(path), "max_chars": _MAX_LIMIT_CHARS}
        )
    except ToolError as exc:
        return str(exc)
    return text.strip()


def attachment_context(path: str | Path, user_text: str) -> str:
    """Extract a short text summary of one attachment for the prompt."""
    p = Path(str(path))
    kind = classify(p)
    if kind == "image":
        return _analyze_image(p, (user_text or "").strip() or "Describe this image.")
    if kind == "document":
        return _read_document(p)
    return f"[{p.name}] attached but its format is not supported for reading."


def build_user_message(attachments: list[str | Path], user_text: str) -> str:
    """Compose the brain-ready user message from attachments + text."""
    text = (user_text or "").strip()
    parts = [text] if text else []
    for attachment in attachments:
        p = Path(str(attachment))
        context = attachment_context(p, text)
        # Trim the context preview so one giant file cannot bloat the turn.
        preview = context[: _MAX_DOC_CHARS]
        if len(context) > _MAX_DOC_CHARS:
            preview += "... [truncated]"
        parts.append(f"\n[Attachment: {p.name}]\n{preview}")
    return "\n".join(parts)