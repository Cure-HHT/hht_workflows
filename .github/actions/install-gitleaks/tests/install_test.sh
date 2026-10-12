#!/usr/bin/env bash
# Tests for install-gitleaks/install.sh, offline.
#
# A stand-in `curl` serves a fixture tarball; a copy of the script runs beside
# a fixture `digests` file. Covers: the recorded digest installs; a changed
# tarball is refused; an unrecorded version is refused; a caller digest that
# disagrees with the record is refused; a malformed version is refused; a
# non-x86_64 runner is refused; a binary reporting another version is not
# installed. The real 8.29.0 release is exercised by the install-gitleaks
# readiness job.
#
# Verifies: HHT-OPS-ci-tool-download-integrity/A+B
#
# Run: bash .github/actions/install-gitleaks/tests/install_test.sh

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
action="$(cd "$here/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
pass=0
fail=0
ok() { echo "ok   - $1"; pass=$((pass + 1)); }
bad() { echo "FAIL - $1"; fail=$((fail + 1)); }

version=9.9.9
asset="gitleaks_${version}_linux_x64.tar.gz"
mkdir -p "$tmp/rel/v$version" "$tmp/build" "$tmp/act" "$tmp/bin" "$tmp/out"
printf '#!/bin/sh\necho "%s"\n' "$version" >"$tmp/build/gitleaks"
chmod +x "$tmp/build/gitleaks"
tar -czf "$tmp/rel/v$version/$asset" -C "$tmp/build" gitleaks
digest="$(sha256sum "$tmp/rel/v$version/$asset" | cut -d' ' -f1)"

cp "$action/install.sh" "$tmp/act/install.sh"
printf '# fixture\n%s %s\n' "$version" "$digest" >"$tmp/act/digests"

cat >"$tmp/bin/curl" <<SHIM
#!/usr/bin/env bash
out=""; url=""
while [ \$# -gt 0 ]; do
  case "\$1" in -o) out="\$2"; shift 2 ;; http*) url="\$1"; shift ;; *) shift ;; esac
done
src="$tmp/rel/\${url#*/download/}"
[ -f "\$src" ] || exit 22
cp "\$src" "\$out"
SHIM
chmod +x "$tmp/bin/curl"

run() {
  rm -f "$tmp/out/gitleaks"
  PATH="$tmp/bin:$PATH" GITLEAKS_RELEASE_BASE_URL=https://fixture.invalid/download \
    "$tmp/act/install.sh" "$@" >"$tmp/log" 2>&1
}

if run "v$version" "" "$tmp/out" && [ -x "$tmp/out/gitleaks" ]; then ok "recorded digest installs"; else bad "recorded digest installs"; cat "$tmp/log"; fi
if run "$version" "$digest" "$tmp/out"; then ok "matching caller digest installs"; else bad "matching caller digest installs"; cat "$tmp/log"; fi

if run "$version" "$(printf 'a%.0s' $(seq 64))" "$tmp/out"; then bad "disagreeing caller digest is refused"; elif grep -q 'disagrees' "$tmp/log"; then ok "disagreeing caller digest is refused"; else bad "disagreeing caller digest is refused (wrong reason)"; fi

cp "$tmp/rel/v$version/$asset" "$tmp/orig"
printf 'x' >>"$tmp/rel/v$version/$asset"
if run "$version" "" "$tmp/out"; then bad "changed tarball is refused"; elif [ ! -e "$tmp/out/gitleaks" ] && grep -q 'mismatch' "$tmp/log"; then ok "changed tarball is refused"; else bad "changed tarball is refused (wrong reason)"; cat "$tmp/log"; fi
cp "$tmp/orig" "$tmp/rel/v$version/$asset"

if run "1.2.3" "" "$tmp/out"; then bad "unrecorded version is refused"; elif grep -q 'no recorded digest' "$tmp/log"; then ok "unrecorded version is refused"; else bad "unrecorded version is refused (wrong reason)"; fi
if run "latest" "" "$tmp/out"; then bad "non X.Y.Z version is refused"; else ok "non X.Y.Z version is refused"; fi

# A non-x86_64 runner is refused before anything is downloaded.
mkdir -p "$tmp/armbin"
cat >"$tmp/armbin/uname" <<'SHIM'
#!/bin/sh
if [ "$1" = "-m" ]; then echo aarch64; else echo Linux; fi
SHIM
chmod +x "$tmp/armbin/uname"
if PATH="$tmp/armbin:$tmp/bin:$PATH" GITLEAKS_RELEASE_BASE_URL=https://fixture.invalid/download \
  "$tmp/act/install.sh" "$version" "" "$tmp/out" >"$tmp/log" 2>&1; then
  bad "non-x86_64 runner is refused"
elif grep -q 'x86_64 only' "$tmp/log"; then ok "non-x86_64 runner is refused"; else bad "non-x86_64 runner is refused (wrong reason)"; cat "$tmp/log"; fi

# A recorded tarball whose binary reports another version never reaches the install dir.
other_version=8.8.8
other_asset="gitleaks_${other_version}_linux_x64.tar.gz"
mkdir -p "$tmp/rel/v$other_version" "$tmp/build2"
printf '#!/bin/sh\necho "1.0.0"\n' >"$tmp/build2/gitleaks"
chmod +x "$tmp/build2/gitleaks"
tar -czf "$tmp/rel/v$other_version/$other_asset" -C "$tmp/build2" gitleaks
printf '%s %s\n' "$other_version" "$(sha256sum "$tmp/rel/v$other_version/$other_asset" | cut -d' ' -f1)" >>"$tmp/act/digests"
if run "$other_version" "" "$tmp/out"; then bad "binary reporting another version is not installed"; elif [ ! -e "$tmp/out/gitleaks" ] && grep -q 'not installing it' "$tmp/log"; then ok "binary reporting another version is not installed"; else bad "binary reporting another version is not installed (wrong reason)"; cat "$tmp/log"; fi

# The shipped table: every line is a version and a well-formed digest.
if awk '!/^#/ && NF { if ($1 !~ /^[0-9]+\.[0-9]+\.[0-9]+$/ || $2 !~ /^[0-9a-f]{64}$/ || NF != 2) exit 1 }' "$action/digests"; then ok "shipped digests file is well formed"; else bad "shipped digests file is well formed"; fi

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
