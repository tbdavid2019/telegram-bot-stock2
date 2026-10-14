"""Regression tests for the yfinance version-check workflow contract."""

from pathlib import Path
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from scripts.yfinance_version import is_newer


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "auto-update-yfinance.yml"
CANONICAL_SCRIPT = Path(__file__).parents[1] / "check_and_update_yfinance.sh"
LEGACY_SCRIPT = Path(__file__).parents[1] / "auto_update_yfinance.sh"


class YFinanceCIContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.canonical_script = CANONICAL_SCRIPT.read_text(encoding="utf-8")
        cls.legacy_script = LEGACY_SCRIPT.read_text(encoding="utf-8")

    def test_workflow_serializes_check_result_in_step_summary(self):
        self.assertIn("GITHUB_STEP_SUMMARY", self.workflow)
        self.assertIn("No update; no commit or push", self.workflow)

    def test_workflow_serializes_concurrent_runs(self):
        self.assertIn("concurrency:", self.workflow)
        self.assertIn("yfinance-version-check", self.workflow)

    def test_commit_and_push_remain_gated_by_version_change(self):
        self.assertIn("if: steps.bump.outputs.updated == 'true'", self.workflow)
        self.assertIn("git diff --cached --quiet -- requirements.txt", self.workflow)

    def test_shell_updater_does_not_hide_pull_or_commit_failures(self):
        self.assertIn("git pull --rebase --autostash origin \"$BRANCH\"", self.canonical_script)
        self.assertNotIn("git pull --rebase --autostash origin \"$BRANCH\" ||", self.canonical_script)
        self.assertNotIn('git commit -m "chore: bump yfinance to ${LATEST_VERSION} and trigger auto-rebuild" ||', self.canonical_script)
        self.assertIn('YFINANCE_LATEST:-$(fetch_pypi_version)', self.canonical_script)

    def test_legacy_shell_entrypoint_delegates_to_canonical_updater(self):
        self.assertIn('exec bash "$repo_dir/check_and_update_yfinance.sh" "$@"', self.legacy_script)

    def test_release_comparison(self):
        for current, latest, expected in [
            ("1.7.0", "1.7.0", False),
            ("1.7.0", "1.6.9", False),
            ("1.9.0", "1.10.0", True),
            ("1.7", "1.7.0", False),
        ]:
            with self.subTest(current=current, latest=latest):
                self.assertEqual(is_newer(current, latest), expected)
        with self.assertRaises(ValueError):
            is_newer("1.7.0", "garbage")

    def test_actual_workflow_checker_equal_older_and_newer(self):
        code = textwrap.dedent(self.workflow.split("python3 - << 'PY'\n", 1)[1].split("\n          PY", 1)[0])
        for latest, changed in [("1.7.0", False), ("1.6.0", False), ("1.8.0", True)]:
            with self.subTest(latest=latest), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                requirements = root / "requirements.txt"
                original = "yfinance==1.7.0\nrequests\n"
                requirements.write_text(original)
                env = {"GITHUB_OUTPUT": str(root / "output"), "GITHUB_STEP_SUMMARY": str(root / "summary")}
                response = io.BytesIO(json.dumps({"info": {"version": latest}}).encode())
                with contextlib.chdir(root), patch.dict(os.environ, env), patch("urllib.request.urlopen", return_value=response):
                    exec(compile(code, "workflow-checker", "exec"), {})
                self.assertIn(f"updated={str(changed).lower()}", (root / "output").read_text())
                self.assertEqual(requirements.read_text(), original.replace("1.7.0", latest) if changed else original)

    def test_shell_same_and_older_versions_leave_git_untouched(self):
        for latest in ["1.7.0", "1.6.0"]:
            with self.subTest(latest=latest), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "scripts").mkdir()
                shutil.copy(CANONICAL_SCRIPT, root)
                shutil.copy(CANONICAL_SCRIPT.parent / "scripts/yfinance_version.py", root / "scripts")
                (root / "requirements.txt").write_text("yfinance==1.7.0\n")
                def git(*args):
                    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
                git("init", "-q")
                git("add", ".")
                git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture")
                before = git("rev-parse", "HEAD")
                result = subprocess.run(["bash", str(root / CANONICAL_SCRIPT.name)], cwd=root, env={**os.environ, "SKIP_GIT_PULL": "1", "YFINANCE_LATEST": latest}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(git("rev-parse", "HEAD"), before)
                self.assertEqual(git("status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
