"""Offline, fail-closed gate for the demo's keyword-based agent comparison."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


POLICY_KEYS = {
    "min_pass_rate", "max_pass_rate_drop", "max_avg_latency_s",
    "max_total_tokens", "max_total_retries", "required_queries",
}


def number(value, name, *, minimum=0, maximum=None, integer=False):
    valid_type = type(value) is int if integer else type(value) in (int, float)
    if not valid_type or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be a finite {'integer' if integer else 'number'} >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}.")
    return value


def evaluate(results, dataset, baseline, candidate, policy):
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise ValueError(f"Policy must contain exactly: {', '.join(sorted(POLICY_KEYS))}.")
    for key in ("min_pass_rate", "max_pass_rate_drop"):
        number(policy[key], key, maximum=1)
    number(policy["max_avg_latency_s"], "max_avg_latency_s", minimum=0.001)
    number(policy["max_total_tokens"], "max_total_tokens", minimum=1, integer=True)
    number(policy["max_total_retries"], "max_total_retries", integer=True)
    required = policy["required_queries"]
    if not isinstance(required, list) or not required or not all(isinstance(q, str) and q.strip() for q in required):
        raise ValueError("required_queries must be a non-empty list of query strings.")
    if not isinstance(candidate, dict) or not all(
        isinstance(candidate.get(key), str) and candidate[key].strip()
        for key in ("name", "version", "model")
    ):
        raise ValueError("Candidate must contain non-empty name, version, and model strings.")
    version = candidate["version"]
    if not all(isinstance(v, str) and re.fullmatch(r"[1-9]\d*", v) for v in (baseline, version)):
        raise ValueError("Baseline and candidate versions must be positive integer strings.")
    if baseline == version:
        raise ValueError("Baseline and candidate must be different versions of the same agent.")
    if not isinstance(dataset, list) or not dataset:
        raise ValueError("Dataset must contain at least one case.")
    queries = []
    for row in dataset:
        if not isinstance(row, dict) or not isinstance(row.get("query"), str) or not row["query"].strip():
            raise ValueError("Every dataset case needs a non-empty query.")
        terms = row.get("must_include")
        if not isinstance(terms, list) or not terms or not all(isinstance(t, str) and t.strip() for t in terms):
            raise ValueError(f"Dataset case {row['query']!r} needs non-empty must_include strings.")
        queries.append(row["query"])
    if len(set(queries)) != len(queries):
        raise ValueError("Dataset queries must be unique.")
    if not set(required).issubset(queries):
        raise ValueError("Every required query must exist in the evaluation dataset.")
    if not isinstance(results, list) or len(results) != len(dataset):
        raise ValueError("Comparison must cover every dataset case exactly once.")

    metrics = {}
    required_passes = {}
    for target in (baseline, version):
        passed, latency, tokens, retries = 0, 0.0, 0, 0
        required_passes[target] = {}
        for result, case in zip(results, dataset, strict=True):
            if not isinstance(result, dict) or set(result) != {"query", baseline, version}:
                raise ValueError("Comparison rows must contain only query and the two exact version keys.")
            if result["query"] != case["query"]:
                raise ValueError("Comparison queries must match the pinned dataset in order.")
            observation = result[target]
            if not isinstance(observation, dict) or not isinstance(observation.get("answer"), str):
                raise ValueError(f"Version {target} has a missing or invalid answer.")
            expected = all(term.lower() in observation["answer"].lower() for term in case["must_include"])
            if type(observation.get("pass")) is not bool or observation["pass"] != expected:
                raise ValueError(f"Version {target} has an invalid keyword score.")
            latency += number(observation.get("latency_s"), f"v{target} latency_s")
            tokens += number(observation.get("tokens"), f"v{target} tokens", minimum=1, integer=True)
            retries += number(observation.get("retries"), f"v{target} retries", integer=True)
            passed += int(expected)
            if case["query"] in required:
                required_passes[target][case["query"]] = expected
        metrics[target] = {
            "passed": passed, "total": len(dataset), "pass_rate": passed / len(dataset),
            "avg_latency_s": latency / len(dataset), "total_tokens": tokens, "total_retries": retries,
        }

    current, previous = metrics[version], metrics[baseline]
    failures = []
    if current["pass_rate"] < policy["min_pass_rate"]:
        failures.append("Candidate keyword pass rate is below the minimum.")
    if previous["pass_rate"] - current["pass_rate"] > policy["max_pass_rate_drop"]:
        failures.append("Candidate keyword pass rate regressed beyond the permitted drop.")
    if current["avg_latency_s"] > policy["max_avg_latency_s"]:
        failures.append("Candidate average latency exceeds the limit.")
    if current["total_tokens"] > policy["max_total_tokens"]:
        failures.append("Candidate reported token total exceeds the limit.")
    if any(m["total_retries"] > policy["max_total_retries"] for m in metrics.values()):
        failures.append("Retry count exceeds the limit; the comparison is not clean.")
    if not all(required_passes[version].values()):
        failures.append("Candidate failed a required keyword case.")
    return {
        "status": "failed" if failures else "passed",
        "scoring": "demo-keyword-v1",
        "agent": candidate["name"], "model": candidate["model"],
        "baseline_version": baseline, "candidate_version": version,
        "metrics": metrics, "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("results", "dataset", "candidate", "policy", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--revision", required=True, help="Full 40-character source commit SHA")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be a full lowercase 40-character commit SHA")
    inputs = {key: getattr(args, key).read_bytes() for key in ("results", "dataset", "candidate", "policy")}
    try:
        dataset = [json.loads(line) for line in inputs["dataset"].decode().splitlines() if line.strip()]
        report = evaluate(
            json.loads(inputs["results"]), dataset, args.baseline,
            json.loads(inputs["candidate"]), json.loads(inputs["policy"]),
        )
    except ValueError as error:
        parser.error(str(error))
    report["source_revision"] = args.revision
    report["inputs_sha256"] = {key: hashlib.sha256(value).hexdigest() for key, value in inputs.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"Agent release gate: {report['status']}; evidence: {args.output}")
    for failure in report["failures"]:
        print(f"- {failure}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
