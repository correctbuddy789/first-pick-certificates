#!/usr/bin/env python3
"""Build the public analysis archive and verify it after fresh extraction.

Only explicitly listed files and explicitly selected result fields are released.
No applicant records, private loaders, candidate traces, or review notes enter
the archive. Repackaging an extracted public archive needs no private inputs.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
TITLE = "When Can a Ranking Audit Stop? Certifying First Picks with Unresolved Eligibility"
PUBLIC_RESULTS = "public-aggregate-results.json"
MANIFEST = "package-manifest.json"
ARCHIVE = "reproducibility.zip"

PAYLOAD_FILES = (
    "README.md",
    "VERSION",
    "CITATION.cff",
    "CHANGELOG.md",
    "LICENSING.md",
    "LICENSE-MIT.txt",
    "LICENSE-CC-BY-4.0.txt",
    "MAINTENANCE.md",
    "USAGE.md",
    "REUSE.md",
    "BENCHMARK.md",
    "benchmark_runner.py",
    "verify_benchmark_runner.py",
    "benchmark-runner-checks.json",
    "policy_explanation.py",
    "policy-explanation.json",
    "policy-explanation.csv",
    "policy-explanation.md",
    "matched-relevance-design.json",
    "matched-relevance-design.md",
    "matched-relevance-results.json",
    "matched-relevance-results.csv",
    "matched-relevance-results.md",
    "BUDGET.md",
    "budget_study.py",
    "budget_design.json",
    "budget-design.md",
    "budget-results.json",
    "budget-results.csv",
    "budget-checks.json",
    "figures/budgeted-acquisition.pdf",
    "figures/budgeted-acquisition.png",
    "panel_io.py",
    "policy_runner.py",
    "reuse_demo.py",
    "verify_reuse.py",
    "examples/cost_sensitive_policy.py",
    "examples/open_resources/panel.json",
    "examples/open_resources/panel-csv.json",
    "examples/open_resources/panel-unavailable.json",
    "examples/open_resources/tiers.csv",
    "examples/open_resources/responses-negative.json",
    "examples/open_resources/responses-positive.json",
    "examples/open_resources/responses-nonanswer.json",
    "examples/open_resources/responses-unavailable.json",
    "examples/open_resources/expected-results.json",
    "dnf_baselines.py",
    "verify_dnf_baselines.py",
    "benchmark_extensions.py",
    "extension-design.json",
    "extension-design.md",
    "extension-results.json",
    "extension-results.csv",
    "extension-checks.json",
    "walkthrough.py",
    "package_artifacts.py",
    "certificates.py",
    "query_policies.py",
    "verify_methods.py",
    "verify_policies.py",
    "verification.json",
    "policy-verification.json",
    PUBLIC_RESULTS,
    "stress-results.json",
    "target-sensitivity.json",
    "computational_design.json",
    "computational-design.md",
    "computational_study.py",
    "computational-results.json",
    "computational-results.csv",
    "computational-checks.json",
    "make_figures.py",
    "figures/certification-and-queries.pdf",
    "figures/certification-and-queries.png",
)
INPUT_HASH_PATHS = (
    "pilot/data/export-20260826.json",
    "pilot/data/den_ranks.json",
)
PRIVATE_INPUT_PATHS = (*INPUT_HASH_PATHS, "pilot/data/bm25_ranks.json")
PRIVATE_MODULE_PATHS = (
    "paper/decision-certificates/analyze_certificates.py",
    "paper/decision-certificates/stress_analysis.py",
    "paper/decision-certificates/analyze_target_sensitivity.py",
    "pilot/scripts/analyze.py",
    "pilot/scripts/sensitivity.py",
)
SUMMARY_FIELDS = (
    "requisitions",
    "candidate_pairs",
    "initial_unknown",
    "historical_binary_answers",
    "initial_certified",
    "final_certified",
    "retrospective_minimum_queries_for_certified",
    "all_completion_count",
    "initial_mean_membership_bounds",
    "final_mean_membership_bounds",
    "random_order_expected_queries",
)
ROW_FIELDS = (
    "requisition",
    "n_candidates",
    "n_initial_unknown",
    "n_recorded_binary",
    "n_still_unresolved",
    "initial_possible_outcomes",
    "final_possible_outcomes",
    "certificate_size",
    "n_completions",
    "n_completion_hits",
    "random_order_expected_queries",
)
POLICY_NAMES = ("pick_then_blockers", "candidate_order")
POLICY_FIELDS = ("queries", "unresolved_answers", "certified", "possible_outcomes")
FORBIDDEN_KEYS = {
    "certificate_indices", "query_indices", "pick_initial_state",
    "pick_observed_state", "candidate_id", "cand_id", "candidates",
    "tiers", "observed", "positive", "negative", "blockers",
}


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def select_fields(record, fields):
    return {field: record[field] for field in fields}


def check_no_private_fields(value):
    if isinstance(value, dict):
        forbidden = FORBIDDEN_KEYS.intersection(value)
        if forbidden:
            raise ValueError(f"Private fields in public results: {sorted(forbidden)}")
        for child in value.values():
            check_no_private_fields(child)
    elif isinstance(value, list):
        for child in value:
            check_no_private_fields(child)


def public_results(source):
    """Whitelist aggregate fields; do not recursively copy arbitrary source keys."""
    summary = select_fields(source["summary"], SUMMARY_FIELDS)
    for field in ("policy_queries", "policy_unresolved_answers"):
        summary[field] = select_fields(source["summary"][field], POLICY_NAMES)
    rows = []
    for original in source["rows"]:
        row = select_fields(original, ROW_FIELDS)
        if not re.fullmatch(r"[ep][1-5]", row["requisition"]):
            raise ValueError("Unexpected requisition code in public report")
        row["policies"] = {
            policy: select_fields(original["policies"][policy], POLICY_FIELDS)
            for policy in POLICY_NAMES
        }
        for field in ("optimal_binary_worst_case_queries", "tree_states"):
            if field in original:
                row[field] = original[field]
        rows.append(row)
    if len(rows) != summary["requisitions"]:
        raise ValueError("Public requisition count does not match its summary")
    hashes = select_fields(source["input_sha256"], INPUT_HASH_PATHS)
    if not all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in hashes.values()):
        raise ValueError("Invalid recorded input digest")
    result = {
        "analysis": "Exploratory secondary analysis; no new human judgments or model runs",
        "target": "Membership of the fixed first pick in the mechanically defined majority top set; empty or no-majority sets have membership zero",
        "release_scope": "Aggregate and per-requisition decision/count outputs only; no candidate indices, query traces, individual eligibility states, or raw judgments",
        "summary": summary,
        "rows": rows,
        "input_sha256": hashes,
    }
    check_no_private_fields(result)
    return result


def write_archive(payload):
    """Use stable relative paths, timestamps, and regular-file permissions."""
    path = HERE / ARCHIVE
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            member = PurePosixPath(name)
            if member.is_absolute() or ".." in member.parts:
                raise ValueError(f"Unsafe archive path: {name}")
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            mode = 0o755 if name.endswith(".py") and data.startswith(b"#!") else 0o644
            entry.external_attr = (stat.S_IFREG | mode) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return path


def verify_archive(path, payload):
    """Check exact contents, then execute without repository or site-package imports."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(payload):
            raise ValueError("Archive contents do not match the explicit payload")
        if archive.testzip() is not None:
            raise ValueError("Archive CRC check failed")
        for name, expected in payload.items():
            if archive.read(name) != expected:
                raise ValueError(f"Archive bytes differ for {name}")
        with tempfile.TemporaryDirectory(prefix="decision-certificates-check-") as temporary:
            root = Path(temporary)
            archive.extractall(root)
            verified = {}
            for script, recorded in (("verify_methods.py", "verification.json"),
                                     ("verify_policies.py", "policy-verification.json")):
                output = "rerun-" + recorded
                subprocess.run(
                    [sys.executable, "-E", "-S", script, "--out", output],
                    cwd=root, check=True, capture_output=True, text=True,
                )
                expected = json.loads((root / recorded).read_text())
                actual = json.loads((root / output).read_text())
                expected.pop("elapsed_seconds", None)
                actual.pop("elapsed_seconds", None)
                if actual != expected or actual.get("result") != "PASS":
                    raise ValueError(f"Fresh-extraction {script} differs from recorded checks")
                verified[script] = actual
            subprocess.run(
                [sys.executable, "-E", "-S", "computational_study.py", "--verify-only",
                 "--checks-out", "rerun-computational-checks.json"],
                cwd=root, check=True, capture_output=True, text=True,
            )
            checks = json.loads((root / "rerun-computational-checks.json").read_text())
            if checks.get("passed") is not True:
                raise ValueError("Fresh-extraction computational checks failed")
            verified["computational_study.py"] = checks
            subprocess.run(
                [sys.executable, "-E", "-S", "verify_dnf_baselines.py", "--out",
                 "rerun-extension-checks.json"],
                cwd=root, check=True, capture_output=True, text=True,
            )
            extension_checks = json.loads((root / "rerun-extension-checks.json").read_text())
            if extension_checks != json.loads((root / "extension-checks.json").read_text()):
                raise ValueError("Fresh-extraction comparator checks differ")
            verified["verify_dnf_baselines.py"] = extension_checks
            subprocess.run(
                [sys.executable, "-E", "-S", "benchmark_extensions.py", "--verify-stored"],
                cwd=root, check=True, capture_output=True, text=True,
            )
            verified["benchmark_extensions.py"] = "Stored hashes, summaries and original-policy totals verified"
            subprocess.run(
                [sys.executable, "-E", "-S", "verify_reuse.py", "--out",
                 "rerun-reuse-checks.json"],
                cwd=root, check=True, capture_output=True, text=True,
            )
            reuse_checks = json.loads((root / "rerun-reuse-checks.json").read_text())
            if reuse_checks.get("passed") is not True:
                raise ValueError("Fresh-extraction reuse checks failed")
            verified["verify_reuse.py"] = reuse_checks
            for script, args in (
                ("verify_benchmark_runner.py", []),
                ("policy_explanation.py", ["--verify-stored"]),
                ("budget_study.py", ["--verify-stored"]),
            ):
                subprocess.run([sys.executable, "-E", "-S", script, *args],
                               cwd=root, check=True, capture_output=True, text=True)
                verified[script] = "PASS: independent interface or stored-output checks"
            runner_record = json.loads((root / "benchmark-runner-checks.json").read_text())
            for name, digest in runner_record["sources"].items():
                if sha256((root / name).read_bytes()) != digest:
                    raise ValueError(f"Shared-runner source changed after full check: {name}")
            for name, digest in runner_record["equivalence"]["protected_extension_sha256"].items():
                if sha256((root / name).read_bytes()) != digest:
                    raise ValueError(f"Protected comparator file changed: {name}")
    return verified


