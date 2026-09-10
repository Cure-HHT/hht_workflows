"""Offline unit tests for the obtain-upstream action's pin resolution.

A pin names one artifact or it names nothing. These cases cover the ways a
caller can hand over something that looks like a pin but is not one: a short
sha, a branch name, and uppercase hex. Each must refuse rather than resolve,
because a pin that silently becomes a different reference is the failure this
whole arrangement exists to remove -- a deliverable would then describe a
revision the build never used, and nothing downstream could tell.

Uppercase hex gets its own case on purpose. Normalising it would be the
friendly thing to do and the wrong one: it means the pin a reviewer reads is
not the pin that resolved.
"""

import pytest

from resolve_pin import PinError, image_reference

GOOD = "cbbbf10438edc6c2d83e8d0efbee4b32ced4feae"


def test_builds_a_commit_tagged_reference():
    assert image_reference("ghcr.io", "cure-hht/hht_diary", GOOD) == (
        f"ghcr.io/cure-hht/hht_diary:commit-{GOOD}"
    )


def test_rejects_a_short_sha():
    with pytest.raises(PinError, match="40 hex characters"):
        image_reference("ghcr.io", "cure-hht/hht_diary", GOOD[:12])


def test_rejects_a_branch_name():
    with pytest.raises(PinError, match="40 hex characters"):
        image_reference("ghcr.io", "cure-hht/hht_diary", "main")


def test_rejects_uppercase_hex_rather_than_lowercasing_it():
    with pytest.raises(PinError, match="40 hex characters"):
        image_reference("ghcr.io", "cure-hht/hht_diary", GOOD.upper())


def test_rejects_an_empty_repository():
    with pytest.raises(PinError, match="repository"):
        image_reference("ghcr.io", "", GOOD)
