# Are the compiled deliverables reproducible?

Measured, not assumed. A check that a committed deliverable still matches one
rebuilt from the same pinned inputs can only bind something that is actually
byte-stable, and which artifact that is decides how such a check is written.

## Result

Under a fixed `SOURCE_DATE_EPOCH`, **the content is fully reproducible and the
containers are not**. Two compiles of the same sources produce documents that
say exactly the same thing in bytes that are not equal.

| Artifact | Byte-identical | What differs |
| -------- | -------------- | ------------ |
| `build/urs-assembled.pdf.md` | yes | — |
| `build/urs-assembled.docx.md` | yes | — |
| `docs/urs-build-provenance.md` | yes | — |
| `docs/urs-term-index.docx` | yes | — |
| `docs/urs.docx` | no | zip container only; the unpacked contents are identical |
| `docs/urs.pdf` | no | the `/ID` trailer only |
| `docs/urs-term-index.pdf` | no | same as above |

## What the PDF difference actually is

Both files are 58928 bytes and their extracted text is identical. They diverge
at byte 58362, inside the cross-reference trailer:

```text
run a:  /Type/XRef/ID[<6ebce1990b1b20f9dcb4cff4fa85e8e4><6ebce1990b1b20f9dcb4cff4fa85e8e4>]
run b:  /Type/XRef/ID[<482cb324b2f0e0790e9b9222a3bb513f><482cb324b2f0e0790e9b9222a3bb513f>]
```

XeTeX generates a document identifier per run. It is not a timestamp, so
`SOURCE_DATE_EPOCH` does not fix it, and nothing else in the file moves.

## What the DOCX difference actually is

Unzipping both and comparing the trees reports no differences at all. Only the
zip container's own bytes differ. As with the PDF, the document is the same
document.

`urs-term-index.docx` came out byte-identical while `urs.docx` did not, from the
same toolchain in the same pair of runs. That inconsistency is unexplained here
and is worth knowing before anyone concludes DOCX is reliably stable.

## What this means for the agreement check

Bind the **assembled intermediate**, not the rendered deliverables.

`build/urs-assembled.pdf.md` and `build/urs-assembled.docx.md` are byte-stable,
and they are the documents the renderer consumes — everything the deliverable
says is decided by the time they exist. A check on them catches a hand-edited
deliverable, a stale one, and a moved pin, which is the whole job.

Binding the rendered forms would need the renderer's identifier pinned or the
containers normalised before comparison. Both are possible; neither is worth
doing to re-derive a guarantee the intermediate already gives.

The renderer is not left unguarded by this. It is one of the pinned inputs, so a
change to it changes the pin, and the pin is reviewed.

## Reproducing this measurement

```sh
cd scripts/urs-compile
for run in a b; do
  cp -r test_compile_urs/fixtures/readiness "/tmp/urs-repro-$run"
  git init -q "/tmp/urs-repro-$run/primary"
  git init -q "/tmp/urs-repro-$run/associate"
  SOURCE_DATE_EPOCH=1788998400 ./compile-urs.sh \
    "/tmp/urs-repro-$run/primary" "/tmp/urs-repro-$run/associate"
done

for f in urs.pdf urs.docx urs-term-index.pdf urs-term-index.docx \
         urs-build-provenance.md; do
  if cmp -s "/tmp/urs-repro-a/primary/docs/$f" \
            "/tmp/urs-repro-b/primary/docs/$f"; then
    echo "IDENTICAL  $f"
  else
    echo "DIFFERS    $f"
  fi
done
```

Both runs must use the same epoch. With the epoch unset the provenance file
differs whenever the two runs straddle midnight UTC, which measures the clock
rather than the compile.

## Toolchain measured

```text
pandoc 3.1.3
XeTeX 3.141592653-2.6-0.999995 (TeX Live 2023/Debian)
```

A different renderer version may move these results in either direction. The
table above describes this toolchain, and the commands above are how to find out
whether it still holds.
