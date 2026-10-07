#!/usr/bin/env bash
# Tests for install-doppler-cli/install.sh, offline.
#
# A stand-in `curl` on PATH serves fixture files instead of the network, so
# each refusal path can be driven: a tampered tarball, a signature made by some
# other key, a key file swapped for another key, a malformed version. The happy
# path uses a fixture signed by a throwaway key whose fingerprint the copy of
# the script under test is pinned to; the real key and a real download are
# exercised by the install-doppler-cli readiness job.
#
# Verifies: HHT-OPS-ci-tool-download-integrity/A+B
#
# Run: bash .github/actions/install-doppler-cli/tests/install_test.sh
# Needs: bash, gpg, tar, curl-free (the stand-in replaces it).

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
action="$(cd "$here/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

pass=0
fail=0
ok() { echo "ok   - $1"; pass=$((pass + 1)); }
bad() { echo "FAIL - $1"; fail=$((fail + 1)); }

export GNUPGHOME="$tmp/keys"
mkdir -m 0700 "$GNUPGHOME"
newkey() {
  gpg --batch --passphrase '' --quick-gen-key "$1" ed25519 sign 1d >/dev/null 2>&1
  gpg --batch --with-colons --list-keys "$1" | awk -F: '/^fpr/{print $10; exit}'
}
signer_fpr="$(newkey signer@example.invalid)"
other_fpr="$(newkey other@example.invalid)"

version=9.9.9
asset="doppler_${version}_linux_amd64.tar.gz"

# Fixture release: a doppler stand-in that reports the version, tarred and signed.
mkdir -p "$tmp/rel/$version" "$tmp/build"
printf '#!/bin/sh\necho "v%s"\n' "$version" >"$tmp/build/doppler"
chmod +x "$tmp/build/doppler"
tar -czf "$tmp/rel/$version/$asset" -C "$tmp/build" doppler
gpg --batch --yes -u signer@example.invalid --detach-sign -o "$tmp/rel/$version/$asset.sig" "$tmp/rel/$version/$asset"

# Copy of the action pinned to the fixture signer's key.
setup_action() {
  local key_uid="$1" pin="$2" dir="$tmp/action-$RANDOM"
  mkdir -p "$dir"
  sed "s/^readonly DOPPLER_CLI_SIGNER_FPR=.*/readonly DOPPLER_CLI_SIGNER_FPR=$pin/" "$action/install.sh" >"$dir/install.sh"
  chmod +x "$dir/install.sh"
  gpg --batch --armor --export "$key_uid" >"$dir/doppler-cli-release.asc"
  echo "$dir"
}

# Stand-in curl: `curl ... -o <out> <url>` copies <url>'s path from the fixture tree.
mkdir -p "$tmp/bin"
cat >"$tmp/bin/curl" <<EOF
#!/usr/bin/env bash
out=""; url=""
while [ \$# -gt 0 ]; do
  case "\$1" in -o) out="\$2"; shift 2 ;; http*) url="\$1"; shift ;; *) shift ;; esac
done
src="$tmp/rel/\${url#*/download/}"
[ -f "\$src" ] || exit 22
cp "\$src" "\$out"
EOF
chmod +x "$tmp/bin/curl"

run() {
  # Run with the stand-in curl and a fresh install dir; GNUPGHOME is the
  # script's own business, so drop the test keyring from its environment.
  local dir="$1"; shift
  mkdir -p "$tmp/out"
  rm -f "$tmp/out/doppler"
  env -u GNUPGHOME PATH="$tmp/bin:$PATH" DOPPLER_RELEASE_BASE_URL=https://fixture.invalid/download \
    "$dir/install.sh" "$@" "$tmp/out" >"$tmp/log" 2>&1
}

good="$(setup_action signer@example.invalid "$signer_fpr")"

if run "$good" "v$version" && [ -x "$tmp/out/doppler" ]; then ok "signed release installs"; else bad "signed release installs"; cat "$tmp/log"; fi

cp "$tmp/rel/$version/$asset" "$tmp/orig.tgz"
printf 'x' >>"$tmp/rel/$version/$asset"
if run "$good" "$version"; then bad "tampered tarball is refused"; elif [ ! -e "$tmp/out/doppler" ] && grep -q 'does not verify' "$tmp/log"; then ok "tampered tarball is refused"; else bad "tampered tarball is refused (wrong reason)"; cat "$tmp/log"; fi
cp "$tmp/orig.tgz" "$tmp/rel/$version/$asset"

cp "$tmp/rel/$version/$asset.sig" "$tmp/orig.sig"
gpg --batch --yes -u other@example.invalid --detach-sign -o "$tmp/rel/$version/$asset.sig" "$tmp/rel/$version/$asset"
if run "$good" "$version"; then bad "signature by another key is refused"; elif [ ! -e "$tmp/out/doppler" ]; then ok "signature by another key is refused"; else bad "signature by another key is refused"; fi
cp "$tmp/orig.sig" "$tmp/rel/$version/$asset.sig"

# Key file swapped for another key, signature remade with it: the pin catches it.
swapped="$(setup_action other@example.invalid "$signer_fpr")"
gpg --batch --yes -u other@example.invalid --detach-sign -o "$tmp/rel/$version/$asset.sig" "$tmp/rel/$version/$asset"
if run "$swapped" "$version"; then bad "swapped key file is refused"; elif grep -q 'not signed by the Doppler CLI release key' "$tmp/log"; then ok "swapped key file is refused"; else bad "swapped key file is refused (wrong reason)"; cat "$tmp/log"; fi
cp "$tmp/orig.sig" "$tmp/rel/$version/$asset.sig"

if run "$good" "latest"; then bad "non X.Y.Z version is refused"; else ok "non X.Y.Z version is refused"; fi

if run "$good" "1.2.3"; then bad "missing release is refused"; elif grep -q 'could not download' "$tmp/log"; then ok "missing release is refused"; else bad "missing release is refused (wrong reason)"; fi

: "$other_fpr"
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
