#!/usr/bin/env bash
# Deploy/update ResolveQA backend stack from a verified bundle.
# Intended for CI on main after human merge. Does not merge git.
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-us-east-1}"
STACK="${AWS_STACK_NAME:-resolveqa-demo-backend}"
BUCKET="${AWS_ARTIFACT_BUCKET:-resolveqa-deployment-artifacts}"
VPC_ID="${AWS_VPC_ID:?AWS_VPC_ID required}"
SUBNET_ID="${AWS_SUBNET_ID:?AWS_SUBNET_ID required}"
INSTANCE_TYPE="${AWS_INSTANCE_TYPE:-t4g.micro}"
ENV_NAME="${AWS_ENVIRONMENT_NAME:-demo}"
CORS_ORIGINS="${AWS_CORS_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000,https://dsh3ja1i4695p.cloudfront.net,https://d10ry6ff7l79jo.cloudfront.net}"

aws --region "$REGION" sts get-caller-identity >/dev/null
echo "AWS credentials validated."

python3 scripts/package_bundle.py --allow-dirty
BUNDLE="dist/resolveqa-bundle.tar.gz"
test -f "$BUNDLE"
SHA256=$(sha256sum "$BUNDLE" | awk '{print $1}')
KEY="builds/resolveqa-bundle-${SHA256:0:12}.tar.gz"

aws --region "$REGION" s3api head-bucket --bucket "$BUCKET" 2>/dev/null || \
  aws --region "$REGION" s3api create-bucket --bucket "$BUCKET"
aws --region "$REGION" s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws --region "$REGION" s3 cp "$BUNDLE" "s3://${BUCKET}/${KEY}" --only-show-errors

STATUS=$(aws --region "$REGION" cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo 'DOES_NOT_EXIST')

PARAMS_FILE=$(mktemp)
trap 'rm -f "$PARAMS_FILE"' EXIT

write_params() {
  # JSON avoids AWS CLI splitting comma-rich ParameterValue (CORS list).
  local mode="$1"
  python3 - "$PARAMS_FILE" "$mode" <<'PY'
import json, os, sys
path, mode = sys.argv[1], sys.argv[2]
params = [
    {"ParameterKey": "ArtifactBucket", "ParameterValue": os.environ["BUCKET"]},
    {"ParameterKey": "ArtifactKey", "ParameterValue": os.environ["KEY"]},
    {"ParameterKey": "ArtifactSha256", "ParameterValue": os.environ["SHA256"]},
    {"ParameterKey": "VpcId", "ParameterValue": os.environ["VPC_ID"]},
    {"ParameterKey": "SubnetId", "ParameterValue": os.environ["SUBNET_ID"]},
    {"ParameterKey": "InstanceType", "ParameterValue": os.environ["INSTANCE_TYPE"]},
    {"ParameterKey": "EnvironmentName", "ParameterValue": os.environ["ENV_NAME"]},
    {"ParameterKey": "CorsOrigins", "ParameterValue": os.environ["CORS_ORIGINS"]},
]
if mode == "create":
    params.append({"ParameterKey": "OriginSecretHeader", "ParameterValue": os.environ["ORIGIN_SECRET"]})
else:
    params.extend([
        {"ParameterKey": "OriginSecretHeader", "UsePreviousValue": True},
        {"ParameterKey": "CloudFrontPrefixListId", "UsePreviousValue": True},
        {"ParameterKey": "AmiId", "UsePreviousValue": True},
    ])
with open(path, "w", encoding="utf-8") as fh:
    json.dump(params, fh)
PY
}

export BUCKET KEY SHA256 VPC_ID SUBNET_ID INSTANCE_TYPE ENV_NAME CORS_ORIGINS

if [[ "$STATUS" == "DOES_NOT_EXIST" ]]; then
  if [[ "${ALLOW_STACK_CREATE:-}" != "1" && "${ENV_NAME}" != "staging" ]]; then
    echo "Stack missing; refusing create without OriginSecretHeader (use authorized bootstrap)." >&2
    exit 2
  fi
  ORIGIN_SECRET="${ORIGIN_SECRET_HEADER:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
  export ORIGIN_SECRET
  echo "Creating stack ${STACK} (env=${ENV_NAME}) with generated OriginSecretHeader."
  write_params create
  aws --region "$REGION" cloudformation create-stack \
    --stack-name "$STACK" \
    --template-body "file://infra/aws/template.yaml" \
    --parameters "file://${PARAMS_FILE}" \
    --capabilities CAPABILITY_IAM \
    >/dev/null
  aws --region "$REGION" cloudformation wait stack-create-complete --stack-name "$STACK"
else
  write_params update
  set +e
  UPDATE_OUT=$(aws --region "$REGION" cloudformation update-stack \
    --stack-name "$STACK" \
    --template-body "file://infra/aws/template.yaml" \
    --parameters "file://${PARAMS_FILE}" \
    --capabilities CAPABILITY_IAM 2>&1)
  UPDATE_RC=$?
  set -e
  if [[ $UPDATE_RC -ne 0 ]]; then
    if echo "$UPDATE_OUT" | grep -qi 'No updates are to be performed'; then
      echo "No stack update required (or already current)."
    else
      echo "$UPDATE_OUT" >&2
      exit 1
    fi
  else
    aws --region "$REGION" cloudformation wait stack-update-complete --stack-name "$STACK"
  fi
fi
BASE=$(aws --region "$REGION" cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontBaseUrl'].OutputValue | [0]" --output text)
echo "CloudFrontBaseUrl=${BASE}"
python3 scripts/smoke_test.py --base-url "$BASE"
