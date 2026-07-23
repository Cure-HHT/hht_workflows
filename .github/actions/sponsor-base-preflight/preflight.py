#!/usr/bin/env python3
"""Base-image preflight for the sponsor final-image build (CUR-1668).

Two independent checks, run before the sponsor image is built:

``pins``
    Every base image the sponsor final image is built FROM, as declared in the
    sponsor's ``deployment/base-config.json``, is a content digest. A mutable
    tag is rejected. Realizes HSI-OPS-image-promotion/G.

``capabilities``
    The pinned portal-server base declares every permission the sponsor's
    ``role-permissions.yaml`` grants. Realizes HSI-OPS-image-promotion/H.

Why the second check exists: the portal server fails closed at boot when a role
is granted a permission no Action declares. That is correct behavior, but it
surfaces after a deploy as an opaque "container failed to start and listen on
PORT" — the CUR-1624 incident. Deciding it at build time names the offending
permissions instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Iterable

# `name@sha256:<64 lowercase hex>`, with no tag on the name. A registry host may
# carry a port (`localhost:5000/x/y@sha256:...`), so "has a tag" means a colon
# in the LAST path segment, not anywhere in the name.
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _pin_error(key: str, value: object) -> str | None:
    """Return an error message for one base_images entry, or None if it is a pin."""
    if not isinstance(value, str) or not value:
        return (
            f"base_images.{key}: expected a digest-pinned image reference, "
            f"got {value!r}"
        )
    if "@" not in value:
        return (
            f"base_images.{key}: '{value}' is not pinned to a content digest. "
            f"Use '<image>@sha256:<digest>'; a mutable tag lets two builds of "
            f"the same commit embed different base content (CUR-1668)."
        )
    name, _, digest = value.partition("@")
    if not _DIGEST_RE.match(digest):
        return (
            f"base_images.{key}: '{value}' does not end in a sha256 content "
            f"digest (expected '@sha256:' followed by 64 lowercase hex chars)."
        )
    if ":" in name.rsplit("/", 1)[-1]:
        return (
            f"base_images.{key}: '{value}' carries both a tag and a digest. "
            f"The tag is ignored at resolution and misreads as the pin — "
            f"give the digest alone."
        )
    return None


# Implements: HSI-OPS-image-promotion/G
def check_pins(config: dict) -> list[str]:
    """Errors for every non-digest base image reference in a base-config document."""
    base_images = config.get("base_images")
    if not isinstance(base_images, dict) or not base_images:
        return [
            "base_images: section is missing or empty. The sponsor final image "
            "is built FROM at least one base image; every one of them must be "
            "declared here so it can be pinned and checked."
        ]
    errors = []
    for key in sorted(base_images):
        error = _pin_error(key, base_images[key])
        if error is not None:
            errors.append(error)
    return errors


def parse_declared_permissions(text: str) -> set[str]:
    """Parse the base image's /app/PORTAL_ACTIONS manifest (one name per line)."""
    names = {line.strip() for line in text.splitlines() if line.strip()}
    if not names:
        raise ValueError(
            "the base image's permission manifest is empty — the server "
            "declares no permissions, which almost certainly means the "
            "manifest was not extracted from the image correctly"
        )
    return names


def granted_permission_names(doc: dict) -> set[str]:
    """Union of the permission names granted to any role in a role-permissions doc."""
    grants = doc.get("grants")
    if not isinstance(grants, dict):
        raise ValueError(
            "role-permissions document has no 'grants' mapping; refusing to "
            "treat that as 'nothing is granted'"
        )
    names: set[str] = set()
    for role, permissions in grants.items():
        if permissions is None:
            continue
        # A scalar is the dangerous case: `CRA: portal.site.view` (a missing
        # `-`) is valid YAML, and iterating a string yields one "permission"
        # per character — the build would fail naming single letters instead
        # of the typo.
        if isinstance(permissions, str) or not isinstance(permissions, (list, tuple)):
            raise ValueError(
                f"grants.{role} must be a list of permission names, got "
                f"{type(permissions).__name__}. A single permission still "
                f"needs to be a list item (`- {permissions}`)."
                if isinstance(permissions, str)
                else f"grants.{role} must be a list of permission names, got "
                f"{type(permissions).__name__}."
            )
        for entry in permissions:
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError(
                    f"grants.{role} contains an entry that is not a permission "
                    f"name: {entry!r}"
                )
            names.add(entry.strip())
    return names


# Implements: HSI-OPS-image-promotion/H
def check_capabilities(declared: Iterable[str], grants_yaml: str) -> list[str]:
    """Errors when the sponsor overlay grants a permission the base does not declare."""
    import yaml  # imported here so the pins check needs no third-party dep

    try:
        document = yaml.safe_load(grants_yaml) or {}
    except yaml.YAMLError as exc:
        # Re-raised as ValueError so the CLI has one expected-failure type to
        # catch without importing yaml for the pins path.
        raise ValueError(f"role-permissions document is not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(
            "role-permissions document must be a mapping with a 'grants' key"
        )
    granted = granted_permission_names(document)
    missing = sorted(granted - set(declared))
    if not missing:
        return []
    return [
        "the pinned portal-server base does not declare "
        f"{len(missing)} granted permission(s): {', '.join(missing)}. "
        "The base predates the Actions this sponsor configuration grants; "
        "advance base_images.portal_server to a core build that declares them. "
        "Shipping this image would fail closed at portal boot."
    ]


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise OSError(f"could not read {path}: {exc.strerror or exc}") from exc


def _with_path(path: str, fn, *args):
    """Run a parse step, naming the file it was reading if it rejects the input."""
    try:
        return fn(*args)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _load_json(path: str) -> dict:
    text = _read_text(path)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def _report(errors: list[str], ok_message: str) -> int:
    if not errors:
        print(f"ok - {ok_message}")
        return 0
    for error in errors:
        print(f"::error::{error}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pins = sub.add_parser("pins", help="check base_images are digest-pinned")
    pins.add_argument("--base-config", required=True)

    caps = sub.add_parser("capabilities", help="check base declares granted permissions")
    caps.add_argument(
        "--declared",
        required=True,
        help="path to the manifest extracted from the base image (/app/PORTAL_ACTIONS)",
    )
    caps.add_argument("--grants", required=True, help="path to role-permissions.yaml")

    args = parser.parse_args(argv)

    # Every failure this tool can anticipate — an unreadable or malformed
    # input, an empty manifest, a grants file that is not shaped like one —
    # is a build failure that a human has to act on. Report each as the same
    # single ::error:: annotation the checks themselves emit; a raw traceback
    # buries the actionable line in a stack.
    try:
        if args.command == "pins":
            config = _load_json(args.base_config)
            return _report(
                check_pins(config),
                f"every base image in {args.base_config} is pinned to a content digest",
            )

        declared = _with_path(args.declared, parse_declared_permissions, _read_text(args.declared))
        return _report(
            _with_path(args.grants, check_capabilities, declared, _read_text(args.grants)),
            f"the pinned base declares every permission granted in {args.grants}",
        )
    except (OSError, ValueError) as exc:
        # Workflow-command annotations are single-line: a raw multi-line
        # parser error (PyYAML's are) would be truncated at the first newline,
        # hiding the part that says what is wrong.
        print(f"::error::{' '.join(str(exc).split())}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
