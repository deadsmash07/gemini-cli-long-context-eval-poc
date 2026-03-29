#!/bin/bash
set -e

cat > /usr/local/bin/hook-gen << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
import json
import os
import sys
from collections import OrderedDict
from pathlib import Path

def detect_project_type(project_path):
    """Detect if project is Python or JavaScript."""
    project_files = list(Path(project_path).rglob('*'))

    has_package_json = any(f.name == 'package.json' for f in project_files)
    has_python_files = any(
        f.name in ['requirements.txt', 'setup.py', 'pyproject.toml']
        for f in project_files
    )

    if has_package_json:
        return 'javascript'
    elif has_python_files:
        return 'python'
    else:
        return None

def generate_python_precommit_hook(checks):
    """Generate pre-commit hook for Python projects."""
    hook_lines = ['#!/bin/bash', '', 'set -e', '']
    hook_lines.append('# Get list of staged Python files')
    hook_lines.append(
        'STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | '
        r'grep -E "\.py$" || true)'
    )
    hook_lines.append('')
    hook_lines.append('if [ -z "$STAGED_FILES" ]; then')
    hook_lines.append('  exit 0')
    hook_lines.append('fi')
    hook_lines.append('')

    if 'linting' in checks:
        hook_lines.append('# Run linting')
        hook_lines.append('echo "Running ruff check..."')
        hook_lines.append('if ! ruff check $STAGED_FILES; then')
        hook_lines.append('  echo "Error: Linting failed. Fix issues before committing."')
        hook_lines.append('  exit 1')
        hook_lines.append('fi')
        hook_lines.append('')

    hook_lines.append('echo "✓ Pre-commit checks passed"')
    hook_lines.append('exit 0')

    return '\n'.join(hook_lines)

def generate_python_prepush_hook(checks):
    """Generate pre-push hook for Python projects."""
    hook_lines = ['#!/bin/bash', '', 'set -e', '']

    if 'testing' in checks:
        hook_lines.append('# Run tests')
        hook_lines.append('echo "Running pytest..."')
        hook_lines.append('if ! pytest --cov --cov-fail-under=80; then')
        hook_lines.append('  echo "Error: Tests failed or coverage below 80%"')
        hook_lines.append('  exit 1')
        hook_lines.append('fi')
        hook_lines.append('')

    if 'linting' in checks:
        hook_lines.append('# Run linting on modified files')
        hook_lines.append('echo "Running ruff check on modified files..."')
        hook_lines.append(r'MODIFIED_FILES=$(git diff --name-only main...HEAD | grep -E "\.py$" || true)')
        hook_lines.append('if [ -n "$MODIFIED_FILES" ]; then')
        hook_lines.append('  if ! ruff check $MODIFIED_FILES; then')
        hook_lines.append('    echo "Error: Linting failed on modified files"')
        hook_lines.append('    exit 1')
        hook_lines.append('  fi')
        hook_lines.append('fi')
        hook_lines.append('')

    hook_lines.append('echo "✓ Pre-push checks passed"')
    hook_lines.append('exit 0')

    return '\n'.join(hook_lines)

def generate_javascript_precommit_hook(checks):
    """Generate pre-commit hook for JavaScript projects."""
    hook_lines = ['#!/bin/bash', '', 'set -e', '']
    hook_lines.append('# Get list of staged JavaScript files')
    hook_lines.append(
        'STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | '
        'grep -E "\\.(js|jsx|ts|tsx)$" || true)'
    )
    hook_lines.append('')
    hook_lines.append('if [ -z "$STAGED_FILES" ]; then')
    hook_lines.append('  exit 0')
    hook_lines.append('fi')
    hook_lines.append('')

    if 'linting' in checks:
        hook_lines.append('# Run linting')
        hook_lines.append('echo "Running eslint..."')
        hook_lines.append('if ! npx eslint $STAGED_FILES; then')
        hook_lines.append('  echo "Error: Linting failed. Fix issues before committing."')
        hook_lines.append('  exit 1')
        hook_lines.append('fi')
        hook_lines.append('')

    hook_lines.append('echo "✓ Pre-commit checks passed"')
    hook_lines.append('exit 0')

    return '\n'.join(hook_lines)

def generate_javascript_prepush_hook(checks):
    """Generate pre-push hook for JavaScript projects."""
    hook_lines = ['#!/bin/bash', '', 'set -e', '']

    if 'testing' in checks:
        hook_lines.append('# Run tests')
        hook_lines.append('echo "Running npm test..."')
        hook_lines.append('if ! npm test -- --coverage --coverageThreshold=\'{"global":{"lines":80}}\'; then')
        hook_lines.append('  echo "Error: Tests failed or coverage below 80%"')
        hook_lines.append('  exit 1')
        hook_lines.append('fi')
        hook_lines.append('')

    if 'linting' in checks:
        hook_lines.append('# Run linting on modified files')
        hook_lines.append('echo "Running eslint on modified files..."')
        hook_lines.append('MODIFIED_FILES=$(git diff --name-only main...HEAD | grep -E "\\.(js|jsx|ts|tsx)$" || true)')
        hook_lines.append('if [ -n "$MODIFIED_FILES" ]; then')
        hook_lines.append('  if ! npx eslint $MODIFIED_FILES; then')
        hook_lines.append('    echo "Error: Linting failed on modified files"')
        hook_lines.append('    exit 1')
        hook_lines.append('  fi')
        hook_lines.append('fi')
        hook_lines.append('')

    hook_lines.append('echo "✓ Pre-push checks passed"')
    hook_lines.append('exit 0')

    return '\n'.join(hook_lines)

