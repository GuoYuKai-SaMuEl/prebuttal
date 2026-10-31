"""A LaTeX project as a .zip (Overleaf's "Download Source"), unpacked safely.

The archive is the user's own, but it may come from anywhere (a co-author, a
template site), so unpacking never trusts it: no member may land outside the
temporary folder, symlinks are skipped, and the unpacked size is capped while
writing (a member's declared size can lie).
"""

from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

MAX_MEMBERS = 10_000
MAX_BYTES = 512 * 1024 * 1024  # unpacked; figures included
_CHUNK = 1024 * 1024


class ArchiveError(Exception):
    pass


def _member_path(name: str) -> PurePosixPath | None:
    """The member's relative path, None for entries to skip; raises on escapes."""
    rel = PurePosixPath(name.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or (rel.parts and ":" in rel.parts[0]):
        raise ArchiveError(f"unsafe path in the archive: {name!r}")
    if not rel.parts or rel.parts[0] == "__MACOSX":
        return None
    return rel


@contextmanager
def unpacked_zip(path: Path) -> Iterator[Path]:
    """Unpack ``path`` into a temporary folder that lives for the ``with`` block."""
    folder = Path(tempfile.mkdtemp(prefix="prebuttal-zip-"))
    try:
        try:
            with zipfile.ZipFile(path) as zf:
                members = zf.infolist()
                if len(members) > MAX_MEMBERS:
                    raise ArchiveError(f"{path.name}: over {MAX_MEMBERS:,} files — not unpacked")
                written = 0
                for info in members:
                    rel = _member_path(info.filename)
                    if rel is None or info.is_dir():
                        continue
                    if stat.S_ISLNK(info.external_attr >> 16):
                        continue  # a symlink could point anywhere on this machine
                    target = folder.joinpath(*rel.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, target.open("wb") as dst:
                        while chunk := src.read(_CHUNK):
                            written += len(chunk)
                            if written > MAX_BYTES:
                                raise ArchiveError(
                                    f"{path.name}: unpacks to over {MAX_BYTES // 2**20} MB "
                                    "— not unpacked"
                                )
                            dst.write(chunk)
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as e:
            raise ArchiveError(f"{path.name}: not a readable .zip archive ({e})") from e
        except RuntimeError as e:  # encrypted members
            raise ArchiveError(f"{path.name}: {e}") from e
        except OSError as e:
            raise ArchiveError(f"{path.name}: cannot unpack: {e}") from e
        if not any(folder.rglob("*.tex")):
            raise ArchiveError(
                f"{path.name} has no .tex file — expected a LaTeX project "
                "(Overleaf: Menu → Download → Source)"
            )
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)
