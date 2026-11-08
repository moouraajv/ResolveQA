#!/usr/bin/env bash
# ResolveQA Deployment Command Generator & Dry-Run Verifier
# Packages code deterministically (clean working tree required), calculates SHA-256,
# validates template, and generates CloudFormation parameters and CLI commands
# without exposing secrets.
#
# Uses standard AWS credential chain (configure via AWS_PROFILE / AWS_REGION if needed).
# NOTICE: This script is strictly a helper / dry-run validator; it executes ZERO
# cloud mutations (no AWS API create/update/deploy actions are executed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BUCKET_NAME="${1:-resolveqa-deployment-artifacts}"
STACK_NAME="${2:-resolveqa-demo-backend}"
ENV_NAME="${3:-demo}"
VPC_ID="${4:-<VPC_ID>}"
SUBNET_ID="${5:-<SUBNET_ID>}"
REGION="${AWS_REGION:-us-east-1}"

echo "======================================================================"
echo "ResolveQA AWS Deployment Workflow (Dry-Run Generator)"
echo "Target Stack:    ${STACK_NAME}"
echo "Environment:     ${ENV_NAME}"
echo "Region:          ${REGION}"
echo "Artifact Bucket: ${BUCKET_NAME}"
echo "Notice:          Strictly dry-run; ZERO cloud mutations will be performed."
echo "======================================================================"

# Step 1: Build deterministic, reproducible bundle (clean tree required by default)
echo "[Step 1] Building deterministic deployment bundle..."
mkdir -p "${REPO_ROOT}/dist"
BUNDLE_OUTPUT="$(python3 "${REPO_ROOT}/scripts/package_bundle.py")"
echo "${BUNDLE_OUTPUT}"

BUNDLE_FILE="${REPO_ROOT}/dist/resolveqa-bundle.tar.gz"
REL_BUNDLE_FILE="dist/resolveqa-bundle.tar.gz"
if [ ! -f "${BUNDLE_FILE}" ]; then
  echo "[ERROR] Bundle file was not generated: ${REL_BUNDLE_FILE}" >&2
  exit 1
fi

SHA256_HASH="$(sha256sum "${BUNDLE_FILE}" | awk '{print $1}')"
KEY_NAME="builds/resolveqa-bundle-${SHA256_HASH:0:12}.tar.gz"

# Step 2: Generate 256-bit random origin secret and save to private parameters file (chmod 600)
# The secret is NEVER printed to stdout or logs.
PARAMS_FILE="${REPO_ROOT}/dist/parameters-${ENV_NAME}.json"
REL_PARAMS_FILE="dist/parameters-${ENV_NAME}.json"
ORIGIN_SECRET="$(python3 -c "import secrets; print(secrets.token_hex(32))")"

cat << EOF > "${PARAMS_FILE}"
[
  {
    "ParameterKey": "EnvironmentName",
    "ParameterValue": "${ENV_NAME}"
  },
  {
    "ParameterKey": "InstanceType",
    "ParameterValue": "t4g.nano"
  },
  {
    "ParameterKey": "VpcId",
    "ParameterValue": "${VPC_ID}"
  },
  {
    "ParameterKey": "SubnetId",
    "ParameterValue": "${SUBNET_ID}"
  },
  {
    "ParameterKey": "ArtifactBucket",
    "ParameterValue": "${BUCKET_NAME}"
  },
  {
    "ParameterKey": "ArtifactKey",
    "ParameterValue": "${KEY_NAME}"
  },
  {
    "ParameterKey": "ArtifactSha256",
    "ParameterValue": "${SHA256_HASH}"
  },
  {
    "ParameterKey": "OriginSecretHeader",
    "ParameterValue": "${ORIGIN_SECRET}"
  }
]
EOF
chmod 600 "${PARAMS_FILE}"

echo "[Security] Generated 256-bit origin verification secret."
echo "[Security] Stored private CloudFormation parameters in: ${REL_PARAMS_FILE} (permissions: 0600)."
echo "[Security] Token is REDACTED from stdout, shell logs, and process tables."

# Step 3: Validate CloudFormation Template
echo "[Step 2] Validating CloudFormation template..."
bash "${REPO_ROOT}/scripts/validate_template.sh"

echo "======================================================================"
echo "DRY-RUN COMPLETE: NO CLOUD MUTATIONS PERFORMED."
echo "======================================================================"
echo "When authorized by the coordinator, execute the following commands"
echo "(using standard AWS credential chain; set AWS_PROFILE / AWS_REGION if needed):"
echo ""
echo "# 1. Upload verified artifact bundle to private S3 bucket:"
echo "aws s3 cp \"${REL_BUNDLE_FILE}\" \"s3://${BUCKET_NAME}/${KEY_NAME}\" \\"
echo "  --region \"${REGION}\""
echo ""
echo "# 2. Deploy CloudFormation stack (references private parameters file; token redacted from argv):"
echo "aws cloudformation create-stack \\"
echo "  --stack-name \"${STACK_NAME}\" \\"
echo "  --template-body \"file://infra/aws/template.yaml\" \\"
echo "  --parameters \"file://${REL_PARAMS_FILE}\" \\"
echo "  --capabilities CAPABILITY_IAM \\"
echo "  --region \"${REGION}\""
echo ""
echo "# 3. Wait for instance bootstrap and readiness signal (CreationPolicy + cfn-signal):"
echo "aws cloudformation wait stack-create-complete \\"
echo "  --stack-name \"${STACK_NAME}\" \\"
echo "  --region \"${REGION}\""
echo ""
echo "# 4. Retrieve CloudFront HTTPS endpoints:"
echo "aws cloudformation describe-stacks \\"
echo "  --stack-name \"${STACK_NAME}\" \\"
echo "  --query \"Stacks[0].Outputs\" \\"
echo "  --region \"${REGION}\""
echo ""
echo "# 5. Smoke test public CloudFront HTTPS URL:"
echo "# NOTE: CloudFront automatically injects the origin verification header."
echo "# The client/tester calls the public HTTPS URL WITHOUT needing or providing the secret."
echo "CLOUDFRONT_URL=\$(aws cloudformation describe-stacks \\"
echo "  --stack-name \"${STACK_NAME}\" \\"
echo "  --query \"Stacks[0].Outputs[?OutputKey=='CloudFrontBaseUrl'].OutputValue\" \\"
echo "  --output text --region \"${REGION}\")"
echo "python3 scripts/smoke_test.py --base-url \"\${CLOUDFRONT_URL}\""
echo ""
echo "# 6. (Optional) Direct origin verification test:"
echo "# Direct access to EC2 IP on port 8080 without header returns HTTP 403 Forbidden."
echo "# Access with header is verified by passing the origin secret token from ${REL_PARAMS_FILE}."
echo "======================================================================"
