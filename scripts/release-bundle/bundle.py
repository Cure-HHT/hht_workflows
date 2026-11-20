#!/usr/bin/env python3
"""A release's evidence bundle: its manifest, its completeness, and the verdict
of rebuilding its deliverables from nothing but itself.

A bundle is one directory a custodian holds for the retention horizon:

  MANIFEST            plain text, naming every other file and its SHA-256
  rebuild             executable run INSIDE the toolchain image, offline; it
                      compiles the deliverables from source/ into $REBUILD_OUT
  toolchain/image.tar the compile image, as `docker save` wrote it
  source/...          the source snapshot the deliverables were compiled from
  evidence/...        test results, traceability matrix, component records
  deliverables/...    the deliverables as shipped

The toolchain is the only irreplaceable part. A hash of the archive proves it
is the bytes that were uploaded; it does not prove those bytes rebuild
anything. That is proved by restoring the bundle where nothing of the estate
is reachable, running `rebuild` with no network, and comparing what comes out
with what shipped. This program writes the manifest, checks a bundle against
it, compares a rebuild, and decides whether a verdict admits the bundle to the
locked store. The rebuild itself is rebuild.sh.

Subcommands:

  manifest --bundle DIR --release ID --image REF --image-id ID --epoch N
      Write DIR/MANIFEST. Refuses a deliverable with no named comparison.

  verify --bundle DIR
      Every listed file is present with its hash, and nothing is unlisted.

  compare --bundle DIR --rebuilt DIR --out VERDICT
      Record, per deliverable, whether the rebuild reproduced it. Writes the
      verdict and exits 0 whatever it says: the verdict is the result, and
      refusing is `admit`'s job, so the evidence of a failed rebuild is kept.

  admit --bundle DIR --verdict VERDICT
      Exit 0 only if the verdict is for this bundle's manifest and every
      deliverable reproduced. This is the check the locked store's writer runs.

  pack --bundle DIR --out FILE.tar
      A deterministic tar of the bundle (sorted, fixed owner and time), and its
      SHA-256 on stdout, to be recorded OUTSIDE the bundle and its storage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path

FORMAT = "release-evidence-bundle/1"
MANIFEST = "MANIFEST"
REBUILD = "rebuild"
SECTIONS = ("toolchain", "source", "evidence", "deliverables")

#: The comparison each deliverable type is held to, and why it holds. Every
#: deliverable is compared byte for byte; the reason differs per type, and is
#: stated per type so a reader knows what the guarantee rests on.
COMPARISONS = {
    ".pdf": ("bytes", "rendered under SOURCE_DATE_EPOCH; the trailer /ID is normalised to a digest of the content"),
    ".docx": ("bytes", "archive entries normalised to the epoch, a fixed order and fixed attributes"),
    ".xlsx": ("bytes", "archive entries and Office clock properties normalised to the epoch"),
    ".csv": ("bytes", "plain text written in a fixed order"),
    ".md": ("bytes", "plain text; the provenance record's date is the epoch"),
}

_IMAGE_REF = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_LINE = re.compile(r"^([0-9a-f]{64})  (\S+)  (\S+)  (.+)$")


class Refusal(Exception):
    """A bundle, rebuild or verdict that must not proceed."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(bundle: Path) -> list[str]:
    """Every file in the bundle except the manifest, as sorted POSIX paths."""
    out = []
    for p in bundle.rglob("*"):
        if p.is_symlink():
            raise Refusal(f"{p.relative_to(bundle)} is a symbolic link; a bundle holds bytes, not pointers")
        if p.is_file():
            rel = p.relative_to(bundle).as_posix()
            if rel != MANIFEST:
                out.append(rel)
    return sorted(out)


def _section(rel: str) -> str:
    if rel == REBUILD:
        return "rebuild"
    top = rel.split("/", 1)[0]
    if top not in SECTIONS or "/" not in rel:
        raise Refusal(f"{rel} is outside the bundle's sections ({', '.join(SECTIONS)})")
    return top


