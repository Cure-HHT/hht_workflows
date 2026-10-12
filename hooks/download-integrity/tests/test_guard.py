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
    is_dockerfile,
    is_workflow,
    main,
    scan,
    select_files,
)

SHA_A = "a" * 64


def dockerfile(body: str):
    return check_dockerfile("Dockerfile", textwrap.dedent(body))


def step(script: str, env: dict | None = None, workflow_env: dict | None = None):
    s = {"name": "s", "run": textwrap.dedent(script)}
    if env:
        s["env"] = env
    wf = {"jobs": {"j": {"steps": [s]}}}
    if workflow_env:
        wf["env"] = workflow_env
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


def test_exemption_marker_with_reason_and_ticket():
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


# ------------------------------------------------------------ signatures and checksum files (1)


def test_signature_named_by_no_verification_is_a_download_when_used():
    found = step("""
        curl -fsSL -o key.asc https://example.com/key.asc
        gpg --import key.asc
    """)
    assert len(found) == 1, found


def test_signature_piped_into_gpg_import_is_a_download():
    assert len(step("curl -fsSL https://example.com/key.asc | gpg --import\n")) == 1


def test_postgres_key_piped_into_gpg_dearmor_is_a_download():
    found = dockerfile("""
        RUN curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pg.gpg
    """)
    assert len(found) == 1 and "piped into gpg" in found[0].message, found


def test_signature_teed_into_keyrings_is_a_download():
    found = step("curl -fsSL https://example.com/k.asc | sudo tee /usr/share/keyrings/k.asc >/dev/null\n")
    assert len(found) == 1, found


def test_key_written_under_keyrings_is_a_download_even_unused():
    assert len(step("curl -fsSL -o /usr/share/keyrings/k.gpg https://example.com/k.gpg\n")) == 1


def test_key_checked_by_fingerprint_before_dearmor_passes():
    assert dockerfile("""
        RUN curl -fsSL -o /tmp/pg.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc && \\
            verify-download key /tmp/pg.asc B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8 && \\
            gpg --dearmor -o /usr/share/keyrings/pg.gpg /tmp/pg.asc
    """) == []


def test_checksum_file_is_a_download_and_cancels_nothing():
    found = step("""
        curl -fsSLo t.tgz https://example.com/t.tgz
        curl -fsSLo SHA256SUMS https://example.com/SHA256SUMS
        sha256sum -c SHA256SUMS --ignore-missing
        tar xzf t.tgz
    """)
    assert len(found) == 2, found
    assert any("not authentic" in f.message for f in found), found


def test_checksum_file_fetched_alone_is_still_a_download():
    assert len(step("curl -fsSLo checksums.txt https://example.com/checksums.txt\n")) == 1


def test_signed_checksum_file_verifies_the_asset():
    assert step("""
        curl -fsSLo t.zip https://example.com/t.zip
        curl -fsSLo t_SHA256SUMS https://example.com/t_SHA256SUMS
        curl -fsSLo t_SHA256SUMS.sig https://example.com/t_SHA256SUMS.sig
        gpg --batch --verify t_SHA256SUMS.sig t_SHA256SUMS
        grep t.zip t_SHA256SUMS | sha256sum -c -
        unzip t.zip
    """) == []


# ------------------------------------------------------------ run by an interpreter (2)


def test_process_substitution_into_bash():
    assert any("interpreter" in f.message for f in step("bash <(curl -fsSL https://example.com/i.sh)\n"))


def test_command_substitution_into_sh_c():
    assert any("interpreter" in f.message for f in step('sh -c "$(wget -qO- https://example.com/i.sh)"\n'))


def test_command_substitution_into_eval_and_source():
    assert step('eval "$(curl -fsSL https://example.com/env)"\n')
    assert step("source <(curl -fsSL https://example.com/env)\n")
    assert step(". <(curl -fsSL https://example.com/env)\n")


def test_wrappers_before_the_interpreter():
    for sink in ("env FOO=1 bash", "sudo -E bash -", "xargs -0 sh", "sudo env A=b sh -s"):
        found = step(f"curl -fsSL https://example.com/i.sh | {sink}\n")
        assert any("interpreter" in f.message for f in found), (sink, found)


def test_api_reply_parsed_by_python_c_is_not_run():
    assert step("""curl -fsSL https://api.example.com/x | python3 -c 'import json,sys; print(json.load(sys.stdin))'\n""") == []


def test_exemption_never_covers_an_interpreter():
    found = step("""
        # download-integrity: exempt vendor-only installer CUR-0000
        curl -fsSL https://example.com/i.sh | sh
    """)
    assert any("interpreter" in f.message for f in found), found


# ------------------------------------------------------------ redirection (3)


