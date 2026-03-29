import json
import os
import subprocess


def test_script_exists():
    """Test that hook-gen script exists and is executable."""
    assert os.path.exists('/usr/local/bin/hook-gen')
    assert os.access('/usr/local/bin/hook-gen', os.X_OK)


def test_report_json_generated():
    """Test that hook report JSON is generated."""
    assert os.path.exists('/app/output/hook-report.json')


def test_hooks_directory_created():
    """Test that hooks directory is created."""
    assert os.path.exists('/app/output/hooks')
    assert os.path.isdir('/app/output/hooks')


def test_report_structure():
    """Test that report has correct top-level structure."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    assert 'project_type' in report
    assert 'project_path' in report
    assert 'hooks_generated' in report
    assert 'checks_configured' in report


def test_project_type_detected():
    """Test that project type is correctly detected."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    assert report['project_type'] in ['python', 'javascript']


def test_python_project_detection():
    """Test that Python project is correctly detected."""
    with open('/app/output/hook-report-python.json', 'r') as f:
        report = json.load(f)

    assert report['project_type'] == 'python'


def test_javascript_project_detection():
    """Test that JavaScript project is correctly detected."""
    with open('/app/output/hook-report-javascript.json', 'r') as f:
        report = json.load(f)

    assert report['project_type'] == 'javascript'


def test_hooks_generated_structure():
    """Test that hooks_generated has correct structure."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    for hook in report['hooks_generated']:
        assert 'hook_name' in hook
        assert 'hook_path' in hook
        assert 'checks_enabled' in hook
        assert 'executable' in hook
        assert hook['hook_name'] in ['pre-commit', 'pre-push']
        assert isinstance(hook['checks_enabled'], list)
        assert isinstance(hook['executable'], bool)


def test_checks_configured_structure():
    """Test that checks_configured has correct structure."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    checks = report['checks_configured']

    assert 'linting' in checks
    assert 'testing' in checks
    assert 'commit_format' in checks

    for check_name, check_config in checks.items():
        assert 'enabled' in check_config
        assert 'hooks' in check_config
        assert isinstance(check_config['enabled'], bool)
        assert isinstance(check_config['hooks'], list)


def test_linting_config():
    """Test that linting configuration is present."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    linting = report['checks_configured']['linting']
    assert 'tool' in linting
    assert linting['tool'] in ['ruff', 'eslint', 'flake8']


def test_testing_config():
    """Test that testing configuration is present."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    testing = report['checks_configured']['testing']
    assert 'command' in testing
    assert isinstance(testing['command'], str)


def test_commit_format_config():
    """Test that commit format configuration is present."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    commit_format = report['checks_configured']['commit_format']
    assert 'standard' in commit_format
    assert commit_format['standard'] == 'conventional-commits'


def test_python_linting_tool():
    """Test that Python projects use appropriate linting tool."""
    with open('/app/output/hook-report-python.json', 'r') as f:
        report = json.load(f)

    assert report['checks_configured']['linting']['tool'] in ['ruff', 'flake8']


def test_javascript_linting_tool():
    """Test that JavaScript projects use eslint."""
    with open('/app/output/hook-report-javascript.json', 'r') as f:
        report = json.load(f)

    assert report['checks_configured']['linting']['tool'] == 'eslint'


def test_hooks_are_executable():
    """Test that generated hooks are executable."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    for hook in report['hooks_generated']:
        assert hook['executable'] is True
        hook_path = hook['hook_path']
        assert os.path.exists(hook_path)
        assert os.access(hook_path, os.X_OK)


def test_hooks_have_shebang():
    """Test that generated hooks have shebang."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    for hook in report['hooks_generated']:
        hook_path = hook['hook_path']
        with open(hook_path, 'r') as f:
            first_line = f.readline()
        # Accept both #!/bin/bash and #!/usr/bin/env bash
        valid_shebangs = ['#!/bin/bash', '#!/usr/bin/env bash']
        assert first_line.strip() in valid_shebangs, \
            f"Expected one of {valid_shebangs}, got {first_line.strip()}"


def test_precommit_hook_generated():
    """Test that pre-commit hook is generated when configured."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    hook_names = [h['hook_name'] for h in report['hooks_generated']]
    assert 'pre-commit' in hook_names


def test_prepush_hook_generated():
    """Test that pre-push hook is generated when configured."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    hook_names = [h['hook_name'] for h in report['hooks_generated']]
    assert 'pre-push' in hook_names


def test_hooks_sorted_alphabetically():
    """Test that hooks are sorted by name."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    hook_names = [h['hook_name'] for h in report['hooks_generated']]
    assert hook_names == sorted(hook_names)


def test_precommit_has_correct_checks():
    """Test that pre-commit hook has correct checks enabled."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    precommit = next(
        (h for h in report['hooks_generated'] if h['hook_name'] == 'pre-commit'),
        None,
    )
    assert precommit is not None

    # Based on our test config: linting and commit_format in pre-commit
    checks = precommit['checks_enabled']
    assert 'linting' in checks or 'commit_format' in checks


def test_prepush_has_correct_checks():
    """Test that pre-push hook has correct checks enabled."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    prepush = next(
        (h for h in report['hooks_generated'] if h['hook_name'] == 'pre-push'),
        None,
    )
    assert prepush is not None

    # Based on our test config: testing in pre-push
    assert 'testing' in prepush['checks_enabled']


