"""The release evidence bundle: its manifest, the offline rebuild, and the
admission check the locked store's writer runs.

The rebuild runs against a stub `docker` that executes the bundle's `rebuild`
on the host with the paths the real run would mount, and logs its argv, so the
suite can assert both what the rebuild produced and that it was denied the
network. The stub is the only substitute; bundle.py and rebuild.sh run as CI
runs them.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
sys.path.insert(0, str(TOOL))

import bundle as bd  # noqa: E402

IMAGE_ID = "sha256:" + "1" * 64
IMAGE = "ghcr.io/example/pipeline@sha256:" + "2" * 64
EPOCH = 1788998400

STUB_DOCKER = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$DOCKER_LOG"
case "$1" in
  load) exit 0 ;;
  image) echo "$STUB_IMAGE_ID" ;;
  run)
    shift
    bundle_host=""; out_host=""
    envs=()
    entry=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --volume)
          IFS=: read -r host ctr _ <<< "$2"
          case "$ctr" in /bundle) bundle_host="$host" ;; /rebuilt) out_host="$host" ;; esac
          shift 2 ;;
        --env) envs+=("$2"); shift 2 ;;
        --entrypoint) entry="$2"; shift 2 ;;
        --network|--rm) [ "$1" = --network ] && shift; shift ;;
        *) shift ;;
      esac
    done
    env -i PATH="$PATH" "${envs[@]}" BUNDLE="$bundle_host" REBUILD_OUT="$out_host" "$bundle_host${entry#/bundle}"
    ;;
  *) echo "stub docker: unhandled $1" >&2; exit 1 ;;
esac
"""

# The bundle's rebuild: "compiles" each deliverable from its source file.
REBUILD = """#!/usr/bin/env bash
set -euo pipefail
for src in "$BUNDLE"/source/*.txt; do
  name="$(basename "$src" .txt)"
  printf 'compiled at %s from: %s' "$SOURCE_DATE_EPOCH" "$(cat "$src")" > "$REBUILD_OUT/$name.md"
done
"""


def _make_bundle(root: Path, sources: dict[str, str]) -> Path:
    b = root / "bundle"
    (b / "toolchain").mkdir(parents=True)
    (b / "toolchain" / "image.tar").write_bytes(b"image bytes")
    (b / "source").mkdir()
    (b / "evidence").mkdir()
    (b / "evidence" / "results.json").write_text("{}")
    (b / "deliverables").mkdir()
    for name, text in sources.items():
        (b / "source" / f"{name}.txt").write_text(text)
        (b / "deliverables" / f"{name}.md").write_text(f"compiled at {EPOCH} from: {text}")
    (b / "rebuild").write_text(REBUILD)
    (b / "rebuild").chmod(0o755)
    bd.write_manifest(b, "2026-11.1", IMAGE, IMAGE_ID, EPOCH)
    return b


def _rebuild(tmp_path: Path, bundle: Path) -> tuple[subprocess.CompletedProcess, Path, str]:
    stub = tmp_path / "bin" / "docker"
    stub.parent.mkdir(exist_ok=True)
    stub.write_text(STUB_DOCKER)
    stub.chmod(0o755)
    log = tmp_path / "docker.log"
    verdict = tmp_path / "verdict.json"
    env = {**os.environ, "DOCKER": str(stub), "DOCKER_LOG": str(log), "STUB_IMAGE_ID": IMAGE_ID,
           "PYTHON": sys.executable}
    r = subprocess.run(["bash", str(TOOL / "rebuild.sh"), str(bundle), str(verdict)],
                       env=env, capture_output=True, text=True)
    return r, verdict, log.read_text() if log.exists() else ""


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL / "bundle.py"), *args], capture_output=True, text=True)


# --- the manifest ------------------------------------------------------------


