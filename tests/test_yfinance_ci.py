"""Regression tests for the yfinance version-check workflow contract."""

from pathlib import Path
import unittest


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


if __name__ == "__main__":
    unittest.main()
