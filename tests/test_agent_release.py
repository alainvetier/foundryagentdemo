import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import yaml


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples/agent-lifecycle"
SPEC = importlib.util.spec_from_file_location("agent_release", ROOT / "scripts/check-agent-release.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class AgentReleaseTests(unittest.TestCase):
    def setUp(self):
        self.dataset = [
            json.loads(line) for line in (ROOT / "data/eval/whisker-eval.jsonl").read_text().splitlines()
            if line.strip()
        ]
        self.policy = json.loads((SAMPLES / "gate-policy.json").read_text())
        self.candidate = {"name": "whiskers-concierge-pro-release", "version": "9", "model": "gpt-5-mini"}
        self.results = []
        for case in self.dataset:
            observation = {
                "answer": " ".join(case["must_include"]), "pass": True,
                "latency_s": 1.0, "tokens": 100, "retries": 0,
            }
            self.results.append({"query": case["query"], "7": copy.deepcopy(observation), "9": observation})

    def evaluate(self):
        return gate.evaluate(self.results, self.dataset, "7", self.candidate, self.policy)

    def fail_case(self, index, versions=("9",)):
        for version in versions:
            self.results[index][version].update(answer="No matching evidence.", **{"pass": False})

    def test_exact_seven_of_eight_passes_and_six_of_eight_fails(self):
        self.fail_case(0, ("7", "9"))
        report = self.evaluate()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["metrics"]["9"]["pass_rate"], 0.875)
        self.fail_case(1, ("7", "9"))
        report = self.evaluate()
        self.assertEqual(report["status"], "failed")
        self.assertIn("Candidate keyword pass rate is below the minimum.", report["failures"])

    def test_regression_fails_even_when_absolute_threshold_passes(self):
        self.fail_case(0)
        self.assertIn("regressed", " ".join(self.evaluate()["failures"]))

    def test_required_case_failure_cannot_hide_behind_aggregate_pass_rate(self):
        self.fail_case(6, ("7", "9"))
        report = self.evaluate()
        self.assertEqual(report["metrics"]["9"]["pass_rate"], 0.875)
        self.assertIn("Candidate failed a required keyword case.", report["failures"])

    def test_latency_tokens_and_retries_enforce_inclusive_limits(self):
        for result in self.results:
            result["9"].update(latency_s=60, tokens=2500)
        self.assertEqual(self.evaluate()["status"], "passed")
        for field, value, message in (
            ("latency_s", 60.01, "latency"), ("tokens", 2501, "token"),
            ("retries", 1, "Retry"),
        ):
            with self.subTest(field=field):
                original = self.results[0]["9"][field]
                self.results[0]["9"][field] = value
                self.assertIn(message, " ".join(self.evaluate()["failures"]))
                self.results[0]["9"][field] = original
        self.results[0]["7"]["retries"] = 1
        self.assertEqual(self.evaluate()["status"], "failed")

    def test_missing_invalid_or_fabricated_evidence_is_rejected(self):
        mutations = [
            lambda: self.results.pop(),
            lambda: self.results.reverse(),
            lambda: self.results[0].pop("9"),
            lambda: self.results[0].update({"latest": self.results[0]["9"]}),
            lambda: self.results[0]["9"].update(tokens=None),
            lambda: self.results[0]["9"].update(tokens=True),
            lambda: self.results[0]["9"].update(latency_s=float("nan")),
            lambda: self.results[0]["9"].update(latency_s=-1),
            lambda: self.results[0]["9"].update(retries="0"),
            lambda: self.results[0]["9"].update(**{"pass": "true"}),
            lambda: self.results[0]["9"].update(answer="fabricated success", **{"pass": True}),
            lambda: self.dataset[0].update(must_include=[]),
            lambda: self.dataset[0].update(must_include=[""]),
            lambda: self.dataset[1].update(query=self.dataset[0]["query"]),
            lambda: self.policy.update(required_queries=["Missing safety case"]),
            lambda: self.policy.update(min_pass_rate=1.1),
            lambda: self.policy.update(max_avg_latency_s=float("inf")),
            lambda: self.policy.update(max_total_tokens=True),
            lambda: self.policy.update(unrecognized_threshold=0),
            lambda: self.candidate.update(version="7"),
            lambda: self.candidate.update(name=""),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.setUp()
                mutate()
                with self.assertRaises(ValueError):
                    self.evaluate()
        with self.assertRaises(ValueError):
            gate.evaluate([], [], "7", self.candidate, self.policy)

    def test_cli_writes_lineage_and_returns_failure_on_a_failed_gate(self):
        for passes in (True, False):
            with self.subTest(passes=passes), TemporaryDirectory() as directory:
                root = Path(directory)
                if not passes:
                    self.fail_case(6, ("7", "9"))
                payloads = {
                    "results": json.dumps(self.results),
                    "dataset": "\n".join(json.dumps(case) for case in self.dataset),
                    "candidate": json.dumps(self.candidate), "policy": json.dumps(self.policy),
                }
                arguments = ["check-agent-release.py", "--baseline", "7", "--revision", "a" * 40]
                for name, payload in payloads.items():
                    target = root / f"{name}.json"
                    target.write_text(payload)
                    arguments.extend([f"--{name}", str(target)])
                output = root / "nested/gate.json"
                arguments.extend(["--output", str(output)])
                with patch.object(sys, "argv", arguments), patch("builtins.print"):
                    self.assertEqual(gate.main(), 0 if passes else 1)
                report = json.loads(output.read_text())
                self.assertEqual(report["candidate_version"], "9")
                self.assertEqual(report["baseline_version"], "7")
                self.assertEqual(report["source_revision"], "a" * 40)
                self.assertEqual(report["inputs_sha256"], {
                    key: hashlib.sha256(value.encode()).hexdigest() for key, value in payloads.items()
                })


class LifecycleSampleTests(unittest.TestCase):
    def load(self, filename):
        return yaml.load((SAMPLES / filename).read_text(), Loader=yaml.BaseLoader)

    def test_samples_are_inactive_and_actions_are_pinned(self):
        for filename in ("pr-checks.yml", "release-agent.yml"):
            workflow = self.load(filename)
            self.assertIn("workflow_dispatch", workflow["on"])
            self.assertNotIn("pull_request_target", workflow["on"])
            for job in workflow["jobs"].values():
                self.assertIn("timeout-minutes", job)
                for step in job["steps"]:
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"^[\w/-]+@[0-9a-f]{40}$")
                    self.assertNotIn("continue-on-error", step)
            self.assertFalse((ROOT / ".github/workflows" / filename).exists())
        self.assertEqual(set(self.load("release-agent.yml")["on"]), {"workflow_dispatch"})

    def test_release_requires_evaluation_and_protected_approval_without_deployment(self):
        workflow = self.load("release-agent.yml")
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        candidate = workflow["jobs"]["candidate"]
        approval = workflow["jobs"]["approve-release-record"]
        self.assertEqual(candidate["needs"], "offline-checks")
        self.assertEqual(candidate["permissions"]["id-token"], "write")
        self.assertEqual(candidate["environment"], "agent-staging")
        self.assertEqual(approval["needs"], "candidate")
        self.assertEqual(approval["environment"], "agent-release-approval")
        self.assertNotIn("id-token", approval.get("permissions", {}))
        source = (SAMPLES / "release-agent.yml").read_text()
        self.assertIn('--output-json ../../release/candidate.json', source)
        self.assertIn('--a "$BASELINE_VERSION" --b "$CANDIDATE_VERSION"', source)
        self.assertNotIn("NEW_VERSION - 1", source)
        self.assertIn('report["promotion_status"] = "not_deployed"', source)
        self.assertEqual(source.count("python scripts/check-agent-release.py"), 2)

    def test_workflow_shell_and_embedded_python_syntax(self):
        for filename in ("pr-checks.yml", "release-agent.yml"):
            for job in self.load(filename)["jobs"].values():
                for step in job["steps"]:
                    if "run" not in step:
                        continue
                    with self.subTest(workflow=filename, step=step.get("name", step["run"][:50])):
                        subprocess.run(
                            ["bash", "-n"], input=step["run"], text=True,
                            check=True, capture_output=True,
                        )
                        for source in re.findall(r"python - <<'PY'\n(.*?)\nPY", step["run"], re.DOTALL):
                            compile(source, filename, "exec")

    def test_notebook_showcase_is_markdown_only_and_linked(self):
        notebook = json.loads((ROOT / "docs/whisker-works-demo-runbook.ipynb").read_text())
        cell = next(cell for cell in notebook["cells"] if cell["id"] == "agent-release-lifecycle")
        self.assertEqual(cell["cell_type"], "markdown")
        text = "".join(cell["source"])
        self.assertIn("do not run", text.lower())
        self.assertIn("not_deployed", text)
        self.assertIn("../samples/agent-lifecycle/release-agent.yml", text)
        navigation = "".join(next(c for c in notebook["cells"] if c["id"] == "navigation")["source"])
        self.assertIn("#agent-release-lifecycle-and-cicd", navigation)
        positions = {c["id"]: i for i, c in enumerate(notebook["cells"])}
        self.assertLess(positions["run-model-comparison"], positions["agent-release-lifecycle"])
        self.assertLess(positions["agent-release-lifecycle"], positions["topic-7"])
        self.assertFalse(any("check-agent-release.py" in "".join(c["source"])
                             for c in notebook["cells"] if c["cell_type"] == "code"))

    def test_pipeline_diagram_is_embedded_and_marks_future_rollout_separately(self):
        notebook = json.loads((ROOT / "docs/whisker-works-demo-runbook.ipynb").read_text())
        cell = next(cell for cell in notebook["cells"] if cell["id"] == "agent-release-lifecycle")
        filename = "agent-release-lifecycle.png"
        self.assertIn(f"(attachment:{filename})", "".join(cell["source"]))
        png = base64.b64decode(cell["attachments"][filename]["image/png"], validate=True)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(int.from_bytes(png[16:20], "big"), 1200)
        self.assertEqual(int.from_bytes(png[20:24], "big"), 1520)
        svg = ET.parse(ROOT / "docs/images/agent-release-lifecycle.svg").getroot()
        ns = {"s": "http://www.w3.org/2000/svg"}
        self.assertIsNotNone(svg.find("s:title", ns))
        self.assertIsNotNone(svg.find("s:desc", ns))
        labels = [text.text for text in svg.findall("s:text", ns)]
        steps = [text for text in labels if re.match(r"^[1-7]\. ", text)]
        self.assertEqual(len(steps), 7)
        self.assertIn("STOP: do not approve", labels)
        self.assertIn("STOP: keep current release", labels)
        self.assertIn("promotion_status: not_deployed", labels)
        self.assertIn("Future lifecycle: separate adapters, NOT implemented by the sample", labels)
        self.assertEqual(len(svg.findall("s:path[@class='future']", ns)), 2)
        for marker in svg.findall(".//s:marker", ns):
            self.assertEqual(marker.get("markerUnits"), "userSpaceOnUse")
            self.assertEqual(marker.get("markerWidth"), "8")
        self.assertIn("../../docs/images/agent-release-lifecycle.svg", (SAMPLES / "README.md").read_text())

    def test_documentation_links_resolve(self):
        for source in (SAMPLES / "README.md", ROOT / "docs/08-change-model-safely.md"):
            for link in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", source.read_text()):
                if not link.startswith(("http://", "https://", "#")):
                    self.assertTrue((source.parent / link.split("#")[0]).exists(), link)


if __name__ == "__main__":
    unittest.main()
import base64
