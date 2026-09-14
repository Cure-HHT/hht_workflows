# oq-compile

The generator makes the OQ traceability report from the elspais graph.

It writes two kinds of file:

- `promotion-evidence/_reports/oq-req.csv` and `oq-uat.csv`. These files are
  deterministic. Commit them. CI makes them again and compares them.
- `promotion-evidence/_build/oq-report.xlsx`. This workbook has three sheets.
  Do not commit it. Upload it as an artifact of the run that made it.

## Layout

| Path | Function |
| --- | --- |
| `oq-compile.sh` | Start here. It federates the associates, runs elspais, and calls the orchestrator. |
| `compile-oq.py` | The orchestrator. It calls the loader, then the pivot, then the writers. |
| `oq_compile/manifest.py` | It reads the manifest and validates it. |
| `oq_compile/urs_sections.py` | It gets each URS section number from `urs-compile`. |
| `oq_compile/load.py` | It reads the trace and the graph. |
| `oq_compile/pivot.py` | It makes the two sheets and calculates the verdicts. |
| `oq_compile/render.py` | It writes the CSV files and the workbook. |

## Run the generator

```sh
pip install -r scripts/oq-compile/requirements-oq.txt
scripts/oq-compile/oq-compile.sh /path/to/primary /path/to/associate
```

## The two verdicts

The requirement sheet shows two verdicts for each requirement. Each verdict has
its own column. The generator does not combine them.

| Column | Question |
| --- | --- |
| test result | Did the tests of this requirement pass? |
| UAT result | Did a user journey that validates this requirement pass? |

Both columns use the same three values:

- `FAIL`. Something failed.
- `PASS`. The verification is complete. Partial verification is not a `PASS`.
- `NOT RUN`. All other conditions.

A test can exist before a result exists. The generator shows `NOT RUN` for that
test. It does not show `FAIL`. No result is not the same as a failed result.

Two columns show the reader which kind of evidence is absent. One combined
verdict hides this. If a result comes from a baseline, and not from a new run,
the cell also shows `(carried)`. The legend on the provenance sheet gives all of
these values.

The generator asks elspais for each value by name. It does not use
`--dimension uat`. That dimension removes the `verified` and `tested` values.
The test-result column needs them.

## Configuration

The consuming repository supplies `spec/OQ-manifest/oq.yaml`. This file gives
the document title, the project, and the elspais scope name. It also gives the
prefix for UAT case identifiers, and the titles of the sheets and the columns.
The same repository declares the scope in its `.elspais.toml`. The generator holds no
values of any consumer.

### Namespaces

A federated report gets rows from the consuming repository and from each
associate. The trace does not show which associates must be present. If an
associate is absent, the generator can make a correct report that has only the
rows of the consumer. Such a report has a small part of the evidence, and the
command exits 0.

`require_namespaces` gives the namespaces that the report must contain:

```yaml
require_namespaces: ["SPN", "PLT"]
```

If a namespace in this list has no rows, the generator writes nothing. The
error message gives the namespace that is absent, the namespaces that are
present, and the namespaces that the manifest declares.

If the manifest has no `require_namespaces`, the generator does not do this
test. `--allow-empty` does not stop this test.

### URS sections

`urs_manifest` gives the URS manifest of the consuming repository:

```yaml
urs_manifest: spec/URS-manifest/urs.yaml
```

If the manifest has `urs_manifest`, the requirement sheet gets one more column.
This column shows the number of the URS section of each requirement. It shows
the number only. A number is narrow, and it sorts correctly in the filter. The
column is the second column. It is adjacent to the requirement identifier.

The source file of a requirement does not give its section. A sponsor chapter
can list the same files as a core chapter. The two chapters then collect
requirements of different namespaces from those files. This rule belongs to the
URS generator. This generator does not repeat the rule. It gives the manifest to
the loader of `urs-compile`, and asks `urs_compile.ordering` for the section.

If the URS gives no section to a requirement, the cell is empty. An empty cell
shows that the section is not known.

If the manifest has no `urs_manifest`, the sheet does not get this column.

## Conditions that stop the generator

The generator writes nothing, and exits with an error, if:

- the trace selects no requirements;
- the selection gives no UAT test cases;
- a namespace in `require_namespaces` has no rows;
- the REQ sheet in the manifest does not declare five columns, or six columns
  with `urs_manifest`;
- the manifest declares a `urs_manifest`, but that file is absent;
- the URS manifest puts one requirement in two sections;
- the trace is a mapping, and the generator does not recognise its rows key;
- a row of the trace does not have a necessary field;
- the trace names a journey, but the graph has no journey node.

`--allow-empty` applies only to the first two conditions.

## Tests

```sh
pytest scripts/oq-compile/test_oq_compile/ -v
```
