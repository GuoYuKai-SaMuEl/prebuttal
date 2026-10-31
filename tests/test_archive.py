"""A LaTeX project as a .zip (Overleaf's Download Source), unpacked safely."""

import json
import stat
import tempfile
import zipfile
from pathlib import Path

import pytest

from prebuttal import cli
from prebuttal.check import CheckError, check_source
from prebuttal.ingestion import IngestError, ingest
from prebuttal.ingestion import archive as archive_mod
from prebuttal.venues import get_venue


def _zip(path: Path, files: dict[str, str], prefix: str = "") -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(prefix + name, text)
    return path


def _project_files(project: Path) -> dict[str, str]:
    return {
        p.relative_to(project).as_posix(): p.read_text(encoding="utf-8")
        for p in project.rglob("*")
        if p.is_file() and p.suffix in (".tex", ".bbl")
    }


@pytest.mark.parametrize("prefix", ["", "My Paper/"])  # Overleaf zips are flat; others nest
def test_zip_reads_like_the_folder(latex_project, tmp_path, prefix):
    archive = _zip(tmp_path / "paper.zip", _project_files(latex_project), prefix)
    from_zip, from_folder = ingest(str(archive)), ingest(str(latex_project))
    assert from_zip.title == from_folder.title
    assert [s.heading for s in from_zip.sections] == [s.heading for s in from_folder.sections]
    assert len(from_zip.tables) == len(from_folder.tables)
    assert from_zip.source_path.endswith("paper.zip")


def test_check_takes_a_zip(latex_project, tmp_path):
    archive = _zip(tmp_path / "paper.zip", _project_files(latex_project))
    result = check_source(str(archive), get_venue("iclr"))
    assert result.kind == "latex" and result.source == str(archive)
    folder = check_source(str(latex_project), get_venue("iclr"))
    assert [f.message for f in result.findings] == [f.message for f in folder.findings]


def test_run_on_a_zip_keeps_no_temporary_path(
    latex_project, tmp_path, monkeypatch, fake_statuses, fake_config
):
    archive = _zip(tmp_path / "paper.zip", _project_files(latex_project))
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["run", "paper.zip", "--config", str(fake_config), "--json", "out.json"])
    assert rc == cli.EXIT_OK
    text = (tmp_path / "out.json").read_text(encoding="utf-8")
    assert json.loads(text)["paper"]["source_path"] == "paper.zip"
    assert "prebuttal-zip" not in text
    assert archive.is_file()


@pytest.mark.parametrize("name", ["../evil.tex", "/etc/evil.tex", "C:/evil.tex", "a/../../x.tex"])
def test_paths_outside_the_folder_are_refused(tmp_path, name):
    archive = _zip(tmp_path / "bad.zip", {"main.tex": r"\documentclass{article}", name: "x"})
    with pytest.raises(IngestError, match="unsafe path"):
        ingest(str(archive))
    with pytest.raises(CheckError, match="unsafe path"):
        check_source(str(archive), get_venue("iclr"))


def test_symlinks_are_skipped(tmp_path):
    archive = tmp_path / "link.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("main.tex", "\\documentclass{article}\n\\input{secret}\n")
        link = zipfile.ZipInfo("secret.tex")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(link, "/etc/passwd")
    with archive_mod.unpacked_zip(archive) as folder:
        assert sorted(p.name for p in folder.iterdir()) == ["main.tex"]


def _unpack(archive: Path) -> None:
    with archive_mod.unpacked_zip(archive):
        pass


def test_size_and_count_caps(tmp_path, monkeypatch):
    archive = _zip(tmp_path / "big.zip", {"main.tex": "x" * 5000, "b.tex": "y"})
    monkeypatch.setattr(archive_mod, "MAX_BYTES", 4000)
    with pytest.raises(archive_mod.ArchiveError, match="unpacks to over"):
        _unpack(archive)
    monkeypatch.setattr(archive_mod, "MAX_BYTES", 10**6)
    monkeypatch.setattr(archive_mod, "MAX_MEMBERS", 1)
    with pytest.raises(archive_mod.ArchiveError, match="over 1 files"):
        _unpack(archive)


def test_unusable_archives_say_why(tmp_path):
    not_zip = tmp_path / "paper.zip"
    not_zip.write_bytes(b"not a zip")
    with pytest.raises(IngestError, match=r"not a readable \.zip"):
        ingest(str(not_zip))
    no_tex = _zip(tmp_path / "figs.zip", {"fig.png": "png"})
    with pytest.raises(IngestError, match=r"no \.tex file"):
        ingest(str(no_tex))


def test_the_temporary_folder_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    archive = _zip(tmp_path / "paper.zip", {"main.tex": r"\documentclass{article}"})
    with archive_mod.unpacked_zip(archive) as folder:
        assert folder.is_dir()
    assert not folder.exists()
    with pytest.raises(archive_mod.ArchiveError):  # also when unpacking fails
        _unpack(_zip(tmp_path / "x.zip", {"../x": ""}))
    assert list((tmp_path / "tmp").iterdir()) == []
