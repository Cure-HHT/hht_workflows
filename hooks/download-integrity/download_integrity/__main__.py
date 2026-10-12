#!/usr/bin/env python3
"""download-integrity: refuse a build definition that downloads a file without verifying it.

Pre-commit hook (and, through the download-integrity-check action, a CI check)
distributed from cure-hht/hht_workflows. Scans container build files
(Dockerfile*, *.Dockerfile, Containerfile*, any case), GitHub workflows,
composite actions, and workflow templates (*.yml.template / *.yaml.template,
which become workflows in the repositories they are copied into). Run by
pre-commit it checks the files pre-commit passes (and every container build
file when .github/versions.env is among them); run with no file arguments it
checks every tracked file.

The unit of execution is a Dockerfile RUN or a workflow step's `run:` script.
Within a unit the script is split into pipelines (quote-aware, comments
dropped), and each download is matched to a verification of that file. See
hooks/download-integrity/README.md for what counts as each.

This proves a verification is present, not that it is correct. Its job is to
stop the unverified-download class from coming back.

Exit 0 when clean, 1 with one line per finding otherwise.
"""
# Implements: HHT-OPS-ci-tool-download-integrity/C

from __future__ import annotations

import dataclasses
import os
import pathlib
import re
import shlex
import subprocess
import sys

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - environment problem, not a finding
    print("download-integrity: needs PyYAML", file=sys.stderr)
    raise SystemExit(2)

VERSIONS_ENV = ".github/versions.env"
REQ = "HHT-OPS-ci-tool-download-integrity"
# An exception is a whole comment line in the unit naming the ticket that
# tracks it. It never covers a download run by an interpreter.
EXEMPT = re.compile(r"^#\s*download-integrity:\s*exempt\s+\S.*\bCUR-\d+\b")

# Actions whose job is to run a vendor installer that nothing verifies, mapped
# to why and to the verified replacement. Add an entry when another is found.
UNVERIFIED_INSTALLER_ACTIONS = {
    "dopplerhq/cli-action": (
        "runs https://cli.doppler.com/install.sh without verifying it; install the CLI with "
        "Cure-HHT/hht_workflows/.github/actions/install-doppler-cli, which checks Doppler's signature first"
    ),
}

_LOCAL_HOSTS = r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|169\.254\.169\.254|metadata\.google\.internal)"
# A URL we would have to trust. Loopback, link-local and the metadata server
# are the local machine or the platform itself, not a download.
_URL = re.compile(r"https?://(?!" + _LOCAL_HOSTS + r"(?:[:/\"'\s]|$))[^\s\"'|;&)]+")
_LOCAL_URL = re.compile(r"https?://" + _LOCAL_HOSTS + r"(?:[:/\"'\s]|$)")
# A GitHub expression whose value the file does not show.
_GHA = "__GHAEXPR__"
_GHA_EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")

_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_SOURCERS = {"eval", "source", "."}
_INTERPRETERS = _SHELLS | _SOURCERS | {"python", "python3", "perl", "ruby", "node", "pwsh"}
# A pipe into one of these uses the bytes before anything could check them.
_SINKS = {"tar", "bsdtar", "unzip", "funzip", "gunzip", "zcat", "xz", "unxz", "bunzip2", "zstd", "cpio",
          "gpg", "gpg2", "apt-key", "install", "dpkg", "rpm", "7z"}
# Commands that put a downloaded file to work.
_EXEC_USE = _SINKS | _INTERPRETERS | {"chmod", "cp", "mv", "ln", "apt", "apt-get", "yum", "dnf", "apk",
                                      "pip", "pip3", "npm", "npx", "java", "flatpak", "snap"}
_KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "time"}
_NOT_COMMANDS = {"for", "case", "select", "function", "esac", "export", "local", "readonly", "declare"}

_ARTIFACT_EXT = (".tgz", ".tar", ".zip", ".deb", ".rpm", ".sh", ".whl", ".gz", ".xz", ".bz2", ".zst",
                 ".appimage", ".apk", ".jar", ".bin", ".run", ".exe", ".msi", ".pkg", ".dmg", ".py", ".7z")
_DATA_EXT = (".json", ".xml", ".txt", ".html", ".htm", ".md", ".csv", ".yaml", ".yml", ".log", ".out")
_SIGNATURE_EXT = (".sig", ".asc", ".bundle", ".sigstore")
_CHECKSUM_NAME = re.compile(r"(?:^|[._-])(?:checksums?|sha256sums?|shasums?)(?:\.txt)?$|\.sha256(?:sum)?$", re.I)
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_VAR = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")

# curl / wget options that take a value.
_CURL_SHORT_VALUE = set("oHduXAewTFbcKxmrzECDQUtPYy")
_CURL_LONG_VALUE = {
    "--output", "--header", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii",
    "--json", "--user", "--request", "--user-agent", "--referer", "--write-out", "--upload-file", "--form",
    "--form-string", "--cookie", "--cookie-jar", "--config", "--proxy", "--max-time", "--range",
    "--time-cond", "--cert", "--cacert", "--capath", "--key", "--continue-at", "--dump-header", "--quote",
    "--proxy-user", "--retry", "--retry-delay", "--retry-max-time", "--connect-timeout", "--output-dir",
    "--proto", "--proto-redir", "--resolve", "--interface", "--limit-rate", "--max-filesize", "--oauth2-bearer",
    "--url-query", "--variable", "--keepalive-time", "--speed-time", "--speed-limit", "--tls-max",
    "--ciphers", "--pinnedpubkey", "--connect-to", "--max-redirs", "--stderr", "--trace", "--trace-ascii",
    "--netrc-file", "--aws-sigv4", "--etag-save", "--etag-compare",
}
# A request that sends data or reads only its status is an API call, not a tool.
_CURL_API = {"--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii", "--json", "--form",
             "--form-string", "--upload-file", "--write-out", "--head", "--url-query"}
