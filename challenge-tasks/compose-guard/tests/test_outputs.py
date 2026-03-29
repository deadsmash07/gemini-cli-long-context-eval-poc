import json
import subprocess
from pathlib import Path

CLI = "/usr/local/bin/compose-guard"
INPUT = Path("/app/input")


def run(*paths):
    res = subprocess.run([CLI, *map(str, paths)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    try:
        data = json.loads(res.stdout.strip() or "[]")
    except Exception as e:
        raise AssertionError(f"invalid JSON: {res.stdout}") from e
    return data


def rules(data, rule):
    return [v for v in data if v.get("rule") == rule]


def find(data, rule, service):
    return [v for v in data if v.get("rule") == rule and v.get("service") == service]


def test_immutable_image_and_limits_and_healthcheck():
    """Services must pin images, set resource limits, and define healthchecks."""
    data = run(INPUT / "simple" / "compose.yaml")
    imm = find(data, "IMAGE_IMMUTABLE", "web")
    assert imm and imm[0]["path"] == "services.web.image"
    hc = [
        v
        for v in data
        if v["rule"] == "HEALTHCHECK_AND_LIMITS"
        and v["service"] == "web"
        and v["path"].endswith(".healthcheck")
    ]
    lim = [
        v
        for v in data
        if v["rule"] == "HEALTHCHECK_AND_LIMITS"
        and v["service"] == "web"
        and ("limits" in v["path"] or "mem_limit" in v["path"])
    ]
    assert hc, data
    assert lim, data


def test_build_exemption_and_ok_service_has_no_violations():
    """Services built from source and configured correctly produce no violations."""
    data = run(INPUT / "simple" / "compose.yaml")
    svc_ok = [v for v in data if v.get("service") == "worker"]
    assert not svc_ok, svc_ok


def test_extends_across_files_and_precedence_and_ports_trigger():
    """Extends chains still flag missing health checks and limits after overrides."""
    data = run(INPUT / "extends" / "docker-compose.yaml")
    imm = find(data, "IMAGE_IMMUTABLE", "api")
    assert imm and imm[0]["path"] == "services.api.image"
    hc = [
        v
        for v in data
        if v["rule"] == "HEALTHCHECK_AND_LIMITS"
        and v["service"] == "web"
        and v["path"].endswith(".healthcheck")
    ]
    lim = [
        v
        for v in data
        if v["rule"] == "HEALTHCHECK_AND_LIMITS"
        and v["service"] == "web"
        and ("limits" in v["path"] or "mem_limit" in v["path"])
    ]
    assert hc and lim, data


def test_env_precedence_inline_over_envfile_over_dotenv_over_missing():
    """Inline env vars override env files, dotenv files, and missing defaults."""
    data = run(INPUT / "envmerge" / "compose.yml")
    imm = find(data, "IMAGE_IMMUTABLE", "ui")
    assert imm and "services.ui.image" == imm[0]["path"], data


def test_deterministic_ordering_by_file_then_service_then_path():
    """Violation ordering remains deterministic regardless of CLI argument order."""
    d1 = run(
        INPUT / "extends" / "docker-compose.yaml", INPUT / "simple" / "compose.yaml"
    )
    d2 = run(
        INPUT / "simple" / "compose.yaml", INPUT / "extends" / "docker-compose.yaml"
    )
    assert d1 == d2, "ordering must not depend on argv order"


def test_cycle_in_extends_is_reported_once_and_processing_continues():
    """Extends cycles are reported once and linting continues for other services."""
    data = run(INPUT / "cycles" / "compose.yaml")
    cyc = rules(data, "EXTENDS_CYCLE")
    assert len(cyc) == 1, data

    imm = find(data, "IMAGE_IMMUTABLE", "lonely")
    assert imm, data
