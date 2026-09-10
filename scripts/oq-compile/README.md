# oq-compile

Generates the OQ traceability deliverables from the elspais graph:

- `promotion-evidence/_reports/oq-req.csv` and `oq-uat.csv` — deterministic
  extracts, committed and diffed.
- `promotion-evidence/_build/oq-report.xlsx` — the three-sheet workbook,
  uploaded as a run-bound artifact rather than committed.

## Layout

| Path | Role |
| --- | --- |
| `oq-compile.sh` | Entrypoint: federates associates, runs elspais, invokes the orchestrator. |
| `compile-oq.py` | Orchestrator: loader to pivot to render. |
| `oq_compile/manifest.py` | Manifest loading and validation. |
| `oq_compile/urs_sections.py` | Section lookup, delegated to `urs-compile`. |
| `oq_compile/load.py` | Trace and graph parsing. |
| `oq_compile/pivot.py` | Both sheets and the verdict rollup. |
| `oq_compile/render.py` | CSV and workbook writers. |

## Local run

```sh
pip install -r scripts/oq-compile/requirements-oq.txt
scripts/oq-compile/oq-compile.sh /path/to/primary /path/to/associate
```

## The two kinds of evidence

The requirement sheet reports two verdicts per requirement, in two columns,
and never combines them:

| Column | Question it answers |
| --- | --- |
| test result | Did this requirement's own tests (unit, integration, end-to-end) pass? |
| UAT result | Did a user journey validating this requirement pass? |

Both use the same three labels and the same asymmetry. FAIL when something
actually failed; PASS only on complete verification, never on partial; NOT RUN
for every remaining state. A test that exists but whose result has not been
ingested reports NOT RUN, never FAIL — absence of evidence is not evidence of
failure.

They are kept apart so a reader can see which kind of evidence is missing or
failing, which a single rolled-up verdict hides. A test result whose
verification was carried forward from a baseline rather than produced by a
fresh run is marked `(carried)` on the cell, and the provenance sheet's legend
explains both columns, both meanings of NOT RUN, and the marker.

The trace export therefore names its values explicitly rather than selecting
`--dimension uat`: that dimension suppresses the `verified` and `tested`
figures the test-result column is computed from.

## Configuration

The consuming repo supplies `spec/OQ-manifest/oq.yaml` (document title and
project, the elspais scope name, the UAT case prefix, sheet and column titles)
and declares that scope in its `.elspais.toml`. This tool holds no
consumer-specific values.

### Declaring the namespaces the report must contain

A federated report draws its rows from the consuming repo plus the associate
repos it federates. Nothing in the trace states which associates were meant to
be present, so a run with an associate unconfigured produces a well-formed,
correctly-provenanced report holding only the consumer's own requirements — a
fraction of the evidence, at exit 0.

An optional `require_namespaces` in the manifest names the requirement-id
namespaces the report must contain. The generator refuses to write when any
declared namespace contributes no row, naming what is missing, what was found
and what was expected:

```yaml
require_namespaces: ["SPN", "PLT"]
```

Declaring nothing keeps the generator agnostic about who is federated, so
consumers that do not federate are unaffected. The check is not covered by
`--allow-empty`: an empty report can be honest, but a report missing a
namespace the manifest declares never is.

### Stating each requirement's URS section

An optional `urs_manifest` names the consuming repo's URS manifest, relative to
that repo:

```yaml
urs_manifest: spec/URS-manifest/urs.yaml
```

Declared, the requirement sheet carries one further column holding the number
of the URS section each requirement appears in — the number only, so it sorts
under the sheet's autofilter and stays narrow. It sits second, next to the
requirement id and the frozen first column, ahead of the wide description.

Which section a requirement belongs to is not a property of its source file:
a sponsor-scoped chapter lists the same files the core chapters do and
collects the other namespace's requirements from them. That routing rule
belongs to the URS generator, so this one does not restate it — it hands the
manifest to `urs-compile`'s own loader and asks `urs_compile.ordering`'s
section index for the answer. This tool holds no part of any consumer's
chapter structure.

A requirement the URS places in no section — one in a file no section lists,
or at a level the URS excludes — gets an empty cell. An empty cell states an
absence honestly; a guessed number in a regulatory column does not.

Declaring nothing omits the column, so a consumer that publishes no URS still
gets a report.

## Refusals

The generator writes nothing and exits non-zero when:

- the trace selects zero requirements;
- the selection yields zero UAT test cases (a full REQ sheet with an empty UAT
  sheet is what a dropped or renamed `journeys` key produces);
- a namespace declared in `require_namespaces` contributes no row;
- the manifest's REQ sheet does not declare exactly five columns — six with a
  `urs_manifest` declared — (requirement id, the URS section, description, test
  result, UAT result, and the journey column that repeats);
- a `urs_manifest` is declared but no such file exists;
- the URS manifest places one requirement in two different sections;
- the trace is a dict carrying no recognised rows key;
- a required field is absent from a trace row;
- the graph yields no journey node while the trace cites at least one.

`--allow-empty` covers the first two only.

## Tests

```sh
pytest scripts/oq-compile/test_oq_compile/ -v
```
