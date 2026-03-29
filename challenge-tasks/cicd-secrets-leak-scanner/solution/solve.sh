#!/bin/bash
set -e

cat > /usr/local/bin/cicd-secrets-scanner << 'EOF'
#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path
from collections import OrderedDict

PIPELINE_DIR = Path('/app/input/pipeline')

AWS_KEY_PATTERN = re.compile(r'AKIA[A-Z0-9]{16}')
GITHUB_TOKEN_PATTERN = re.compile(r'ghp_[a-zA-Z0-9]{36}')
BEARER_TOKEN_PATTERN = re.compile(r'Bearer\s+[A-Za-z0-9+/=]{20,}')
JWT_PATTERN = re.compile(r'eyJ[A-Za-z0-9+/=]{10,}\.[A-Za-z0-9+/=]{10,}\.[A-Za-z0-9+/=]{10,}')
PRIVATE_KEY_PATTERN = re.compile(r'-----BEGIN.*PRIVATE KEY-----', re.IGNORECASE)
PASSWORD_PATTERN = re.compile(
    r'(?i)["\']?(password|passwd|pwd)["\']?\s*[:=]\s*["\']([^"\']+)["\']'
)

PLACEHOLDER_PATTERNS = [
    r'(?i)your_\w+_here',
    r'(?i)placeholder',
    r'(?i)xxx+',
    r'(?i)\*{3,}',
    r'(?i)redacted',
]


def is_placeholder(value):
    """Check if a value is a placeholder."""
    if not value or len(value) < 2:
        return True
    
    for pattern in PLACEHOLDER_PATTERNS:
        if re.match(pattern, value):
            return True
    
    if len(set(value.lower())) == 1:
        return True
    
    return False


def calculate_severity(leak_type, line_content, key_context=''):
    """Calculate severity score and label."""
    if leak_type in ['private_key', 'aws_access_key']:
        return 'CRITICAL', 100
    
    if leak_type in ['jwt_token', 'github_token']:
        return 'HIGH', 80
    
    if leak_type == 'bearer_token':
        return 'MEDIUM', 50
    
    if leak_type == 'password':
        # Check key name (before : or =) for production keywords
        key_lower = key_context.lower()
        if any(x in key_lower for x in ['prod', 'live', 'production']):
            return 'HIGH', 80
        return 'LOW', 30
    
    return 'LOW', 30


def extract_secret_value(line, leak_type):
    """Extract the actual secret value from a line for deduplication."""
    if leak_type == 'aws_access_key':
        match = AWS_KEY_PATTERN.search(line)
        return match.group(0) if match else None
    elif leak_type == 'github_token':
        match = GITHUB_TOKEN_PATTERN.search(line)
        return match.group(0) if match else None
    elif leak_type == 'bearer_token':
        match = BEARER_TOKEN_PATTERN.search(line)
        return match.group(0) if match else None
    elif leak_type == 'jwt_token':
        match = JWT_PATTERN.search(line)
        return match.group(0) if match else None
    elif leak_type == 'private_key':
        match = PRIVATE_KEY_PATTERN.search(line)
        return match.group(0) if match else None
    elif leak_type == 'password':
        match = PASSWORD_PATTERN.search(line)
        return match.group(2) if match else None
    return None


def scan_file_for_secrets(file_path):
    """Scan a file for hardcoded secrets."""
    leaks = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line_num, line in enumerate(lines, start=1):
            context = line.strip()
            
            if AWS_KEY_PATTERN.search(line):
                severity, score = calculate_severity('aws_access_key', line, '')
                secret_value = extract_secret_value(line, 'aws_access_key')
                leaks.append({
                    'line': line_num,
                    'leak_type': 'aws_access_key',
                    'severity': severity,
                    'severity_score': score,
                    'context': context,
                    'secret_value': secret_value
                })
            
            if GITHUB_TOKEN_PATTERN.search(line):
                severity, score = calculate_severity('github_token', line, '')
                secret_value = extract_secret_value(line, 'github_token')
                leaks.append({
                    'line': line_num,
                    'leak_type': 'github_token',
                    'severity': severity,
                    'severity_score': score,
                    'context': context,
                    'secret_value': secret_value
                })
            
            if BEARER_TOKEN_PATTERN.search(line):
                severity, score = calculate_severity('bearer_token', line, '')
                secret_value = extract_secret_value(line, 'bearer_token')
                leaks.append({
                    'line': line_num,
                    'leak_type': 'bearer_token',
                    'severity': severity,
                    'severity_score': score,
                    'context': context,
                    'secret_value': secret_value
                })
            
            if JWT_PATTERN.search(line):
                severity, score = calculate_severity('jwt_token', line, '')
                secret_value = extract_secret_value(line, 'jwt_token')
                leaks.append({
                    'line': line_num,
                    'leak_type': 'jwt_token',
                    'severity': severity,
                    'severity_score': score,
                    'context': context,
                    'secret_value': secret_value
                })
            
            if PRIVATE_KEY_PATTERN.search(line):
                severity, score = calculate_severity('private_key', line, '')
                secret_value = extract_secret_value(line, 'private_key')
                leaks.append({
                    'line': line_num,
                    'leak_type': 'private_key',
                    'severity': severity,
                    'severity_score': score,
                    'context': context,
                    'secret_value': secret_value
                })
            
            pwd_match = PASSWORD_PATTERN.search(line)
            if pwd_match:
                password_value = pwd_match.group(2)
                if not is_placeholder(password_value):
                    # Extract full key name (everything before : or =)
                    match_start = pwd_match.start()
                    key_context = line[:match_start].strip()
                    # Strip quotes from key name
                    key_context = key_context.strip('"\'')
                    severity, score = calculate_severity(
                        'password', line, key_context
                    )
                    leaks.append({
                        'line': line_num,
                        'leak_type': 'password',
                        'severity': severity,
                        'severity_score': score,
                        'context': context,
                        'secret_value': password_value
                    })
        
        return leaks
    except Exception as e:
        print(f"Error scanning {file_path}: {e}", file=sys.stderr)
        return []


