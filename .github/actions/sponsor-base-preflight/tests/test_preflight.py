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
    references_from,
    granted_permission_names,
    main,
    parse_declared_permissions,
)

DIGEST = "sha256:" + "a" * 64


# ---------------------------------------------------------------- pins (G)


class TestCheckPins:
    """Verifies: HSI-OPS-image-promotion/G

    The references checked here are the ones the build is about to consume. The
    sponsor names a commit and the build resolves it to a digest, so the value
    being checked exists only at the point the build consumes it.
    """

    def test_accepts_digest_pinned_references(self):
        assert check_pins([f"ghcr.io/cure-hht/sponsor-ci@{DIGEST}",
                           f"ghcr.io/cure-hht/portal-server@{DIGEST}"]) == []

    def test_rejects_the_mutable_tag_that_caused_cur_1668(self):
        errors = check_pins(["ghcr.io/cure-hht/portal-server:main-latest"])
        assert len(errors) == 1
        assert "main-latest" in errors[0]

    def test_rejects_a_bare_name_with_no_reference_at_all(self):
        assert len(check_pins(["ghcr.io/cure-hht/sponsor-ci"])) == 1

    def test_rejects_a_short_or_malformed_digest(self):
        errors = check_pins([
            "ghcr.io/x/y@sha256:abc",
            "ghcr.io/x/y@sha512:" + "a" * 128,
            "ghcr.io/x/y@" + "a" * 64,
        ])
        assert len(errors) == 3

    def test_rejects_an_uppercase_digest(self):
        """A digest is lowercase hex; the registry will not resolve this one."""
        errors = check_pins(["ghcr.io/x/y@sha256:" + "A" * 64])
        assert len(errors) == 1
        assert "lowercase" in errors[0]

    def test_rejects_a_tag_and_digest_together(self):
        """Docker resolves the digest and ignores the tag, so the tag is a lie."""
        assert len(check_pins([f"ghcr.io/x/y:main-latest@{DIGEST}"])) == 1

    def test_accepts_a_registry_host_carrying_a_port(self):
        assert check_pins([f"localhost:5000/x/y@{DIGEST}"]) == []

    def test_reports_every_offender_not_just_the_first(self):
        errors = check_pins([
            "ghcr.io/x/a:latest",
            "ghcr.io/x/b:main",
            f"ghcr.io/x/c@{DIGEST}",
        ])
        assert len(errors) == 2

    def test_no_references_at_all_is_an_error_not_a_pass(self):
        """A build consuming no checked base is not a build that passed.

        The empty case is how this check silently stops checking: a caller that
        stops passing its references gets a green preflight for a build whose
        bases nothing examined.
        """
        assert len(check_pins([])) == 1

    def test_an_empty_reference_is_named_rather_than_skipped(self):
        """An unset workflow input arrives as an empty string, not as absence."""
        errors = check_pins(["", f"ghcr.io/x/y@{DIGEST}"])
        assert len(errors) == 1
        assert "line 1" in errors[0]