def test_python_hook_contains_ruff():
    """Test that Python pre-commit hook contains linting commands."""
    with open('/app/output/hook-report-python.json', 'r') as f:
        report = json.load(f)

    precommit = next(
        (h for h in report['hooks_generated'] if h['hook_name'] == 'pre-commit'),
        None,
    )

    if precommit and 'linting' in precommit['checks_enabled']:
        with open(precommit['hook_path'], 'r') as f:
            content = f.read()
        # Check that hook uses a Python linting tool (ruff, flake8, pylint, etc.)
        linting_tools = ['ruff', 'flake8', 'pylint', 'lint']
        assert any(tool in content.lower() for tool in linting_tools), \
            "Hook should contain Python linting commands"


def test_python_hook_contains_pytest():
    """Test that Python pre-push hook contains testing commands."""
    with open('/app/output/hook-report-python.json', 'r') as f:
        report = json.load(f)

    prepush = next(
        (h for h in report['hooks_generated'] if h['hook_name'] == 'pre-push'),
        None,
    )

    if prepush and 'testing' in prepush['checks_enabled']:
        with open(prepush['hook_path'], 'r') as f:
            content = f.read()
        # Check that hook uses a Python testing tool (pytest, unittest, nose, etc.)
        testing_tools = ['pytest', 'unittest', 'nose', 'test']
        assert any(tool in content.lower() for tool in testing_tools), \
            "Hook should contain Python testing commands"


def test_javascript_hook_contains_eslint():
    """Test that JavaScript pre-commit hook contains linting commands."""
    with open('/app/output/hook-report-javascript.json', 'r') as f:
        report = json.load(f)

    # Verify project type is JavaScript
    assert report['project_type'] == 'javascript'

    precommit = next(
        (h for h in report['hooks_generated'] if h['hook_name'] == 'pre-commit'),
        None,
    )

    if precommit and 'linting' in precommit['checks_enabled']:
        # Hook file should exist
        assert os.path.exists(precommit['hook_path'])
        # Tool should be a JavaScript linter (eslint, standard, jshint, etc.)
        linting_tool = report['checks_configured']['linting']['tool']
        js_linters = ['eslint', 'standard', 'jshint', 'jslint', 'lint']
        assert any(linter in linting_tool.lower() for linter in js_linters), \
            f"Expected JavaScript linting tool, got: {linting_tool}"


def test_javascript_hook_contains_npm_test():
    """Test that JavaScript pre-push hook contains npm test commands."""
    with open('/app/output/hook-report-javascript.json', 'r') as f:
        report = json.load(f)

    # Verify project type is JavaScript
    assert report['project_type'] == 'javascript'

    prepush = next(
        (h for h in report['hooks_generated'] if h['hook_name'] == 'pre-push'),
        None,
    )

    if prepush and 'testing' in prepush['checks_enabled']:
        # Hook file should exist
        assert os.path.exists(prepush['hook_path'])
        # Command should use npm/yarn/pnpm for JavaScript testing
        command = report['checks_configured']['testing']['command']
        valid_tools = ['npm test', 'yarn test', 'pnpm test', 'npm run test']
        assert any(tool in command for tool in valid_tools), \
            f"Expected JavaScript testing command, got: {command}"


def test_hook_has_error_messages():
    """Test that hooks have helpful error messages."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    for hook in report['hooks_generated']:
        with open(hook['hook_path'], 'r') as f:
            content = f.read()
        assert 'Error:' in content or 'error' in content.lower()


def test_hook_exits_on_failure():
    """Test that hooks include exit 1 for failures."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    for hook in report['hooks_generated']:
        with open(hook['hook_path'], 'r') as f:
            content = f.read()
        assert 'exit 1' in content


def test_checks_enabled_is_sorted():
    """Test that checks_enabled list is sorted."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    for hook in report['hooks_generated']:
        checks = hook['checks_enabled']
        assert checks == sorted(checks)


def test_enabled_checks_match_hooks():
    """Test that enabled checks match the hooks they're in."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    for check_name, check_config in report['checks_configured'].items():
        if check_config['enabled']:
            for hook_name in check_config['hooks']:
                # Find the hook
                hook = next(
                    (
                        h
                        for h in report['hooks_generated']
                        if h['hook_name'] == hook_name
                    ),
                    None,
                )
                if hook:
                    assert check_name in hook['checks_enabled']


def test_project_path_included():
    """Test that project path is included in report."""
    with open('/app/output/hook-report.json', 'r') as f:
        report = json.load(f)

    assert '/app/project' in report['project_path']


def test_exit_code_success():
    """Test that script exits with code 0 on success."""
    result = subprocess.run(
        ['/usr/local/bin/hook-gen'], capture_output=True, text=True
    )
    assert result.returncode == 0

