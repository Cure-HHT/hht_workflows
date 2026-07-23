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
    for permissions in grants.values():
        if permissions:
            names.update(str(p) for p in permissions)
    return names


def check_capabilities(declared: Iterable[str], grants_yaml: str) -> list[str]:
    """Errors when the sponsor overlay grants a permission the base does not declare."""
    import yaml  # imported here so the pins check needs no third-party dep

    granted = granted_permission_names(yaml.safe_load(grants_yaml) or {})
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

    if args.command == "pins":
        with open(args.base_config, encoding="utf-8") as handle:
            config = json.load(handle)
        return _report(
            check_pins(config),
            f"every base image in {args.base_config} is pinned to a content digest",
        )

    with open(args.declared, encoding="utf-8") as handle:
        declared = parse_declared_permissions(handle.read())
    with open(args.grants, encoding="utf-8") as handle:
        grants_yaml = handle.read()
    return _report(
        check_capabilities(declared, grants_yaml),
        f"the pinned base declares every permission granted in {args.grants}",
    )


if __name__ == "__main__":
    sys.exit(main())
