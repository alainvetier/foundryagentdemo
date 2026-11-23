import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hosted_local", ROOT / "scripts/run-hosted-local.py")
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class HostedLocalTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "FOUNDRY_PROJECT_ENDPOINT": "https://foundry.example/api/projects/whisker-works",
            "CHAT_MODEL": "existing-model",
            "APIM_GATEWAY_URL": "https://gateway.example",
            "APIM_GOLD_KEY": "gold-test-key",
            "APIM_SUBSCRIPTION_KEY": "bronze-test-key",
        }

    def test_existing_model_and_gold_key_are_used_without_mutation(self):
        original = self.settings.copy()
        environment = local.local_environment(self.settings)
        self.assertEqual(environment["AZURE_AI_MODEL_DEPLOYMENT_NAME"], "existing-model")
        self.assertEqual(environment["APIM_SUBSCRIPTION_KEY"], "gold-test-key")
        self.assertEqual(environment["APIM_MCP_PATH"], "whisker-mcp")
        self.assertEqual(self.settings, original)

    def test_configured_mcp_path_is_preserved(self):
        self.settings["APIM_MCP_PATH"] = "existing-mcp"
        self.assertEqual(local.local_environment(self.settings)["APIM_MCP_PATH"], "existing-mcp")

    def test_required_settings_fail_explicitly_without_exposing_values(self):
        for name in ("FOUNDRY_PROJECT_ENDPOINT", "CHAT_MODEL", "APIM_GATEWAY_URL", "APIM_GOLD_KEY"):
            for value in (None, ""):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, name) as error:
                        local.local_environment({**self.settings, name: value})
                    self.assertNotIn("gold-test-key", str(error.exception))
                    self.assertNotIn("bronze-test-key", str(error.exception))

    def test_check_does_not_start_server_or_change_process_environment(self):
        with patch("sys.argv", ["run-hosted-local.py", "--check"]), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(local, "dotenv_values", return_value=self.settings), \
             patch.object(local.os.environ, "update") as update, \
             patch.object(local.os, "chdir") as chdir, \
             patch("builtins.print") as output:
            local.main()
        update.assert_not_called()
        chdir.assert_not_called()
        self.assertNotIn("gold-test-key", str(output.call_args_list))

    def test_missing_settings_file_fails_before_startup(self):
        with patch("sys.argv", ["run-hosted-local.py"]), \
             patch.object(Path, "is_file", return_value=False):
            with self.assertRaisesRegex(FileNotFoundError, "environment setup"):
                local.main()

    def test_server_uses_existing_factory_loopback_and_isolated_state(self):
        factory = Mock()
        server = Mock()
        with patch("sys.argv", ["run-hosted-local.py"]), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(local, "dotenv_values", return_value=self.settings), \
             patch.dict(local.os.environ, {}, clear=True), \
             patch.object(local.os, "chdir"), \
             patch.object(local.sys, "path", local.sys.path.copy()), \
             patch.dict("sys.modules", {
                 "main": SimpleNamespace(create_agent=factory),
                 "agent_framework_foundry_hosting": SimpleNamespace(ResponsesHostServer=server),
             }), patch("builtins.print"):
            local.main()
            self.assertEqual(local.os.environ["AGENTSERVER_STATE_ROOT"],
                             str(ROOT / ".build" / "agent-inspector"))
            self.assertEqual(local.os.environ["APIM_SUBSCRIPTION_KEY"], "gold-test-key")
        factory.assert_not_called()
        server.assert_called_once_with(agent=factory, history_source="agent_server")
        server.return_value.run.assert_called_once_with(host="127.0.0.1", port=8088)

    def test_hosted_environment_is_rejected(self):
        with patch("sys.argv", ["run-hosted-local.py"]), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(local, "dotenv_values", return_value=self.settings), \
             patch.dict(local.os.environ, {"FOUNDRY_HOSTING_ENVIRONMENT": "hosted"}), \
             patch.object(local.os, "chdir") as chdir, patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "local debugging"):
                local.main()
        chdir.assert_not_called()

    def test_launch_uses_isolated_interpreter_and_repository_source(self):
        config = json.loads((ROOT / ".vscode/launch.json").read_text())["configurations"][0]
        self.assertEqual(config["python"], "${workspaceFolder}/agents/hosted/.venv/bin/python")
        self.assertEqual(config["program"], "${workspaceFolder}/scripts/run-hosted-local.py")
        self.assertNotIn("env", config)
        self.assertNotIn("envFile", config)

    def test_inspector_task_opens_the_local_toolkit_view(self):
        config = json.loads((ROOT / ".vscode/tasks.json").read_text())
        self.assertEqual(config["inputs"][0]["command"], "ai-mlstudio.openTestTool")
        self.assertEqual(config["inputs"][0]["args"]["port"], 8088)
        self.assertEqual(config["tasks"][0]["label"], "Whisker Works: Open Agent Inspector")


if __name__ == "__main__":
    unittest.main()
