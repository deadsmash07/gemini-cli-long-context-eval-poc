"""
Run challenge task evaluations on Modal cloud VMs.

Each task gets its own container with the environment pre-built.
Gemini API is called from inside the container to generate solutions,
which are then tested with pytest.

Usage:
    modal run runner/modal_challenge_eval.py
    modal run runner/modal_challenge_eval.py --model gemini-2.5-pro
    modal run runner/modal_challenge_eval.py --task git-hook-generator
"""

import json
import os
import subprocess
import time
from pathlib import Path

import modal

app = modal.App("challenge-eval")

# Base image with Python 3.11 + common deps
base_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "curl")
    .pip_install("pytest==8.2.0", "requests")
)


def read_task_files(task_dir: Path) -> dict:
    """Read instruction and environment files from a task directory."""
    instruction = (task_dir / "instruction.md").read_text()

    env_files = {}
    env_dir = task_dir / "environment"
    if env_dir.exists():
        for f in env_dir.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                rel = str(f.relative_to(env_dir))
                content = f.read_text(errors="replace")
                if len(content) < 5000 and rel not in ("Dockerfile", "docker-compose.yaml"):
                    env_files[rel] = content

    return {"instruction": instruction, "env_files": env_files}


def build_prompt(instruction: str, env_files: dict) -> str:
    """Build the prompt for Gemini API."""
    prompt = f"""You are a senior software engineer. Solve the following coding task.

## Task

{instruction}

## Environment Files

These files exist in the working environment:

"""
    for path, content in env_files.items():
        prompt += f"### {path}\n```\n{content}\n```\n\n"

    prompt += """## Output Format

Write a complete bash script that creates or modifies files to make all tests pass.
Use heredocs to write files: cat << 'EOF' > /path/to/file
All code must work with Python 3.11 and pytest.

Output ONLY a single ```bash code block. No explanation."""

    return prompt