def test_redirected_fetch_writes_a_file():
    assert len(step("curl -fsSL https://example.com/tool.tgz > tool.tgz && tar xzf tool.tgz\n")) == 1
    assert len(step("curl -fsSL https://example.com/tool >> /usr/local/bin/tool\n")) == 1


def test_redirected_fetch_then_verified_passes():
    assert step("""
        curl -fsSL https://example.com/tool.tgz > tool.tgz
        echo "$TOOL_SHA256  tool.tgz" | sha256sum -c -
        tar xzf tool.tgz
    """) == []


# ------------------------------------------------------------ split across steps (4)


def test_artifact_download_without_use_in_the_step_is_still_a_download():
    assert len(step("curl -fsSLo /tmp/tool.tgz https://example.com/tool.tgz\n")) == 1
    assert len(step("wget -q https://example.com/tool\n")) == 1


def test_data_fetch_that_nothing_uses_is_not_a_download():
    for name in ("r.json", "r.xml", "notes.txt", "page.html", "README.md"):
        assert step(f"curl -fsSLo {name} https://example.com/{name}\n") == [], name


def test_data_fetch_that_is_run_is_a_download():
    assert len(step("""
        curl -fsSLo cfg.yaml https://example.com/cfg.yaml
        python3 cfg.yaml
    """)) == 1


# ------------------------------------------------------------ URL variables and unknown URLs (5)


def test_url_from_step_env():
    assert len(step('curl -fsSLo t.tgz "$TOOL_URL"\n', env={"TOOL_URL": "https://example.com/t.tgz"})) == 1


def test_url_from_workflow_env_expression():
    assert len(step('curl -fsSLo t.tgz "${{ env.TOOL_URL }}"\n', workflow_env={"TOOL_URL": "https://example.com/t.tgz"})) == 1


def test_unknown_url_in_a_workflow_is_a_download():
    assert len(step('curl -fsSLo t.tgz "${{ inputs.url }}"\n')) == 1
    assert len(step('curl -fsSLo t.tgz "$SOME_URL"\n')) == 1


def test_unknown_url_in_a_composite_action_is_a_download():
    action = {"runs": {"using": "composite", "steps": [
        {"name": "fetch", "shell": "bash", "run": 'curl -fsSL -o tool "${{ inputs.url }}"\nchmod +x tool\n'}]}}
    assert len(check_workflow(".github/actions/x/action.yml", yaml.safe_dump(action))) == 1


def test_local_url_variable_is_not_a_download():
    assert step('curl -fsS -o out "$U"\n', env={"U": "http://localhost:8080/x"}) == []


def test_api_call_with_unknown_url_is_not_a_download():
    assert step("""
        code="$(curl -sS -o "$resp" -w '%{http_code}' -X POST "$API/issues" -d @body.json)"
    """) == []


def test_unknown_url_in_a_dockerfile_is_not_assumed():
    assert dockerfile('RUN curl -fsSL -o /tmp/r "$X" && cat /tmp/r\n') == []


def test_dockerfile_arg_url_is_known():
    assert len(dockerfile("""
        ARG TOOL_URL=https://example.com/tool.tgz
        RUN curl -fsSLo /tmp/t.tgz "$TOOL_URL" && tar xzf /tmp/t.tgz
    """)) == 1


# ------------------------------------------------------------ exemption marker (6)


def test_exemption_needs_a_ticket():
    assert len(step("""
        # download-integrity: exempt vendor publishes nothing stable
        curl -fsSLo x.zip https://example.com/x.zip && unzip x.zip
    """)) == 1


def test_exemption_inside_a_string_does_not_count():
    assert len(step("""
        echo "# download-integrity: exempt see CUR-1"
        curl -fsSLo x.zip https://example.com/x.zip && unzip x.zip
    """)) == 1


def test_exemption_as_trailing_comment_does_not_count():
    assert len(step("""
        curl -fsSLo x.zip https://example.com/x.zip  # download-integrity: exempt see CUR-1
        unzip x.zip
    """)) == 1


# ------------------------------------------------------------ real, timely, named verification (7)


def test_verification_after_use_does_not_count():
    found = step("""
        curl -fsSLo t.tgz https://example.com/t.tgz
        tar xzf t.tgz
        echo "$SHA  t.tgz" | sha256sum -c -
    """)
    assert len(found) == 1 and "before it is verified" in found[0].message, found


def test_verification_of_another_file_does_not_count():
    assert len(step("""
        curl -fsSLo t.tgz https://example.com/t.tgz
        echo "$SHA  other.tgz" | sha256sum -c -
        tar xzf t.tgz
    """)) == 1


