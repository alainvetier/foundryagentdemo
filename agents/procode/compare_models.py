"""Side-by-side comparison of two agent versions (e.g. gpt-4.1-mini vs gpt-5-mini) on the eval set.

A lightweight "eval-lite" for the demo; use Foundry Evaluations for the formal version.

Usage:
    python compare_models.py --a 1 --b 2
"""
import argparse
import json
import os
import pathlib
import sys
import time
from datetime import datetime

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from openai import BadRequestError, RateLimitError

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE / "../../src/catstore-api"))
from foundry_errors import throttle_retry_delay

load_dotenv(HERE / ".env")


def run(openai, agent: str, version: str, query: str, max_retries: int = 5) -> dict:
    start = time.perf_counter()
    for attempt in range(max_retries + 1):
        try:
            response = openai.responses.create(
                input=query,
                extra_body={"agent_reference": {"name": agent, "version": version, "type": "agent_reference"}},
            )
            break
        except (BadRequestError, RateLimitError) as error:
            delay = throttle_retry_delay(error, attempt)
            if delay is None or attempt == max_retries:
                if delay is not None:
                    print(f"v{version}: throttling persisted after {max_retries} retries; comparison stopped.",
                          file=sys.stderr)
                raise
            print(f"v{version}: rate limited; retry {attempt + 1}/{max_retries} in {delay:g}s.",
                  file=sys.stderr, flush=True)
            time.sleep(delay)
    return {
        "answer": response.output_text,
        "latency_s": round(time.perf_counter() - start, 2),
        "tokens": response.usage.total_tokens if response.usage else None,
        "retries": attempt,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="whiskers-concierge-pro")
    parser.add_argument("--a", required=True, help="Baseline version")
    parser.add_argument("--b", required=True, help="Candidate version")
    parser.add_argument("--dataset", default=str(HERE / "../../data/eval/whisker-eval.jsonl"))
    parser.add_argument("--output", type=pathlib.Path, help="Write results to an explicit path for CI/CD")
    parser.add_argument("--max-retries", type=int, default=5, help="Retries per query/version for rate limiting (default: 5)")
    args = parser.parse_args()
    if args.max_retries < 0:
        parser.error("--max-retries must be non-negative")

    project = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], credential=DefaultAzureCredential())
    openai = project.get_openai_client()
    rows = [json.loads(line) for line in pathlib.Path(args.dataset).read_text().splitlines() if line.strip()]

    results, totals = [], {args.a: [0, 0.0, 0], args.b: [0, 0.0, 0]}
    for row in rows:
        entry = {"query": row["query"]}
        for v in (args.a, args.b):
            r = run(openai, args.agent, v, row["query"], max_retries=args.max_retries)
            r["pass"] = all(k.lower() in r["answer"].lower() for k in row["must_include"])
            entry[v] = r
            totals[v][0] += int(r["pass"])
            totals[v][1] += r["latency_s"]
            totals[v][2] += r["tokens"] or 0
        results.append(entry)
        print(f"- {row['query'][:60]:<60} v{args.a}:{'✅' if entry[args.a]['pass'] else '❌'}  v{args.b}:{'✅' if entry[args.b]['pass'] else '❌'}")

    print("\nversion | pass rate | avg latency (s) | total tokens")
    for v, (passed, lat, tok) in totals.items():
        print(f"v{v:<6} | {passed}/{len(rows):<7} | {lat / len(rows):<15.2f} | {tok}")

    out = args.output or HERE / "results" / f"compare-v{args.a}-v{args.b}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\nDetails: {out}")


if __name__ == "__main__":
    main()
