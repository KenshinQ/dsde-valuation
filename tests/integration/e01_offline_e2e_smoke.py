"""Official production-path offline E2E smoke (backlog item 6 / Gap #9).

This is not A-02 (phase12 mature_operating smallest complete synthetic
workflow) and not VTP-criteria E-01 (routing truth table / 10×12×4).

The command sequence follows scripts/e2e_offline_demo.sh:

    demo (writes frozen canonical data)
    → validate-data → build-snapshot → estimate → simulate
    → project-paths → value → returns → sensitivity → evaluate

Replay: re-run the post-demo steps from the saved data directory with
the same seed / as-of / ticker / path counts (K-02). A dummy proxy is
never treated as isolation.

`vms value` is the official script's step; its own help text notes it is
the legacy 0.1 FCFF pipeline (prefer phase4). This smoke does not swap
that step and does not close production 10×12×4 routing.

Does not claim ENGINEERING_ACCEPTED or investment value. The
evaluation_report may contain a run-level ENGINEERING_PASS label for
this synthetic evaluate; that is not a repository verdict.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

TICKER = "SYN000001.SZ"
ASOF = "2025-06-30"
SEED = "42"
# Official script omits --paths on demo; config default_paths is 10000.
# Later official steps use 40/30/30/30/20. Smoke bounds demo the same way.
DEMO_PATHS = "40"
PATHS_SIM, PATHS_FP, PATHS_VAL, PATHS_RET, PATHS_SENS = "40", "30", "30", "30", "20"
PIPELINE_PARTS = ("snap", "est", "sim", "fp", "val", "ret", "sens", "eval")
# Forecast JSON files carry a wall-clock outcomes.evaluation_as_of.
EVAL_TIMESTAMP_FIELD = "outcomes.evaluation_as_of"


def _vms(repo: Path, python: str, log: Path, *args: str) -> None:
    cmd = [python, "-m", "vms.cli.main", *args]
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write("\n$ " + " ".join(cmd) + "\n")
        handle.flush()
        proc = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, check=False)
        handle.write(proc.stdout or "")
        if proc.stderr:
            handle.write("\n[stderr]\n")
            handle.write(proc.stderr)
        handle.write(f"\n[exit {proc.returncode}]\n")
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr or proc.stdout}"
        )


def sha_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def run_from_saved_data(repo: Path, python: str, data: Path, dest: Path, log: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    _vms(repo, python, log, "validate-data", "--input", str(data), "--as-of", ASOF, "--ticker", TICKER)
    _vms(repo, python, log, "build-snapshot", "--input", str(data), "--ticker", TICKER,
         "--as-of", ASOF, "--out", str(dest / "snap"))
    _vms(repo, python, log, "estimate", "--input", str(data), "--ticker", TICKER,
         "--as-of", ASOF, "--out", str(dest / "est"), "--seed", SEED)
    _vms(repo, python, log, "simulate", "--input", str(data), "--ticker", TICKER,
         "--as-of", ASOF, "--out", str(dest / "sim"), "--paths", PATHS_SIM, "--years", "3", "--seed", SEED)
    _vms(repo, python, log, "project-paths", "--input", str(data), "--ticker", TICKER,
         "--as-of", ASOF, "--out", str(dest / "fp"), "--paths", PATHS_FP, "--years", "3", "--seed", SEED)
    _vms(repo, python, log, "value", "--input", str(data), "--ticker", TICKER,
         "--as-of", ASOF, "--out", str(dest / "val"), "--paths", PATHS_VAL, "--years", "3", "--seed", SEED)
    _vms(repo, python, log, "returns", "--input", str(data), "--ticker", TICKER,
         "--as-of", ASOF, "--out", str(dest / "ret"), "--paths", PATHS_RET, "--years", "3",
         "--horizons", "1,3", "--seed", SEED)
    _vms(repo, python, log, "sensitivity", "--input", str(data), "--ticker", TICKER,
         "--as-of", ASOF, "--out", str(dest / "sens"), "--paths", PATHS_SENS, "--years", "3", "--seed", SEED)
    _vms(repo, python, log, "evaluate", "--universe", str(repo / "config" / "universe.synthetic.yaml"),
         "--start", "2018-01-01", "--end", "2022-12-31", "--out", str(dest / "eval"))


def _flatten(obj, prefix: str = ""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten(value, path)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _flatten(value, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def forecast_non_timestamp_diffs(path1: Path, path2: Path) -> list[str]:
    a = dict(_flatten(json.loads(path1.read_text(encoding="utf-8"))))
    b = dict(_flatten(json.loads(path2.read_text(encoding="utf-8"))))
    diffs = []
    for key in sorted(set(a) | set(b)):
        if a.get(key) != b.get(key) and key != EVAL_TIMESTAMP_FIELD:
            diffs.append(key)
    return diffs


def compare_runs(run1: Path, run2: Path) -> dict:
    cmp: dict = {"matched": {}, "differed": {}, "only_in_run1": {}, "only_in_run2": {}}
    hashes1 = {part: sha_tree(run1 / part) for part in PIPELINE_PARTS}
    hashes2 = {part: sha_tree(run2 / part) for part in PIPELINE_PARTS}
    for part in PIPELINE_PARTS:
        a, b = hashes1[part], hashes2[part]
        keys = set(a) | set(b)
        matched, differed, only1, only2 = [], [], [], []
        for key in sorted(keys):
            if key not in b:
                only1.append(key)
            elif key not in a:
                only2.append(key)
            elif a[key] == b[key]:
                matched.append(key)
            else:
                differed.append({"path": key, "run1": a[key], "run2": b[key]})
        cmp["matched"][part] = matched
        cmp["differed"][part] = differed
        cmp["only_in_run1"][part] = only1
        cmp["only_in_run2"][part] = only2
    cmp["hashes1"] = hashes1
    cmp["hashes2"] = hashes2
    return cmp


def official_asserts(run1: Path) -> dict:
    required = ["demo", *PIPELINE_PARTS]
    missing = [name for name in required if not (run1 / name).exists()]
    if missing:
        raise AssertionError(f"missing run-bundle parts: {missing}")
    ret = json.loads((run1 / "ret" / "return_distribution_summary.json").read_text(encoding="utf-8"))
    ev = json.loads((run1 / "eval" / "evaluation_report.json").read_text(encoding="utf-8"))
    labels = ev["labels"]
    if not str(ret.get("schema_version", "")).startswith("vms-0.2"):
        raise AssertionError(f"unexpected returns schema_version: {ret.get('schema_version')}")
    if labels.get("investment_value") != "INVESTMENT_VALUE_NOT_ESTABLISHED":
        raise AssertionError(f"investment_value={labels.get('investment_value')}")
    if labels.get("pass_claim_authorized") is True:
        raise AssertionError("synthetic smoke must not authorize a PASS claim")
    return {
        "return_schema_version": ret.get("schema_version"),
        "eval_schema_version": ev.get("schema_version"),
        "labels": labels,
        "release_gates": ev.get("release_gates") or labels.get("release_gates"),
        "note": (
            "evaluation_report ENGINEERING_PASS, if present, is a run-level "
            "label for this synthetic evaluate, not a repository ENGINEERING_ACCEPTED verdict."
        ),
    }


def run_smoke(repo: Path, out: Path, python: str | None = None) -> dict:
    python = python or sys.executable
    out.mkdir(parents=True, exist_ok=True)
    log = out / "commands_stdout.txt"
    run1 = out / "run1"
    run2 = out / "run2"
    _vms(repo, python, log, "demo", "--out", str(run1 / "demo"), "--seed", SEED,
         "--paths", DEMO_PATHS, "--as-of", ASOF)
    data = run1 / "demo" / "data"
    if not data.is_dir():
        raise AssertionError(f"demo did not write data directory: {data}")
    run_from_saved_data(repo, python, data, run1, log)
    run_from_saved_data(repo, python, data, run2, log)
    asserts = official_asserts(run1)
    cmp = compare_runs(run1, run2)
    summary = {
        "pipeline": (
            "scripts/e2e_offline_demo.sh production CLI path "
            "(demo data → validate-data → build-snapshot → estimate → simulate "
            "→ project-paths → value → returns → sensitivity → evaluate)"
        ),
        "demo_paths": int(DEMO_PATHS),
        "note_demo_paths": (
            "Official script omits --paths on demo; config default_paths is 10000. "
            "Smoke uses explicit 40 to bound the data-generation step; later path "
            "counts match the official script."
        ),
        "ticker": TICKER,
        "as_of": ASOF,
        "seed": int(SEED),
        "asserts": asserts,
        "replay_from": str(data),
        "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
        "replay_comparison": {
            "n_matched": {k: len(v) for k, v in cmp["matched"].items()},
            "n_differed": {k: len(v) for k, v in cmp["differed"].items()},
            "differed": cmp["differed"],
            "only_in_run1": cmp["only_in_run1"],
            "only_in_run2": cmp["only_in_run2"],
        },
    }
    (out / "run1_sha256.json").write_text(json.dumps(cmp["hashes1"], indent=2, sort_keys=True) + "\n")
    (out / "run2_sha256.json").write_text(json.dumps(cmp["hashes2"], indent=2, sort_keys=True) + "\n")
    slim = {k: cmp[k] for k in ("matched", "differed", "only_in_run1", "only_in_run2")}
    (out / "replay_comparison.json").write_text(json.dumps(slim, indent=2, sort_keys=True) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
    return {"summary": summary, "comparison": cmp, "run1": run1, "run2": run2, "data": data}


def assert_replay_acceptable(run1: Path, run2: Path, cmp: dict) -> None:
    for part in ("snap", "est", "sim", "fp", "val", "ret", "sens"):
        assert cmp["differed"][part] == [], f"{part} hashes changed on replay: {cmp['differed'][part]}"
        assert cmp["only_in_run1"][part] == [] and cmp["only_in_run2"][part] == []
    assert "evaluation_report.json" in cmp["matched"]["eval"]
    leftover = []
    for row in cmp["differed"]["eval"]:
        rel = row["path"]
        diffs = forecast_non_timestamp_diffs(run1 / "eval" / rel, run2 / "eval" / rel)
        if diffs:
            leftover.append({rel: diffs})
    assert leftover == [], f"evaluate replay differed beyond {EVAL_TIMESTAMP_FIELD}: {leftover}"


if __name__ == "__main__":
    repo = Path(os.environ.get("E01_REPO") or Path(__file__).resolve().parents[2])
    out = Path(os.environ.get("E01_OUT") or "/tmp/e01_offline_e2e_smoke")
    result = run_smoke(repo, out)
    assert_replay_acceptable(result["run1"], result["run2"], result["comparison"])
    print(json.dumps({
        "ok": True,
        "summary_path": str(out / "summary.json"),
        "n_differed": {k: len(v) for k, v in result["comparison"]["differed"].items()},
    }, indent=2, sort_keys=True))
