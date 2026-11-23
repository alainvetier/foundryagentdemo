import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urljoin

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("create_agent", ROOT / "agents/procode/create_agent.py")
create_agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(create_agent)


class CreateAgentTests(unittest.TestCase):
    def test_food_a2a_uses_foundry_endpoint_and_ga_protocol_without_apim(self):
        project = Mock()
        project.connections.get.return_value = SimpleNamespace(id="/project/connections/whisker-cat-food")
        with patch.dict(os.environ, {
            "FOUNDRY_PROJECT_ENDPOINT": "https://foundry.example/api/projects/whisker/",
        }, clear=True):
            tool = create_agent.build_a2a_tool(project, {
                "agent_name": "purrfessor-nibbles",
                "project_connection_name": "whisker-cat-food",
            }).as_dict()
        self.assertEqual(tool, {
            "type": "a2a",
            "a2a_version": "1.0",
            "base_url": "https://foundry.example/api/projects/whisker/agents/purrfessor-nibbles/endpoint/protocols/a2a",
            "project_connection_id": "/project/connections/whisker-cat-food",
        })
        project.connections.get.assert_called_once_with("whisker-cat-food")

    def test_food_delegation_is_opt_in_and_preserves_existing_tools(self):
        cfg = yaml.safe_load((create_agent.HERE / "agent.yaml").read_text())
        self.assertFalse(cfg["a2a"]["enabled"])
        cfg["a2a"]["enabled"] = True
        project = Mock()
        project.connections.get.return_value = SimpleNamespace(id="/project/connections/whisker-cat-food")
        project.get_openai_client.return_value.files.create.return_value = SimpleNamespace(id="file-sales")
        project.agents.create_version.return_value = SimpleNamespace(name=cfg["name"], version="3")
        with (
            patch.dict(os.environ, {
                "FOUNDRY_PROJECT_ENDPOINT": "https://foundry.example/api/projects/whisker",
                "APIM_GATEWAY_URL": "https://gateway.test",
            }),
            patch.object(create_agent, "AIProjectClient", return_value=project),
            patch.object(create_agent, "DefaultAzureCredential"),
            patch.object(create_agent, "get_or_create_vector_store", return_value=SimpleNamespace(id="vs-knowledge")),
            patch.object(create_agent.yaml, "safe_load", return_value=cfg),
            patch("sys.argv", ["create_agent.py"]),
        ):
            create_agent.main()
        definition = project.agents.create_version.call_args.kwargs["definition"].as_dict()
        self.assertEqual([tool["type"] for tool in definition["tools"]],
                         ["file_search", "code_interpreter", "mcp", "a2a"])
        self.assertIn("Purrfessor Nibbles", definition["instructions"])
        self.assertIn("specialist is unavailable", definition["instructions"])

    def test_wellness_a2a_uses_isolated_connection_and_authenticated_discovery(self):
        cfg = yaml.safe_load((create_agent.HERE / "wellness-agent.yaml").read_text())
        project = Mock()
        project.connections.get.return_value = SimpleNamespace(id="/project/connections/whisker-wellness-a2a")
        with patch.dict(os.environ, {
            "APIM_GATEWAY_URL": "https://gateway.test/",
            "MCP_PROJECT_CONNECTION_NAME": "whisker-store",
        }):
            tool = create_agent.build_a2a_tool(project, cfg["a2a"]).as_dict()
        self.assertEqual(tool, {
            "type": "a2a_preview",
            "base_url": "https://gateway.test/wellness-agent",
            "project_connection_id": "/project/connections/whisker-wellness-a2a",
            "agent_card_path": "/wellness-agent/.well-known/agent-card.json",
            "send_credentials_for_agent_card": True,
        })
        self.assertEqual(
            urljoin(tool["base_url"], tool["agent_card_path"]),
            "https://gateway.test/wellness-agent/.well-known/agent-card.json",
        )
        self.assertNotIn("knowledge", cfg)
        self.assertNotIn("mcp", cfg)
        project.connections.get.assert_called_once_with("whisker-wellness-a2a")
        self.assertTrue((create_agent.HERE / cfg["instructions_file"]).is_file())

    def test_wellness_creation_only_adds_a2a_tool(self):
        project = Mock()
        project.connections.get.return_value = SimpleNamespace(id="/project/connections/whisker-wellness-a2a")
        project.agents.create_version.return_value = SimpleNamespace(
            name="whiskers-wellness-concierge", version="1",
        )
        with (
            patch.dict(os.environ, {
                "FOUNDRY_PROJECT_ENDPOINT": "https://example.test",
                "APIM_GATEWAY_URL": "https://gateway.test",
            }),
            patch.object(create_agent, "AIProjectClient", return_value=project),
            patch.object(create_agent, "DefaultAzureCredential"),
            patch("sys.argv", [
                "create_agent.py", "--config", str(create_agent.HERE / "wellness-agent.yaml"),
            ]),
        ):
            create_agent.main()
        arguments = project.agents.create_version.call_args.kwargs
        self.assertEqual(arguments["agent_name"], "whiskers-wellness-concierge")
        definition = arguments["definition"].as_dict()
        self.assertEqual([tool["type"] for tool in definition["tools"]], ["a2a_preview"])
        project.get_openai_client.return_value.files.create.assert_not_called()
        project.get_openai_client.return_value.vector_stores.create.assert_not_called()

    def test_learn_config_does_not_inherit_store_routing_or_connection(self):
        cfg = yaml.safe_load((create_agent.HERE / "learn-agent.yaml").read_text())
        with patch.dict(os.environ, {
            "APIM_GATEWAY_URL": "https://gateway.test/",
            "APIM_MCP_PATH": "whisker-mcp",
            "MCP_PROJECT_CONNECTION_NAME": "whisker-store",
        }):
            tool = create_agent.build_mcp_tool(cfg["mcp"]).as_dict()
        self.assertEqual(tool["server_url"], "https://gateway.test/learn-mcp/mcp")
        self.assertEqual(tool["project_connection_id"], "whisker-learn")
        self.assertNotIn("headers", tool)
        self.assertEqual(tool["allowed_tools"], cfg["mcp"]["allowed_tools"])
        self.assertTrue((create_agent.HERE / cfg["instructions_file"]).is_file())

    def test_existing_mcp_environment_defaults_are_preserved(self):
        with patch.dict(os.environ, {
            "APIM_GATEWAY_URL": "https://gateway.test",
            "APIM_MCP_PATH": "existing-store",
            "MCP_PROJECT_CONNECTION_NAME": "existing-connection",
        }):
            tool = create_agent.build_mcp_tool({}).as_dict()
        self.assertEqual(tool["server_url"], "https://gateway.test/existing-store/mcp")
        self.assertEqual(tool["project_connection_id"], "existing-connection")

    def test_sales_upload_and_tool_schema(self):
        client = Mock()

        def upload(*, file, purpose):
            self.assertEqual(purpose, "assistants")
            self.assertEqual(Path(file.name).name, "whisker-sales-2026.csv")
            self.assertTrue(file.read())
            self.assertFalse(file.closed)
            return SimpleNamespace(id="file-sales")

        client.files.create.side_effect = upload
        tool = create_agent.build_code_interpreter_tool(
            client, {"files": ["../../data/sales/whisker-sales-2026.csv"]}
        )
        self.assertEqual(tool.as_dict(), {
            "type": "code_interpreter",
            "container": {"type": "auto", "file_ids": ["file-sales"]},
        })
        self.assertTrue(client.files.create.call_args.kwargs["file"].closed)

    def test_missing_input_fails_before_any_upload(self):
        client = Mock()
        with self.assertRaisesRegex(FileNotFoundError, "Code Interpreter input file not found"):
            create_agent.build_code_interpreter_tool(client, {
                "files": ["../../data/sales/whisker-sales-2026.csv", "missing-sales.csv"],
            })
        client.files.create.assert_not_called()

    def test_upload_failure_is_not_hidden(self):
        client = Mock()
        client.files.create.side_effect = RuntimeError("upload failed")
        with self.assertRaisesRegex(RuntimeError, "upload failed"):
            create_agent.build_code_interpreter_tool(
                client, {"files": ["../../data/sales/whisker-sales-2026.csv"]}
            )
        self.assertTrue(client.files.create.call_args.kwargs["file"].closed)

    def test_baseline_creates_all_three_tools(self):
        cfg = yaml.safe_load((create_agent.HERE / "agent.yaml").read_text())
        client = Mock()
        client.files.create.return_value = SimpleNamespace(id="file-sales")
        project = Mock()
        project.get_openai_client.return_value = client
        project.agents.create_version.return_value = SimpleNamespace(name=cfg["name"], version="2")
        with (
            patch.dict(os.environ, {
                "FOUNDRY_PROJECT_ENDPOINT": "https://example.test/api/projects/whisker",
                "APIM_GATEWAY_URL": "https://gateway.test",
            }),
            patch.object(create_agent, "AIProjectClient", return_value=project),
            patch.object(create_agent, "DefaultAzureCredential"),
            patch.object(create_agent, "get_or_create_vector_store", return_value=SimpleNamespace(id="vs-knowledge")),
            patch("sys.argv", ["create_agent.py"]),
        ):
            create_agent.main()
        definition = project.agents.create_version.call_args.kwargs["definition"].as_dict()
        self.assertEqual(project.agents.create_version.call_args.kwargs["agent_name"], cfg["name"])
        self.assertEqual([tool["type"] for tool in definition["tools"]],
                         ["file_search", "code_interpreter", "mcp"])
        self.assertEqual(definition["tools"][0]["vector_store_ids"], ["vs-knowledge"])
        self.assertEqual(definition["tools"][1]["container"]["file_ids"], ["file-sales"])
        self.assertEqual(definition["model"], cfg["model"])

    def test_disabled_or_absent_config_does_not_upload(self):
        for config in ({}, {"code_interpreter": {"enabled": False}}):
            with self.subTest(config=config):
                cfg = {"name": "whiskers-test", "model": "gpt-4.1-mini",
                       "instructions_file": "instructions.md", **config}
                project = Mock()
                project.agents.create_version.return_value = SimpleNamespace(name=cfg["name"], version="1")
                with (
                    patch.dict(os.environ, {"FOUNDRY_PROJECT_ENDPOINT": "https://example.test"}),
                    patch.object(create_agent, "AIProjectClient", return_value=project),
                    patch.object(create_agent, "DefaultAzureCredential"),
                    patch.object(create_agent.yaml, "safe_load", return_value=cfg),
                    patch("sys.argv", ["create_agent.py"]),
                ):
                    create_agent.main()
                project.get_openai_client.return_value.files.create.assert_not_called()
                definition = project.agents.create_version.call_args.kwargs["definition"].as_dict()
                self.assertEqual(definition["tools"], [])

    def test_name_override_and_result_capture_preserve_source_config(self):
        source = (create_agent.HERE / "agent.yaml").read_text()
        cfg = yaml.safe_load(source)
        project = Mock()
        project.get_openai_client.return_value.files.create.return_value = SimpleNamespace(id="file-sales")
        project.agents.create_version.return_value = SimpleNamespace(name="whiskers-concierge-pro-live", version=7)
        with TemporaryDirectory() as directory:
            result = Path(directory) / "created-agent.json"
            with (
                patch.dict(os.environ, {
                    "FOUNDRY_PROJECT_ENDPOINT": "https://example.test",
                    "APIM_GATEWAY_URL": "https://gateway.test",
                }),
                patch.object(create_agent, "AIProjectClient", return_value=project),
                patch.object(create_agent, "DefaultAzureCredential"),
                patch.object(create_agent, "get_or_create_vector_store", return_value=SimpleNamespace(id="vs-knowledge")),
                patch("sys.argv", [
                    "create_agent.py", "--name", "whiskers-concierge-pro-live",
                    "--model", "gpt-5-mini", "--output-json", str(result),
                ]),
            ):
                create_agent.main()
            self.assertEqual(json.loads(result.read_text()), {
                "name": "whiskers-concierge-pro-live", "version": "7", "model": "gpt-5-mini",
            })
        arguments = project.agents.create_version.call_args.kwargs
        self.assertEqual(arguments["agent_name"], "whiskers-concierge-pro-live")
        definition = arguments["definition"].as_dict()
        self.assertEqual(definition["model"], "gpt-5-mini")
        self.assertEqual(definition["instructions"], (create_agent.HERE / cfg["instructions_file"]).read_text())
        self.assertEqual([tool["type"] for tool in definition["tools"]],
                         ["file_search", "code_interpreter", "mcp"])
        self.assertEqual((create_agent.HERE / "agent.yaml").read_text(), source)

    def test_failed_creation_does_not_write_a_success_result(self):
        project = Mock()
        project.agents.create_version.side_effect = RuntimeError("creation failed")
        cfg = {"name": "whiskers-test", "model": "gpt-4.1-mini", "instructions_file": "instructions.md"}
        with TemporaryDirectory() as directory:
            result = Path(directory) / "created-agent.json"
            with (
                patch.dict(os.environ, {"FOUNDRY_PROJECT_ENDPOINT": "https://example.test"}),
                patch.object(create_agent, "AIProjectClient", return_value=project),
                patch.object(create_agent, "DefaultAzureCredential"),
                patch.object(create_agent.yaml, "safe_load", return_value=cfg),
                patch("sys.argv", ["create_agent.py", "--output-json", str(result)]),
            ):
                with self.assertRaisesRegex(RuntimeError, "creation failed"):
                    create_agent.main()
            self.assertFalse(result.exists())


if __name__ == "__main__":
    unittest.main()
