#!/usr/bin/env bash
# Validate CloudFormation template syntax and schema.
# Uses standard AWS credential chain (respects AWS_PROFILE and AWS_REGION).
# Does NOT mutate or deploy cloud resources.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE_FILE="${REPO_ROOT}/infra/aws/template.yaml"

if [ ! -f "${TEMPLATE_FILE}" ]; then
  echo "[ERROR] Template file not found: infra/aws/template.yaml" >&2
  exit 1
fi

echo "[Validate] Checking template file existence and non-emptiness: infra/aws/template.yaml"
if [ ! -s "${TEMPLATE_FILE}" ]; then
  echo "[ERROR] Template file is empty: infra/aws/template.yaml" >&2
  exit 1
fi

# Basic local structural sanity checks
for section in "AWSTemplateFormatVersion" "Parameters:" "Resources:" "Outputs:"; do
  if ! grep -q "${section}" "${TEMPLATE_FILE}"; then
    echo "[ERROR] Template missing required section '${section}'" >&2
    exit 1
  fi
done

# Locate AWS CLI via standard PATH
AWS_BIN=""
if command -v aws >/dev/null 2>&1; then
  AWS_BIN="$(command -v aws)"
fi

if [ -n "${AWS_BIN}" ]; then
  AWS_ARGS=(--region "${AWS_REGION:-us-east-1}")
  if [ -n "${AWS_PROFILE:-}" ]; then
    AWS_ARGS+=(--profile "${AWS_PROFILE}")
  fi

  if "${AWS_BIN}" sts get-caller-identity "${AWS_ARGS[@]}" >/dev/null 2>&1; then
    echo "[Validate] Running 'aws cloudformation validate-template' (read-only syntax/schema check)..."
    VALIDATE_OUTPUT="$("${AWS_BIN}" cloudformation validate-template \
      --template-body "file://${TEMPLATE_FILE}" \
      "${AWS_ARGS[@]}" 2>&1)" || {
        echo "[ERROR] CloudFormation validation failed:" >&2
        echo "${VALIDATE_OUTPUT}" >&2
        exit 1
      }

    echo "[Validate] CloudFormation API validation PASSED:"
    echo "${VALIDATE_OUTPUT}"
  elif [ "${REQUIRE_AWS_VALIDATION:-0}" = "1" ]; then
    echo "[ERROR] Active AWS credentials required (REQUIRE_AWS_VALIDATION=1) but credential chain failed." >&2
    exit 1
  else
    echo "[WARN] No active AWS credentials in standard chain (set AWS_PROFILE or credentials for online check); skipping online API validation."
  fi
else
  if [ "${REQUIRE_AWS_VALIDATION:-0}" = "1" ]; then
    echo "[ERROR] aws CLI not found in PATH (REQUIRE_AWS_VALIDATION=1)." >&2
    exit 1
  fi
  echo "[WARN] aws CLI not found in PATH; skipping online CloudFormation API validation."
fi

echo "[Validate] CloudFormation template checks completed successfully."
exit 0