def main():
    if not PIPELINE_DIR.exists():
        print(f"Error: Pipeline directory not found: {PIPELINE_DIR}", file=sys.stderr)
        sys.exit(1)
    
    file_extensions = ['*.yaml', '*.yml', '*.json']
    all_files = []
    for ext in file_extensions:
        all_files.extend(PIPELINE_DIR.rglob(ext))
    
    total_files_scanned = len(all_files)
    all_leaks = []
    
    # Sort files alphabetically for deterministic processing
    all_files_sorted = sorted(all_files, key=lambda p: str(p.relative_to(PIPELINE_DIR)))
    
    for file_path in all_files_sorted:
        relative_path = file_path.relative_to(PIPELINE_DIR)
        leaks = scan_file_for_secrets(file_path)
        
        for leak in leaks:
            leak['file'] = str(relative_path)
            all_leaks.append(leak)
    
    # Sort by file (alphabetically) then line number for deduplication
    all_leaks.sort(key=lambda x: (x['file'], x['line']))
    
    # Deduplicate: keep only first occurrence of each secret value
    seen_secrets = set()
    deduplicated_leaks = []
    for leak in all_leaks:
        secret_value = leak.get('secret_value')
        if secret_value and secret_value not in seen_secrets:
            seen_secrets.add(secret_value)
            deduplicated_leaks.append(leak)
    
    # Now sort by severity, then file, then line for final output
    deduplicated_leaks.sort(
        key=lambda x: (-x['severity_score'], x['file'], x['line'])
    )
    
    files_with_leaks = set(leak['file'] for leak in deduplicated_leaks)
    
    total_leaks = len(deduplicated_leaks)
    files_with_leaks_count = len(files_with_leaks)
    
    critical_leaks = sum(
        1 for leak in deduplicated_leaks if leak['severity'] == 'CRITICAL'
    )
    high_leaks = sum(
        1 for leak in deduplicated_leaks if leak['severity'] == 'HIGH'
    )
    medium_leaks = sum(
        1 for leak in deduplicated_leaks if leak['severity'] == 'MEDIUM'
    )
    low_leaks = sum(
        1 for leak in deduplicated_leaks if leak['severity'] == 'LOW'
    )
    
    if total_leaks == 0:
        summary = "No secrets found"
    else:
        parts = []
        if critical_leaks > 0:
            parts.append(f"{critical_leaks} CRITICAL")
        if high_leaks > 0:
            parts.append(f"{high_leaks} HIGH")
        if medium_leaks > 0:
            parts.append(f"{medium_leaks} MEDIUM")
        if low_leaks > 0:
            parts.append(f"{low_leaks} LOW")
        
        summary = f"Found {total_leaks} secrets in {files_with_leaks_count} files ({', '.join(parts)})"
    
    formatted_leaks = []
    for leak in deduplicated_leaks:
        # Remove internal secret_value field from output
        leak_obj = OrderedDict([
            ('file', leak['file']),
            ('line', leak['line']),
            ('leak_type', leak['leak_type']),
            ('severity', leak['severity']),
            ('severity_score', leak['severity_score']),
            ('context', leak['context'])
        ])
        formatted_leaks.append(leak_obj)
    
    output = OrderedDict([
        ('total_files_scanned', total_files_scanned),
        ('files_with_leaks', files_with_leaks_count),
        ('total_leaks', total_leaks),
        ('critical_leaks', critical_leaks),
        ('high_leaks', high_leaks),
        ('medium_leaks', medium_leaks),
        ('low_leaks', low_leaks),
        ('leaks', formatted_leaks),
        ('summary', summary)
    ])
    
    print(json.dumps(output, indent=2))
    
    if critical_leaks > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
EOF

chmod +x /usr/local/bin/cicd-secrets-scanner
