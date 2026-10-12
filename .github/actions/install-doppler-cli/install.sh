#!/usr/bin/env bash
# install-doppler-cli: install a Doppler CLI release only if Doppler signed it.
#
#   install.sh <version> [install-dir]
#
# Downloads doppler_<version>_linux_amd64.tar.gz and its detached signature
# from the DopplerHQ/cli GitHub release, verifies the signature against the
# Doppler CLI release key shipped beside this script, and only then unpacks
# and installs the binary. The key's primary fingerprint is pinned below, so
# a replaced key file is refused as well as a replaced tarball.
#
# This replaces `curl https://cli.doppler.com/install.sh | sudo sh`, which
# runs a downloaded script as root before anything can check it.
#
# Any failure exits non-zero before the binary is installed.

set -euo pipefail

# DopplerHQ <support@doppler.com>, the key that signs CLI release assets.
# Expires 2029-10-29; Doppler rotates it before then and this pin moves with it.
readonly DOPPLER_CLI_SIGNER_FPR=B70BD7FCA460C4A3D0EEB965D3D593D50EE79DEC

die() {
  echo "::error::install-doppler-cli: $*" >&2
  exit 1
}

[ $# -ge 1 ] || die "usage: install.sh <version> [install-dir]"
version="${1#v}"
dest="${2:-/usr/local/bin}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version '$1' is not X.Y.Z (a leading v is accepted)"
# The action fetches the linux_amd64 asset only; anything else would install a
# binary that cannot run, after verifying the wrong thing.
arch="$(uname -m)"
[ "$arch" = "x86_64" ] || die "supports Linux x86_64 only; this runner is $(uname -s) $arch"
command -v gpg >/dev/null 2>&1 || die "gpg is required to verify the release signature"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

asset="doppler_${version}_linux_amd64.tar.gz"
base="${DOPPLER_RELEASE_BASE_URL:-https://github.com/DopplerHQ/cli/releases/download}/${version}"

fetch() {
  curl -fsSL --retry 3 --retry-all-errors --proto '=https' --tlsv1.2 \
    -o "$work/$1" "$base/$1" || die "could not download $base/$1"
}
fetch "$asset"
fetch "$asset.sig"

# A throwaway keyring holding only the pinned key: nothing else on the runner
# can vouch for the tarball.
export GNUPGHOME="$work/gnupg"
mkdir -m 0700 "$GNUPGHOME"
gpg --batch --quiet --import "$here/doppler-cli-release.asc" 2>/dev/null ||
  die "could not import $here/doppler-cli-release.asc"

status="$(gpg --batch --status-fd 1 --verify "$work/$asset.sig" "$work/$asset" 2>/dev/null)" ||
  die "the signature on $asset does not verify; refusing to install"
# VALIDSIG's last field is the fingerprint of the primary key that made the
# signature. Requiring it to be the pinned one rules out any other key.
grep -Eq "^\[GNUPG:\] VALIDSIG .* ${DOPPLER_CLI_SIGNER_FPR}\$" <<<"$status" ||
  die "$asset is not signed by the Doppler CLI release key ${DOPPLER_CLI_SIGNER_FPR}"
echo "install-doppler-cli: $asset signature verified (key ${DOPPLER_CLI_SIGNER_FPR})"

tar -xzf "$work/$asset" -C "$work" doppler || die "$asset does not contain a doppler binary"
# Check what the verified tarball holds before it reaches the install dir.
reported="$("$work/doppler" --version 2>/dev/null | head -1)"
case "$reported" in
  *"$version"*) ;;
  *) die "the binary in $asset reports '$reported', expected $version; not installing it" ;;
esac
if [ -w "$dest" ]; then
  install -m 0755 "$work/doppler" "$dest/doppler"
else
  sudo install -m 0755 "$work/doppler" "$dest/doppler"
fi
echo "install-doppler-cli: installed doppler $reported at $dest/doppler"
