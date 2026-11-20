"""The OQ deliverables name what they were compiled from, and a rebuild from the
same inputs writes the same bytes.

Drives the real oq-compile.sh with the stub elspais from test_entrypoint, so
the identity lookups and the normalisation run exactly as a consumer's CI runs
them.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import openpyxl

from .test_entrypoint import ENTRYPOINT, _git_init_with_commit, _make_primary, _make_stub_elspais

EPOCH = "1788998400"  # 2026-09-10T00:00:00Z
DIGEST = "sha256:" + "a" * 64
STAMPED = "015293a47d7c64c8fcacd8d94f8b87a3d88bc138"


def _run(tmp_path: Path, primary: Path, *args: str, **env_extra: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    _make_stub_elspais(bin_dir)
    env = os.environ.copy()
    env.pop("SOURCE_DATE_EPOCH", None)
    env.pop("COMPILE_IMAGE", None)
    env.pop("PRIMARY_COMMIT", None)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env.update(env_extra)
    return subprocess.run(["bash", str(ENTRYPOINT), str(primary), *args], env=env, capture_output=True, text=True)


def _provenance(primary: Path) -> dict[str, list[str]]:
    wb = openpyxl.load_workbook(primary / "promotion-evidence" / "_build" / "oq-report.xlsx")
    rows: dict[str, list[str]] = {}
    for row in wb["Provenance"].iter_rows(values_only=True):
        if row and row[0]:
            rows.setdefault(row[0], []).append(row[1] if len(row) > 1 else None)
    return rows


def _fabricated(path: Path) -> None:
    """A tree as a pipeline image leaves it: a repository initialised over the
    content, authored by the pipeline."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=pipeline", "-c", "user.email=pipeline@invalid",
         "commit", "-q", "--allow-empty", "-m", "pipeline: initialised tree"],
        cwd=path, check=True,
    )


def test_a_rebuild_of_one_tree_is_byte_identical(tmp_path):
    primary = tmp_path / "primary"
    _make_primary(primary)
    xlsx = primary / "promotion-evidence" / "_build" / "oq-report.xlsx"
    assert _run(tmp_path, primary, SOURCE_DATE_EPOCH=EPOCH).returncode == 0
    first = xlsx.read_bytes()
    # A second later the wall clock has moved; the bytes must not have.
    subprocess.run(["sleep", "2"], check=True)
    assert _run(tmp_path, primary, SOURCE_DATE_EPOCH=EPOCH).returncode == 0
    assert xlsx.read_bytes() == first


def test_without_an_epoch_the_generated_at_stamp_is_the_clock(tmp_path):
    """Negative control: the epoch is what fixes the stamp, not something else."""
    primary = tmp_path / "primary"
    _make_primary(primary)
    assert _run(tmp_path, primary).returncode == 0
    assert _provenance(primary)["Generated at (UTC)"] != ["2026-09-10T00:00:00Z"]


def test_the_epoch_is_the_generated_at_stamp(tmp_path):
    primary = tmp_path / "primary"
    _make_primary(primary)
    assert _run(tmp_path, primary, SOURCE_DATE_EPOCH=EPOCH).returncode == 0
    assert _provenance(primary)["Generated at (UTC)"] == ["2026-09-10T00:00:00Z"]


def test_the_compile_image_is_named_on_the_provenance_sheet(tmp_path):
    primary = tmp_path / "primary"
    _make_primary(primary)
    image = f"ghcr.io/example/pipeline@{DIGEST}"
    assert _run(tmp_path, primary, COMPILE_IMAGE=image).returncode == 0
    assert _provenance(primary)["Compile image"] == [image]


def test_a_compile_image_named_by_tag_is_refused(tmp_path):
    primary = tmp_path / "primary"
    _make_primary(primary)
    r = _run(tmp_path, primary, COMPILE_IMAGE="ghcr.io/example/pipeline:latest")
    assert r.returncode != 0
    assert "by digest" in r.stderr
    assert not (primary / "promotion-evidence" / "_build" / "oq-report.xlsx").exists()


