"""Tests for `pipeline/join`.

The load-bearing case is the collision: two legs writing the same path. That is
the one thing a join can check without knowing anything about what the legs did,
and without it the leg that landed second silently overwrites the first, leaving
an image that looks complete and is missing a leg's work.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import pathlib

import pytest

JOIN_PATH = pathlib.Path(__file__).resolve().parents[1] / "join"


def _load():
    spec = importlib.util.spec_from_loader(
        "join_under_test",
        importlib.machinery.SourceFileLoader("join_under_test", str(JOIN_PATH)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


join = _load()


def _delta(tmp_path, name, files):
    d = tmp_path / name
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return d


def test_paths_are_relative_to_the_delta_root(tmp_path):
    d = _delta(tmp_path, "e2e", {"evidence/acme/e2e.rc": "0", "reports/e2e.html": "<html>"})
    assert join.paths_in(str(d)) == {"evidence/acme/e2e.rc", "reports/e2e.html"}


def test_an_empty_delta_has_no_paths(tmp_path):
    d = tmp_path / "nothing"
    d.mkdir()
    assert join.paths_in(str(d)) == set()


def test_two_legs_writing_different_paths_do_not_collide():
    already = {"e2e": {"reports/e2e.html"}}
    assert join.collisions({"reports/mobile.xml"}, already) == {}


def test_two_legs_writing_ONE_path_collide_and_the_leg_is_named():
    """The case the join exists for."""
    already = {"e2e": {"reports/shared.xml", "reports/e2e.html"}}

    clashes = join.collisions({"reports/shared.xml", "reports/mobile.xml"}, already)

    assert clashes == {"e2e": {"reports/shared.xml"}}


def test_a_collision_across_several_legs_names_all_of_them():
    already = {
        "e2e": {"reports/a.xml"},
        "mobile": {"reports/b.xml"},
        "device": {"reports/c.xml"},
    }

    clashes = join.collisions({"reports/a.xml", "reports/c.xml"}, already)

    assert set(clashes) == {"e2e", "device"}


def test_the_first_join_onto_a_clean_image_collides_with_nothing():
    assert join.collisions({"anything"}, {}) == {}


def test_a_bare_image_id_is_refused_as_a_base():
    """Docker would read it as a repository name and fail obscurely.

    It is also machine-local: the join would work here and resolve to nothing
    anywhere else, which is the whole reason a step records the digest it got.
    """
    ok, why = join.usable_base("sha256:d20246e853d2db4ff4c11ffbe3c34b012ff0185e54a56851e8effaddad7f42b0")
    assert not ok
    assert "bare image id" in why


def test_a_digest_reference_is_accepted():
    ok, _ = join.usable_base("ghcr.io/cure-hht/x-pipeline@sha256:" + "a" * 64)
    assert ok


def test_a_tagged_reference_is_accepted():
    ok, _ = join.usable_base("sponsor-pipeline:local")
    assert ok


def test_a_name_with_neither_tag_nor_digest_is_refused():
    ok, why = join.usable_base("ghcr.io/cure-hht/x-pipeline")
    assert not ok
    assert "neither a digest nor a tag" in why


def test_the_join_restores_the_users_the_base_ran_as():
    """A join adds evidence. It must not change what the image runs as.

    The first version left every joined image running as root, which broke git
    in the workspace -- the files belong to the build user and the process no
    longer did -- and silently changed the runtime user of a published image.
    """
    text = join.dockerfile_for("base@sha256:" + "a" * 64, "/evidence/acme", "devuser")

    assert "--chown=devuser" in text
    instructions = [l for l in text.splitlines() if l and not l.startswith("#")]
    assert not any(l.startswith("USER") for l in instructions), (
        "a join must not change what the image runs as"
    )


def test_a_base_that_declares_no_user_is_a_root_base():
    """An empty user means the base really does run as root.

    This test used to be called "left alone" while asserting --chown=root,
    which are opposite claims -- it locked in the behaviour join exists to
    prevent. The name now matches what is asserted, and the case where the
    user could not be READ is covered separately, because those two must not
    give the same answer.
    """
    text = join.dockerfile_for("base:tag", "/evidence", "")
    assert "--chown=root" in text
    instructions = [l for l in text.splitlines() if l and not l.startswith("#")]
    assert not any(l.startswith("USER") for l in instructions)


def test_a_user_that_cannot_be_read_is_refused_not_assumed_root(monkeypatch):
    """The failure path that used to be indistinguishable from a root base."""
    class _Failed:
        returncode = 1
        stdout = ""
        stderr = "no such image"

    monkeypatch.setattr(join, "_run", lambda *a, **k: _Failed())
    with pytest.raises(RuntimeError, match="cannot read the user"):
        join.base_user("base:tag")


def test_a_repo_that_is_not_a_name_is_refused(tmp_path):
    """`--repo 'ns$(id -u)'` ran the substitution inside the base image."""
    with pytest.raises(SystemExit, match="not a name"):
        join._checked_name("ns$(id -u)", "--repo")


def test_a_leg_that_escapes_the_work_directory_is_refused(tmp_path):
    """`--leg ../../escaped` wrote outside the context and still exited 0.

    The image then carried no manifest for the leg, so the next join was free
    to overwrite its files -- the collision refusal defeated by a leg name.
    """
    with pytest.raises(SystemExit, match="not a name"):
        join._checked_name("../../escaped", "--leg")


def test_ordinary_names_are_accepted():
    for ok in ("e2e", "mobile", "hht_diary", "callisto", "leg-1", "a.b"):
        assert join._checked_name(ok, "--leg") == ok
