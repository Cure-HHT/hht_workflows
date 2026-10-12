#!/usr/bin/env bash
# install-gitleaks: install a gitleaks release only if it matches a recorded digest.
#
#   install.sh <version> [expected-sha256] [install-dir]
#
# The expected digest comes from the `digests` file beside this script. A
# caller may also pass one; it must then agree with the file, so a caller can
# assert a pin but cannot widen what this action accepts. A version the file
# does not list is refused. Any failure exits non-zero before installing.

set -euo pipefail

die() {
  echo "::error::install-gitleaks: $*" >&2
  exit 1
}

[ $# -ge 1 ] || die "usage: install.sh <version> [expected-sha256] [install-dir]"
version="${1#v}"
given="${2:-}"
dest="${3:-/usr/local/bin}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version '$1' is not X.Y.Z (a leading v is accepted)"
# The action fetches the linux_x64 asset only; anything else would install a
# binary that cannot run.
arch="$(uname -m)"
[ "$arch" = "x86_64" ] || die "supports Linux x86_64 only; this runner is $(uname -s) $arch"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required to verify the download"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
recorded="$(awk -v v="$version" '$1 == v { print $2 }' "$here/digests")"
[ -n "$recorded" ] || die "gitleaks $version has no recorded digest in $here/digests; add one in a reviewed change"
[[ "$recorded" =~ ^[0-9a-f]{64}$ ]] || die "recorded digest for $version is not a SHA-256: $recorded"
if [ -n "$given" ] && [ "$given" != "$recorded" ]; then
  die "caller's sha256 $given disagrees with the recorded digest $recorded for $version"
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
asset="gitleaks_${version}_linux_x64.tar.gz"
url="${GITLEAKS_RELEASE_BASE_URL:-https://github.com/gitleaks/gitleaks/releases/download}/v${version}/${asset}"
curl -fsSL --retry 3 --retry-all-errors --proto '=https' --tlsv1.2 -o "$work/$asset" "$url" ||
  die "could not download $url"

actual="$(sha256sum "$work/$asset" | cut -d' ' -f1)"
[ "$actual" = "$recorded" ] || die "SHA-256 mismatch for $asset: recorded $recorded, downloaded $actual; refusing to install"
echo "install-gitleaks: $asset matches recorded SHA-256"

tar -xzf "$work/$asset" -C "$work" gitleaks || die "$asset does not contain a gitleaks binary"
# Check what the verified tarball holds before it reaches the install dir.
reported="$("$work/gitleaks" version 2>/dev/null | head -1)"
case "$reported" in
  *"$version"*) ;;
  *) die "the binary in $asset reports '$reported', expected $version; not installing it" ;;
esac
if [ -w "$dest" ]; then
  install -m 0755 "$work/gitleaks" "$dest/gitleaks"
else
  sudo install -m 0755 "$work/gitleaks" "$dest/gitleaks"
fi
echo "install-gitleaks: installed gitleaks $reported at $dest/gitleaks"
