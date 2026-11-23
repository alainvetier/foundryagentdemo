import ast
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "docs/whisker-works-demo-runbook.ipynb"
GUIDES = [
    "01-agent-building-blocks.md",
    "02-build-prompt-agent-foundry-portal.md",
    "03-connect-store-tools-mcp.md",
    "04-create-prompt-agent-code.md",
    "05-build-hosted-agent-framework.md",
    "06-optional-container-apps-agent.md",
    "07-versions-traces-evaluations.md",
    "08-change-model-safely.md",
    "09-govern-model-calls.md",
    "10-content-safety-gateway.md",
    "11-govern-mcp-tools.md",
    "12-govern-agent-to-agent-calls.md",
]


def markdown(path):
    text = path.read_text()
    if path.suffix == ".ipynb":
        notebook = json.loads(text)
        text = "\n".join(
            "".join(cell["source"])
            for cell in notebook["cells"]
            if cell["cell_type"] == "markdown"
        )
    return re.sub(r"^```.*?^```[^\n]*", "", text, flags=re.MULTILINE | re.DOTALL)


def anchors(text):
    result = set(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', text))
    counts = {}
    for heading in re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE):
        heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(f"{slug}-{count}" if count else slug)
    return result


class DocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = TemporaryDirectory(prefix="whisker-docs-git-")
        cls.addClassCleanup(temporary.cleanup)
        subprocess.run(["git", "init", "--bare", "--quiet", temporary.name], check=True)
        cls.git = [
            "git", "-c", "core.excludesFile=/dev/null",
            f"--git-dir={temporary.name}", f"--work-tree={ROOT}",
        ]
        result = subprocess.run(
            cls.git + ["ls-files", "--others", "--exclude-standard", "-z"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        cls.files = [ROOT / name for name in result.stdout.split("\0") if name]

    def test_local_documentation_links_and_fragments(self):
        checked = 0
        publishable = {path.resolve() for path in self.files}
        for path in self.files:
            if path.suffix not in (".md", ".ipynb"):
                continue
            text = markdown(path)
            targets = re.findall(r"\[[^\]]*\]\((<?[^\s)]+>?)\)", text)
            targets += re.findall(r"^\[[^\]]+\]:\s*(\S+)", text, re.MULTILINE)
            for target in targets:
                target = target.strip("<>")
                url = urlsplit(target)
                if url.scheme or target.startswith("//"):
                    continue
                checked += 1
                with self.subTest(source=str(path.relative_to(ROOT)), target=target):
                    resolved = path.parent / unquote(url.path) if url.path else path
                    self.assertTrue(resolved.exists(), "Missing local link target")
                    if resolved.is_file():
                        self.assertIn(resolved.resolve(), publishable, "Link points to an unpublished local file")
                    if url.fragment and resolved.suffix in (".md", ".ipynb"):
                        self.assertIn(unquote(url.fragment), anchors(markdown(resolved)))
        self.assertGreater(checked, 100)

    def test_walkthrough_guidance_is_self_paced(self):
        paths = [
            ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")),
            *sorted((ROOT / "docs/images").glob("*.svg")),
            ROOT / "samples/agent-lifecycle/README.md", NOTEBOOK,
        ]
        presentation_language = re.compile(
            r"\b(?:presenters?|attendees?|presenting|presentations?|rehears\w*)\b"
            r"|\b(?:on[ -]stage|stage time|talk(?:ing)? (?:track|points)|show[ -]only)\b"
            r"|\b(?:live (?:session|demo|walkthrough)|customer (?:session|walkthrough|runbook))\b"
            r"|\bduring (?:this|the) demo\b"
            r"|\b(?:before the session|audience joins|two[ -]hour)\b"
            r"|^\s*(?:\*\*)?Time:(?:\*\*)?"
            r"|^#{1,6} [^\n]*\b\d+[ -](?:minute|hour)",
            re.IGNORECASE | re.MULTILINE,
        )
        for path in paths:
            text = markdown(path)
            text = re.sub(r'<a\s+(?:id|name)=["\'][^"\']+["\']></a>', "", text)
            text = re.sub(r"\]\([^)]+\)", "]", text)
            with self.subTest(document=str(path.relative_to(ROOT))):
                self.assertIsNone(presentation_language.search(text))
        self.assertIn("self-paced", markdown(NOTEBOOK).lower())
        self.assertIn("## Pause and resume", markdown(ROOT / "docs/demo-run-of-show.md"))

    def test_readme_and_run_of_show_follow_notebook_order(self):
        notebook_topics = re.findall(r"^## (\d+)\. ", markdown(NOTEBOOK), re.MULTILINE)
        expected = [str(number) for number in range(1, 14)]
        self.assertEqual(notebook_topics, expected)
        for path in (ROOT / "README.md", ROOT / "docs/demo-run-of-show.md"):
            text = path.read_text()
            rows = re.findall(r"^\| (\d+)(?: \(optional[^|]*)? \|", text, re.MULTILINE)
            self.assertEqual([number for number in rows if number != "0"], expected)
            prefix = "docs/" if path.name == "README.md" else ""
            positions = [text.index(f"]({prefix}{name})") for name in GUIDES]
            self.assertEqual(positions, sorted(positions))

    def test_guide_filenames_follow_notebook_order(self):
        numbered_guides = sorted(
            path.name for path in (ROOT / "docs").glob("[0-9][0-9]-*.md")
            if not path.name.startswith("00-")
        )
        self.assertEqual(numbered_guides, GUIDES)
        for number, name in enumerate(GUIDES, 1):
            self.assertTrue(name.startswith(f"{number:02d}-"))

    def test_numbered_guide_references_resolve_after_renaming(self):
        guide_names = {path.name for path in (ROOT / "docs").glob("*.md")}
        for path in self.files:
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            references = re.findall(
                r"(?<![\w-])(?:\d{2}[a-z]?-|optional-)[a-z0-9-]+\.md\b",
                text,
            )
            for name in references:
                with self.subTest(source=str(path.relative_to(ROOT)), reference=name):
                    self.assertIn(name, guide_names, "Stale documentation filename")

    def test_guide_titles_match_notebook_topics_exactly(self):
        topics = re.findall(r"^## (\d+\. .+)$", markdown(NOTEBOOK), re.MULTILINE)
        self.assertEqual(len(topics), len(GUIDES) + 1)
        for name, topic in zip(GUIDES, topics):
            with self.subTest(guide=name):
                titles = re.findall(
                    r"^# (.+)$", markdown(ROOT / "docs" / name), re.MULTILINE,
                )
                self.assertEqual(titles, [topic])

    def test_legacy_guide_title_anchors_are_preserved(self):
        legacy_titles = [
            "01 — Refresher: the building blocks of an agent",
            "02 — Low-code: create an agent in the Foundry portal",
            "03 — Create the Store MCP server and connect Whiskers",
            "04 — Pro-code: VS Code + Foundry Toolkit + GitHub Copilot",
            "05 — Hosted agents in Foundry with Microsoft Agent Framework",
            "06 - Optional: your runtime, Foundry observability, APIM controls",
            "07 — Show the agent details in Foundry",
            "08 — Update an agent to use a new model",
            "09 — APIM AI gateway, Layer 1: Models",
            "10 — Demo Azure AI Content Safety through API Management",
            "11 — APIM, Layer 2: MCP governance and human approval",
            "12 — APIM, Layer 3: Agents — govern an A2A agent",
        ]
        original_numbers = ["01", "02", "03", "05", "11", "11B", "04", "06", "07", "08", "09", "10"]
        for name, title, original_number in zip(GUIDES, legacy_titles, original_numbers):
            with self.subTest(guide=name):
                original_title = re.sub(r"^\S+", original_number, title)
                expected = anchors(f"# {title}") | anchors(f"# {original_title}")
                self.assertTrue(expected.issubset(anchors(markdown(ROOT / "docs" / name))))

    def test_notebooks_have_no_saved_execution_state(self):
        for path in self.files:
            if path.suffix != ".ipynb":
                continue
            notebook = json.loads(path.read_text())
            for index, cell in enumerate(notebook["cells"]):
                with self.subTest(notebook=str(path.relative_to(ROOT)), cell=index):
                    self.assertFalse(cell.get("outputs"), "Clear outputs before publishing")
                    self.assertIsNone(cell.get("execution_count"))

    def test_runbook_requires_fresh_approval_for_live_actions(self):
        notebook = json.loads(NOTEBOOK.read_text())
        checked = 0
        for cell in notebook["cells"]:
            if cell["cell_type"] != "code":
                continue
            for node in ast.walk(ast.parse("".join(cell["source"]))):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id != "run_demo":
                    continue
                keywords = {keyword.arg: keyword.value for keyword in node.keywords}
                if "confirmation" in keywords:
                    checked += 1
                    with self.subTest(cell=cell["id"]):
                        self.assertIn("approval", keywords)
                        self.assertEqual(ast.literal_eval(keywords["approval"]), "")
        self.assertGreater(checked, 0)

    def test_private_state_is_ignored_but_templates_and_source_are_publishable(self):
        private = [
            ".env", ".env.local", "agents/procode/.env",
            "agents/hosted/.env.production", ".azure/demo.parameters.json",
            "agents/hosted/.azure/demo/.env", ".foundry/state.json",
            "live-agent/whiskers-live/.foundry/.deployment.json",
            ".build/store.zip", ".copilot-azure/session/report.md",
            ".github/modernize/assessment/report.json", "infra/main.json",
            "agents/procode/results/comparison.json", "debug.log", "certificate.pfx",
            "private.pem", "private.key", "site.publishsettings",
        ]
        public = [
            ".env.sample", "agents/procode/.env.sample", "agents/hosted/.env.sample",
            "agents/cat-food/.env.sample", ".env.example", ".env.template",
            "infra/main.bicep", ".vscode/mcp.json", ".github/workflows/update-agent.yml",
        ]
        result = subprocess.run(
            self.git + ["check-ignore", "--no-index", "--stdin"],
            input="\n".join(private + public) + "\n", cwd=ROOT,
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(set(result.stdout.splitlines()), set(private))


if __name__ == "__main__":
    unittest.main()