def call_gemini(prompt: str, model: str, api_key: str) -> dict:
    """Call Gemini REST API."""
    import requests as req

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    start = time.time()

    resp = req.post(url, json={
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 16384},
    }, timeout=120)

    duration_ms = int((time.time() - start) * 1000)

    if resp.status_code != 200:
        raise RuntimeError(f"API {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    tokens = data.get("usageMetadata", {}).get("totalTokenCount", 0)

    return {"text": text, "tokens": tokens, "duration_ms": duration_ms}


def extract_solution(response: str) -> str:
    """Extract bash script from model response."""
    import re
    m = re.search(r"```(?:bash|sh)\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r"```\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1)
    return response


def parse_pytest_output(output: str) -> dict:
    """Parse pytest output for pass/fail counts."""
    import re
    # Match the summary line like "28 failed, 2 passed" or "6 failed" or "1 passed, 7 errors"
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    errors = int(m.group(1)) if (m := re.search(r"(\d+) error", output)) else 0
    total = passed + failed + errors
    return {"passed": passed, "failed": failed + errors, "total": total if total > 0 else 1}


@app.function(
    image=base_image,
    timeout=600,
    secrets=[modal.Secret.from_name("gemini-api-key")],
)
def evaluate_task(
    task_name: str,
    instruction: str,
    env_files: dict,
    test_files: dict,
    solution_script: str,
    model: str,
    api_key: str,
) -> dict:
    """Run a single challenge task evaluation inside a Modal container."""
    import tempfile

    result = {
        "task": task_name,
        "model": model,
        "status": "error",
        "testsPassed": 0,
        "testsFailed": 0,
        "testsTotal": 0,
        "passRate": 0,
        "apiDurationMs": 0,
        "apiTokens": 0,
        "solutionLength": 0,
    }

    # Set up working directory
    work_dir = Path(tempfile.mkdtemp())
    app_dir = work_dir / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    # Write environment files
    for rel_path, content in env_files.items():
        p = app_dir / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    # Write test files
    test_dir = work_dir / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in test_files.items():
        p = test_dir / rel_path
        p.write_text(content)

    # Call Gemini API
    try:
        prompt = build_prompt(instruction, env_files)
        api_result = call_gemini(prompt, model, api_key)
        result["apiDurationMs"] = api_result["duration_ms"]
        result["apiTokens"] = api_result["tokens"]

        solution = extract_solution(api_result["text"])
        result["solutionLength"] = len(solution)
    except Exception as e:
        result["error"] = str(e)
        return result

    # Apply solution
    solution_path = work_dir / "solve.sh"
    solution_path.write_text(solution)

    try:
        subprocess.run(
            ["bash", str(solution_path)],
            cwd=str(app_dir),
            timeout=120,
            capture_output=True,
        )
    except Exception:
        pass  # Solution may partially fail, still run tests

    # Run tests
    try:
        test_result = subprocess.run(
            ["python3", "-m", "pytest", str(test_dir), "-v", "--tb=short"],
            cwd=str(work_dir),
            timeout=120,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(app_dir)},
        )
        output = test_result.stdout + test_result.stderr
        parsed = parse_pytest_output(output)
        result.update(parsed)
        result["passRate"] = parsed["passed"] / parsed["total"] if parsed["total"] > 0 else 0
        result["status"] = "pass" if result["passRate"] == 1 else ("partial" if result["passRate"] > 0 else "fail")
        result["testOutput"] = output[-500:]
    except Exception as e:
        result["error"] = f"Test execution failed: {e}"

    return result


@app.local_entrypoint()
def main(model: str = "gemini-2.5-flash", task: str = ""):
    """Run challenge evals on Modal."""
    # Load API key
    env_path = Path(__file__).parent.parent / ".env"
    api_key = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                api_key = line.split("=", 1)[1].strip()

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")

    if not api_key:
        print("Error: GEMINI_API_KEY required")
        return

    # Find tasks
    challenge_dir = Path(__file__).parent.parent / "challenge-tasks"
    task_dirs = sorted([
        d for d in challenge_dir.iterdir()
        if d.is_dir() and (d / "task.toml").exists()
        and (not task or task in d.name)
    ])

    print(f"\nChallenge Task Evaluation (Modal)")
    print(f"Model: {model}")
    print(f"Tasks: {len(task_dirs)}\n")

    # Prepare task data
    tasks_data = []
    for td in task_dirs:
        data = read_task_files(td)

        # Read test files
        test_files = {}
        test_dir = td / "tests"
        if test_dir.exists():
            for f in test_dir.iterdir():
                if f.is_file() and f.suffix == ".py":
                    test_files[f.name] = f.read_text()

        # Read solution for reference
        solution_path = td / "solution" / "solve.sh"
        solution = solution_path.read_text() if solution_path.exists() else ""

        tasks_data.append({
            "task_name": td.name,
            "instruction": data["instruction"],
            "env_files": data["env_files"],
            "test_files": test_files,
            "solution_script": solution,
            "model": model,
            "api_key": api_key,
        })

    # Run all tasks in parallel on Modal
    results = list(evaluate_task.starmap(
        [(d["task_name"], d["instruction"], d["env_files"], d["test_files"],
          d["solution_script"], d["model"], d["api_key"]) for d in tasks_data]
    ))

    # Print results table
    print(f"\n{'='*100}")
    print(f"Challenge Task Results - {model} (Modal)")
    print(f"{'='*100}")
    print(f"{'Task':<38} {'Diff':<8} {'Tests':<12} {'Pass%':<8} {'Time':<8} Status")
    print("-" * 100)

    for r in results:
        name = r["task"][:37].ljust(38)
        tests = f"{r['testsPassed']}/{r['testsTotal']}".ljust(12) if r.get("testsTotal") else "N/A".ljust(12)
        rate = f"{r['passRate']*100:.0f}%".ljust(8) if r.get("testsTotal") else "-".ljust(8)
        time_s = f"{r['apiDurationMs']/1000:.0f}s".ljust(8) if r["apiDurationMs"] else "-".ljust(8)
        print(f"{name}{'':<8}{tests}{rate}{time_s}{r['status'].upper()}")

    print("-" * 100)
    ran = [r for r in results if r.get("testsTotal", 0) > 0]
    avg = sum(r["passRate"] for r in ran) / len(ran) if ran else 0
    full = sum(1 for r in ran if r["passRate"] == 1)
    print(f"Full passes: {full}/{len(ran)}  |  Avg test pass rate: {avg*100:.0f}%")
    print(f"{'='*100}\n")

    # Save results
    output_dir = Path(__file__).parent.parent / "results"
    output_dir.mkdir(exist_ok=True)
    safe_model = model.replace("/", "-").replace(".", "-")
    output_path = output_dir / f"challenge-eval-modal-{safe_model}.json"
    output_path.write_text(json.dumps({
        "model": model,
        "runtime": "modal",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": results,
    }, indent=2))
    print(f"Results saved to {output_path}")
