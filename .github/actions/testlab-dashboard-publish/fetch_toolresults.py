#!/usr/bin/env python3
"""Fetch Firebase Test Lab results from the Tool Results API and assemble the
JSON structure consumed by the Cure-HHT/testlab-dashboard front end.

This is a server-side (CI) port of that dashboard's own browser-side
fetchLive() function, so the two stay easy to keep in sync. Authentication
reuses the gcloud credentials already established earlier in the workflow
via Workload Identity Federation (google-github-actions/auth) -- no
additional secret is required for this step.
"""
import argparse
import datetime
import json
import subprocess
import urllib.error
import urllib.request

API = "https://toolresults.googleapis.com/toolresults/v1beta3"

NAMES = {
    "redfin": "Pixel 5", "cheetah": "Pixel 7 Pro", "shiba": "Pixel 8",
    "panther": "Pixel 7", "oriole": "Pixel 6", "husky": "Pixel 8 Pro",
    "akita": "Pixel 9", "MediumPhone.arm": "Medium Phone (Arm)",
    "SmallPhone.arm": "Small Phone (Arm)",
}


def get_access_token():
    out = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def api_get(path, token):
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"{e.code} {path} — {body[:200]}") from e


def api_all(path, token, key):
    items = []
    page_token = ""
    while True:
        sep = "&" if "?" in path else "?"
        suffix = f"{sep}pageSize=200"
        if page_token:
            suffix += f"&pageToken={page_token}"
        data = api_get(path + suffix, token)
        items.extend(data.get(key, []))
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break
    return items


def dimify(entity):
    return {d["key"]: d["value"] for d in entity.get("dimensionValue", [])}


def label_of(m):
    name = NAMES.get(m.get("Model"), m.get("Model") or "?")
    tail = "-".join(filter(None, [m.get("Locale"), m.get("Orientation")]))
    return f"{name} · API {m.get('Version', '?')}" + (f" · {tail}" if tail else "")


def dsec(x):
    if not x:
        return None
    return float(x.get("seconds", 0)) + float(x.get("nanos", 0)) / 1e9


