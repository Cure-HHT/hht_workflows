# Release evidence bundle

One self-contained bundle per release, for a custodian to hold for the
retention horizon, proved by an offline rebuild before it is locked.

## Layout

```text
bundle/
  MANIFEST              plain text: every other file, its SHA-256, its section,
                        and the comparison a rebuild is held to
  rebuild               run inside the toolchain image, offline; compiles the
                        deliverables from source/ into $REBUILD_OUT
  toolchain/image.tar   the compile image, as `docker save` wrote it
  source/               the source snapshot the deliverables were compiled from
  evidence/             test results, traceability matrix, component records
  deliverables/         the deliverables as shipped
```

The toolchain is the only irreplaceable part. Source survives in every clone,
evidence is small, and intermediates can be derived again given the toolchain
and are unreadable without it.

## What each deliverable is held to

Every deliverable is compared byte for byte with what shipped. The reason
that holds differs by type, and the manifest states it per type:

| Type | Comparison | Why it holds |
| ---- | ---------- | ------------ |
| `.pdf` | bytes | rendered under `SOURCE_DATE_EPOCH`; the trailer `/ID` is normalised to a digest of the content |
| `.docx` | bytes | archive entries normalised to the epoch, a fixed order and fixed attributes |
| `.xlsx` | bytes | archive entries and Office clock properties normalised to the epoch |
| `.csv` | bytes | plain text written in a fixed order |
| `.md` | bytes | plain text; the provenance record's date is the epoch |

A deliverable of any other type is refused when the manifest is written: a
deliverable whose rebuild cannot be judged cannot prove the bundle complete.
The normalisation is `scripts/reproducible/normalise.py`, which the URS and OQ
compiles run on their own output.

## Proving and locking

```sh
bundle.py manifest --bundle DIR --release ID --image NAME@sha256:... \
  --image-id sha256:... --epoch N
rebuild.sh DIR verdict.json        # on a fresh host, --network none
bundle.py admit --bundle DIR --verdict verdict.json
bundle.py pack --bundle DIR --out bundle.tar   # prints the archive's SHA-256
```

`rebuild.sh` checks the bundle against its manifest, loads the toolchain from
the bundle (never from a registry), and runs `rebuild` with no network, shown
only the bundle's inputs (`rebuild`, `MANIFEST`, `source/`, `evidence/`)
read-only. It is not shown `deliverables/`: a rebuild that could read what
shipped could copy it and reproduce nothing. It writes the verdict and exits 0 whatever the
verdict says. `admit` is the refusal: it passes only for a verdict bound to
this bundle's manifest in which every deliverable reproduced. The writer of the
locked store runs it, so the store refuses a bundle that did not rebuild.

The `prove-release-bundle` action runs the same three steps and uploads the
verdict before refusing.

The hash `pack` prints is recorded outside the bundle and outside its storage.
A manifest inside an archive attesting to that archive validates whatever it
was packaged with.
