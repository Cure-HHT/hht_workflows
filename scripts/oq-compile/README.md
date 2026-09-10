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
| `oq_compile/load.py` | Trace and graph parsing. |
| `oq_compile/pivot.py` | Both sheets and the verdict rollup. |
| `oq_compile/render.py` | CSV and workbook writers. |

## Local run

```sh
pip install -r scripts/oq-compile/requirements-oq.txt
scripts/oq-compile/oq-compile.sh /path/to/primary /path/to/associate
```

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

## Refusals

The generator writes nothing and exits non-zero when:

- the trace selects zero requirements;
- the selection yields zero UAT test cases (a full REQ sheet with an empty UAT
  sheet is what a dropped or renamed `journeys` key produces);
- a namespace declared in `require_namespaces` contributes no row;
- the trace is a dict carrying no recognised rows key;
- a required field is absent from a trace row;
- the graph yields no journey node while the trace cites at least one.

`--allow-empty` covers the first two only.

## Tests

```sh
pytest scripts/oq-compile/test_oq_compile/ -v
```
