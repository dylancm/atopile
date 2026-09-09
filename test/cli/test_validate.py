import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

VALID = """\
import Resistor

module App:
    r = new Resistor
    r.resistance = 1kohm +/- 10%
"""

SYNTAX_ERROR = """\
import Resistor

module App:
    r = new Resistor(
"""

MISSING_IMPORT = """\
from "nope/missing.ato" import Missing

module App:
    pass
"""


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _validate(cwd: Path, *args: str) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, "-m", "atopile", "validate", *args],
        env={**os.environ, "NONINTERACTIVE": "1"},
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode, _strip_ansi(result.stdout), _strip_ansi(result.stderr)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "good.ato").write_text(VALID)
    (tmp_path / "bad.ato").write_text(SYNTAX_ERROR)
    (tmp_path / "missing_import.ato").write_text(MISSING_IMPORT)
    (tmp_path / "subdir").mkdir()
    return tmp_path


def test_valid_file_ok(workspace: Path):
    code, stdout, stderr = _validate(workspace, "good.ato")
    assert code == 0
    assert "good.ato: ok" in stdout
    assert "Traceback" not in stderr


def test_syntax_error(workspace: Path):
    code, stdout, stderr = _validate(workspace, "bad.ato")
    assert code == 1
    assert "ok" not in stdout
    assert "Syntax Error" in stderr
    assert "input '(' expecting" in stderr
    assert re.search(r"bad\.ato:4:\d+", stderr)
    assert "Traceback" not in stderr


def test_unresolved_import(workspace: Path):
    code, stdout, stderr = _validate(workspace, "missing_import.ato")
    assert code == 1
    assert "ok" not in stdout
    assert "Unable to resolve import `nope/missing.ato`" in stderr
    assert 'missing_import.ato", line 1' in stderr
    assert "Traceback" not in stderr


def test_multiple_files_reports_all(workspace: Path):
    code, stdout, stderr = _validate(workspace, "bad.ato", "good.ato")
    assert code == 1
    assert "good.ato: ok" in stdout
    assert "bad.ato" not in stdout
    assert re.search(r"bad\.ato:4:\d+", stderr)


def test_directory_rejected(workspace: Path):
    code, stdout, stderr = _validate(workspace, "subdir")
    assert code == 1
    assert stdout.strip() == ""
    assert "`subdir` is a directory" in stderr
    assert "Traceback" not in stderr
