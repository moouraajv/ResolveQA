#!/usr/bin/env bash
# Validate CloudFormation template syntax and schema
# Does NOT mutate or deploy cloud resources.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE_FILE="${REPO_ROOT}/infra/aws/template.yaml"

if [ ! -f "${TEMPLATE_FILE}" ]; then
  echo "[ERROR] Template file not found: ${TEMPLATE_FILE}" >&2
  exit 1
fi

echo "[Validate] Checking template file existence and non-emptiness: ${TEMPLATE_FILE}"
if [ ! -s "${TEMPLATE_FILE}" ]; then
  echo "[ERROR] Template file is empty: ${TEMPLATE_FILE}" >&2
  exit 1
fi

# Locate AWS CLI
AWS_BIN=""
if command -v aws >/dev/null 2>&1; then
  AWS_BIN="$(command -v aws)"
elif [ -x "<LOCAL_HOME>/.local/bin/aws" ]; then
  AWS_BIN="<LOCAL_HOME>/.local/bin/aws"
fi

if [ -n "${AWS_BIN}" ]; then
  echo "[Validate] Running '${AWS_BIN} cloudformation validate-template' (read-only syntax/schema check)..."
  PROFILE_ARG=()
  if "${AWS_BIN}" configure list-profiles 2>/dev/null | grep -q "^<AWS_PROFILE>$"; then
    PROFILE_ARG=( --region us-east-1)
  fi

  VALIDATE_OUTPUT="$("${AWS_BIN}" cloudformation validate-template \
    --template-body "file://${TEMPLATE_FILE}" \
    "${PROFILE_ARG[@]}" 2>&1)" || {
      echo "[ERROR] CloudFormation validation failed:" >&2
      echo "${VALIDATE_OUTPUT}" >&2
      exit 1
    }

  echo "[Validate] CloudFormation API validation PASSED:"
  echo "${VALIDATE_OUTPUT}"
else
  echo "[WARN] aws CLI not found in PATH; skipping online CloudFormation API validation."
fi

echo "[Validate] CloudFormation template checks completed successfully."
exit 0