class TestSplittingTheCallersList:
    """Verifies: HSI-OPS-image-promotion/G

    The composite hands over one newline-delimited string and the split happens
    here, not in shell. A shell loop skipping blank lines would drop exactly the
    input the empty-reference check exists to catch: an interpolation that
    resolved to nothing leaves a blank line, and the build would pass with a
    base nothing examined.
    """

    def test_a_blank_line_from_an_unset_interpolation_is_not_dropped(self):
        errors = check_pins(references_from(f"\nghcr.io/cure-hht/portal-server@{DIGEST}\n"))
        assert len(errors) == 1
        assert "line 1" in errors[0]

    def test_the_trailing_newline_of_a_yaml_block_is_not_a_reference(self):
        blob = f"ghcr.io/x/a@{DIGEST}\nghcr.io/x/b@{DIGEST}\n"
        assert check_pins(references_from(blob)) == []

    def test_an_entirely_empty_input_yields_no_references(self):
        """`required: true` is not enforced for a composite action's inputs."""
        assert references_from("") == []
        assert len(check_pins(references_from(""))) == 1

    def test_a_whitespace_only_line_is_an_empty_reference(self):
        errors = check_pins(references_from(f"   \nghcr.io/x/y@{DIGEST}\n"))
        assert len(errors) == 1
        assert "line 1" in errors[0]


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

    def test_a_scalar_grant_raises_instead_of_iterating_characters(self):
        # `CRA: portal.site.view` (no `-`) is valid YAML and a plausible typo.
        # Iterating it yields one "permission" per character, so the build
        # fails with a wall of single letters instead of naming the mistake.
        with pytest.raises(ValueError) as excinfo:
            granted_permission_names({"grants": {"CRA": "portal.site.view"}})
        assert "CRA" in str(excinfo.value)

    def test_a_non_string_grant_entry_raises(self):
        with pytest.raises(ValueError) as excinfo:
            granted_permission_names({"grants": {"CRA": ["portal.site.view", 7]}})
        assert "CRA" in str(excinfo.value)

    def test_an_empty_grant_entry_raises(self):
        with pytest.raises(ValueError) as excinfo:
            granted_permission_names({"grants": {"CRA": ["portal.site.view", "  "]}})
        assert "CRA" in str(excinfo.value)


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


# ------------------------------------------------------------------ CLI


class TestMainReportsFailuresAsAnnotations:
    """Every expected failure exits 1 with an ::error:: line, never a traceback."""

    def _run(self, capsys, argv):
        code = main(argv)
        return code, capsys.readouterr().out

    def test_a_reference_that_is_not_a_pin_is_an_annotation(self, capsys):
        code, out = self._run(capsys, ["pins", "--images", "ghcr.io/x/y:main-latest"])
        assert code == 1
        assert "::error::" in out

    def test_no_images_supplied_is_an_annotation(self, capsys):
        """The way this check stops checking is a caller that passes nothing."""
        code, out = self._run(capsys, ["pins", "--images", ""])
        assert code == 1
        assert "::error::" in out

    def test_pinned_references_still_report_normally(self, capsys):
        code, out = self._run(
            capsys, ["pins", "--images", f"ghcr.io/x/y@{DIGEST}\nghcr.io/x/z@{DIGEST}\n"]
        )
        assert code == 0
        assert out.startswith("ok - ")

    def test_empty_declared_manifest(self, capsys, tmp_path):
        declared = tmp_path / "PORTAL_ACTIONS"
        declared.write_text("\n\n", encoding="utf-8")
        grants = tmp_path / "role-permissions.yaml"
        grants.write_text("grants:\n  CRA:\n    - portal.site.view\n", encoding="utf-8")
        code, out = self._run(
            capsys,
            ["capabilities", "--declared", str(declared), "--grants", str(grants)],
        )
        assert code == 1
        assert "::error::" in out

    def test_malformed_grants_yaml(self, capsys, tmp_path):
        declared = tmp_path / "PORTAL_ACTIONS"
        declared.write_text("portal.site.view\n", encoding="utf-8")
        grants = tmp_path / "role-permissions.yaml"
        grants.write_text("grants:\n  - [unclosed\n", encoding="utf-8")
        code, out = self._run(
            capsys,
            ["capabilities", "--declared", str(declared), "--grants", str(grants)],
        )
        assert code == 1
        assert "::error::" in out
        assert str(grants) in out

    def test_scalar_grant_names_the_role_in_the_annotation(self, capsys, tmp_path):
        declared = tmp_path / "PORTAL_ACTIONS"
        declared.write_text("portal.site.view\n", encoding="utf-8")
        grants = tmp_path / "role-permissions.yaml"
        grants.write_text("grants:\n  CRA: portal.site.view\n", encoding="utf-8")
        code, out = self._run(
            capsys,
            ["capabilities", "--declared", str(declared), "--grants", str(grants)],
        )
        assert code == 1
        assert "::error::" in out
        assert "CRA" in out
