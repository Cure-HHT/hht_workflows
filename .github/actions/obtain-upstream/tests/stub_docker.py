"""A ``docker`` that records its calls and needs no daemon.

Two suites obtain upstreams -- this action's own, and build-urs's loop over
several pins -- and both must stub docker the same way, or one of them is
testing a docker the other would not recognise. The stub lives here so there is
one answer to what a stubbed registry does.

It records every call, which is how a no-op is proved: not by the exit code,
which would be zero either way, but by the absence of a ``cp`` among the
recorded commands.

It also records the argv of whoever invoked it. A token piped to ``docker
login`` on stdin never appears in docker's own arguments, so a test watching
only those cannot tell a token held in the environment from one taken as a
positional argument -- it passes either way, against the very code it exists to
catch. The caller's command line is where that difference is visible, and it is
visible there to every process on the runner, which is the reason it matters.
"""

from __future__ import annotations

import pathlib
import textwrap

DIGEST = "ghcr.io/cure-hht/hht_diary@sha256:" + "b" * 64


def write_stub(
    bin_dir: pathlib.Path, payload: pathlib.Path, *, pull_ok: bool = True
) -> None:
    """Install the stub at `bin_dir/docker`, serving `payload` as the tree."""
    pull_exit = "0" if pull_ok else "1"
    (bin_dir / "docker").write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            # The invoking process, not this one: a token passed positionally
            # to the caller is readable here exactly as it is from /proc by
            # anything else running on the machine.
            if [ -r "/proc/$PPID/cmdline" ]; then
              tr '\\0' ' ' < "/proc/$PPID/cmdline" >> "$DOCKER_CALLS"
              echo >> "$DOCKER_CALLS"
            fi
            echo "$@" >> "$DOCKER_CALLS"
            case "$1" in
              login) exit 0 ;;
              pull) exit {pull_exit} ;;
              image) echo '{DIGEST}' ; exit 0 ;;
              create) echo 'stub-container-id' ; exit 0 ;;
              cp) cp -a '{payload}/.' "${{3}}" ; exit 0 ;;
              rm) exit 0 ;;
              *) echo "unexpected docker $1" >&2 ; exit 2 ;;
            esac
            """
        )
    )
    (bin_dir / "docker").chmod(0o755)


def write_payload(payload: pathlib.Path) -> None:
    """The tree the stubbed registry serves: a spec file and a dotfile."""
    (payload / "spec").mkdir(parents=True, exist_ok=True)
    (payload / "spec" / "a-requirement.md").write_text("# a requirement\n")
    (payload / ".hidden-file").write_text("dotfiles travel too\n")
