"""Exercise the shell guard functions through a real shell.

Verifies: HHT-OPS-repo-bootstrap/F,I
"""
import subprocess
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "hooks-guard.sh"


def run_fn(fn: str, repo: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    script = f'. "{GUARD}"; {fn} "{repo}"'
    full_env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(repo)}
    full_env.update(env or {})
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=full_env
    )


def make_repo(tmp_path: Path, *, namespace="DIARY", cites=None) -> Path:
    repo = tmp_path / "repo"
    (repo / "spec").mkdir(parents=True)
    (repo / ".elspais.toml").write_text(
        f'[project]\nnamespace = "{namespace}"\n'
    )
    body = "## DIARY-OPS-thing: Thing\n"
    if cites:
        body += f"**Refines**: {cites}\n"
    (repo / "spec" / "ops-thing.md").write_text(body)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_linked_ok_when_repo_cites_nobody(tmp_path):
    repo = make_repo(tmp_path)
    assert run_fn("hht_associates_linked", repo).returncode == 0


def test_linked_fails_when_citation_unresolved(tmp_path):
    repo = make_repo(tmp_path, cites="HHT-OPS-repo-bootstrap")
    assert run_fn("hht_associates_linked", repo).returncode == 1


def test_linked_ok_when_local_toml_lists_an_associate(tmp_path):
    repo = make_repo(tmp_path, cites="HHT-OPS-repo-bootstrap")
    (repo / ".elspais.local.toml").write_text(
        '[associates.HHT]\npath = "/somewhere/hht_admin"\n'
    )
    assert run_fn("hht_associates_linked", repo).returncode == 0


def test_guard_names_the_command_when_unlinked(tmp_path):
    repo = make_repo(tmp_path, cites="HHT-OPS-repo-bootstrap")
    res = run_fn("hht_associates_guard", repo, env={"CI": ""})
    assert "elspais associate --all" in res.stdout
    assert res.returncode == 0


def test_guard_is_silent_under_ci(tmp_path):
    repo = make_repo(tmp_path, cites="HHT-OPS-repo-bootstrap")
    res = run_fn("hht_associates_guard", repo, env={"CI": "true"})
    assert res.stdout.strip() == ""


def test_guard_strict_is_fatal(tmp_path):
    repo = make_repo(tmp_path, cites="HHT-OPS-repo-bootstrap")
    res = run_fn(
        "hht_associates_guard", repo, env={"CI": "", "HHT_HOOKS_GUARD": "strict"}
    )
    assert res.returncode == 1


def test_guard_off_is_silent(tmp_path):
    repo = make_repo(tmp_path, cites="HHT-OPS-repo-bootstrap")
    res = run_fn(
        "hht_associates_guard", repo, env={"CI": "", "HHT_HOOKS_GUARD": "off"}
    )
    assert res.stdout.strip() == ""
    assert res.returncode == 0


def test_linked_fails_when_only_citation_is_base_tier(tmp_path):
    repo = make_repo(tmp_path, cites="OTHER-BASE-something")
    assert run_fn("hht_associates_linked", repo).returncode == 1


def test_linked_fails_when_only_citation_is_gui_tier(tmp_path):
    repo = make_repo(tmp_path, cites="HHT-GUI-something")
    assert run_fn("hht_associates_linked", repo).returncode == 1


def test_linked_ok_when_only_citation_is_own_namespace_base_tier(tmp_path):
    repo = make_repo(tmp_path, cites="DIARY-BASE-something")
    assert run_fn("hht_associates_linked", repo).returncode == 0


def test_linked_fails_when_only_citation_is_a_satisfies_edge(tmp_path):
    repo = tmp_path / "repo"
    (repo / "spec").mkdir(parents=True)
    (repo / ".elspais.toml").write_text('[project]\nnamespace = "DIARY"\n')
    (repo / "spec" / "ops-thing.md").write_text(
        "## DIARY-OPS-thing: Thing\n**Satisfies**: HHT-OPS-repo-bootstrap\n"
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert run_fn("hht_associates_linked", repo).returncode == 1


def make_sibling(tmp_path: Path, name: str = "sibling") -> Path:
    sib = tmp_path / name
    sib.mkdir()
    (sib / ".elspais.toml").write_text('[project]\nnamespace = "OTHER"\n')
    return sib


def test_has_linkable_siblings_true_with_genuine_sibling(tmp_path):
    repo = make_repo(tmp_path)
    make_sibling(tmp_path)
    assert run_fn("hht_has_linkable_siblings", repo).returncode == 0


def test_has_linkable_siblings_false_with_no_siblings(tmp_path):
    repo = make_repo(tmp_path)
    assert run_fn("hht_has_linkable_siblings", repo).returncode == 1


def test_has_linkable_siblings_false_when_only_own_toml_present(tmp_path):
    # Regression test for the bug this function replaces: a naive
    # `find "$REPO_ROOT/.." -name .elspais.toml -not -path "$REPO_ROOT/*"`
    # probe would (once fixed to not exclude everything) still need to make
    # sure it doesn't count the repo's own .elspais.toml as a "sibling".
    # Here the repo's parent directory contains nothing but the repo itself,
    # so there is no linkable sibling.
    repo = make_repo(tmp_path)
    assert run_fn("hht_has_linkable_siblings", repo).returncode == 1
