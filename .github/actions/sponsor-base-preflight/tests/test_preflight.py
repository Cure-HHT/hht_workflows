"""Tests for the sponsor build's base-image preflight checks (CUR-1668).

The two checks are independent obligations:

* pins  -> HSI-OPS-image-promotion/G: every base image the sponsor final image
           is built FROM is a content digest, never a mutable tag.
* caps  -> HSI-OPS-image-promotion/H: the pinned base declares every permission
           the sponsor's role-permissions overlay grants.
"""

import textwrap

import pytest

from preflight import (
    check_capabilities,
    check_pins,
    granted_permission_names,
    parse_declared_permissions,
)

DIGEST = "sha256:" + "a" * 64


# ---------------------------------------------------------------- pins (G)


class TestCheckPins:
    """Verifies: HSI-OPS-image-promotion/G"""

    def test_accepts_digest_pinned_bases(self):
        config = {
            "base_images": {
                "sponsor_ci": f"ghcr.io/cure-hht/sponsor-ci@{DIGEST}",
                "portal_server": f"ghcr.io/cure-hht/portal-server@{DIGEST}",
            }
        }
        assert check_pins(config) == []

    def test_rejects_the_mutable_tag_that_caused_cur_1668(self):
        config = {
            "base_images": {"portal_server": "ghcr.io/cure-hht/portal-server:main-latest"}
        }
        errors = check_pins(config)
        assert len(errors) == 1
        assert "portal_server" in errors[0]
        assert "main-latest" in errors[0]

    def test_rejects_a_bare_name_with_no_reference_at_all(self):
        config = {"base_images": {"sponsor_ci": "ghcr.io/cure-hht/sponsor-ci"}}
        assert len(check_pins(config)) == 1

    def test_rejects_a_short_or_malformed_digest(self):
        config = {
            "base_images": {
                "a": "ghcr.io/x/y@sha256:abc123",
                "b": "ghcr.io/x/y@md5:" + "a" * 32,
                "c": "ghcr.io/x/y@sha256:" + "A" * 64,  # uppercase is not a digest
            }
        }
        assert len(check_pins(config)) == 3

    def test_rejects_a_tag_and_digest_together(self):
        # `name:tag@sha256:...` resolves by digest, but the tag is dead weight
        # that reads as if it were the pin. One unambiguous form only.
        config = {"base_images": {"a": f"ghcr.io/x/y:main-latest@{DIGEST}"}}
        assert len(check_pins(config)) == 1

    def test_accepts_a_registry_host_carrying_a_port(self):
        config = {"base_images": {"a": f"localhost:5000/x/y@{DIGEST}"}}
        assert check_pins(config) == []

    def test_reports_every_offender_not_just_the_first(self):
        config = {
            "base_images": {
                "sponsor_ci": "ghcr.io/cure-hht/sponsor-ci:main-latest",
                "portal_server": "ghcr.io/cure-hht/portal-server:main-latest",
            }
        }
        errors = check_pins(config)
        assert len(errors) == 2

    def test_missing_base_images_section_is_an_error_not_a_pass(self):
        # A config that names no base images must not silently succeed: the
        # sponsor image is built FROM something, so an empty section means the
        # pins moved somewhere unchecked.
        assert len(check_pins({})) == 1
        assert len(check_pins({"base_images": {}})) == 1

    def test_non_string_value_is_an_error(self):
        assert len(check_pins({"base_images": {"a": None}})) == 1


# -------------------------------------------------------- capabilities (H)


class TestGrantedPermissionNames:
    def test_collects_the_union_across_roles(self):
        doc = {
            "roles": ["CRA", "Administrator"],
            "grants": {
                "CRA": ["portal.site.view", "portal.site.view_list"],
                "Administrator": ["portal.site.view_list", "portal.user.create"],
            },
        }
        assert granted_permission_names(doc) == {
            "portal.site.view",
            "portal.site.view_list",
            "portal.user.create",
        }

    def test_a_role_granted_nothing_contributes_nothing(self):
        doc = {"grants": {"CRA": None, "SystemOperator": []}}
        assert granted_permission_names(doc) == set()

    def test_missing_grants_section_raises_rather_than_passing_vacuously(self):
        with pytest.raises(ValueError):
            granted_permission_names({"roles": ["CRA"]})


class TestParseDeclaredPermissions:
    def test_reads_one_bare_name_per_line(self):
        text = "portal.site.view\nportal.site.view_list\n"
        assert parse_declared_permissions(text) == {
            "portal.site.view",
            "portal.site.view_list",
        }

    def test_tolerates_trailing_whitespace_and_blank_lines(self):
        text = "portal.site.view  \n\n  portal.user.create\n\n"
        assert parse_declared_permissions(text) == {
            "portal.site.view",
            "portal.user.create",
        }

    def test_an_empty_manifest_raises_rather_than_declaring_nothing(self):
        # An empty /app/PORTAL_ACTIONS would make every grant look undeclared;
        # more likely the extraction failed. Fail loudly on the extraction, not
        # with a wall of false mismatches.
        with pytest.raises(ValueError):
            parse_declared_permissions("   \n\n")


class TestCheckCapabilities:
    """Verifies: HSI-OPS-image-promotion/H"""

    GRANTS = textwrap.dedent(
        """\
        roles:
          - CRA
          - Administrator
        grants:
          CRA:
            - portal.site.view
            - portal.site.view_list
          Administrator:
            - portal.user.create
        """
    )

    def test_passes_when_the_base_declares_every_granted_permission(self):
        declared = {
            "portal.site.view",
            "portal.site.view_list",
            "portal.user.create",
            "portal.audit.view",  # base may declare more than the sponsor grants
        }
        assert check_capabilities(declared, self.GRANTS) == []

    def test_reproduces_cur_1624_a_stale_base_missing_view_list(self):
        # The exact incident: sponsor grants portal.site.view_list, the stale
        # portal-server base predates ACT-SEE-005 and declares no such Action.
        declared = {"portal.site.view", "portal.user.create"}
        errors = check_capabilities(declared, self.GRANTS)
        assert len(errors) == 1
        assert "portal.site.view_list" in errors[0]

    def test_names_every_missing_permission_so_one_build_fixes_them_all(self):
        declared = {"portal.site.view"}
        errors = check_capabilities(declared, self.GRANTS)
        joined = " ".join(errors)
        assert "portal.site.view_list" in joined
        assert "portal.user.create" in joined

    def test_missing_names_are_reported_in_a_stable_order(self):
        declared = set()
        first = check_capabilities(declared, self.GRANTS)
        second = check_capabilities(set(declared), self.GRANTS)
        assert first == second
