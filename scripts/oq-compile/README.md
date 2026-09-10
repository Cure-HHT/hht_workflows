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
sponsor-specific values.

## Tests

```sh
pytest scripts/oq-compile/test_oq_compile/ -v
```