def main():
    source = HERE / "results.json"
    if not source.is_file():
        source = HERE / PUBLIC_RESULTS
    report = public_results(json.loads(source.read_text()))
    (HERE / PUBLIC_RESULTS).write_bytes(json_bytes(report))

    payload = {name: (HERE / name).read_bytes() for name in PAYLOAD_FILES}
    stress = json.loads(payload["stress-results.json"])
    if stress["input_sha256"] != report["input_sha256"]:
        raise ValueError("Empirical and stress outputs have different frozen input hashes")
    manifest = {
        "schema_version": 3,
        "version": (HERE / "VERSION").read_text().strip(),
        "title": TITLE,
        "archive": ARCHIVE,
        "scope": "Standalone certificate operations, tier-file and policy interface, synthetic reuse application, original and extended acquisition benchmarks, matched filtering, budgeted acquisition, independent verification, aggregate empirical outputs, and figure generation",
        "resource_url": "https://github.com/correctbuddy789/first-pick-certificates/releases/tag/v" + (HERE / "VERSION").read_text().strip(),
        "licensing": "MIT for code; CC BY 4.0 for documentation, synthetic inputs/outputs, figures and publishable aggregates; see LICENSING.md",
        "tested_python": platform.python_version(),
        "core_dependencies": "Python standard library",
        "optional_figure_dependency": "matplotlib",
        "empirical_replay_standalone": False,
        "restricted_replay_inputs_not_included": list(PRIVATE_INPUT_PATHS),
        "restricted_replay_modules_not_included": list(PRIVATE_MODULE_PATHS),
        "recorded_input_sha256": report["input_sha256"],
        "digest_scope": "All archive payload files except this manifest itself",
        "files": [
            {"path": name, "bytes": len(data), "sha256": sha256(data)}
            for name, data in sorted(payload.items())
        ],
    }
    manifest_data = json_bytes(manifest)
    (HERE / MANIFEST).write_bytes(manifest_data)
    payload[MANIFEST] = manifest_data
    archive = write_archive(payload)
    verification = verify_archive(archive, payload)
    print(json.dumps({
        "result": "PASS: allowlisted archive checked; standalone verification passed after fresh extraction",
        "archive": archive.name,
        "archive_entries": len(payload),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256(archive.read_bytes()),
        "public_results": PUBLIC_RESULTS,
        "manifest": MANIFEST,
        "verification": verification,
    }, indent=2))


if __name__ == "__main__":
    main()
