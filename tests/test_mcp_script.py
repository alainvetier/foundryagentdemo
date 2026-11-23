import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class McpSubscriptionTests(unittest.TestCase):
    def test_learn_mcp_endpoints_are_a_named_object(self):
        source = (ROOT / "scripts/create-mcp-servers.sh").read_text()
        payload = source.split('cat > "$TMP/learn.json" <<\'EOF\'\n', 1)[1].split("\nEOF", 1)[0]
        properties = json.loads(payload)["properties"]
        self.assertEqual(properties["mcpProperties"], {
            "transportType": "streamable",
            "endpoints": {"message": {"uriTemplate": "/mcp"}},
        })
        self.assertEqual(properties["backendId"], "whisker-learn-mcp")
        self.assertNotIn("serviceUrl", properties)
        backend = source.split('cat > "$TMP/learn-backend.json" <<\'EOF\'\n', 1)[1].split("\nEOF", 1)[0]
        self.assertEqual(json.loads(backend)["properties"]["url"], "https://learn.microsoft.com/api")
        self.assertLess(source.index('put "$BASE/backends/whisker-learn-mcp"'),
                        source.index('put "$BASE/apis/learn-mcp"'))
        self.assertTrue(properties["subscriptionRequired"])

    def run_script(self, subscription, *, fail_preflight=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("scripts", "agents/procode", "apim/policies", "bin"):
                (root / name).mkdir(parents=True)
            shutil.copy(ROOT / "scripts/create-mcp-servers.sh", root / "scripts")
            shutil.copy(ROOT / "apim/policies/mcp-tools-policy.xml", root / "apim/policies")
            settings = (
                "RG=rg-test\nAPIM_RG=rg-test\nAPIM_NAME=whisker-test\n"
                "APIM_GATEWAY_URL=https://gateway.test\n"
            )
            if subscription:
                settings += f"AZURE_SUBSCRIPTION_ID={subscription}\n"
            (root / "agents/procode/.env").write_text(settings)
            fake_az = root / "bin/az"
            fake_az.write_text(
                '#!/usr/bin/env bash\n'
                'printf "%s\\n" "$*" >> "$AZ_TEST_LOG"\n'
                'case "$*" in\n'
                '  "account show "*) echo default-sub ;;\n'
                '  "apim show "*)\n'
                '    if [[ "$FAIL_PREFLIGHT" == true ]]; then exit 1; fi\n'
                '    echo /subscriptions/test/resourceGroups/rg-test ;;\n'
                '  "apim api operation list "*)\n'
                "    echo '[{\"name\":\"listProducts\",\"description\":\"Products\"},"
                "{\"name\":\"placeOrder\",\"description\":\"Order\"}]' ;;\n"
                '  "rest "*) ;;\n'
                '  *) exit 2 ;;\n'
                'esac\n'
            )
            fake_az.chmod(0o755)
            log = root / "az.log"
            env = {
                **os.environ,
                "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
                "AZ_TEST_LOG": str(log),
                "FAIL_PREFLIGHT": str(fail_preflight).lower(),
                "READ_ONLY": "true",
            }
            env.pop("AZURE_SUBSCRIPTION_ID", None)
            result = subprocess.run(
                ["bash", str(root / "scripts/create-mcp-servers.sh")],
                env=env, text=True, capture_output=True, timeout=15,
            )
            return result, log.read_text().splitlines()

    def test_pinned_subscription_used_for_every_resource_operation(self):
        result, calls = self.run_script("demo-sub")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call.startswith("account ") for call in calls))
        self.assertTrue(all("--subscription demo-sub" in call for call in calls))
        writes = [call for call in calls if call.startswith("rest ")]
        self.assertTrue(writes)
        self.assertTrue(all("/subscriptions/demo-sub/" in call for call in writes))
        self.assertFalse(any("/tools/placeOrder" in call for call in calls))
        self.assertIn("Target subscription: demo-sub", result.stdout)

    def test_older_settings_fall_back_to_cli_default(self):
        result, calls = self.run_script(None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(calls[0].startswith("account show "))
        self.assertTrue(all("--subscription default-sub" in call for call in calls[1:]))

    def test_preflight_failure_prevents_all_writes(self):
        result, calls = self.run_script("demo-sub", fail_preflight=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("apim show "))
        self.assertIn("Cannot access the target APIM", result.stderr)


if __name__ == "__main__":
    unittest.main()