_CURL_API_SHORT = set("dFTwIG")
_WGET_SHORT_VALUE = set("OoaPtTUewQiBlARDIX")
_WGET_LONG_VALUE = {
    "--output-document", "--output-file", "--append-output", "--directory-prefix", "--tries", "--timeout",
    "--header", "--user-agent", "--user", "--password", "--post-data", "--post-file", "--method",
    "--body-data", "--body-file", "--execute", "--wait", "--input-file", "--level", "--ca-certificate",
    "--certificate", "--private-key", "--accept", "--reject", "--domains", "--quota", "--base",
    "--read-timeout", "--connect-timeout", "--dns-timeout", "--waitretry", "--limit-rate", "--secure-protocol",
}
_WGET_API = {"--post-data", "--post-file", "--body-data", "--body-file", "--spider"}


@dataclasses.dataclass(frozen=True)
class Finding:
    path: str
    line: int
    message: str
    # The assertion of HHT-OPS-ci-tool-download-integrity the finding breaks,
    # or None when the file could not be checked at all.
    cite: str | None = "A"

    def __str__(self) -> str:
        # The Merge Check names the assertion each finding breaks
        # (HHT-OPS-merge-checked-rule/C).
        if self.cite is None:
            return f"{self.path}:{self.line}: {self.message}"
        return f"{self.path}:{self.line}: {self.message} [breaks {REQ}/{self.cite}]"


@dataclasses.dataclass(frozen=True)
class Problem:
    message: str
    cite: str = "A"
    exemptable: bool = True


# ---------------------------------------------------------------- shell lexing


@dataclasses.dataclass
class Pipeline:
    stages: list[str]
    sep: str = "\n"  # the operator that ends it: \n ; & && ||
    substs: list[list[str]] = dataclasses.field(default_factory=list)  # per stage: $( ), <( ), `` bodies
    heredoc: str = ""
    in_subst: bool = False


def _match_close(text: str, i: int) -> int:
    """Index of the parenthesis closing text[i], skipping quoted text."""
    depth = 0
    quote = None
    j = i
    while j < len(text):
        c = text[j]
        if quote:
            if c == "\\" and quote == '"':
                j += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "\\":
            j += 2
            continue
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return len(text) - 1