def _comparison(rel: str) -> str:
    if _section(rel) != "deliverables":
        return "-"
    suffix = Path(rel).suffix.lower()
    if suffix not in COMPARISONS:
        raise Refusal(
            f"{rel}: no comparison is named for '{suffix}' deliverables; a deliverable whose "
            "rebuild cannot be judged cannot prove the bundle complete"
        )
    return COMPARISONS[suffix][0]


def write_manifest(bundle: Path, release: str, image: str, image_id: str, epoch: int) -> Path:
    if not _IMAGE_REF.match(image):
        raise Refusal(f"image must be named by digest (<name>@sha256:<64 hex>), got {image!r}")
    if not _IMAGE_ID.match(image_id):
        raise Refusal(f"image id must be sha256:<64 hex>, got {image_id!r}")
    files = _files(bundle)
    if REBUILD not in files:
        raise Refusal(f"the bundle has no {REBUILD} entry; nothing could rebuild it")
    if "toolchain/image.tar" not in files:
        raise Refusal("the bundle has no toolchain/image.tar; it cannot be rebuilt without its toolchain")
    if not any(f.startswith("deliverables/") for f in files):
        raise Refusal("the bundle has no deliverables; there is nothing a rebuild could prove")

    lines = [
        f"format: {FORMAT}",
        f"release: {release}",
        f"image: {image}",
        f"image-id: {image_id}",
        f"source-date-epoch: {epoch}",
        "",
        "Every file below is part of this bundle. Columns: SHA-256, section,",
        "the comparison a rebuild is held to ('-' where the file is an input,",
        "not rebuilt), path. Per deliverable type, the guarantee rests on:",
    ]
    for suffix, (rule, why) in sorted(COMPARISONS.items()):
        lines.append(f"  {suffix:6} {rule}: {why}")
    lines.append("")
    for rel in files:
        lines.append(f"{sha256_file(bundle / rel)}  {_section(rel)}  {_comparison(rel)}  {rel}")
    path = bundle / MANIFEST
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def read_manifest(bundle: Path) -> tuple[dict[str, str], list[tuple[str, str, str, str]]]:
    path = bundle / MANIFEST
    if not path.is_file():
        raise Refusal(f"{bundle} has no {MANIFEST}")
    header: dict[str, str] = {}
    entries: list[tuple[str, str, str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line)
        if m:
            entries.append(m.groups())  # type: ignore[arg-type]
        elif ": " in line and not line.startswith(" ") and not entries:
            key, value = line.split(": ", 1)
            header.setdefault(key, value)
    if header.get("format") != FORMAT:
        raise Refusal(f"{MANIFEST} is not a {FORMAT} manifest")
    for key in ("release", "image", "image-id", "source-date-epoch"):
        if key not in header:
            raise Refusal(f"{MANIFEST} names no {key}")
    return header, entries


def verify(bundle: Path) -> list[str]:
    """Problems with the bundle against its manifest; empty when it is whole."""
    _, entries = read_manifest(bundle)
    listed = {rel: digest for digest, _, _, rel in entries}
    present = set(_files(bundle))
    problems = []
    for rel in sorted(set(listed) - present):
        problems.append(f"missing: {rel}")
    for rel in sorted(present - set(listed)):
        problems.append(f"not in the manifest: {rel}")
    for rel in sorted(set(listed) & present):
        if sha256_file(bundle / rel) != listed[rel]:
            problems.append(f"altered: {rel}")
    return problems


def compare(bundle: Path, rebuilt: Path) -> dict:
    header, entries = read_manifest(bundle)
    results = []
    for digest, section, rule, rel in entries:
        if section != "deliverables":
            continue
        name = rel.split("/", 1)[1]
        candidate = rebuilt / name
        got = sha256_file(candidate) if candidate.is_file() else None
        results.append({
            "path": rel,
            "comparison": rule,
            "shipped_sha256": digest,
            "rebuilt_sha256": got,
            "reproduced": got == digest,
        })
    extra = sorted(
        p.relative_to(rebuilt).as_posix() for p in rebuilt.rglob("*") if p.is_file()
        and f"deliverables/{p.relative_to(rebuilt).as_posix()}" not in {r["path"] for r in results}
    ) if rebuilt.is_dir() else []
    return {
        "format": FORMAT,
        "record": "offline-rebuild-verdict",
        "release": header["release"],
        "image": header["image"],
        "manifest_sha256": sha256_file(bundle / MANIFEST),
        "reproduced": bool(results) and all(r["reproduced"] for r in results),
        "deliverables": results,
        "rebuilt_but_not_shipped": extra,
    }


def admit(bundle: Path, verdict_path: Path) -> None:
    problems = verify(bundle)
    if problems:
        raise Refusal("the bundle does not match its manifest: " + "; ".join(problems))
    try:
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refusal(f"the rebuild verdict could not be read: {exc}") from exc
    if verdict.get("record") != "offline-rebuild-verdict" or verdict.get("format") != FORMAT:
        raise Refusal("the verdict is not an offline-rebuild verdict")
    manifest_sha = sha256_file(bundle / MANIFEST)
    if verdict.get("manifest_sha256") != manifest_sha:
        raise Refusal(
            f"the verdict is for manifest {verdict.get('manifest_sha256')}, this bundle's is {manifest_sha}; "
            "a rebuild of another bundle proves nothing about this one"
        )
    if verdict.get("reproduced") is not True:
        failed = [d["path"] for d in verdict.get("deliverables", []) if not d.get("reproduced")]
        raise Refusal(
            "the offline rebuild did not reproduce the shipped deliverables"
            + (f" ({', '.join(failed)})" if failed else "")
            + "; the bundle is not proved complete and must not be locked"
        )


def pack(bundle: Path, out: Path) -> str:
    """A tar whose bytes follow from the bundle's content alone."""
    epoch = int(read_manifest(bundle)[0]["source-date-epoch"])
    names = [MANIFEST, *_files(bundle)]

    def _fixed(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = epoch
        info.mode = 0o755 if info.name == f"bundle/{REBUILD}" else 0o644
        return info

    with tarfile.open(out, "w", format=tarfile.PAX_FORMAT) as tar:
        for rel in names:
            tar.add(bundle / rel, arcname=f"bundle/{rel}", recursive=False, filter=_fixed)
    return sha256_file(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--bundle", type=Path, required=True)
    m.add_argument("--release", required=True)
    m.add_argument("--image", required=True)
    m.add_argument("--image-id", required=True)
    m.add_argument("--epoch", type=int, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--bundle", type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument("--bundle", type=Path, required=True)
    c.add_argument("--rebuilt", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("admit")
    a.add_argument("--bundle", type=Path, required=True)
    a.add_argument("--verdict", type=Path, required=True)
    k = sub.add_parser("pack")
    k.add_argument("--bundle", type=Path, required=True)
    k.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    try:
        if args.cmd == "manifest":
            print(write_manifest(args.bundle, args.release, args.image, args.image_id, args.epoch))
        elif args.cmd == "verify":
            problems = verify(args.bundle)
            for problem in problems:
                print(problem, file=sys.stderr)
            if problems:
                return 1
            print(f"{args.bundle}: every file matches {MANIFEST}")
        elif args.cmd == "compare":
            verdict = compare(args.bundle, args.rebuilt)
            args.out.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            word = "reproduced" if verdict["reproduced"] else "DID NOT reproduce"
            print(f"offline rebuild {word} the shipped deliverables; verdict in {args.out}")
        elif args.cmd == "admit":
            admit(args.bundle, args.verdict)
            print(f"{args.bundle}: proved by an offline rebuild; admitted")
        elif args.cmd == "pack":
            print(pack(args.bundle, args.out))
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
