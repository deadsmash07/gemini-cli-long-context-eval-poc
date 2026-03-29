#!/bin/bash


# Create test scenarios

# Test 1: Python project with all hooks
mkdir -p /app/project
echo "pytest>=7.0.0" > /app/project/requirements.txt
echo "ruff>=0.1.0" >> /app/project/requirements.txt

cat <<EOF > /app/input/hook-config.json
{
  "linting": {
    "enabled": true,
    "pre_commit": true,
    "pre_push": true
  },
  "testing": {
    "enabled": true,
    "pre_commit": false,
    "pre_push": true
  },
  "commit_format": {
    "enabled": true,
    "pre_commit": true,
    "pre_push": false
  }
}
EOF

# Run the generator
/usr/local/bin/hook-gen

# Rename outputs for test 1
mv /app/output/hook-report.json /app/output/hook-report-python.json
mv /app/output/hooks /app/output/hooks-python

# Test 2: JavaScript project
rm -rf /app/project
mkdir -p /app/project
cat <<EOF > /app/project/package.json
{
  "name": "test-project",
  "version": "1.0.0",
  "scripts": {
    "test": "jest"
  },
  "devDependencies": {
    "eslint": "^8.0.0",
    "jest": "^29.0.0"
  }
}
EOF

cat <<EOF > /app/input/hook-config.json
{
  "linting": {
    "enabled": true,
    "pre_commit": true,
    "pre_push": false
  },
  "testing": {
    "enabled": true,
    "pre_commit": false,
    "pre_push": true
  },
  "commit_format": {
    "enabled": false,
    "pre_commit": false,
    "pre_push": false
  }
}
EOF

# Run the generator for JavaScript
/usr/local/bin/hook-gen

# Rename outputs for test 2
mv /app/output/hook-report.json /app/output/hook-report-javascript.json
mv /app/output/hooks /app/output/hooks-javascript

# Test 3: Python project with minimal config (for main tests)
rm -rf /app/project
mkdir -p /app/project
echo "requests>=2.28.0" > /app/project/requirements.txt

cat <<EOF > /app/input/hook-config.json
{
  "linting": {
    "enabled": true,
    "pre_commit": true,
    "pre_push": false
  },
  "testing": {
    "enabled": true,
    "pre_commit": false,
    "pre_push": true
  },
  "commit_format": {
    "enabled": true,
    "pre_commit": true,
    "pre_push": false
  }
}
EOF

# Run the generator for main test
/usr/local/bin/hook-gen

# Run tests
cd "/tests"
pytest test_outputs.py -v -rA



if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