def _lex(script: str, comments: list[tuple[bool, str]] | None = None) -> list[Pipeline]:
    """Split a shell script into pipelines of stages.

    Quote-aware: an operator or `#` inside quotes is text. Comments are removed
    and reported through `comments` as (is_whole_line, text). Command and
    process substitution bodies are recorded per stage, and a heredoc body on
    the pipeline that reads it.
    """
    comments = [] if comments is None else comments
    text = re.sub(r"\\\r?\n", " ", script)
    pipes: list[Pipeline] = []
    stages: list[str] = []
    substs: list[list[str]] = [[]]
    cur: list[str] = []
    heredoc_terms: list[str] = []
    heredoc_body: list[str] = []
    quote: str | None = None
    line_blank = True
    i, n = 0, len(text)

    def end_stage() -> None:
        stages.append("".join(cur))
        cur.clear()
        substs.append([])

    def end_pipe(sep: str) -> None:
        nonlocal stages, substs
        st = stages + ["".join(cur)]
        cur.clear()
        if any(s.strip() for s in st):
            pipes.append(Pipeline(st, sep, substs, "\n".join(heredoc_body)))
        heredoc_body.clear()
        stages = []
        substs = [[]]

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if quote == "'":
            cur.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        # Substitutions are live outside quotes and inside double quotes.
        if c == "$" and nxt == "(":
            j = _match_close(text, i + 1)
            if text[i + 2: i + 3] != "(":  # $(( )) is arithmetic
                substs[-1].append(text[i + 2: j])
            cur.append(text[i: j + 1])
            line_blank = False
            i = j + 1
            continue
        if c == "`":
            j = text.find("`", i + 1)
            j = n - 1 if j < 0 else j
            substs[-1].append(text[i + 1: j])
            cur.append(text[i: j + 1])
            line_blank = False
            i = j + 1
            continue
        if quote == '"':
            cur.append(c)
            if c == "\\":
                cur.append(nxt)
                i += 2
                continue
            if c == '"':
                quote = None
            i += 1
            continue
        # Unquoted from here.
        if c == "\\":
            cur.append(c + nxt)
            i += 2
            continue
        if c in "'\"":
            quote = c
            cur.append(c)
            line_blank = False
            i += 1
            continue
        if c in "<>" and nxt == "(":
            j = _match_close(text, i + 1)
            substs[-1].append(text[i + 2: j])
            cur.append(text[i: j + 1])
            line_blank = False
            i = j + 1
            continue
        if c == "#" and (i == 0 or text[i - 1] in " \t\n;&|()"):
            j = text.find("\n", i)
            j = n if j < 0 else j
            comments.append((line_blank, text[i:j].strip()))
            i = j
            continue
        if c == "<" and text.startswith("<<", i) and not text.startswith("<<<", i):
            m = re.match(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", text[i:])
            if m:
                heredoc_terms.append(m.group(2))
                cur.append(m.group(0))
                line_blank = False
                i += m.end()
                continue
        if c == "\n":
            if heredoc_terms:
                # The heredoc bodies follow this line and belong to it.
                rest = text[i + 1:].split("\n")
                consumed = 0
                for term in heredoc_terms:
                    while consumed < len(rest):
                        line = rest[consumed]
                        consumed += 1
                        if line.strip() == term:
                            break
                        heredoc_body.append(line)
                heredoc_terms.clear()
                end_pipe("\n")
                i += 1 + sum(len(x) + 1 for x in rest[:consumed])
                line_blank = True
                continue
            end_pipe("\n")
            line_blank = True
            i += 1
            continue
        if c == ";":
            end_pipe(";")
            i += 2 if nxt == ";" else 1
            continue
        if c == "&":
            if nxt == "&":
                end_pipe("&&")
                i += 2
                continue
            if (i and text[i - 1] in "<>") or nxt == ">":
                cur.append(c)
                i += 1
                continue
            end_pipe("&")
            i += 1
            continue
        if c == "|":
            if nxt == "|":
                end_pipe("||")
                i += 2
                continue
            end_stage()
            i += 2 if nxt == "&" else 1
            continue
        if c in "()":
            end_pipe(";")
            i += 1
            continue
        if not c.isspace():
            line_blank = False
        cur.append(c)
        i += 1
    end_pipe("\n")
    return pipes


def _tokens(stage: str) -> list[str]:
    lex = shlex.shlex(stage, posix=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError:
        return stage.split()


def _command(stage: str) -> tuple[str | None, list[str], bool]:
    """(command, its arguments, run through xargs) past assignments, keywords and wrappers."""
    toks = _tokens(stage)
    via_xargs = False
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in _NOT_COMMANDS:
            return None, [], False
        if t in _KEYWORDS or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
            i += 1
            continue
        base = t.rsplit("/", 1)[-1]
        if base == "sudo":
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 2 if toks[i] in ("-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U") else 1
            continue
        if base == "env":
            i += 1
            while i < len(toks) and (toks[i].startswith("-") or "=" in toks[i]):
                i += 2 if toks[i] in ("-u", "-C", "-S") else 1
            continue
        if base == "xargs":
            via_xargs = True
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 2 if toks[i] in ("-I", "-n", "-P", "-L", "-d", "-a", "-E", "-s") else 1
            continue
        if base in ("command", "exec", "nohup", "stdbuf", "builtin"):
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 1
            continue
        if base in ("nice", "timeout"):
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 2 if toks[i] in ("-n", "-s", "-k") else 1
            if base == "timeout" and i < len(toks):
                i += 1
            continue
        return base, toks[i + 1:], via_xargs
    return None, [], via_xargs


def _runs_stdin(cmd: str, args: list[str], via_xargs: bool) -> bool:
    """Whether an interpreter fed by a pipe runs what it is fed."""
    if via_xargs:
        return True
    if cmd in _SOURCERS:
        return any(a in ("/dev/stdin", "-") for a in args)
    for a in args:
        if a in ("-c", "-e", "-E", "-p", "--eval", "--print", "-Command"):
            return False  # runs its argument; the pipe is data
        if a in ("-", "/dev/stdin") or (cmd in _SHELLS and a == "-s"):
            return True  # reads its script from stdin
        if not a.startswith("-"):
            return False  # runs a script file; the pipe is data
    return True


def _subst_is_script(stage: str, cmd: str) -> bool:
    """Whether a substitution in this stage is the code the interpreter runs."""
    if cmd in _SOURCERS:
        return True
    m = re.search(r"(?:^|[\s/])" + re.escape(cmd) + r"(\s.*)$", stage, re.S)
    return bool(m and re.match(r"^\s*(?:--?[A-Za-z-]+\s+)*[\"']?(?:\$\(|<\(|`)", m.group(1)))


# ---------------------------------------------------------------- unit context


@dataclasses.dataclass
class Context:
    url_vars: dict[str, str] = dataclasses.field(default_factory=dict)
    local_vars: set[str] = dataclasses.field(default_factory=set)
    # In a workflow or composite action the caller supplies values the file
    # does not show, so a fetch of `$VAR` / `${{ inputs.x }}` is a download.
    unknown_is_url: bool = False

    def copy(self) -> "Context":
        return Context(dict(self.url_vars), set(self.local_vars), self.unknown_is_url)

    def seed(self, name: str, value: object) -> None:
        if not isinstance(value, str):
            return
        v = value.strip()
        if _LOCAL_URL.match(v):
            self.local_vars.add(name)
        elif _URL.match(v):
            self.url_vars[name] = v
        else:
            m = _VAR.match(v)
            if m and m.group(1) in self.url_vars:
                self.url_vars[name] = self.url_vars[m.group(1)] + v[m.end():]


def _norm(tok: str) -> str:
    """The name a path token refers to: its basename, with ${X} written as $X."""
    t = tok.strip().strip("\"'")
    t = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", r"$\1", t)
    t = t.rstrip(");\"'")
    return t.rsplit("/", 1)[-1]


def _keys(pipeline: Pipeline) -> set[str]:
    """Every name a pipeline mentions, including inside quoted strings."""
    keys: set[str] = set()
    texts = list(pipeline.stages) + ([pipeline.heredoc] if pipeline.heredoc else [])
    for text in texts:
        for tok in _tokens(text):
            for part in re.split(r"[\s=]+", tok):
                k = _norm(part)
                if k:
                    keys.add(k)
    return keys


def _classify_url(tok: str, ctx: Context) -> tuple[str | None, str]:
    """('url'|'local'|'unknown'|None, value) for a fetch argument."""
    m = _URL.search(tok)
    if m:
        return "url", m.group(0)
    if _LOCAL_URL.search(tok):
        return "local", ""
    m = _VAR.match(tok)
    if m:
        name = m.group(1)
        if name in ctx.url_vars:
            return "url", ctx.url_vars[name] + tok[m.end():]
        if name in ctx.local_vars:
            return "local", ""
        return "unknown", tok
    if tok.startswith(_GHA):
        return "unknown", tok
    return None, ""


@dataclasses.dataclass
class Fetch:
    url_kind: str  # url | unknown
    url: str
    out: str | None  # the file written, or None for stdout
    api: bool


def _redirect_target(toks: list[str], i: int) -> tuple[str | None, int]:
    """If toks[i] redirects stdout, (target, tokens consumed); else (None, 0)."""
    m = re.match(r"^(\d*|&)(>>?)(.*)$", toks[i])
    if not m or m.group(1) not in ("", "1", "&") or m.group(3).startswith("&"):
        return None, 0
    if m.group(3):
        return m.group(3), 1
    return (toks[i + 1], 2) if i + 1 < len(toks) else (None, 1)


def _parse_fetch(tool: str, args: list[str], ctx: Context) -> Fetch | None:
    curl = tool == "curl"
    short_value = _CURL_SHORT_VALUE if curl else _WGET_SHORT_VALUE
    long_value = _CURL_LONG_VALUE if curl else _WGET_LONG_VALUE
    out: str | None = None
    out_dir = ""
    remote_name = not curl  # wget writes the URL's basename unless told otherwise
    api = False
    positional: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        target, used = _redirect_target(args, i)
        if used:
            # Writing stdout to a file (`> f`, `>> f`) writes the download there.
            out = target or out
            i += used
            continue
        if a in ("<", "2>", "2>>"):
            i += 2
            continue
        if re.match(r"^(?:\d*<|2>)", a):
            i += 1
            continue
        if a.startswith("--"):
            name, eq, value = a.partition("=")
            if not eq and name in long_value:
                value = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if name in (_CURL_API if curl else _WGET_API):
                api = True
            if curl:
                if name == "--output":
                    out = value
                elif name in ("--remote-name", "--remote-name-all"):
                    remote_name = True
                elif name == "--output-dir":
                    out_dir = value
                elif name == "--request" and value.upper() != "GET":
                    api = True
            elif name == "--output-document":
                out = value
            elif name == "--method" and value.upper() != "GET":
                api = True
            i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            letters = a[1:]
            for k, ch in enumerate(letters):
                if curl and ch in _CURL_API_SHORT:
                    api = True
                if curl and ch == "O":
                    remote_name = True
                if ch in short_value:
                    value = letters[k + 1:]
                    if not value:
                        value = args[i + 1] if i + 1 < len(args) else ""
                        i += 1
                    if (curl and ch == "o") or (not curl and ch == "O"):
                        out = value
                    if curl and ch == "X" and value.upper() != "GET":
                        api = True
                    break
            i += 1
            continue
        positional.append(a)
        i += 1
    kind, url = None, ""
    for p in positional:
        k, v = _classify_url(p, ctx)
        if k == "url":
            kind, url = k, v
            break
        if k and kind is None:
            kind, url = k, v
    if kind in (None, "local"):
        return None
    if out is None and remote_name:
        base = re.split(r"[?#]", url)[0].rstrip("/").rsplit("/", 1)[-1]
        out = f"{out_dir}/{base}" if out_dir else base
    elif out and out_dir and "/" not in out:
        out = f"{out_dir}/{out}"
    if out in ("-", "/dev/null", "/dev/stdout", ""):
        out = None
    return Fetch(kind, url, out, api)


def _file_kind(out: str, url: str) -> str:
    """artifact | checksum | signature | keyring | other | data."""
    path = out.strip("\"'")
    name = _norm(path).lower()
    url_name = _norm(re.split(r"[?#]", url)[0]).lower()
    if re.search(r"(?:^|/)(?:keyrings|trusted\.gpg\.d)/", path):
        return "keyring"
    if _CHECKSUM_NAME.search(name) or _CHECKSUM_NAME.search(url_name):
        return "checksum"
    if name.endswith(_SIGNATURE_EXT):
        return "signature"
    if name.endswith(_ARTIFACT_EXT):
        return "artifact"
    if name.endswith(_DATA_EXT):
        return "data"
    stem = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]*|\$\d|" + _GHA.lower(), "", name)
    return "artifact" if "." not in stem else "other"


@dataclasses.dataclass
class Download:
    idx: int
    key: str
    kind: str  # a _file_kind, or "piped"
    sink: str = ""
    text: str = ""


@dataclasses.dataclass
class Verification:
    idx: int
    names: set[str]
    wildcard: bool = False
    valid: bool = True
    # A digest read from this downloaded file: valid only if that file is itself verified.
    source: str | None = None
    swallowed: bool = False
    signature_tool: bool = False


def _fetch_of(stage: str, ctx: Context) -> Fetch | None:
    cmd, args, _ = _command(stage)
    return _parse_fetch(cmd, args, ctx) if cmd in ("curl", "wget") else None


def _fetch_inside(body: str, ctx: Context) -> bool:
    """A substitution body that prints a fetched URL."""
    return any(_fetch_of(p.stages[0], ctx) for p in _lex(body))


def _flatten(pipes: list[Pipeline], depth: int = 0) -> list[Pipeline]:
    """Substitution bodies run before the command that holds them; a heredoc fed to a shell runs too."""
    out: list[Pipeline] = []
    for p in pipes:
        if depth < 4:
            for bodies in p.substs:
                for body in bodies:
                    for q in _flatten(_lex(body), depth + 1):
                        q.in_subst = True
                        out.append(q)
        out.append(p)
        if p.heredoc and depth < 4 and any(_command(s)[0] in _SHELLS for s in p.stages):
            out += _flatten(_lex(p.heredoc), depth + 1)
    return out


def _assignments(pipes: list[Pipeline], ctx: Context) -> None:
    for p in pipes:
        for tok in _tokens(p.stages[0]):
            if tok in ("export", "local", "readonly", "declare") or tok.startswith("-"):
                continue
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", tok)
            if not m:
                break
            ctx.seed(*m.groups())


def _sha_check_files(args: list[str]) -> list[str]:
    """The checksum-file arguments of `sha256sum -c`, up to any redirection."""
    files = []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("<<"):
            break  # a here-string or heredoc feeds stdin
        if a in ("<", ">", ">>", "2>", "1>"):
            i += 2
            continue
        if re.match(r"^(?:\d*[<>]|&>)", a):
            i += 1
            continue
        if not a.startswith("-") and a != "256":
            files.append(a)
        i += 1
    return files


def _verification(p: Pipeline, idx: int, downloaded: dict[str, str], pipes: list[Pipeline]) -> Verification | None:
    """The verification a pipeline performs, if it invokes one. `downloaded` maps earlier downloads to their kind."""
    for s, stage in enumerate(p.stages):
        cmd, args, _ = _command(stage)
        if cmd is None:
            continue
        if cmd == "verify-download" and args[:1] and args[0] in ("sha256", "key"):
            return Verification(idx, {_norm(a) for a in args[1:]})
        if cmd == "cosign" and args[:1] and args[0].startswith("verify-blob"):
            return Verification(idx, {_norm(x) for a in args[1:] for x in a.split("=")}, signature_tool=True)
        if cmd in ("gpg", "gpg2") and "--verify" in args:
            rest = [a for a in args[args.index("--verify") + 1:] if not a.startswith("-")]
            names = {_norm(a) for a in rest}
            if len(rest) == 1:
                names.add(re.sub(r"\.(?:sig|asc)$", "", _norm(rest[0])))
            return Verification(idx, names, signature_tool=True)
        if cmd == "gpgv":
            return Verification(idx, {_norm(a) for a in args if not a.startswith("-")}, signature_tool=True)
        is_sha = cmd == "sha256sum" or (cmd == "shasum" and re.search(r"(?:^|\s)-a\s*256\b", " ".join(args)))
        if not (is_sha and any(a == "--check" or re.match(r"^-[a-zA-Z]*c[a-zA-Z]*$", a) for a in args)):
            continue
        files = [f for f in _sha_check_files(args) if f != "-"]
        here_string = re.search(r"<<<\s*(.*)$", stage)
        if files:
            f = _norm(files[0])
            if f in downloaded:
                return Verification(idx, set(), source=f, wildcard=True)
            # A checksum file written in the unit lists the names it covers.
            names: set[str] = set()
            for q in pipes[:idx]:
                if any(_norm(t) == f for t in re.findall(r">>?\s*(\S+)", " ".join(q.stages))):
                    names |= _keys(q) - {f}
            return Verification(idx, names, wildcard=not names)
        if here_string:
            feed = here_string.group(1)
        elif p.heredoc and "<<" in stage:
            feed = p.heredoc
        elif s > 0:
            fcmd, fargs, _ = _command(p.stages[s - 1])
            if fcmd in ("echo", "printf"):
                feed = " ".join(a for a in fargs if not re.match(r"^-[neE]+$", a))
            else:
                # A digest read from a file: authentic only if that file is.
                fed = {_norm(x) for a in fargs if not a.startswith("-") for x in re.split(r"[\s=]+", a)} - {""}
                from_download = sorted((downloaded[k] != "checksum", k) for k in fed if k in downloaded)
                if from_download:
                    src = from_download[0][1]
                    return Verification(idx, fed - {src}, source=src, wildcard=fed == {src})
                return Verification(idx, fed, wildcard=True)
        else:
            return Verification(idx, set(), valid=False)
        words = [w for w in re.split(r"\s+", feed.strip().strip("\"'")) if w]
        digest = words[0].strip("\"'") if words else ""
        if not (_HEX64.match(digest) or "$" in digest or _GHA in digest):
            return Verification(idx, set(), valid=False)
        names = {_norm(w) for w in words[1:]} - {"", "-"}
        return Verification(idx, names, wildcard=not names)
    return None


def _uses(p: Pipeline, key: str) -> bool:
    """Whether a pipeline extracts, installs, moves or runs the file `key`."""
    if not key or key not in _keys(p):
        return False
    for stage in p.stages:
        cmd, _, _ = _command(stage)
        if cmd is None or cmd in ("curl", "wget"):
            continue
        toks = _tokens(stage)
        if cmd in _EXEC_USE or (toks and _norm(toks[0]) == key) or _norm(cmd) == key:
            return True
    return False


def check_script(script: str, ctx: Context | None = None) -> list[Problem]:
    """Return the problems in one unit of shell. Empty means it passes."""
    ctx = (ctx or Context()).copy()
    comments: list[tuple[bool, str]] = []
    pipes = _flatten(_lex(script, comments))
    exempt = any(whole and EXEMPT.match(text) for whole, text in comments)
    _assignments(pipes, ctx)
    problems: list[Problem] = []
    downloads: list[Download] = []
    verifs: list[Verification] = []
    for idx, p in enumerate(pipes):
        cmds = [_command(s) for s in p.stages]
        # A download run by an interpreter, through a pipe or a substitution.
        head = _fetch_of(p.stages[0], ctx)
        piped = head is not None and any(c in _INTERPRETERS and _runs_stdin(c, a, x) for c, a, x in cmds[1:])
        substituted = any(
            c in (_SHELLS | _SOURCERS) and _subst_is_script(p.stages[s], c)
            and any(_fetch_inside(b, ctx) for b in p.substs[s])
            for s, (c, _, _) in enumerate(cmds) if s < len(p.substs)
        )
        if piped or substituted:
            problems.append(Problem(
                "download run by an interpreter cannot be verified before it runs: "
                + " | ".join(x.strip() for x in p.stages)[:120], exemptable=False))
            continue
        v = _verification(p, idx, {d.key: d.kind for d in downloads}, pipes)
        if v:
            # `verify || x` (or `verify && y || x`) carries on when the check fails.
            j = idx
            while pipes[j].sep == "&&" and j + 1 < len(pipes):
                j += 1
                while pipes[j].in_subst and j + 1 < len(pipes):
                    j += 1
            v.swallowed = pipes[j].sep == "||" and not p.in_subst
            verifs.append(v)
            continue
        if head is None or (head.url_kind == "unknown" and not ctx.unknown_is_url):
            continue
        out = head.out
        if len(p.stages) > 1:
            sink, sargs, _ = cmds[1]
            if sink == "tee":
                files = [a for a in sargs if not a.startswith("-") and not a.startswith(">")]
                out = files[0] if files else None
            elif sink == "dd":
                out = next((a[3:] for a in sargs if a.startswith("of=")), None)
            elif sink in _SINKS:
                downloads.append(Download(idx, "", "piped", sink=sink, text=p.stages[0].strip()))
                continue
            elif out is None:
                continue  # read as data by jq, grep, ...
        if out is None:
            continue
        kind = _file_kind(out, head.url)
        if head.api and kind in ("artifact", "other"):
            kind = "data"
        downloads.append(Download(idx, _norm(out), kind, text=p.stages[0].strip()))

    by_key = {d.key: d for d in downloads}
    memo: dict[int, Problem | None] = {}

    def judge(d: Download, stack: tuple[int, ...] = ()) -> Problem | None:
        """None when d is verified (or is not a download), else the problem."""
        if d.idx in memo:
            return memo[d.idx]
        if d.idx in stack:
            return Problem(f"{d.key} is not verified")
        result = _judge(d, stack + (d.idx,))
        memo[d.idx] = result
        return result

    def _judge(d: Download, stack: tuple[int, ...]) -> Problem | None:
        if d.kind == "piped":
            return Problem(f"download piped into {d.sink} is used before anything can verify it; save it to a "
                           f"file and verify it against a recorded SHA-256 or signing-key fingerprint first: {d.text[:100]}")
        first_use = next((i for i in range(d.idx + 1, len(pipes))
                          if not any(v.idx == i for v in verifs) and _uses(pipes[i], d.key)), None)
        naming = [v for v in verifs if v.idx > d.idx and (d.key in v.names or v.wildcard)]
        if d.kind == "signature" and any(v.signature_tool and d.key in v.names for v in naming):
            return None  # verification material for a gpg/cosign check
        if d.kind in ("data", "other", "signature") and first_use is None:
            return None  # kept as data, not run
        same_origin = False

        def valid(v: Verification) -> bool:
            nonlocal same_origin
            if v.source is None:
                return v.valid
            src = by_key.get(v.source)
            if src is None or src.idx >= v.idx or judge(src, stack) is not None:
                same_origin = True
                return False
            return True

        candidates = [v for v in naming if v.source != d.key]
        timely = [v for v in candidates if first_use is None or v.idx < first_use]
        if any(valid(v) and not v.swallowed for v in timely):
            return None
        if d.kind == "checksum":
            return Problem(f"{d.key}: a checksum file downloaded beside the asset proves the download is intact, "
                           "not authentic; verify against a digest recorded in the repository or a pinned signing key")
        if any(valid(v) and v.swallowed for v in timely):
            return Problem(f"{d.key}: its verification is followed by `||`, so the step carries on when the "
                           "check fails", cite="B")
        if any(valid(v) for v in candidates):
            return Problem(f"{d.key} is used before it is verified; verify it before extracting, installing or running it")
        if same_origin:
            return Problem(f"{d.key} is checked only against a checksum file downloaded beside it, which is not "
                           "authentic; verify against a digest recorded in the repository or a pinned signing key")
        return Problem(f"{d.key} is downloaded but not verified in this step; verify it against a recorded SHA-256 "
                       "or signing-key fingerprint before using it")

    for d in downloads:
        found = judge(d)
        if found:
            problems.append(found)
    if exempt:
        problems = [p for p in problems if not p.exemptable]
    return problems


# ---------------------------------------------------------------- Dockerfiles


def _dockerfile_units(text: str) -> list[tuple[int, str, str]]:
    """Yield (line, instruction, body) for each instruction, continuations joined."""
    units: list[tuple[int, str, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        start = i + 1
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        body = [line]
        # A heredoc body (RUN <<EOF) runs until its terminator.
        heredoc = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        while body[-1].rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            body.append(lines[i])
        if heredoc:
            term = heredoc.group(1)
            while i + 1 < len(lines):
                i += 1
                body.append(lines[i])
                if lines[i].strip() == term:
                    break
        joined = "\n".join(body)
        instr = joined.lstrip().split(None, 1)[0].upper()
        units.append((start, instr, joined))
        i += 1
    return units


def check_dockerfile(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    ctx = Context()
    for line, instr, body in _dockerfile_units(text):
        if instr in ("ARG", "ENV"):
            for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S+)", body):
                ctx.seed(m.group(1), m.group(2).strip("\"'"))
        elif instr == "RUN":
            script = re.sub(r"^\s*RUN\s+(?:--\S+\s+)*", "", body, count=1, flags=re.I)
            m = re.match(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*)\n\s*\1\s*$", script, re.S)
            if m:
                script = m.group(2)
            findings += [Finding(path, line, p.message, p.cite) for p in check_script(script, ctx)]
        elif instr == "ADD":
            m = re.match(r"^\s*ADD\s+(?P<flags>(?:--\S+\s+)*)(?P<src>https?://\S+)", body, re.I)
            if m and "--checksum=sha256:" not in m.group("flags"):
                findings.append(Finding(path, line, f"ADD {m.group('src')} without --checksum=sha256:<digest>"))
    return findings


# ---------------------------------------------------------------- workflows


def _step_line(text: str, step: dict, occurrence: int = 0) -> int:
    """Best-effort line of a step: its name, else its uses:, else the first line of its script.

    `occurrence` picks among steps that share a name (the same install step
    repeated in two jobs), so each is reported at its own line.
    """
    lines = text.splitlines()
    for key in ("name", "uses"):
        value = step.get(key)
        if isinstance(value, str):
            pat = re.compile(r"^\s*-?\s*" + key + r":\s*['\"]?" + re.escape(value) + r"['\"]?\s*(?:#.*)?$")
            hits = [n for n, line in enumerate(lines, 1) if pat.match(line)]
            if hits:
                return hits[min(occurrence, len(hits) - 1)]
    script = step.get("run") or ""
    first = next((s.strip() for s in str(script).splitlines() if s.strip()), "")
    for n, line in enumerate(lines, 1):
        if first and first in line:
            return n
    return 1


def _env_map(node: object) -> dict:
    env = node.get("env") if isinstance(node, dict) else None
    return env if isinstance(env, dict) else {}


def _substitute_expressions(script: str, env: dict) -> str:
    """Replace ${{ ... }}: an env URL the file records by its value, anything else by a placeholder."""
    def repl(m: re.Match) -> str:
        e = re.fullmatch(r"env\.([A-Za-z_][A-Za-z0-9_]*)", m.group(1))
        value = env.get(e.group(1)) if e else None
        if isinstance(value, str) and (_URL.match(value) or _LOCAL_URL.match(value)):
            return value
        return _GHA
    return _GHA_EXPR.sub(repl, script)


def check_workflow(path: str, text: str) -> list[Finding]:
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return [Finding(path, 1, f"cannot check: unparseable YAML: {exc}", cite=None)]
    if not isinstance(doc, dict):
        return []
    top_env = _env_map(doc)
    steps: list[tuple[dict, dict]] = []
    for job in (doc.get("jobs") or {}).values():
        if isinstance(job, dict):
            env = {**top_env, **_env_map(job)}
            steps += [(s, env) for s in job.get("steps") or [] if isinstance(s, dict)]
    runs = doc.get("runs")
    if isinstance(runs, dict):
        steps += [(s, top_env) for s in runs.get("steps") or [] if isinstance(s, dict)]
    findings: list[Finding] = []
    seen: dict[object, int] = {}
    for step, inherited in steps:
        key = step.get("name")
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        uses = step.get("uses")
        if isinstance(uses, str):
            action = uses.split("@", 1)[0].strip().lower()
            if action in UNVERIFIED_INSTALLER_ACTIONS:
                findings.append(Finding(path, _step_line(text, step, occurrence),
                                        f"step '{step.get('name', uses)}': {action} {UNVERIFIED_INSTALLER_ACTIONS[action]}"))
        script = step.get("run")
        if not isinstance(script, str):
            continue
        env = {**inherited, **_env_map(step)}
        ctx = Context(unknown_is_url=True)
        for name, value in env.items():
            ctx.seed(str(name), value)
        for p in check_script(_substitute_expressions(script, env), ctx):
            findings.append(Finding(path, _step_line(text, step, occurrence),
                                    f"step '{step.get('name', '?')}': {p.message}", p.cite))
    return findings


# ---------------------------------------------------------------- pin coherence


def parse_env(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)=(.*?)\s*$", line)
        if m:
            values[m.group(1)] = m.group(2)
    return values


def check_versions_env(path: str, text: str) -> list[Finding]:
    """A malformed recorded digest cannot be the digest assertion A verifies against."""
    findings = []
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*([A-Z0-9_]+_SHA256)=(.*?)\s*$", line)
        if m and not re.fullmatch(r"[0-9a-f]{64}", m.group(2)):
            findings.append(Finding(path, n, f"{m.group(1)} is not a 64-character lowercase hex SHA-256, so it "
                                             "cannot serve as a recorded digest"))
    return findings


def check_arg_defaults(path: str, text: str, pins: dict[str, str]) -> list[Finding]:
    """A Dockerfile's own default for a digest must match versions.env.

    Only the defaults are checked: they are what an argument-less build (e.g.
    `docker compose build`) uses. The version it belongs to is checked with it,
    since a digest default is only meaningful beside the version default. A
    drifted default verifies against a digest the repository does not record
    (assertion A).
    """
    findings = []
    defaults = {}
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*ARG\s+([A-Z0-9_]+)=(\S+)\s*$", line)
        if m:
            defaults[m.group(1)] = (n, m.group(2))
    for name, (n, value) in defaults.items():
        if not name.endswith("_SHA256") or name not in pins:
            continue
        if value != pins[name]:
            findings.append(Finding(path, n, f"ARG {name} default differs from the digest recorded in {VERSIONS_ENV}"))
        version = name[: -len("_SHA256")] + "_VERSION"
        if version in defaults and version in pins and defaults[version][1] != pins[version]:
            findings.append(Finding(path, defaults[version][0], f"ARG {version} default differs from {VERSIONS_ENV}, "
                                                                "so its digest default is for another version"))
    return findings


# ---------------------------------------------------------------- driver


def is_dockerfile(name: str) -> bool:
    base = pathlib.PurePosixPath(name).name.lower()
    return base.startswith(("dockerfile", "containerfile")) or base.endswith((".dockerfile", ".containerfile"))


def is_workflow(name: str) -> bool:
    p = pathlib.PurePosixPath(name)
    if p.name.endswith((".yml.template", ".yaml.template")):
        return True
    if p.suffix not in (".yml", ".yaml"):
        return False
    return name.startswith(".github/workflows/") or (name.startswith(".github/actions/") and p.stem == "action")


def tracked_files(root: pathlib.Path) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True, text=True).stdout
        files = [f for f in out.split("\0") if f]
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [f for f in files if not f.startswith("spec-archive/")]


def scan(root: pathlib.Path, files: list[str] | None = None) -> list[Finding]:
    files = tracked_files(root) if files is None else files
    env_path = root / VERSIONS_ENV
    pins = parse_env(env_path.read_text()) if env_path.exists() else {}
    findings: list[Finding] = []
    if env_path.exists():
        findings += check_versions_env(VERSIONS_ENV, env_path.read_text())
    for name in files:
        path = root / name
        if not path.is_file():
            continue
        if is_dockerfile(name):
            text = path.read_text(errors="replace")
            findings += check_dockerfile(name, text)
            findings += check_arg_defaults(name, text, pins)
        elif is_workflow(name):
            findings += check_workflow(name, path.read_text(errors="replace"))
    return findings


def select_files(root: pathlib.Path, args: list[str]) -> list[str]:
    """The files to check for the FILEs pre-commit passed.

    A change to versions.env can put any Dockerfile's digest default out of
    step, and pre-commit passes only the changed files, so a changed
    versions.env brings every container build file into the check.
    """
    names = [pathlib.PurePosixPath(os.path.normpath(f)).as_posix() for f in args]
    files = [f for f in names if is_dockerfile(f) or is_workflow(f)]
    if VERSIONS_ENV in names:
        files += [f for f in tracked_files(root) if is_dockerfile(f) and f not in files]
    return files


def main(argv: list[str] | None = None) -> int:
    """`download-integrity [--root DIR] [FILE ...]` -- FILEs relative to the root."""
    import argparse

    ap = argparse.ArgumentParser(prog="download-integrity", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="repository root (default: cwd)")
    ap.add_argument("files", nargs="*", help="files to check (default: every tracked file)")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    files = select_files(root, args.files) if args.files else None
    findings = scan(root, files)
    for f in findings:
        print(f)
    if findings:
        print(f"\n{len(findings)} download-integrity finding(s). See {REQ} "
              "and hooks/download-integrity/README.md.", file=sys.stderr)
        return 1
    print("download-integrity: every download is verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
