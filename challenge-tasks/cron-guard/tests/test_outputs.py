import json
import os
import shutil
import subprocess

import pytest

REPORT = "/app/output/cron-guard.json"
INPUT = "/app/input"
CROND = os.path.join(INPUT, "crontab.d")


@pytest.fixture(scope="session")
def run_tool():
    """Callable to run cron-guard and return CompletedProcess."""

    def _run():
        return subprocess.run(["cron-guard"], capture_output=True, text=True)

    return _run


@pytest.fixture(scope="session")
def baseline_report(run_tool):
    """Run once and load the report for stable checks."""
    run_tool()
    with open(REPORT, "r", encoding="utf-8") as f:
        return json.load(f)


def current_report():
    """Load the latest report from disk."""
    with open(REPORT, "r", encoding="utf-8") as f:
        return json.load(f)


def job_by_cmd(rep, needle):
    """Find the first job whose command contains needle."""
    for j in rep["jobs"]:
        if needle in j["command"]:
            return j
    raise AssertionError(f"job containing {needle!r} not found")


def test_cli_on_path():
    """cron-guard binary should be available on PATH."""
    r = subprocess.run(["which", "cron-guard"], capture_output=True, text=True)
    assert r.returncode == 0


def test_runs_and_writes(run_tool):
    """Tool should run and write the JSON report file."""
    r = run_tool()
    assert r.returncode in (0, 1), f"bad exit {r.returncode}\n{r.stdout}\n{r.stderr}"
    assert os.path.exists(REPORT)


def test_schema_and_summary(baseline_report):
    """Report must have jobs list and a summary object with counts."""
    rep = baseline_report
    assert isinstance(rep.get("jobs"), list)
    s = rep.get("summary", {})
    for k in (
        "total_jobs",
        "total_findings",
        "high_findings",
        "jobs_without_path",
        "uses_sudo_count",
        "no_output_capture_count",
        "duplicate_job_count",
    ):
        assert isinstance(s.get(k), int), f"summary.{k} missing or not int"


def test_env_path_propagation(baseline_report):
    """PATH missing in crontab job; present after PATH line in cron.d/app.conf."""
    rep = baseline_report
    j1 = job_by_cmd(rep, "/usr/local/bin/backup-db")
    j2 = job_by_cmd(rep, "/usr/local/bin/job-a")
    assert "PATH" not in j1["env"]
    assert "PATH" in j2["env"]


def test_no_output_capture(baseline_report):
    """No output redir and empty MAILTO should be flagged."""
    rep = baseline_report
    j = job_by_cmd(rep, "rotate-temp")
    kinds = [f["type"] for f in j["findings"]]
    assert "no_output_capture" in kinds


def test_uses_sudo_high(baseline_report):
    """Commands using sudo must be flagged high."""
    rep = baseline_report
    j = job_by_cmd(rep, "systemctl restart app")
    kinds = [f["type"] for f in j["findings"]]
    assert "uses_sudo" in kinds


def test_invalid_user_field(baseline_report):
    """cron.d line missing user should be flagged invalid_user_field."""
    rep = baseline_report
    j = job_by_cmd(rep, "report-metrics")
    kinds = [f["type"] for f in j["findings"]]
    assert "invalid_user_field" in kinds


def test_duplicate_job_detection(baseline_report):
    """Duplicate schedule+command should be reported."""
    rep = baseline_report
    dup_count = rep["summary"]["duplicate_job_count"]
    assert dup_count >= 1


def test_order_is_stable(baseline_report):
    """Jobs must be sorted by (source, line_no)."""
    rep = baseline_report
    pairs = [(j["source"], j["line_no"]) for j in rep["jobs"]]
    assert pairs == sorted(pairs)


def test_exit_codes(run_tool):
    """Exit is 1 when any high finding exists; 0 when highs are removed."""
    # Baseline: sudo and invalid user are high, expect 1
    r = run_tool()
    assert r.returncode == 1
    # Temporarily move cron.d/app.conf to hide high findings
    app_conf = os.path.join(CROND, "app.conf")
    tmp = app_conf + ".tmp"
    try:
        if os.path.exists(app_conf):
            shutil.move(app_conf, tmp)
        r2 = run_tool()
        rep = current_report()
        assert rep["summary"]["high_findings"] == 0
        assert r2.returncode == 0
    finally:
        if os.path.exists(tmp):
            shutil.move(tmp, app_conf)
        run_tool()  # restore baseline
