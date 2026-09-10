"""The build date is a function of the compile's inputs, not of when it ran.

The provenance file beside the deliverables records when they were built. While
that comes from the clock, recompiling from identical pinned inputs produces a
different file the next day -- so nothing downstream can compare a committed
deliverable against a rebuilt one and conclude anything from a difference.

These tests extract the date-derivation block straight out of ``compile-urs.sh``
and run it in isolation, so they cannot drift from the script the way a
reimplementation would. The block is located by matching its opening condition
rather than by line number: it survives the block moving, and fails loudly if
the block is restructured, which is when these tests should be revisited anyway.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "compile-urs.sh"

# Named so the epoch-to-date mapping is checkable by eye rather than trusted:
#   date -u -d @1788998400 +%F  ->  2026-09-10
EPOCH_2026_09_10 = "1788998400"
EPOCH_2026_09_11 = "1789084800"

_OPENS = re.compile(r'^if \[ -n "\$\{SOURCE_DATE_EPOCH:-\}" \]; then$')


def _date_block() -> str:
    """The SOURCE_DATE_EPOCH branch, read out of the script itself."""
    lines = SCRIPT.read_text().splitlines()
    start = next(
        (i for i, line in enumerate(lines) if _OPENS.match(line.strip())),
        None,
    )
    assert start is not None, (
        "compile-urs.sh has no SOURCE_DATE_EPOCH branch; the build date is "
        "still read from the clock"
    )
    end = next(
        (i for i in range(start, len(lines)) if lines[i].strip() == "fi"),
        None,
    )
    assert end is not None, "SOURCE_DATE_EPOCH branch is not closed by fi"
    return "\n".join(lines[start : end + 1])


def _build_date(epoch: str | None) -> str:
    env = {"PATH": "/usr/bin:/bin"}
    if epoch is not None:
        env["SOURCE_DATE_EPOCH"] = epoch
    script = _date_block() + '\nprintf "%s" "$BUILD_DATE"\n'
    return subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_epoch_fixes_the_build_date():
    assert _build_date(EPOCH_2026_09_10) == "2026-09-10"


def test_the_same_epoch_gives_the_same_date_every_time():
    assert _build_date(EPOCH_2026_09_10) == _build_date(EPOCH_2026_09_10)


def test_a_different_epoch_gives_a_different_date():
    assert _build_date(EPOCH_2026_09_10) != _build_date(EPOCH_2026_09_11)


def test_an_unset_epoch_still_produces_a_date():
    """The operator path keeps working until the cutover replaces it."""
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _build_date(None))
