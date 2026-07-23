# sponsor-base-preflight

Guards the sponsor final-image build against consuming the wrong core base
image. Two checks, run before the image is built.

## 1. Pins — `HSI-OPS-image-promotion/G`

Every entry under `base_images` in the sponsor's `deployment/base-config.json`
must be a content digest:

```text
ghcr.io/cure-hht/portal-server@sha256:<64 hex>      accepted
ghcr.io/cure-hht/portal-server:main-latest          rejected
ghcr.io/cure-hht/portal-server:main-latest@sha256:… rejected (tag + digest)
ghcr.io/cure-hht/portal-server                      rejected (no reference)
```

A mutable tag makes the sponsor image non-reproducible: two builds of the same
sponsor commit can embed different base content. It also opens a publish-latency
window — a sponsor build started shortly after a core merge resolves
`:main-latest` to the *pre-merge* base and ships the sponsor half of a two-repo
change without the core half. That is CUR-1668.

## 2. Capabilities — `HSI-OPS-image-promotion/H`

The pinned `portal-server` image carries `/app/PORTAL_ACTIONS`: the permission
names the server declares, one per line, sorted. The sponsor's
`role-permissions.yaml` grants permission names. Every granted name must appear
in the manifest.

A grant the base does not declare makes the portal fail closed at boot. That is
correct behavior, but it surfaces on Cloud Run as `container failed to start and
listen on PORT=8080` — an opaque message several minutes and one wasted deploy
away from the real cause (the CUR-1624 incident). This check names the missing
permissions at build time instead.

**Transition:** a base image built before core started publishing
`/app/PORTAL_ACTIONS` has no manifest. The action emits a warning and skips the
capability check for that build; it does not fail. Every other extraction
failure (auth, network, corrupt layer) is fatal.

## Usage

The caller checks out the sponsor repo and authenticates to the registry first.

```yaml
- uses: actions/checkout@v4
- uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}
- uses: Cure-HHT/hht_workflows/.github/actions/sponsor-base-preflight@<sha>
  with:
    portal-server-image: ${{ steps.config.outputs.portal_server_image }}
```

| Input | Default | Meaning |
| ----- | ------- | ------- |
| `base-config` | `deployment/base-config.json` | sponsor build config to check pins in |
| `portal-server-image` | *(required)* | digest-pinned base to check capabilities against |
| `role-permissions` | `deployment/sponsor/role-permissions.yaml` | sponsor authorization overlay |

## Advancing a pin

Until the core -> sponsor cascade lands (CUR-872), pins are advanced by hand:

```sh
docker manifest inspect -v ghcr.io/cure-hht/portal-server:main-latest \
  | jq -r '.[0].Descriptor.digest // .Descriptor.digest'
```

Put the digest in `base_images.portal_server` and open a sponsor PR. Do the same
for `base_images.sponsor_ci`. Advance both from the *same* core commit — they are
published by one core workflow run, and mixing them reintroduces the skew this
action exists to prevent.

## Tests

```sh
cd .github/actions/sponsor-base-preflight && PYTHONPATH=. pytest tests/ -v
```

Run in CI by `.github/workflows/release-notes-tests.yml` (the repo's Python
suite; the name is legacy).