def test_the_manifest_names_every_file_its_hash_and_the_comparison_it_is_held_to(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    header, entries = bd.read_manifest(b)
    assert header["image"] == IMAGE and header["source-date-epoch"] == str(EPOCH)
    by_path = {rel: (digest, section, rule) for digest, section, rule, rel in entries}
    assert set(by_path) == {"rebuild", "toolchain/image.tar", "source/urs.txt", "evidence/results.json",
                            "deliverables/urs.md"}
    assert by_path["deliverables/urs.md"][2] == "bytes"
    assert by_path["source/urs.txt"][2] == "-"
    assert by_path["toolchain/image.tar"][0] == hashlib.sha256(b"image bytes").hexdigest()
    text = (b / "MANIFEST").read_text()
    for suffix in (".pdf", ".docx", ".xlsx", ".csv", ".md"):
        assert f"  {suffix}" in text, "the guarantee is stated per deliverable type"


def test_a_deliverable_with_no_named_comparison_is_refused(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    (b / "deliverables" / "picture.png").write_bytes(b"x")
    with pytest.raises(bd.Refusal, match="no comparison is named"):
        bd.write_manifest(b, "r", IMAGE, IMAGE_ID, EPOCH)


def test_a_bundle_without_its_toolchain_is_refused(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    (b / "toolchain" / "image.tar").unlink()
    with pytest.raises(bd.Refusal, match="toolchain"):
        bd.write_manifest(b, "r", IMAGE, IMAGE_ID, EPOCH)


def test_an_image_named_by_tag_is_refused(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    with pytest.raises(bd.Refusal, match="by digest"):
        bd.write_manifest(b, "r", "ghcr.io/example/pipeline:latest", IMAGE_ID, EPOCH)


def test_a_symbolic_link_is_refused(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    (b / "evidence" / "link").symlink_to(b / "evidence" / "results.json")
    with pytest.raises(bd.Refusal, match="symbolic link"):
        bd.write_manifest(b, "r", IMAGE, IMAGE_ID, EPOCH)


# --- verify ------------------------------------------------------------------


def test_a_whole_bundle_verifies(tmp_path):
    assert bd.verify(_make_bundle(tmp_path, {"urs": "one"})) == []


@pytest.mark.parametrize("damage,expected", [
    (lambda b: (b / "evidence" / "results.json").unlink(), "missing: evidence/results.json"),
    (lambda b: (b / "evidence" / "extra.json").write_text("{}"), "not in the manifest: evidence/extra.json"),
    (lambda b: (b / "source" / "urs.txt").write_text("edited"), "altered: source/urs.txt"),
])
def test_a_damaged_bundle_does_not_verify(tmp_path, damage, expected):
    b = _make_bundle(tmp_path, {"urs": "one"})
    damage(b)
    assert expected in bd.verify(b)
    assert _cli("verify", "--bundle", str(b)).returncode == 1


# --- the offline rebuild -----------------------------------------------------


def test_a_complete_bundle_rebuilds_offline_to_the_same_bytes_and_is_admitted(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one", "oq": "two"})
    r, verdict, log = _rebuild(tmp_path, b)
    assert r.returncode == 0, r.stderr
    v = json.loads(verdict.read_text())
    assert v["reproduced"] is True
    assert {d["path"] for d in v["deliverables"]} == {"deliverables/urs.md", "deliverables/oq.md"}
    assert _cli("admit", "--bundle", str(b), "--verdict", str(verdict)).returncode == 0


def test_the_rebuild_is_denied_the_network_and_runs_the_bundled_image(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    _, _, log = _rebuild(tmp_path, b)
    run = next(line for line in log.splitlines() if line.startswith("run "))
    assert "--network none" in run
    assert f"{b}:/bundle:ro" in run
    assert run.rstrip().endswith(IMAGE_ID)
    assert not any(line.startswith("pull") for line in log.splitlines())


def test_a_bundle_missing_an_input_does_not_reproduce_and_is_refused(tmp_path):
    """The case the rebuild exists for: the manifest and hashes are all
    consistent, yet the bundle cannot rebuild what shipped -- here because the
    shipped deliverable was compiled from a source the bundle does not hold."""
    b = _make_bundle(tmp_path, {"urs": "one"})
    (b / "deliverables" / "urs.md").write_text(f"compiled at {EPOCH} from: a source nobody bundled")
    bd.write_manifest(b, "2026-11.1", IMAGE, IMAGE_ID, EPOCH)
    assert bd.verify(b) == []  # the hashes alone say nothing is wrong
    r, verdict, _ = _rebuild(tmp_path, b)
    assert r.returncode == 0, "the verdict is the result; refusing is admit's job"
    v = json.loads(verdict.read_text())
    assert v["reproduced"] is False
    refused = _cli("admit", "--bundle", str(b), "--verdict", str(verdict))
    assert refused.returncode == 1
    assert "did not reproduce" in refused.stderr and "deliverables/urs.md" in refused.stderr


def test_a_rebuild_that_fails_outright_still_leaves_a_verdict(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    (b / "rebuild").write_text("#!/usr/bin/env bash\nexit 3\n")
    bd.write_manifest(b, "2026-11.1", IMAGE, IMAGE_ID, EPOCH)
    r, verdict, _ = _rebuild(tmp_path, b)
    assert r.returncode == 0
    assert json.loads(verdict.read_text())["reproduced"] is False


def test_a_tampered_bundle_is_refused_before_anything_runs(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    (b / "source" / "urs.txt").write_text("swapped")
    r, verdict, log = _rebuild(tmp_path, b)
    assert r.returncode == 1
    assert "altered: source/urs.txt" in r.stderr
    assert not verdict.exists() and "run " not in log


def test_an_image_tar_that_loads_another_image_is_refused(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    stub_env_id = "sha256:" + "9" * 64
    stub = tmp_path / "bin" / "docker"
    stub.parent.mkdir()
    stub.write_text(STUB_DOCKER)
    stub.chmod(0o755)
    env = {**os.environ, "DOCKER": str(stub), "DOCKER_LOG": str(tmp_path / "log"), "STUB_IMAGE_ID": stub_env_id,
           "PYTHON": sys.executable}
    r = subprocess.run(["bash", str(TOOL / "rebuild.sh"), str(b), str(tmp_path / "v.json")],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "did not load the image" in r.stderr


# --- admit -------------------------------------------------------------------


def test_a_verdict_for_another_bundle_is_refused(tmp_path):
    a = _make_bundle(tmp_path / "a", {"urs": "one"})
    other = _make_bundle(tmp_path / "b", {"urs": "two"})
    _, verdict, _ = _rebuild(tmp_path / "a", a)
    refused = _cli("admit", "--bundle", str(other), "--verdict", str(verdict))
    assert refused.returncode == 1 and "another bundle" in refused.stderr


def test_an_absent_verdict_is_refused(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    refused = _cli("admit", "--bundle", str(b), "--verdict", str(tmp_path / "absent.json"))
    assert refused.returncode == 1 and "could not be read" in refused.stderr


def test_a_bundle_altered_after_its_rebuild_is_refused(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    _, verdict, _ = _rebuild(tmp_path, b)
    (b / "evidence" / "results.json").write_text('{"edited": true}')
    refused = _cli("admit", "--bundle", str(b), "--verdict", str(verdict))
    assert refused.returncode == 1 and "altered: evidence/results.json" in refused.stderr


# --- pack --------------------------------------------------------------------


def test_packing_is_deterministic_and_the_hash_names_the_archive(tmp_path):
    b = _make_bundle(tmp_path, {"urs": "one"})
    first = bd.pack(b, tmp_path / "one.tar")
    os.utime(b / "evidence" / "results.json", (1, 1))
    second = bd.pack(b, tmp_path / "two.tar")
    assert first == second == hashlib.sha256((tmp_path / "one.tar").read_bytes()).hexdigest()
    with tarfile.open(tmp_path / "one.tar") as t:
        members = {m.name: m for m in t.getmembers()}
    assert members["bundle/rebuild"].mode == 0o755
    assert {m.mtime for m in members.values()} == {EPOCH}