def main():
    config_file = Path('/app/input/hook-config.json')
    project_path = Path('/app/project')
    output_dir = Path('/app/output/hooks')
    output_json = Path('/app/output/hook-report.json')

    # Check if config exists
    if not config_file.exists():
        print("Error: Configuration file not found at /app/input/hook-config.json", file=sys.stderr)
        sys.exit(1)

    # Load config
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
    except json.JSONDecodeError:
        print("Error: Invalid JSON in configuration file", file=sys.stderr)
        sys.exit(1)

    # Detect project type
    project_type = detect_project_type(project_path)
    if not project_type:
        print("Error: Could not detect project type. Expected package.json or requirements.txt/setup.py", file=sys.stderr)
        sys.exit(1)

    # Prepare output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine which checks are enabled
    checks_config = OrderedDict()

    # Parse config
    linting_config = config.get('linting', {})
    testing_config = config.get('testing', {})
    commit_format_config = config.get('commit_format', {})

    # Build checks_configured
    linting_tool = 'ruff' if project_type == 'python' else 'eslint'
    testing_command = 'pytest --cov --cov-fail-under=80' if project_type == 'python' else 'npm test -- --coverage'

    linting_hooks = []
    if linting_config.get('enabled'):
        if linting_config.get('pre_commit'):
            linting_hooks.append('pre-commit')
        if linting_config.get('pre_push'):
            linting_hooks.append('pre-push')

    testing_hooks = []
    if testing_config.get('enabled'):
        if testing_config.get('pre_commit'):
            testing_hooks.append('pre-commit')
        if testing_config.get('pre_push'):
            testing_hooks.append('pre-push')

    commit_format_hooks = []
    if commit_format_config.get('enabled'):
        if commit_format_config.get('pre_commit'):
            commit_format_hooks.append('pre-commit')
        if commit_format_config.get('pre_push'):
            commit_format_hooks.append('pre-push')

    checks_config['linting'] = OrderedDict([
        ('enabled', linting_config.get('enabled', False)),
        ('tool', linting_tool),
        ('hooks', linting_hooks)
    ])

    checks_config['testing'] = OrderedDict([
        ('enabled', testing_config.get('enabled', False)),
        ('command', testing_command),
        ('hooks', testing_hooks)
    ])

    checks_config['commit_format'] = OrderedDict([
        ('enabled', commit_format_config.get('enabled', False)),
        ('standard', 'conventional-commits'),
        ('hooks', commit_format_hooks)
    ])

    # Generate hooks
    hooks_generated = []

    # Determine which checks go in pre-commit and pre-push
    all_checks = {
        'linting': linting_config,
        'testing': testing_config,
        'commit_format': commit_format_config
    }
    precommit_checks = [
        name for name, cfg in all_checks.items()
        if cfg.get('enabled') and cfg.get('pre_commit')
    ]
    prepush_checks = [
        name for name, cfg in all_checks.items()
        if cfg.get('enabled') and cfg.get('pre_push')
    ]

    # Generate pre-commit hook
    if precommit_checks:
        hook_path = output_dir / 'pre-commit'
        if project_type == 'python':
            hook_content = generate_python_precommit_hook(precommit_checks)
        else:
            hook_content = generate_javascript_precommit_hook(precommit_checks)

        with open(hook_path, 'w') as f:
            f.write(hook_content)
        os.chmod(hook_path, 0o755)

        hooks_generated.append(OrderedDict([
            ('hook_name', 'pre-commit'),
            ('hook_path', str(hook_path)),
            ('checks_enabled', sorted(precommit_checks)),
            ('executable', True)
        ]))

    # Generate pre-push hook
    if prepush_checks:
        hook_path = output_dir / 'pre-push'
        if project_type == 'python':
            hook_content = generate_python_prepush_hook(prepush_checks)
        else:
            hook_content = generate_javascript_prepush_hook(prepush_checks)

        with open(hook_path, 'w') as f:
            f.write(hook_content)
        os.chmod(hook_path, 0o755)

        hooks_generated.append(OrderedDict([
            ('hook_name', 'pre-push'),
            ('hook_path', str(hook_path)),
            ('checks_enabled', sorted(prepush_checks)),
            ('executable', True)
        ]))

    # Sort hooks by name
    hooks_generated.sort(key=lambda x: x['hook_name'])

    # Build report
    report = OrderedDict([
        ('project_type', project_type),
        ('project_path', str(project_path)),
        ('hooks_generated', hooks_generated),
        ('checks_configured', checks_config)
    ])

    # Write JSON report
    with open(output_json, 'w') as f:
        json.dump(report, f, indent=2)

if __name__ == '__main__':
    main()
PYTHON_SCRIPT

chmod +x /usr/local/bin/hook-gen
