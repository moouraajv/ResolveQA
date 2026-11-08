#!/usr/bin/env bash
# ResolveQA Deployment Helper & Dry-Run Script
# Packages code, verifies integrity, validates template, and prepares exact CLI commands.
# By default, runs in DRY-RUN mode (zero cloud mutations).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BUCKET_NAME="${1:-resolveqa-deployment-artifacts}"
STACK_NAME="${2:-resolveqa-demo-backend}"
ENV_NAME="${3:-demo}"
VPC_ID="${4:-<VPC_ID>}"
SUBNET_ID="${5:-<SUBNET_ID>}"

echo "======================================================================"
echo "ResolveQA AWS Deployment Workflow (Dry-Run Mode)"
echo "Target Stack:   ${STACK_NAME}"
echo "Environment:    ${ENV_NAME}"
echo "Artifact Bucket: ${BUCKET_NAME}"
echo "======================================================================"

# Step 1: Build versioned bundle
echo "[Step 1] Building deployment bundle..."
BUNDLE_OUTPUT="$(python3 "${REPO_ROOT}/scripts/package_bundle.py")"
echo "${BUNDLE_OUTPUT}"

BUNDLE_FILE="${REPO_ROOT}/dist/resolveqa-bundle.tar.gz"
if [ ! -f "${BUNDLE_FILE}" ]; then
  echo "[ERROR] Bundle file was not generated: ${BUNDLE_FILE}" >&2
  exit 1
fi

SHA256_HASH="$(sha256sum "${BUNDLE_FILE}" | awk '{print $1}')"
KEY_NAME="builds/resolveqa-bundle-${SHA256_HASH:0:12}.tar.gz"

# Step 2: Generate random origin secret
ORIGIN_SECRET="$(python3 -c "import secrets; print(secrets.token_hex(32))")"

# Step 3: Validate CloudFormation Template
echo "[Step 2] Validating CloudFormation template..."
bash "${REPO_ROOT}/scripts/validate_template.sh"

echo "======================================================================"
echo "DRY-RUN COMPLETE: NO CLOUD MUTATIONS PERFORMED."
echo "======================================================================"
echo "To execute deployment when authorized, run the following commands:"
echo ""
echo "# 1. Upload verified artifact bundle to private S3 bucket:"
echo "aws s3 cp \"${BUNDLE_FILE}\" \"s3://${BUCKET_NAME}/${KEY_NAME}\" \\"
echo "   --region us-east-1"
echo ""
echo "# 2. Deploy CloudFormation stack (waits for cfn-signal from instance):"
echo "aws cloudformation create-stack \\"
echo "  --stack-name \"${STACK_NAME}\" \\"
echo "  --template-body \"file://${REPO_ROOT}/infra/aws/template.yaml\" \\"
echo "  --parameters \\"
echo "      ParameterKey=EnvironmentName,ParameterValue=\"${ENV_NAME}\" \\"
echo "      ParameterKey=InstanceType,ParameterValue=t4g.nano \\"
echo "      ParameterKey=VpcId,ParameterValue=\"${VPC_ID}\" \\"
echo "      ParameterKey=SubnetId,ParameterValue=\"${SUBNET_ID}\" \\"
echo "      ParameterKey=ArtifactBucket,ParameterValue=\"${BUCKET_NAME}\" \\"
echo "      ParameterKey=ArtifactKey,ParameterValue=\"${KEY_NAME}\" \\"
echo "      ParameterKey=ArtifactSha256,ParameterValue=\"${SHA256_HASH}\" \\"
echo "      ParameterKey=OriginSecretHeader,ParameterValue=\"${ORIGIN_SECRET}\" \\"
echo "  --capabilities CAPABILITY_IAM \\"
echo "   --region us-east-1"
echo ""
echo "# 3. Wait for instance bootstrap and readiness signal:"
echo "aws cloudformation wait stack-create-complete \\"
echo "  --stack-name \"${STACK_NAME}\" \\"
echo "   --region us-east-1"
echo ""
echo "# 4. Retrieve CloudFront HTTPS endpoints:"
echo "aws cloudformation describe-stacks \\"
echo "  --stack-name \"${STACK_NAME}\" \\"
echo "  --query \"Stacks[0].Outputs\" \\"
echo "   --region us-east-1"
echo ""
echo "# 5. Run smoke test against public CloudFront URL:"
echo "CLOUDFRONT_URL=\$(aws cloudformation describe-stacks \\"
echo "  --stack-name \"${STACK_NAME}\" \\"
echo "  --query \"Stacks[0].Outputs[?OutputKey=='CloudFrontBaseUrl'].OutputValue\" \\"
echo "  --output text  --region us-east-1)"
echo "python3 \"${REPO_ROOT}/scripts/smoke_test.py\" --base-url \"\${CLOUDFRONT_URL}\" --origin-secret \"${ORIGIN_SECRET}\""
echo "======================================================================"
