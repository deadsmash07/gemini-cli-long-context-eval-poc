#!/bin/bash

# Create test pipeline files with various secrets
mkdir -p /app/input/pipeline/ci /app/input/pipeline/cd /app/input/pipeline/secrets

# File 1: GitHub Actions with AWS key leak
cat > /app/input/pipeline/github-actions.yml << 'EOF'
name: Deploy to AWS
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Configure AWS
        run: |
          export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
      - name: Deploy
        run: ./deploy.sh
EOF

# File 2: Production password (HIGH) and JWT token (HIGH)
cat > /app/input/pipeline/ci/api-config.json << 'EOF'
{
  "database": {
    "prod_password": "SecureP@ss123",
    "connection_string": "postgresql://localhost/db"
  },
  "auth": {
    "jwt_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
  }
}
EOF

# File 3: GitHub token (HIGH) and placeholder password (should be filtered)
cat > /app/input/pipeline/ci/Jenkinsfile.yaml << 'EOF'
pipeline:
  agent: any
  environment:
    GITHUB_TOKEN: ghp_1234567890abcdefghijklmnopqrstuv1234
    PLACEHOLDER_PWD: "your_password_here"
  stages:
    - stage: Build
      steps:
        - sh: npm install
EOF

# File 4: Bearer token (MEDIUM)
cat > /app/input/pipeline/cd/deploy-script.yml << 'EOF'
deployment:
  api_call:
    headers:
      Authorization: Bearer AbCdEf1234567890+/==XyZaBcDeF1234567890
  endpoint: https://api.example.com/deploy
EOF

# File 5: Private key (CRITICAL)
cat > /app/input/pipeline/secrets/deploy-keys.yaml << 'EOF'
ssh_keys:
  deploy_key: |
    -----BEGIN RSA PRIVATE KEY-----
    MIIEowIBAAKCAQEA1234567890abcdef...
    -----END RSA PRIVATE KEY-----
EOF

# File 6: Low severity password
cat > /app/input/pipeline/cd/test-config.json << 'EOF'
{
  "test_env": {
    "db_password": "testpass123"
  }
}
EOF

# File 7: Multiple placeholders (should all be filtered) + DUPLICATE secrets
cat > /app/input/pipeline/config-template.yml << 'EOF'
defaults:
  password: "PLACEHOLDER"
  api_key: "xxx"
  secret: "***"
  token: "REDACTED"
  pwd: "aaaaaaa"
# Duplicates for deduplication testing (should NOT be reported)
backup_github_token: ghp_1234567890abcdefghijklmnopqrstuv1234
backup_aws_key: AKIAIOSFODNN7EXAMPLE
EOF

cd "/tests"
pytest test_outputs.py -rA


if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
