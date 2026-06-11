# URS Compile Pipeline

Build the URS PDF + DOCX regulated deliverables from a consumer repo
holding the sponsor-overlay content (`spec/URS-manifest/`) and an
optional sibling associate repo providing cross-referenced spec
content via the federated elspais graph.

## Layout

```text
scripts/urs-compile/
├── compile-urs.sh             # Local-dev / CI entry point
├── compile-urs.py             # Python orchestrator
├── urs_compile/               # Helper modules (graph_loader, ordering, manifest, render)
├── pandoc-filters/            # Lua filters (table-grid, image-normalize, code-breakable, assertion-label-italic)
├── urs-template.latex         # Generic LaTeX template; sponsor identity comes from \sponsorName macros
├── urs-section-map.yaml       # Chapter/section ordering manifest
├── build_docx_reference.py    # Generates the pandoc docx style reference at build time
├── requirements-compile.txt   # Python dependencies for the orchestrator
└── test_compile_urs/          # pytest suite
```

`urs-reference.docx` is not committed — it is generated each build
from `build_docx_reference.py` so the headers and footers carry the
sponsor identity of the active build.

## Sponsor identity

The consumer repo supplies `spec/URS-manifest/sponsor-info.yaml`:

```yaml
sponsor_name: "Acme Therapeutics, Inc."
protocol_number: "ACME-1234-C01"
protocol_version: "1.0"
```

`compile-urs.py` reads this file at build time and writes a small
LaTeX include-in-header file (`build/sponsor-header.tex`) that
`\renewcommand`'s the `\sponsorName`, `\protocolNumber`, and
`\protocolVersion` macros declared with `\providecommand` defaults in
`urs-template.latex`. The same file is reused for the term-index PDF
so the two deliverables stay in lockstep.

If `sponsor-info.yaml` is absent, the template's placeholder defaults
(`[SPONSOR_NAME]`, `[PROTOCOL]`, `1.0`) render in the output — a
deliberately visible failure mode.

## Consumer-supplied URS-manifest layout

`compile-urs.py` looks for each manifest-referenced prose file in
PRIMARY_ROOT first, then ASSOCIATE_ROOT as a fallback. This lets the
sponsor-overlay prose (cover, frontmatter, sponsor-info) live in the
sponsor repo while platform-generic prose (chapter intros, appendices)
stays in the platform repo.

Sponsor-overlay (PRIMARY_ROOT only):

```text
spec/URS-manifest/
├── sponsor-info.yaml          # Sponsor identity (above)
├── urs-cover.tex              # LaTeX cover snippet (uses \sponsorName etc.)
├── urs-term-index-cover.tex   # LaTeX cover snippet for the term-index PDF
├── cover.md                   # Markdown cover prepended to the DOCX output
├── frontmatter.md             # Markdown frontmatter prepended to both outputs
├── ch7-intro.md               # Sponsor Configuration Requirements chapter intro
└── appendices.md              # Appendix prose appended after the body
```

Platform-generic (typically ASSOCIATE_ROOT, but may live in either):

```text
spec/URS-manifest/
└── ch4-intro.md, ch5-intro.md, ch6-intro.md   # Chapter intros
```

## Section ordering and pagination

Within each manifest section, REQs keep their source order, except that
REQs sharing one kebab name after the namespace/level prefix
(`DIARY-PRD-user-account-deactivate` + `DIARY-GUI-user-account-deactivate`)
merge into a single level-3 section: one numbered heading (the PRD twin's
title), the GUI twin following heading-less in the same section — see
`urs_compile/ordering.py`. Only PRD and GUI levels appear in the
deliverable.

Chapters declare a `scope`: `core` chapters emit DIARY-* REQs only;
a `sponsor` chapter collects every sponsor-namespace REQ from the files
it references, so sponsor configuration REQs land in their own chapter
instead of interleaving with the platform REQs.

Pagination: every body section (level-2 heading) starts on a fresh page;
every level-3 heading starts on a fresh page EXCEPT the first one of
each section, which shares the section's opening page. The assembler
emits a page-break marker before each section heading (`{=latex}` for
the PDF — which also raises the flag the template's `\subsection`
format consumes — and `{=openxml}` for the docx, folded into
`pageBreakBefore` by `_apply_heading_page_breaks`). Frontmatter,
appendix, and glossary headings are unaffected.

## Local CLI usage

From the consumer repo's worktree:

```bash
/path/to/hht_workflows/scripts/urs-compile/compile-urs.sh \
    /path/to/consumer/worktree \
    /path/to/associate/worktree   # optional
```

Outputs land in `<primary-root>/docs/`:

```text
docs/urs-compiled.pdf
docs/urs-compiled.docx
docs/urs-term-index.pdf
docs/urs-term-index.docx
```

Prerequisites:

- `pandoc` 3.x and `xelatex` on `PATH`
- `python3` 3.12+ with `pip install -r requirements-compile.txt`
- `elspais` 0.117+ (the consumer repo's `.elspais.toml` plus a local
  `.elspais.local.toml` declaring the associate path)

## Composite action

In a consumer-repo workflow:

```yaml
- uses: actions/checkout@v4
  with: { path: primary }
- uses: actions/checkout@v4
  with:
    repository: Cure-HHT/hht_diary
    path: associate
    token: ${{ secrets.ASSOCIATE_REPO_TOKEN }}
- uses: Cure-HHT/hht_workflows/actions/build-urs@main
  with:
    primary-root: primary
    associate-root: associate
```

The action installs pandoc, xelatex, and elspais; runs `compile-urs.sh`;
and uploads the four URS deliverables as a `urs-deliverables` artifact.

## Tests

```bash
cd scripts/urs-compile
pip install -r requirements-compile.txt pytest
pytest test_compile_urs/
```
