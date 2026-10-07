"""Tests for the download-integrity hook.

The cases are the shapes the Cure-HHT estate actually had: a tarball unpacked
unchecked, a vendor installer piped into `sudo sh`, an apt key piped into gpg, a
release checked against the checksums.txt published beside it, a download whose
URL is assembled in a shell variable, a workflow template copied into sponsor
repositories. And the shapes it must not flag: an API reply kept as evidence, a
health probe, a URL in a comment, a download checked against a recorded digest
or a pinned signing key.
"""
# Verifies: HHT-OPS-ci-tool-download-integrity/C

import pathlib
import subprocess
import textwrap

import yaml

from download_integrity.__main__ import (
    check_arg_defaults,
    check_dockerfile,
    check_versions_env,
    check_workflow,
    is_workflow,
    main,
    scan,
)

SHA_A = "a" * 64


def dockerfile(body: str):
    return check_dockerfile("Dockerfile", textwrap.dedent(body))


def step(script: str):
    wf = {"jobs": {"j": {"steps": [{"name": "s", "run": textwrap.dedent(script)}]}}}
    return check_workflow("wf.yml", yaml.safe_dump(wf))


# ------------------------------------------------------------ flagged


def test_tarball_unpacked_without_verification():
    assert len(dockerfile("""
        RUN wget -q https://example.com/tool.tar.xz && \\
            tar -xJf tool.tar.xz
    """)) == 1


def test_vendor_installer_piped_to_sudo_sh():
    found = step("""
        curl -Ls --tlsv1.2 --proto "=https" --retry 3 https://cli.example.com/install.sh \\
          | sudo sh -s -- --version "1.2.3"
    """)
    assert any("interpreter" in f.message for f in found), found


def test_signing_key_piped_into_gpg_without_fingerprint_check():
    assert len(dockerfile("""
        RUN curl -fsSL https://apt.example.com/gpg | gpg --dearmor -o /usr/share/keyrings/x.gpg
    """)) == 1


def test_checksum_file_from_the_same_release_is_not_a_verification():
    found = step("""
        base="https://github.com/acme/cli/releases/download/1.2.3"
        asset="cli_1.2.3_linux_amd64.tar.gz"
        curl -fsSL -o "/tmp/$asset" "$base/$asset"
        curl -fsSL -o /tmp/checksums.txt "$base/checksums.txt"
        (cd /tmp && awk -v f="$asset" '$2 == f' checksums.txt | sha256sum -c -)
        sudo tar -xzf "/tmp/$asset" -C /usr/local/bin cli
    """)
    assert any("not authentic" in f.message for f in found), found


def test_url_assembled_in_a_variable_is_still_a_download():
    found = step("""
        base="https://example.com/releases/1.0"
        curl -fsSL -o /tmp/tool.tgz "$base/tool.tgz"
        tar -xzf /tmp/tool.tgz
    """)
    assert len(found) == 1, found


def test_verification_only_in_a_comment_does_not_count():
    assert len(step("""
        # echo "$SHA  tool.tgz" | sha256sum -c -
        wget -q https://example.com/tool.tgz
        tar -xzf tool.tgz
    """)) == 1


def test_add_url_without_checksum():
    assert len(dockerfile("ADD https://example.com/tool /usr/local/bin/tool\n")) == 1


def test_two_downloads_one_verification():
    assert len(dockerfile("""
        RUN curl -fsSLo a.tgz https://example.com/a.tgz && \\
            curl -fsSLo b.tgz https://example.com/b.tgz && \\
            echo "$A  a.tgz" | sha256sum -c - && \\
            tar xzf a.tgz && tar xzf b.tgz
    """)) == 1


# ------------------------------------------------------------ accepted


def test_recorded_digest_before_unpack():
    assert dockerfile("""
        RUN wget -q https://example.com/doppler.tgz && \\
            echo "${SHA}  doppler.tgz" | sha256sum -c - && \\
            tar xzf doppler.tgz
    """) == []


def test_signature_against_pinned_key():
    assert step("""
        curl -fsSL -o t.tgz https://example.com/t.tgz
        curl -fsSL -o t.tgz.sig https://example.com/t.tgz.sig
        gpg --batch --verify t.tgz.sig t.tgz
        tar -xzf t.tgz
    """) == []


def test_install_scripts_of_this_repository_verify():
    assert step("""
        "${GITHUB_ACTION_PATH}/../install-gitleaks/install.sh" "$GITLEAKS_VERSION"
    """) == []


def test_api_reply_kept_as_evidence_is_not_a_tool():
    assert step("""
        curl --fail -sS -H "Authorization: Bearer $T" \\
          "https://testing.googleapis.com/v1/projects/p/testMatrices/m" -o evidence/m.json
    """) == []


def test_local_health_probe_is_not_a_download():
    assert dockerfile("RUN curl -fsS -o /dev/null http://127.0.0.1:8080/health && tar --version\n") == []


def test_exemption_marker_with_reason():
    assert step("""
        # download-integrity: exempt vendor publishes no stable artifact; tracked in CUR-0000
        curl -fsSLo x.zip https://example.com/x.zip && unzip x.zip
    """) == []


def test_add_url_with_checksum():
    assert dockerfile(f"ADD --checksum=sha256:{SHA_A} https://example.com/t /t\n") == []


# ------------------------------------------------------------ scope and pins


def test_workflow_templates_are_scanned():
    assert is_workflow("scaffold/hotfix-deploy/hotfix.yml.template")
    assert not is_workflow("docs/notes.yml.example")


def test_malformed_digest_in_versions_env():
    assert len(check_versions_env("versions.env", "TOOL_SHA256=ABC\n")) == 1


def test_dockerfile_default_digest_must_match_versions_env():
    pins = {"TOOL_VERSION": "1.0", "TOOL_SHA256": SHA_A}
    assert len(check_arg_defaults("Dockerfile", f"ARG TOOL_VERSION=1.0\nARG TOOL_SHA256={'b' * 64}\n", pins)) == 1


def test_main_checks_only_the_files_passed(tmp_path, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".github/workflows").mkdir(parents=True)
    bad = {"jobs": {"j": {"steps": [{"name": "s", "run": "curl -fsSL https://x.example/i.sh | sh\n"}]}}}
    (tmp_path / ".github/workflows/bad.yml").write_text(yaml.safe_dump(bad))
    (tmp_path / "README.md").write_text("not scanned")
    assert main(["--root", str(tmp_path), "README.md"]) == 0
    assert main(["--root", str(tmp_path), ".github/workflows/bad.yml"]) == 1


def test_each_finding_names_the_assertion_it_breaks():
    found = step("curl -fsSL https://x.example/i.sh | sh\n")
    assert found and all(str(f).endswith("[breaks HHT-OPS-ci-tool-download-integrity/A]") for f in found)


def test_this_repository_is_clean():
    root = pathlib.Path(__file__).resolve().parents[3]
    findings = scan(root)
    assert findings == [], "\n".join(map(str, findings))
