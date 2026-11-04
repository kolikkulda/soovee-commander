import io
import os
from pathlib import Path
from threading import Event

import pytest

from soovee_commander.advanced import (compare, folder_size, multi_rename, rename_names,
                                        search, sync_entries, move_entries)
from soovee_commander.operations import Cancelled, copy_entries, preview
from soovee_commander.providers import ArchiveProvider, Entry, LocalProvider
from soovee_commander.extensions import expand_args, validate_tools


@pytest.fixture
def pair(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir(); right.mkdir()
    return LocalProvider(), str(left), str(right)


def test_recursive_search_content_crosses_chunks_and_does_not_follow_links(pair):
    p, a, b = pair
    root = Path(a)
    (root / "nested").mkdir()
    (root / "nested" / "žluťoučký.TXT").write_bytes(b"x" * (256 * 1024 - 2) + b"NEEDLE" + b"end")
    (Path(b) / "outside.txt").write_text("NEEDLE")
    (root / "outside").symlink_to(b, target_is_directory=True)
    result, errors = search(p, a, "*.txt;*.md", "NEEDLE", Event())
    assert [r[0] for r in result] == ["nested/žluťoučký.TXT"]
    assert not errors
    assert folder_size(p, a, Event()) == ((256 * 1024 - 2) + 9, 1, 1)


def test_search_cancellation_and_match_limit(pair):
    p, a, _ = pair
    (Path(a) / "one").touch()
    cancel = Event(); cancel.set()
    with pytest.raises(Cancelled):
        search(p, a, "*", "", cancel)
    with pytest.raises(ValueError, match="Narrow"):
        search(p, a, "*", "", Event(), limit=1)


def test_compare_hash_not_just_size_or_date_and_sync_both_directions(pair):
    p, a, b = pair
    x, y = Path(a), Path(b)
    (x / "same").write_text("same"); (y / "same").write_text("same")
    (x / "changed").write_text("123"); (y / "changed").write_text("abc")
    (x / "tree").mkdir(); (x / "tree" / "child").write_text("child")
    (y / "extra").write_text("keep")
    os.utime(y / "changed", (1000, 1000)); os.utime(x / "changed", (1000, 1000))
    differences = compare(p, a, p, b, Event())
    assert {d.name: d.status for d in differences}["changed"] == 'Different'
    sync_entries(p, a, p, b, differences, Event())
    assert (y / "changed").read_text() == "123"
    assert (y / "tree" / "child").read_text() == "child"
    assert (y / "extra").read_text() == "keep"
    differences = compare(p, a, p, b, Event())
    sync_entries(p, b, p, a, differences, Event(), direction="left")
    assert (x / "extra").read_text() == "keep"
    assert all(d.status == 'Equal' for d in compare(p, a, p, b, Event()))


def test_sync_changed_destination_and_conflict_abort_before_any_write(pair):
    p, a, b = pair
    x, y = Path(a), Path(b)
    (x / "first").write_text("new")
    (x / "z-conflict").mkdir(); (y / "z-conflict").write_text("file")
    differences = compare(p, a, p, b, Event())
    with pytest.raises(ValueError, match="conflict"):
        sync_entries(p, a, p, b, differences, Event())
    assert not (y / "first").exists()
    (x / "z-conflict").rmdir(); (y / "z-conflict").unlink()
    (x / "edit").write_text("before"); (y / "edit").write_text("old")
    differences = compare(p, a, p, b, Event())
    (y / "edit").write_text("modified meanwhile")
    with pytest.raises(RuntimeError, match="changed"):
        sync_entries(p, a, p, b, differences, Event())
    assert not (y / "first").exists()
    assert (y / "edit").read_text() == "modified meanwhile"
    with pytest.raises(ValueError, match="overlap"):
        sync_entries(p, a, p, a, [], Event())


def test_multi_rename_preview_cycle_undo_and_collision(pair):
    p, a, _ = pair
    root = Path(a)
    (root / "a.txt").write_text("A"); (root / "b.txt").write_text("B")
    entries = sorted(p.list(a), key=lambda e: e.name)
    assert rename_names(entries, "foto-[C]-[N]", "[E]", start=3, digits=2) == ["foto-03-a.txt", "foto-04-b.txt"]
    multi_rename(p, a, entries, ["b.txt", "a.txt"], Event())
    assert (root / "a.txt").read_text() == "B"
    assert (root / "b.txt").read_text() == "A"
    current = {e.name: e for e in p.list(a)}
    multi_rename(p, a, [current["b.txt"], current["a.txt"]], ["a.txt", "b.txt"], Event())
    assert (root / "a.txt").read_text() == "A"
    with pytest.raises(ValueError):
        rename_names(entries, "identical", "txt")
    (root / "outside").touch()
    with pytest.raises(FileExistsError):
        multi_rename(p, a, entries, ["outside", "other"], Event())
    assert (root / "a.txt").read_text() == "A"


def test_multi_rename_rolls_back_completed_cycle_on_error(pair, monkeypatch):
    p, a, _ = pair
    root = Path(a)
    for n in ("a", "b", "c"):
        (root / n).write_text(n)
    entries = sorted(p.list(a), key=lambda e: e.name)
    original = p.rename
    calls = []
    def failing(src, dst):
        calls.append((src, dst))
        if len(calls) == 6:
            raise OSError("Simulated error during final rename")
        return original(src, dst)
    monkeypatch.setattr(p, "rename", failing)
    with pytest.raises(OSError):
        multi_rename(p, a, entries, ["b", "c", "a"], Event())
    assert {item.name: item.read_text() for item in root.iterdir()} == {n: n for n in ("a", "b", "c")}


def test_7z_selected_read_without_extraction_and_traversal_rejected(pair):
    import libarchive
    p, a, b = pair
    root = Path(a)
    (root / "source").write_text("native 7z")
    archive = root / "archive.7z"
    with libarchive.file_writer(str(archive), "7zip") as output:
        for name in ('nested/český.txt', '../escape', 'untouched'):
            output.add_file_from_memory(name, 9, b'native 7z')
    provider = ArchiveProvider(str(archive))
    assert {e.name for e in provider.list("/")} == {"nested", "untouched"}
    name = provider.list("/nested")[0].name
    import unicodedata
    assert unicodedata.normalize("NFC", name) == "český.txt"
    assert preview(provider, "/nested/" + name) == b"native 7z"
    copy_entries(provider, "/nested", p, b, provider.list("/nested"), Event())
    assert [unicodedata.normalize("NFC", file.name) for file in Path(b).iterdir()] == ["český.txt"]
    assert not (Path(b).parent / "escape").exists()


def test_command_plugin_expansion_is_literal_and_validated():
    assert expand_args(["{files}", "--dir={path}", "{file}", "{other}"], "/a b", "/c", ["/x/{path}", "/x/$(touch nope)"]) == ["/x/{path}", "/x/$(touch nope)", "--dir=/a b", "/x/{path}", "/c"]
    with pytest.raises(ValueError):
        expand_args(["--files={files}"], "/", "/", ["a"])
    with pytest.raises(ValueError):
        validate_tools([{"executable": "relative"}])
    assert len(validate_tools([])) == 16


def test_zip_add_tree_rename_remove_and_failed_copy_is_atomic(pair):
    import zipfile
    p, a, b = pair
    root = Path(a); target = Path(b) / "target.zip"
    with zipfile.ZipFile(target, "w") as z:
        z.writestr("original.txt", "preserved")
    (root / "tree").mkdir(); (root / "tree" / "new.txt").write_text("new")
    archive = ArchiveProvider(str(target))
    assert not archive.readonly
    copy_entries(p, a, archive, "/", p.list(a), Event())
    assert preview(archive, "/tree/new.txt") == b"new"
    assert preview(archive, "/original.txt") == b"preserved"
    archive.rename("/tree", "/renamed")
    assert preview(archive, "/renamed/new.txt") == b"new"
    archive.remove("/renamed", archive.list("/")[1])
    assert {e.name for e in archive.list("/")} == {"original.txt"}
    before = target.read_bytes()
    cancel = Event()
    def stop(message, count):
        if count:
            cancel.set()
    with pytest.raises(Cancelled):
        copy_entries(p, a, archive, "/", p.list(a), cancel, stop)
    assert target.read_bytes() == before
    assert {e.name for e in archive.list("/")} == {"original.txt"}
    with pytest.raises(ValueError, match="into itself"):
        copy_entries(p, b, archive, "/", p.list(b), Event())


def test_rar5_real_selected_read(pair):
    p, a, b = pair
    archive = ArchiveProvider(str(Path(__file__).parent / "fixtures" / "rar5-crc.rar"))
    assert archive.readonly
    assert {e.name for e in archive.list("/")} == {"stest1.txt", "stest2.txt"}
    copy_entries(archive, "/", p, b, [archive.list("/")[0]], Event())
    assert len(list(Path(b).iterdir())) == 1
    assert next(Path(b).iterdir()).read_bytes().startswith(b"000\n001\n002\n")


def test_search_date_size_and_type_filters(tmp_path):
    import os
    from threading import Event
    from soovee_commander.advanced import search
    from soovee_commander.providers import LocalProvider
    (tmp_path / 'old.txt').write_bytes(b'needle')
    (tmp_path / 'new.txt').write_bytes(b'needle' * 20)
    (tmp_path / 'folder').mkdir()
    os.utime(tmp_path / 'old.txt', (1000000000, 1000000000))
    os.utime(tmp_path / 'new.txt', (1700000000, 1700000000))
    result, errors = search(LocalProvider(), str(tmp_path), '*', 'needle', Event(), modified_after=1600000000, modified_before=1800000000, min_size=100, max_size=200, kind='files')
    assert [e.name for _, _, e in result] == ['new.txt'] and not errors
    result, _ = search(LocalProvider(), str(tmp_path), '*', '', Event(), kind='folders')
    assert [e.name for _, _, e in result] == ['folder']
