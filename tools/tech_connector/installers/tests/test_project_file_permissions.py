import stat

from services.project_service import is_read_only_file, make_file_writable


def test_make_file_writable_clears_read_only_bit(tmp_path):
    path = tmp_path / "locked.py"
    path.write_text("print('locked')\n", encoding="utf-8")
    path.chmod(path.stat().st_mode & ~stat.S_IWRITE)

    assert is_read_only_file(str(path)) is True

    ok, msg = make_file_writable(str(path))

    assert ok is True
    assert msg == str(path)
    assert is_read_only_file(str(path)) is False
