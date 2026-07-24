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
