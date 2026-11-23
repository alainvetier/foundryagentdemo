import ast
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "docs" / "whisker-works-demo-runbook.ipynb"


class RunbookApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notebook = json.loads(NOTEBOOK.read_text())
        cls.sources = [
            "".join(cell["source"])
            for cell in cls.notebook["cells"]
            if cell["cell_type"] == "code"
        ]
        cls.helper = next(
            node
            for source in cls.sources
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "run_demo"
        )

    def setUp(self):
        self.subprocess = Mock()
        namespace = {
            "subprocess": self.subprocess,
            "shlex": shlex,
            "REPO_ROOT": ROOT,
        }
        exec(compile(ast.Module(body=[self.helper], type_ignores=[]), str(NOTEBOOK), "exec"), namespace)
        self.run_demo = namespace["run_demo"]

    def test_unapproved_command_fails_without_input_or_subprocess(self):
        for approval in ("", "WRONG"):
            with self.subTest(approval=approval), patch("builtins.input") as prompt:
                with self.assertRaisesRegex(ValueError, "Not run.*approval='CREATE_AGENT'"):
                    self.run_demo(["command"], confirmation="CREATE_AGENT", approval=approval)
                prompt.assert_not_called()
                self.subprocess.run.assert_not_called()

    def test_matching_approval_runs_command_without_input(self):
        with patch("builtins.input") as prompt, patch("builtins.print"):
            self.run_demo(
                ["command"], confirmation="CREATE_AGENT", approval="CREATE_AGENT",
                input_text="hello\n", env={"DEMO": "value"},
            )
        prompt.assert_not_called()
        self.subprocess.run.assert_called_once_with(
            ["command"], cwd=str(ROOT), env={"DEMO": "value"},
            input="hello\n", text=True, check=True,
        )

    def test_initialization_allows_fresh_checkout_without_settings_or_cloud_calls(self):
        source = next(
            "".join(cell["source"]) for cell in self.notebook["cells"]
            if cell["id"] == "initialize"
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/test-gateway.py").touch()
            for settings_exist in (False, True):
                if settings_exist:
                    (root / "agents/procode").mkdir(parents=True)
                    (root / "agents/procode/.env").touch()
                with self.subTest(settings_exist=settings_exist), \
                     patch("pathlib.Path.cwd", return_value=root), \
                     patch("os.chdir") as change_directory, \
                     patch("subprocess.run") as run, \
                     patch("builtins.print") as output:
                    namespace = {}
                    exec(compile(source, str(NOTEBOOK), "exec"), namespace)
                    self.assertTrue(callable(namespace["run_demo"]))
                    self.assertEqual(namespace["ENV_FILE"], root / "agents/procode/.env")
                    change_directory.assert_called_once_with(root)
                    run.assert_not_called()
                    expected = (
                        "Local settings file: present (contents hidden)" if settings_exist
                        else "Local settings file: missing. Run environment deployment before agent or gateway cells."
                    )
                    output.assert_any_call(expected)

    def test_every_gated_cell_has_explicit_valid_approval(self):
        gated_calls = 0
        for source in self.sources:
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id != "run_demo":
                    continue
                keywords = {kw.arg: kw.value for kw in node.keywords}
                if "confirmation" in keywords:
                    gated_calls += 1
                    self.assertIn("approval", keywords)
                    approval = ast.literal_eval(keywords["approval"])
                    if approval:
                        self.assertEqual(approval, ast.literal_eval(keywords["confirmation"]))
        self.assertGreater(gated_calls, 0)

    def test_learn_and_smoke_cells_are_self_contained_and_gated(self):
        cells = {cell["id"]: cell for cell in self.notebook["cells"]}
        create = "".join(cells["create-learn-guide"]["source"])
        smoke = "".join(cells["run-agent-mcp-validation"]["source"])
        self.assertIn('"--config", "learn-agent.yaml"', create)
        self.assertIn('"scripts/test-agent-mcp.py"', smoke)
        for source in (create, smoke):
            self.assertIn('approval=""', source)
        self.assertIn("include_orders_discovery = False", smoke)

    def test_live_creation_chat_and_comparison_use_returned_identity(self):
        cells = {cell["id"]: "".join(cell["source"]) for cell in self.notebook["cells"]}
        calls = []

        def run_command(arguments, **kwargs):
            arguments = [str(value) for value in arguments]
            calls.append(arguments)
            if arguments[1] == "create_agent.py":
                name = arguments[arguments.index("--name") + 1]
                candidate = "--model" in arguments
                result = {"name": name, "version": "9" if candidate else "7",
                          "model": "gpt-5-mini" if candidate else "gpt-4.1-mini"}
                Path(arguments[arguments.index("--output-json") + 1]).write_text(json.dumps(result))

        namespace = {
            "REPO_ROOT": ROOT, "Path": Path, "sys": sys, "json": json,
            "TemporaryDirectory": TemporaryDirectory, "run_demo": run_command,
            "procode_dir": ROOT / "agents/procode", "live_agent_name": "whiskers-concierge-pro-live",
        }
        with patch("builtins.print"), patch("builtins.input") as prompt:
            for cell_id in ("create-pro-agent", "create-new-model-version", "pro-agent-chat", "run-model-comparison"):
                exec(compile(cells[cell_id], str(NOTEBOOK), "exec"), namespace)
        prompt.assert_not_called()
        self.assertEqual(calls[2][1:], [
            "chat.py", "--agent", "whiskers-concierge-pro-live", "--version", "7",
        ])
        self.assertEqual(calls[3][1:], [
            "compare_models.py", "--agent", "whiskers-concierge-pro-live", "--a", "7", "--b", "9",
        ])
        for arguments in calls[:2]:
            self.assertFalse(Path(arguments[arguments.index("--output-json") + 1]).exists())

    def test_live_agent_cells_fail_explicitly_when_prerequisites_are_missing(self):
        cells = {cell["id"]: "".join(cell["source"]) for cell in self.notebook["cells"]}
        for cell_id in ("preview-pro-agent", "create-pro-agent", "pro-agent-chat",
                        "create-new-model-version", "run-model-comparison"):
            with self.subTest(cell=cell_id):
                with self.assertRaisesRegex(RuntimeError, "Run|Create"):
                    exec(compile(cells[cell_id], str(NOTEBOOK), "exec"), {})

    def test_comparison_rejects_mismatched_agents_or_identical_versions(self):
        source = next("".join(cell["source"]) for cell in self.notebook["cells"]
                      if cell["id"] == "run-model-comparison")
        for candidate in ({"name": "original-agent", "version": "2"},
                          {"name": "live-agent", "version": "1"}):
            with self.subTest(candidate=candidate):
                run_command = Mock()
                namespace = {
                    "baseline_agent": {"name": "live-agent", "version": "1"},
                    "candidate_agent": candidate, "run_demo": run_command,
                }
                with self.assertRaisesRegex(ValueError, "two different versions of the same live agent"):
                    exec(compile(source, str(NOTEBOOK), "exec"), namespace)
                run_command.assert_not_called()

    def test_failed_creation_clears_stale_notebook_targets(self):
        cells = {cell["id"]: "".join(cell["source"]) for cell in self.notebook["cells"]}
        for cell_id, result_key in (("create-pro-agent", "baseline_agent"),
                                    ("create-new-model-version", "candidate_agent")):
            with self.subTest(cell=cell_id):
                namespace = {
                    "REPO_ROOT": ROOT, "Path": Path, "sys": sys, "json": json,
                    "TemporaryDirectory": TemporaryDirectory,
                    "run_demo": Mock(side_effect=RuntimeError("creation failed")),
                    "procode_dir": ROOT / "agents/procode", "live_agent_name": "live-agent",
                    "baseline_agent": {"name": "live-agent", "version": "1"},
                    "candidate_agent": {"name": "live-agent", "version": "2"},
                }
                with self.assertRaisesRegex(RuntimeError, "creation failed"):
                    exec(compile(cells[cell_id], str(NOTEBOOK), "exec"), namespace)
                self.assertIsNone(namespace[result_key])
                self.assertIsNone(namespace["candidate_agent"])

    def test_hosted_prerequisites_verify_deployment_without_printing_credentials(self):
        source = next("".join(cell["source"]) for cell in self.notebook["cells"]
                      if cell["id"] == "hosted-agent-prerequisites")
        agent = {
            "name": "kernel-panic-ops", "version": "1", "status": "active",
            "definition": {"kind": "hosted", "environment_variables": {
                "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-4.1-mini",
                "APIM_GATEWAY_URL": "https://whisker.example",
                "APIM_SUBSCRIPTION_KEY": "test-key-not-for-display",
            }},
        }
        with TemporaryDirectory() as directory:
            Path(directory, "azure.yaml").touch()
            with patch.dict("os.environ", {"WHISKER_HOSTED_PROJECT": directory}), \
                 patch("subprocess.run", return_value=Mock(stdout=json.dumps(agent))) as run, \
                 patch("builtins.print") as output, patch("builtins.input") as prompt:
                namespace = {}
                exec(compile(source, str(NOTEBOOK), "exec"), namespace)
            self.assertTrue(namespace["hosted_agent_ready"])
            prompt.assert_not_called()
            run.assert_called_once_with(
                ["azd", "ai", "agent", "show", "kernel-panic-ops", "--output", "json"],
                cwd=str(Path(directory).resolve()), capture_output=True, text=True, check=True,
            )
            self.assertNotIn("test-key-not-for-display", str(output.call_args_list))

            for name, value in (("status", "failed"), ("name", "another-agent"),
                                ("definition", {"kind": "prompt"}),
                                ("definition", {"kind": "hosted", "environment_variables": {}})):
                with self.subTest(field=name, value=value), \
                     patch.dict("os.environ", {"WHISKER_HOSTED_PROJECT": directory}), \
                     patch("subprocess.run", return_value=Mock(stdout=json.dumps({**agent, name: value}))):
                    with self.assertRaises(RuntimeError):
                        exec(compile(source, str(NOTEBOOK), "exec"), namespace)
                    self.assertFalse(namespace["hosted_agent_ready"])

    def test_hosted_prerequisites_require_initialized_project(self):
        source = next("".join(cell["source"]) for cell in self.notebook["cells"]
                      if cell["id"] == "hosted-agent-prerequisites")
        with TemporaryDirectory() as directory, \
             patch.dict("os.environ", {"WHISKER_HOSTED_PROJECT": directory}), \
             patch("subprocess.run") as run:
            namespace = {"hosted_agent_ready": True}
            with self.assertRaisesRegex(FileNotFoundError, "Complete Topic 5 setup"):
                exec(compile(source, str(NOTEBOOK), "exec"), namespace)
            self.assertFalse(namespace["hosted_agent_ready"])
            run.assert_not_called()

    def test_hosted_prerequisites_clear_readiness_when_azd_fails(self):
        source = next("".join(cell["source"]) for cell in self.notebook["cells"]
                      if cell["id"] == "hosted-agent-prerequisites")
        with TemporaryDirectory() as directory:
            Path(directory, "azure.yaml").touch()
            with patch.dict("os.environ", {"WHISKER_HOSTED_PROJECT": directory}), \
                 patch("subprocess.run", side_effect=FileNotFoundError("azd not found")):
                namespace = {"hosted_agent_ready": True}
                with self.assertRaisesRegex(FileNotFoundError, "azd not found"):
                    exec(compile(source, str(NOTEBOOK), "exec"), namespace)
                self.assertFalse(namespace["hosted_agent_ready"])

    def test_hosted_invocation_requires_preflight_and_uses_verified_project(self):
        source = next("".join(cell["source"]) for cell in self.notebook["cells"]
                      if cell["id"] == "hosted-agent-invoke")
        with self.assertRaisesRegex(RuntimeError, "prerequisite cell"):
            exec(compile(source, str(NOTEBOOK), "exec"), {})
        run = Mock()
        namespace = {"hosted_agent_ready": True, "hosted_project": Path("/verified/project"),
                     "run_demo": run}
        with patch("builtins.input") as prompt:
            exec(compile(source, str(NOTEBOOK), "exec"), namespace)
        prompt.assert_not_called()
        self.assertEqual(run.call_args.kwargs["cwd"], Path("/verified/project"))
        self.assertEqual(run.call_args.kwargs["approval"], "")


class RunbookFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notebook = json.loads(NOTEBOOK.read_text())
        cls.cells = {cell["id"]: cell for cell in cls.notebook["cells"]}
        cls.positions = {cell["id"]: i for i, cell in enumerate(cls.notebook["cells"])}

    def test_build_validate_govern_and_storefront_topics_are_in_order(self):
        expected = [
            "topic-1", "topic-2", "topic-3", "topic-5", "topic-11", "topic-11b",
            "topic-4", "topic-6", "topic-7", "topic-8", "topic-9", "topic-10", "topic-12",
        ]
        topics = [cell for cell in self.notebook["cells"] if cell["id"].startswith("topic-")]
        self.assertEqual([cell["id"] for cell in topics], expected)
        for number, cell in enumerate(topics, 1):
            self.assertTrue(cell["source"][0].startswith(f"## {number}. "))
            self.assertNotRegex(cell["source"][0], r"\bmin(?:ute)?s?\b")
        self.assertEqual(len(self.cells), len(self.notebook["cells"]))

    def test_navigation_and_session_map_follow_the_same_order(self):
        def slug(heading):
            return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")

        topics = [cell for cell in self.notebook["cells"] if cell["id"].startswith("topic-")]
        titles = [cell["source"][0].removeprefix("## ").strip() for cell in topics]
        navigation = "".join(self.cells["navigation"]["source"])
        session_map = "".join(self.cells["session-map"]["source"])
        navigation_positions = [navigation.index(f"[{title}](#{slug(title)})") for title in titles]
        map_positions = [session_map.index(f"| {title} |") for title in titles]
        self.assertEqual(navigation_positions, sorted(navigation_positions))
        self.assertEqual(map_positions, sorted(map_positions))
        headings = {
            slug(line.lstrip("#").strip())
            for cell in self.notebook["cells"] if cell["cell_type"] == "markdown"
            for line in cell["source"] if line.startswith("#")
        }
        for target in re.findall(r"\]\(#([^)]+)\)", navigation):
            self.assertIn(target, headings)
        self.assertNotIn("| Time |", session_map)
        self.assertNotRegex(session_map, r"\d\d:\d\d")

    def test_executable_prerequisites_remain_before_their_consumers(self):
        dependencies = {
            "create-mcp-fallback": ("initialize",),
            "preview-pro-agent": ("initialize", "create-mcp-fallback"),
            "create-pro-agent": ("preview-pro-agent",),
            "pro-agent-chat": ("create-pro-agent",),
            "hosted-agent-invoke": ("initialize", "hosted-agent-prerequisites"),
            "external-agent-verify": ("initialize",),
            "seed-traces": ("initialize",),
            "create-new-model-version": ("create-pro-agent",),
            "run-model-comparison": ("create-pro-agent", "create-new-model-version"),
            "create-learn-guide": ("initialize",),
            "run-agent-mcp-validation": ("create-learn-guide",),
        }
        for consumer, prerequisites in dependencies.items():
            for prerequisite in prerequisites:
                with self.subTest(consumer=consumer, prerequisite=prerequisite):
                    self.assertLess(self.positions[prerequisite], self.positions[consumer])
        for cell in self.notebook["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), cell["id"], "exec")

    def test_all_diagrams_still_resolve_to_embedded_attachments(self):
        diagrams = 0
        for cell in self.notebook["cells"]:
            if cell["cell_type"] != "markdown":
                continue
            for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", "".join(cell["source"])):
                self.assertTrue(target.startswith("attachment:"))
                attachment = cell["attachments"][target.removeprefix("attachment:")]
                self.assertIn("image/png", attachment)
                self.assertTrue(attachment["image/png"])
                diagrams += 1
        self.assertEqual(diagrams, 12)

    def test_walkthrough_cells_execute_in_order_with_or_without_optional_runtime(self):
        initialize = ast.parse("".join(self.cells["initialize"]["source"]))
        helper = next(node for node in initialize.body
                      if isinstance(node, ast.FunctionDef) and node.name == "run_demo")
        for include_optional in (False, True):
            with self.subTest(include_optional=include_optional), TemporaryDirectory() as directory:
                Path(directory, "azure.yaml").touch()
                commands = []
                agent = {
                    "name": "kernel-panic-ops", "version": "1", "status": "active",
                    "definition": {"kind": "hosted", "environment_variables": {
                        "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-4.1-mini",
                        "APIM_GATEWAY_URL": "https://whisker.example",
                        "APIM_SUBSCRIPTION_KEY": "test-key-not-for-display",
                    }},
                }

                def run_command(arguments, **kwargs):
                    commands.append(arguments)
                    if "--output-json" in arguments:
                        candidate = "--model" in arguments
                        result = {
                            "name": arguments[arguments.index("--name") + 1],
                            "version": "9" if candidate else "7",
                            "model": "gpt-5-mini" if candidate else "gpt-4.1-mini",
                        }
                        Path(arguments[arguments.index("--output-json") + 1]).write_text(json.dumps(result))
                    return Mock(stdout=json.dumps(agent), returncode=0)

                namespace = {
                    "REPO_ROOT": ROOT, "Path": Path, "sys": sys, "os": os,
                    "shlex": shlex, "subprocess": subprocess,
                }
                exec(compile(ast.Module(body=[helper], type_ignores=[]), str(NOTEBOOK), "exec"), namespace)
                skip = {"initialize", "deploy-environment", "check-dependencies"}
                if not include_optional:
                    skip.add("external-agent-verify")
                with patch.dict(os.environ, {"WHISKER_HOSTED_PROJECT": directory}), \
                     patch("subprocess.run", side_effect=run_command), \
                     patch("builtins.input", side_effect=AssertionError("Unexpected input prompt")), \
                     patch("builtins.print"), patch("IPython.display.display"):
                    for cell in self.notebook["cells"]:
                        if cell["cell_type"] == "code" and cell["id"] not in skip:
                            tree = ast.parse("".join(cell["source"]))
                            for node in ast.walk(tree):
                                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                                    continue
                                if node.func.id != "run_demo":
                                    continue
                                keywords = {kw.arg: kw for kw in node.keywords}
                                if "confirmation" in keywords:
                                    # Simulate fresh consent without saving it in the shared notebook.
                                    keywords["approval"].value = keywords["confirmation"].value
                            exec(compile(ast.fix_missing_locations(tree), cell["id"], "exec"), namespace)
                self.assertEqual(namespace["baseline_agent"]["version"], "7")
                self.assertEqual(namespace["candidate_agent"]["version"], "9")
                self.assertEqual(namespace["baseline_agent"]["name"], namespace["candidate_agent"]["name"])
                self.assertTrue(namespace["hosted_agent_ready"])
                comparison = next(command for command in commands if "compare_models.py" in command)
                self.assertEqual(comparison[-4:], ["--a", "7", "--b", "9"])
                self.assertEqual(
                    sum("scripts/test-external-agent.py" in command for command in commands),
                    int(include_optional),
                )
                self.assertTrue(any("scripts/test-agent-mcp.py" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