def test_without_a_compile_image_the_sheet_says_so(tmp_path):
    primary = tmp_path / "primary"
    _make_primary(primary)
    assert _run(tmp_path, primary).returncode == 0
    (value,) = _provenance(primary)["Compile image"]
    assert value.startswith("none recorded")


def test_a_stamped_associate_reports_its_stamped_commit(tmp_path):
    """An obtained tree has no .git; before, it reported `unknown`."""
    primary = tmp_path / "primary"
    _make_primary(primary)
    associate = tmp_path / "associate"
    associate.mkdir()
    (associate / ".upstream-commit").write_text(STAMPED + "\n")
    assert _run(tmp_path, primary, str(associate)).returncode == 0
    assert _provenance(primary)["Associate repository commit"] == [f"associate@{STAMPED}"]


def test_a_stamp_wins_over_a_history_the_pipeline_fabricated(tmp_path):
    primary = tmp_path / "primary"
    _make_primary(primary)
    associate = tmp_path / "associate"
    _fabricated(associate)
    (associate / ".upstream-commit").write_text(STAMPED + "\n")
    assert _run(tmp_path, primary, str(associate)).returncode == 0
    assert _provenance(primary)["Associate repository commit"] == [f"associate@{STAMPED}"]


def test_a_fabricated_associate_history_without_a_stamp_is_refused(tmp_path):
    """The pipeline's commit names nothing upstream; reporting it would be a
    plausible wrong answer on the provenance sheet."""
    primary = tmp_path / "primary"
    _make_primary(primary)
    associate = tmp_path / "associate"
    _fabricated(associate)
    r = _run(tmp_path, primary, str(associate))
    assert r.returncode != 0
    assert "fabricated" in r.stderr


def test_a_fabricated_primary_history_is_refused_unless_the_commit_is_passed(tmp_path):
    primary = tmp_path / "primary"
    manifest_dir = primary / "spec" / "OQ-manifest"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "oq.yaml").write_text((Path(__file__).parent / "fixtures" / "sample-manifest.yaml").read_text())
    subprocess.run(["git", "init", "-q"], cwd=primary, check=True)
    subprocess.run(
        ["git", "-c", "user.name=pipeline", "-c", "user.email=pipeline@invalid",
         "commit", "-q", "--allow-empty", "-m", "pipeline"],
        cwd=primary, check=True,
    )
    refused = _run(tmp_path, primary)
    assert refused.returncode != 0 and "fabricated" in refused.stderr

    passed = _run(tmp_path, primary, PRIMARY_COMMIT=STAMPED)
    assert passed.returncode == 0, passed.stderr
    assert _provenance(primary)["Primary repository commit"] == [STAMPED]


def test_a_real_checkout_still_reports_its_head(tmp_path):
    """Negative control for the refusal: an ordinary history is not refused."""
    primary = tmp_path / "primary"
    _make_primary(primary)
    associate = tmp_path / "associate"
    sha = _git_init_with_commit(associate)
    assert _run(tmp_path, primary, str(associate)).returncode == 0
    assert _provenance(primary)["Associate repository commit"] == [f"associate@{sha}"]


def test_without_an_epoch_a_rebuild_differs(tmp_path):
    """Negative control for the byte-identity case: it is the epoch that makes
    the rebuild identical, so without it the stamp moves with the clock."""
    primary = tmp_path / "primary"
    _make_primary(primary)
    xlsx = primary / "promotion-evidence" / "_build" / "oq-report.xlsx"
    assert _run(tmp_path, primary).returncode == 0
    first = xlsx.read_bytes()
    subprocess.run(["sleep", "2"], check=True)
    assert _run(tmp_path, primary).returncode == 0
    assert xlsx.read_bytes() != first