def test_verification_followed_by_or_breaks_b():
    for tail in ("|| true", "|| echo skipped", "&& echo ok || echo skipped"):
        found = step(f"""
            curl -fsSLo t.tgz https://example.com/t.tgz
            echo "$SHA  t.tgz" | sha256sum -c - {tail}
            tar xzf t.tgz
        """)
        assert len(found) == 1 and str(found[0]).endswith("/B]"), (tail, found)


def test_if_not_verification_then_exit_passes():
    assert step("""
        curl -fsSLo t.tgz https://example.com/t.tgz
        if ! echo "${SHA}  t.tgz" | sha256sum -c -; then
          exit 1
        fi
        tar xzf t.tgz
    """) == []


def test_mentions_are_not_verifications():
    for fake in ('echo "run sha256sum -c later"', ": verify-download sha256 x t.tgz",
                 'echo "see install-gitleaks/install.sh"'):
        assert len(step(f"""
            curl -fsSLo t.tgz https://example.com/t.tgz
            {fake}
            tar xzf t.tgz
        """)) == 1, fake


def test_stdin_digest_must_be_literal_or_variable():
    assert len(step("""
        curl -fsSLo t.tgz https://example.com/t.tgz
        echo "deadbeef  t.tgz" | sha256sum -c -
        tar xzf t.tgz
    """)) == 1
    assert step(f"""
        curl -fsSLo t.tgz https://example.com/t.tgz
        echo "{SHA_A}  t.tgz" | sha256sum -c -
        tar xzf t.tgz
    """) == []
    assert step("""
        curl -fsSLo t.tgz https://example.com/t.tgz
        sha256sum -c <<< "${SHA}  t.tgz"
        tar xzf t.tgz
    """) == []


# ------------------------------------------------------------ unverified-installer actions (8)


def test_doppler_cli_action_is_refused():
    wf = {"jobs": {"j": {"steps": [{"name": "Install Doppler CLI", "uses": "dopplerhq/cli-action@v3"}]}}}
    found = check_workflow("wf.yml", yaml.safe_dump(wf))
    assert len(found) == 1 and "install-doppler-cli" in found[0].message, found


def test_doppler_cli_action_in_a_composite_action_is_refused():
    action = {"runs": {"using": "composite", "steps": [{"uses": "DopplerHQ/cli-action@" + "0" * 40}]}}
    assert len(check_workflow(".github/actions/x/action.yml", yaml.safe_dump(action))) == 1


# ------------------------------------------------------------ citations (9)


def test_unparseable_yaml_cites_no_assertion():
    found = check_workflow("wf.yml", "jobs: [unclosed\n")
    assert len(found) == 1 and "cannot check" in str(found[0]) and "breaks" not in str(found[0])


def test_pin_findings_cite_a():
    assert str(check_versions_env("versions.env", "TOOL_SHA256=ABC\n")[0]).endswith("/A]")
    pins = {"TOOL_SHA256": SHA_A}
    assert str(check_arg_defaults("Dockerfile", f"ARG TOOL_SHA256={'b' * 64}\n", pins)[0]).endswith("/A]")


# ------------------------------------------------------------ file selection (10)


def test_dockerfile_names():
    for name in ("Dockerfile", "Dockerfile-ci", "Dockerfile.dev", "dockerfile", "app.Dockerfile",
                 "x/Containerfile", "Containerfile.prod", "x.containerfile"):
        assert is_dockerfile(name), name
    assert not is_dockerfile("docs/notes.md")


def test_versions_env_change_scans_every_dockerfile(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github/versions.env").write_text(f"TOOL_SHA256={SHA_A}\n")
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc/Dockerfile-api").write_text(f"ARG TOOL_SHA256={'b' * 64}\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    assert "svc/Dockerfile-api" in select_files(tmp_path, [".github/versions.env"])
    assert main(["--root", str(tmp_path), ".github/versions.env"]) == 1


# ------------------------------------------------------------ heredocs


def test_dockerfile_heredoc_run_is_checked():
    assert len(dockerfile("""
        RUN <<EOF
        set -e
        curl -fsSLo /tmp/t.tgz https://example.com/t.tgz
        tar xzf /tmp/t.tgz
        EOF
    """)) == 1


def test_heredoc_fed_to_a_shell_is_checked():
    found = step("""
        bash <<'EOS'
        curl -fsSL https://example.com/i.sh | sh
        EOS
    """)
    assert any("interpreter" in f.message for f in found), found


def test_checksum_file_written_from_a_recorded_digest_verifies():
    assert step("""
        cat > /tmp/sums <<EOF
        ${SHA}  t.tgz
        EOF
        curl -fsSLo t.tgz https://example.com/t.tgz
        sha256sum -c /tmp/sums
        tar xzf t.tgz
    """) == []
