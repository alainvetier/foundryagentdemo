import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = ROOT / "agents/cat-food"


@unittest.skipUnless(importlib.util.find_spec("agent_framework"), "Run with the MAF hosted-agent environment")
class CatFoodAgentTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("cat_food_agent", AGENT_ROOT / "main.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    async def test_real_maf_tool_returns_packaged_sources_and_catalog(self):
        contents = await self.module.cat_food_guide.invoke(arguments={})
        guide = "\n".join(content.text for content in contents)
        for expected in ("WW-006", "WW-011", "WW-012", "2 kcal/treat", "ages 1-7",
                         "not live inventory", "Product Guide", "Cat Care Basics"):
            self.assertIn(expected, guide)

    async def test_missing_guide_fails_explicitly(self):
        with patch.object(self.module, "HERE", AGENT_ROOT / "missing"):
            with self.assertRaises(FileNotFoundError):
                await self.module.cat_food_guide.invoke(arguments={})

    async def test_request_factory_propagates_headers_and_closes_all_clients(self):
        credential = SimpleNamespace(close=AsyncMock())

        class FakeClient:
            def __init__(self, **kwargs):
                self.options = kwargs
                self.project_client = SimpleNamespace(close=AsyncMock())
                self.client = SimpleNamespace(close=AsyncMock())

        with (
            patch.dict(os.environ, {
                "FOUNDRY_PROJECT_ENDPOINT": "https://foundry.example/api/projects/whisker",
                "AZURE_AI_MODEL_DEPLOYMENT_NAME": "existing-model",
                "FOUNDRY_AGENT_INSTANCE_CLIENT_ID": "agent-identity",
            }),
            patch.object(self.module.AgentConfig, "from_env", return_value=SimpleNamespace(is_hosted=True)),
            patch.object(self.module, "DefaultAzureCredential", return_value=credential) as auth,
            patch.object(self.module, "FoundryChatClient", FakeClient),
            patch.object(self.module, "get_request_context") as context,
            patch.object(self.module, "Agent") as agent,
        ):
            context.return_value.platform_headers.return_value = {"x-request-id": "cat-request"}
            self.module.create_agent()
        options = agent.call_args.kwargs
        self.assertEqual(options["tools"], [self.module.cat_food_guide])
        self.assertEqual(options["default_options"], {"store": False})
        client = options["client"]
        self.assertEqual(client.options["model"], "existing-model")
        self.assertEqual(client.options["default_headers"], {"x-request-id": "cat-request"})
        self.assertEqual(auth.call_args.kwargs["managed_identity_client_id"], "agent-identity")
        for key, value in auth.call_args.kwargs.items():
            if key.startswith("exclude_"):
                self.assertTrue(value)
        with self.assertRaisesRegex(RuntimeError, "model failed"):
            async with client:
                raise RuntimeError("model failed")
        credential.close.assert_awaited_once()
        client.project_client.close.assert_awaited_once()
        client.client.close.assert_awaited_once()

    async def test_hosted_factory_requires_agent_identity(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.module.AgentConfig, "from_env", return_value=SimpleNamespace(is_hosted=True)),
        ):
            with self.assertRaisesRegex(RuntimeError, "FOUNDRY_AGENT_INSTANCE_CLIENT_ID"):
                self.module.create_agent()

    async def test_local_start_reuses_settings_without_overriding_explicit_model(self):
        with (
            patch.dict(os.environ, {"CHAT_MODEL": "store-model", "AZURE_AI_MODEL_DEPLOYMENT_NAME": "chosen-model"}),
            patch.object(self.module.AgentConfig, "from_env", return_value=SimpleNamespace(is_hosted=False)),
            patch.object(self.module, "load_dotenv") as load,
            patch.object(self.module, "ResponsesHostServer") as server,
        ):
            self.module.main()
            self.assertEqual(os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"], "chosen-model")
        self.assertEqual(load.call_count, 2)
        server.assert_called_once_with(agent=self.module.create_agent, history_source="agent_server")
        server.return_value.run.assert_called_once_with(host="127.0.0.1")

    async def test_hosted_start_does_not_load_local_credentials(self):
        with (
            patch.object(self.module.AgentConfig, "from_env", return_value=SimpleNamespace(is_hosted=True)),
            patch.object(self.module, "load_dotenv") as load,
            patch.object(self.module, "ResponsesHostServer") as server,
        ):
            self.module.main()
        load.assert_not_called()
        server.return_value.run.assert_called_once_with(host="0.0.0.0")


class CatFoodConfigurationTests(unittest.TestCase):
    def test_deploy_configuration_and_package_exclusions(self):
        cfg = yaml.safe_load((AGENT_ROOT / "azure.yaml").read_text())
        service = cfg["services"]["purrfessor-nibbles"]
        self.assertEqual(service["kind"], "hosted")
        self.assertEqual(service["protocols"], [{"protocol": "responses", "version": "2.0.0"}])
        self.assertTrue((AGENT_ROOT / service["codeConfiguration"]["entryPoint"]).is_file())
        for filename in (".agentignore", ".dockerignore"):
            exclusions = (AGENT_ROOT / filename).read_text().splitlines()
            for entry in (".env", ".env.*", ".venv/", ".azure/"):
                self.assertIn(entry, exclusions)

    def test_a2a_enable_preserves_responses_and_adds_food_skill(self):
        spec = importlib.util.spec_from_file_location("cat_food_a2a", AGENT_ROOT / "enable_a2a.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        project = Mock()
        project.agents.update_details.return_value = SimpleNamespace(name="purrfessor-nibbles")
        with (
            patch.dict(os.environ, {"FOUNDRY_PROJECT_ENDPOINT": "https://example.test"}),
            patch.object(module, "load_dotenv"),
            patch.object(module, "DefaultAzureCredential"),
            patch.object(module, "AIProjectClient") as factory,
            patch("builtins.print"),
        ):
            factory.return_value.__enter__.return_value = project
            module.main()
        arguments = project.agents.update_details.call_args.kwargs
        self.assertEqual(arguments["agent_name"], "purrfessor-nibbles")
        self.assertEqual(arguments["agent_endpoint"].as_dict(), {
            "protocol_configuration": {"responses": {}, "a2a": {}},
        })
        self.assertEqual(arguments["agent_card"].skills[0].id, "cat-food")


if __name__ == "__main__":
    unittest.main()
