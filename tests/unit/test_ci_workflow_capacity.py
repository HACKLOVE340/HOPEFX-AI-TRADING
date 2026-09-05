# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ci_workflow_capacity.py
=======================================
CI was starving itself, and the load budget was never measured.

**Concurrency.** Measured against the last ten Codacy runs on this repository
(3804 total), wall-clock times were 28, 30, 30, 35, 36, 40 and 44 minutes, and
almost all ended `cancelled`. The jobs cap execution at `timeout-minutes: 15`,
so those are queue waits, not work.

The cause is the concurrency configuration. `codacy.yml` and `codeql.yml` have
no `concurrency:` block at all, and `ci.yml` and `tests.yml` had:

    concurrency:
      group: ci-${{ github.ref }}-${{ github.sha }}
      cancel-in-progress: false

Keying the group on the commit SHA gives every commit its own group, so the
group can never match a second run and nothing is ever superseded — the block
is inert. Pushing five commits to a branch queues five complete pipelines, all
of which run to completion against code nobody is waiting on any more.

Grouping by ref instead, with `cancel-in-progress` on for everything except the
default branch, means a new push supersedes the old run. `main` keeps
`cancel-in-progress: false` because its runs are the release record and must
not be cancelled by the next merge.

**k6.** `k6/load_tests.js` defines six scenarios and seven thresholds — p95
latency budgets for orders, signals, ML inference and macro endpoints, and a
1% error-rate ceiling. Its own header documents `smoke` as "1 VU, 30 s (CI
gate)". No workflow referenced it, so none of those budgets had ever been
measured. `tests/unit/test_k6_load_tests.py` checks the file's *contents*,
which is not the same as running it: it would pass just as happily if every
threshold were unreachable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

WORKFLOWS = Path(".github/workflows")


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


class TestConcurrencyActuallySupersedes:
    @pytest.mark.parametrize("name", ["ci.yml", "tests.yml", "codacy.yml", "codeql.yml"])
    def test_the_workflow_declares_concurrency(self, name):
        wf = _load(name)

        assert "concurrency" in wf, (
            f"{name} has no concurrency group, so every push queues another full run; "
            f"measured Codacy wall times reached 44 minutes, almost all cancelled"
        )

    @pytest.mark.parametrize("name", ["ci.yml", "tests.yml", "codacy.yml", "codeql.yml"])
    def test_the_group_is_not_keyed_on_the_commit_sha(self, name):
        """A per-commit group can never collide, so it supersedes nothing."""
        group = str(_load(name)["concurrency"]["group"])

        assert "github.sha" not in group, (
            f"{name} keys its concurrency group on github.sha, giving every commit its "
            f"own group — the block is inert and no run is ever superseded"
        )

    @pytest.mark.parametrize("name", ["ci.yml", "tests.yml", "codacy.yml", "codeql.yml"])
    def test_the_group_is_keyed_on_the_ref(self, name):
        group = str(_load(name)["concurrency"]["group"])

        assert "github.ref" in group

    @pytest.mark.parametrize("name", ["ci.yml", "tests.yml", "codacy.yml", "codeql.yml"])
    def test_superseded_runs_are_cancelled_except_on_the_default_branch(self, name):
        """main's runs are the release record; a merge must not cancel them."""
        cancel = str(_load(name)["concurrency"]["cancel-in-progress"])

        assert "github.ref" in cancel and "refs/heads/main" in cancel, (
            f"{name} should cancel superseded runs on feature branches and PRs while "
            f"leaving main alone; got cancel-in-progress: {cancel!r}"
        )


class TestCodacyDoesNotBurnCapacityForNothing:
    def test_the_scan_is_skipped_when_its_token_is_absent(self):
        """Without CODACY_PROJECT_TOKEN the action fails immediately.

        The job carries continue-on-error: true precisely because of that, so
        every run checked out the repository and started the action only to
        swallow the failure. Skipping is the same signal for none of the cost.
        """
        job = _load("codacy.yml")["jobs"]["codacy-security-scan"]

        assert "if" in job, "the Codacy job should not run at all without its token"

    def test_the_guard_does_not_read_secrets_in_a_job_level_if(self):
        """`secrets` is not available there, so the check silently inverts.

        A first attempt used `if: ${{ secrets.CODACY_PROJECT_TOKEN != '' }}`.
        GitHub does not expose the secrets context to a job-level `if`, so that
        evaluates as '' != '' and skips the job unconditionally — including for
        the repositories that do have the token configured. The guard has to
        come through `needs`, which *is* available there.
        """
        job = _load("codacy.yml")["jobs"]["codacy-security-scan"]
        condition = str(job["if"])

        assert "secrets." not in condition, (
            "the secrets context is unavailable in a job-level if; this condition "
            "is always false and the job never runs"
        )
        assert "needs." in condition

    def test_the_gate_job_reads_the_secret_where_it_is_allowed(self):
        gate = _load("codacy.yml")["jobs"]["token-check"]
        probe = gate["steps"][0]

        assert "CODACY_PROJECT_TOKEN" in str(probe.get("env", {})), "a step env: is where a secret can legally be read"
        assert "has_token" in str(gate["outputs"])

    def test_the_pr_quality_gate_still_runs_unconditionally(self):
        """ruff + bandit on changed files is the job in this file with teeth."""
        job = _load("codacy.yml")["jobs"]["pr-quality-gate"]

        assert "if" not in job or "CODACY" not in str(job.get("if", ""))


class TestK6IsActuallyRun:
    def test_a_workflow_references_the_load_tests(self):
        referencing = [p.name for p in WORKFLOWS.glob("*.yml") if "k6" in p.read_text()]

        assert referencing, (
            "k6/load_tests.js defines seven latency and error-rate thresholds and no "
            "workflow runs it, so none of those budgets has ever been measured"
        )

    def test_it_runs_on_a_schedule_and_on_demand(self):
        """Not on pull requests, and the workflow says why.

        Driven against a real server the suite reaches 96% of checks passing
        with http_req_failed at 3.64%, and every one of those failures is
        /api/trading/ohlcv/{symbol} answering 503 because no market-data feed is
        attached. Making that a required check would be red for an environmental
        reason — the pathology being removed from codacy.yml in this same change.
        """
        wf = _load("load-test.yml")
        triggers = wf.get(True, wf.get("on", {}))

        assert "schedule" in triggers
        assert "workflow_dispatch" in triggers
        assert "pull_request" not in triggers

    def test_every_scenario_is_reachable_on_demand(self):
        wf = _load("load-test.yml")
        options = wf.get(True, wf.get("on", {}))["workflow_dispatch"]["inputs"]["scenario"]["options"]

        assert set(options) == {"smoke", "load", "soak", "spike", "stress", "breakpoint"}

    def test_the_run_is_authenticated(self):
        """Without a token the suite reaches four public endpoints and measures
        none of the latency budgets it exists for."""
        raw = (WORKFLOWS / "load-test.yml").read_text()

        assert "AUTH_TOKEN" in raw
        assert "add-mask" in raw, "a minted token must not be printable in the log"

    def test_the_job_fails_when_a_threshold_is_breached(self):
        """k6 exits non-zero on a threshold breach; nothing may swallow that."""
        raw = (WORKFLOWS / "load-test.yml").read_text()

        assert "continue-on-error: true" not in raw, "a load gate that cannot fail measures nothing"

    def test_the_app_is_started_before_the_load_test_runs(self):
        raw = (WORKFLOWS / "load-test.yml").read_text()

        assert "BASE_URL" in raw
        assert "run.py" in raw or "uvicorn" in raw, "k6 needs something to load"
