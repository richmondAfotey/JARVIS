"""
Clipboard helpers (Phase 32) - paste images and files into JARVIS.

Two paste sources, both read from the Windows clipboard on demand:

* ``paste_image``   - grabs whatever image is on the clipboard
  (a copied screenshot or a copied image) and saves it to the uploads
  folder as a PNG/JPEG.
* ``paste_files``   - grabs a copied set of files (FileDropList) and
  copies each into the uploads folder, returning the local paths.

The clipboard is only ever *read* when the user clicks the paste button -
never monitored in the background. Missing helper libraries degrade to a
clear error message instead of a crash.
"""

from __future__ import annotations

import datetime
import shutil
from pathlib import Path

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")


def _stamp(name: str) -> str:
    return datetime.datetime.now().strftime(name)


def paste_image(target_dir: Path) -> Path | None:
    """Save the clipboard image (if any) into ``target_dir``.

    Returns the saved path, or None when the clipboard holds no image.
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        raise RuntimeError(
            "Pasting images needs the 'Pillow' library. Run: pip install Pillow"
        )
    try:
        image = ImageGrab.grabclipboard()
    except Exception as exc:  # platform clipboard quirks must not crash
        raise RuntimeError(f"Could not read the clipboard: {exc}") from exc
    if image is None:
        return None
    if isinstance(image, list):
        return None  # that was a file list, not an image

    target_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(image, Path) or isinstance(image, str):
        # Clipboard may hand back a filename rather than an image object.
        src = Path(image)
        if not src.exists():
            return None
        dst = target_dir / (_stamp("pasted_%Y%m%d_%H%M%S") + src.suffix.lower())
        shutil.copy2(src, dst)
        return dst

    # A PIL Image: normalise to RGB PNG so any source format round-trips.
    try:
        image = image.convert("RGB")
    except Exception:
        pass
    dst = target_dir / (_stamp("pasted_%Y%m%d_%H%M%S") + ".png")
    image.save(dst, "PNG")
    return dst


def paste_files(target_dir: Path) -> list[Path]:
    """Copy the clipboard's copied file list (FileDropList) to ``target_dir``.

    Returns the list of saved paths (empty when no files are copied).
    """
    try:
        import win32clipboard
    except ImportError:
        raise RuntimeError(
            "Pasting files needs the 'pywin32' library. Run: pip install pywin32"
        )

    paths: list[str] = []
    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(
                win32clipboard.CF_HDROP
            ):
                paths = list(win32clipboard.GetClipboardData(win32clipboard.CF_HDROP) or ())
        finally:
            win32clipboard.CloseClipboard()
    except Exception as exc:  # clipboard access can race another app
        raise RuntimeError(f"Could not read the clipboard: {exc}") from exc

    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for raw in paths:
        src = Path(raw)
        if not src.is_file():
            continue
        dst = target_dir / src.name
        if dst.exists():
            dst = target_dir / (
                _stamp("pasted_%Y%m%d_%H%M%S") + "_" + src.name
            )
        try:
            shutil.copy2(src, dst)
            saved.append(dst)
        except OSError:
            continue
    return saved


def paste_anything(target_dir: Path) -> list[Path]:
    """Paste whichever of an image or file list is on the clipboard.

    Prefers an image (the common screenshot case); falls back to a copied
    file list. Returns the saved paths (possibly empty when nothing was
    pastable), and raises RuntimeError when no clipboard support exists.
    """
    try:
        image = paste_image(target_dir)
    except RuntimeError:
        image = None
    if image is not None:
        return [image]
    try:
        return paste_files(target_dir)
    except RuntimeError:
        return [] if image is None else [image]