def fetch(project, history, execution, token):
    ep = f"/projects/{project}/histories/{history}/executions/{execution}"
    execu = api_get(ep, token)

    creation = execu.get("creationTime")
    completion = execu.get("completionTime")
    duration = None
    if creation and completion:
        duration = int(completion["seconds"]) - int(creation["seconds"])

    out = {
        "meta": {
            "projectId": project,
            "historyId": history,
            "executionId": execution,
            "source": "CI / fetch_toolresults.py",
            "fetchedAt": datetime.datetime.utcnow().isoformat() + "Z",
        },
        "execution": {
            "outcome": (execu.get("outcome") or {}).get("summary", "unset"),
            "state": execu.get("state"),
            "creationTime": creation,
            "completionTime": completion,
            "durationSec": duration,
        },
        "environments": [], "steps": [], "testCases": [], "perf": [],
        "thumbnails": [], "artifacts": [],
    }

    for env in api_all(ep + "/environments", token, "environments"):
        m = dimify(env)
        er = env.get("environmentResult", {})
        out["environments"].append({
            "id": env.get("environmentId"), "model": m.get("Model"),
            "modelName": NAMES.get(m.get("Model"), m.get("Model")),
            "version": m.get("Version"), "locale": m.get("Locale"),
            "orientation": m.get("Orientation"), "label": label_of(m),
            "outcome": (er.get("outcome") or {}).get("summary", "unset"),
        })

    steps = api_all(ep + "/steps", token, "steps")
    totals = {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "flaky": 0}

    for st in steps:
        m = dimify(st)
        label = label_of(m)
        tes = st.get("testExecutionStep", {})
        counts = {"total": 0, "failures": 0, "errors": 0, "skipped": 0, "flaky": 0}
        xunit = None
        for ov in tes.get("testSuiteOverviews", []):
            counts["total"] += int(ov.get("totalCount", 0))
            counts["failures"] += int(ov.get("failureCount", 0))
            counts["errors"] += int(ov.get("errorCount", 0))
            counts["skipped"] += int(ov.get("skippedCount", 0))
            counts["flaky"] += int(ov.get("flakyCount", 0))
            if not xunit:
                xunit = (ov.get("xmlSource") or {}).get("fileUri")

        passed = max(counts["total"] - counts["failures"] - counts["errors"] - counts["skipped"], 0)
        totals["tests"] += counts["total"]
        totals["failed"] += counts["failures"]
        totals["errors"] += counts["errors"]
        totals["skipped"] += counts["skipped"]
        totals["passed"] += passed

        outputs = []
        tool_exec = tes.get("toolExecution", {})
        for o in tool_exec.get("toolOutputs", []):
            uri = (o.get("output") or {}).get("fileUri")
            if uri:
                outputs.append({"name": uri.rsplit("/", 1)[-1], "fileUri": uri})
        for log in tool_exec.get("toolLogs", []):
            uri = log.get("fileUri")
            if uri:
                outputs.append({"name": uri.rsplit("/", 1)[-1], "fileUri": uri})
        if xunit:
            outputs.append({"name": xunit.rsplit("/", 1)[-1], "fileUri": xunit})
        for o in outputs:
            out["artifacts"].append({"envLabel": label, "stepId": st.get("stepId"), **o})

        out["steps"].append({
            "stepId": st.get("stepId"), "name": st.get("name"), "envLabel": label,
            "model": m.get("Model"), "modelName": NAMES.get(m.get("Model"), m.get("Model")),
            "version": m.get("Version"),
            "outcome": (st.get("outcome") or {}).get("summary", "unset"),
            "durationSec": dsec(st.get("runDuration")),
            "testCounts": counts, "xUnitUri": xunit, "outputs": outputs,
        })

        try:
            for tc in api_all(f"{ep}/steps/{st.get('stepId')}/testCases", token, "testCases"):
                ref = tc.get("testCaseReference", {})
                out["testCases"].append({
                    "id": tc.get("testCaseId"), "name": ref.get("name", "(unnamed)"),
                    "className": ref.get("className", ""), "envLabel": label,
                    "model": NAMES.get(m.get("Model"), m.get("Model")),
                    "status": tc.get("status", "passed"),
                    "durationSec": dsec(tc.get("elapsedTime")),
                    "stackTrace": (tc.get("stackTrace") or {}).get("exception", ""),
                    "skippedMessage": tc.get("skippedMessage", ""),
                })
        except RuntimeError:
            pass

        try:
            series = {}
            for ss in api_all(f"{ep}/steps/{st.get('stepId')}/perfSampleSeries", token, "perfSampleSeries"):
                basic = ss.get("basicPerfSampleSeries", {})
                key = basic.get("perfMetricType", "metric")
                samples = api_all(
                    f"{ep}/steps/{st.get('stepId')}/perfSampleSeries/{ss.get('sampleSeriesId')}/samples",
                    token, "perfSamples",
                )
                pts = sorted(
                    ({"t": int((s.get("sampleTime") or {}).get("seconds", 0)), "v": s.get("value", 0)} for s in samples),
                    key=lambda p: p["t"],
                )
                if pts:
                    t0 = pts[0]["t"]
                    for p in pts:
                        p["t"] = round(p["t"] - t0, 2)
                    series[key] = pts
            if series:
                out["perf"].append({
                    "envLabel": label, "model": NAMES.get(m.get("Model"), m.get("Model")),
                    "stepId": st.get("stepId"), "series": series,
                })
        except RuntimeError:
            pass

        try:
            thumbs = api_get(f"{ep}/steps/{st.get('stepId')}/thumbnails", token)
            for im in thumbs.get("thumbnails", []):
                t = im.get("thumbnail", {})
                if t.get("data"):
                    out["thumbnails"].append({
                        "envLabel": label, "stepId": st.get("stepId"),
                        "dataUri": f"data:{t.get('contentType', 'image/jpeg')};base64,{t['data']}",
                    })
        except RuntimeError:
            pass

    out["totals"] = {**totals, "devices": len(out["environments"]) or len(steps)}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--execution", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    token = get_access_token()
    data = fetch(args.project, args.history, args.execution, token)
    with open(args.out, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {args.out}: {data['totals']['tests']} tests across {data['totals']['devices']} devices.")


if __name__ == "__main__":
    main()
