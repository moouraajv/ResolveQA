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

CORS_ORIGINS="${AWS_CORS_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000,https://dsh3ja1i4695p.cloudfront.net,https://d10ry6ff7l79jo.cloudfront.net}"

PARAMS=(
  "ParameterKey=ArtifactBucket,ParameterValue=${BUCKET}"
  "ParameterKey=ArtifactKey,ParameterValue=${KEY}"
  "ParameterKey=ArtifactSha256,ParameterValue=${SHA256}"
  "ParameterKey=VpcId,ParameterValue=${VPC_ID}"
  "ParameterKey=SubnetId,ParameterValue=${SUBNET_ID}"
  "ParameterKey=InstanceType,ParameterValue=${INSTANCE_TYPE}"
  "ParameterKey=EnvironmentName,ParameterValue=${ENV_NAME}"
  "ParameterKey=CorsOrigins,ParameterValue=${CORS_ORIGINS}"
)

if [[ "$STATUS" == "DOES_NOT_EXIST" ]]; then
  if [[ "${ALLOW_STACK_CREATE:-}" != "1" && "${ENV_NAME}" != "staging" ]]; then
    echo "Stack missing; refusing create without OriginSecretHeader (use authorized bootstrap)." >&2
    exit 2
  fi
  ORIGIN_SECRET="${ORIGIN_SECRET_HEADER:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
  echo "Creating stack ${STACK} (env=${ENV_NAME}) with generated OriginSecretHeader."
  CREATE_PARAMS=(
    "${PARAMS[@]}"
    "ParameterKey=OriginSecretHeader,ParameterValue=${ORIGIN_SECRET}"
  )
  aws --region "$REGION" cloudformation create-stack \
    --stack-name "$STACK" \
    --template-body "file://infra/aws/template.yaml" \
    --parameters "${CREATE_PARAMS[@]}" \
    --capabilities CAPABILITY_IAM \
    >/dev/null
  aws --region "$REGION" cloudformation wait stack-create-complete --stack-name "$STACK"
else
  # Keep existing origin verify secret (NoEcho) on updates.
  PARAMS+=(
    "ParameterKey=OriginSecretHeader,UsePreviousValue=true"
    "ParameterKey=CloudFrontPrefixListId,UsePreviousValue=true"
    "ParameterKey=AmiId,UsePreviousValue=true"
  )

  aws --region "$REGION" cloudformation update-stack \
    --stack-name "$STACK" \
    --template-body "file://infra/aws/template.yaml" \
    --parameters "${PARAMS[@]}" \
    --capabilities CAPABILITY_IAM \
    >/dev/null || {
      # No-op updates return ValidationError; treat as success if stack is healthy.
      if aws --region "$REGION" cloudformation describe-stacks --stack-name "$STACK" \
        --query 'Stacks[0].StackStatus' --output text | grep -Eq 'COMPLETE$'; then
        echo "No stack update required (or already current)."
      else
        exit 1
      fi
    }

  aws --region "$REGION" cloudformation wait stack-update-complete --stack-name "$STACK" 2>/dev/null || true
fi
BASE=$(aws --region "$REGION" cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontBaseUrl'].OutputValue | [0]" --output text)
echo "CloudFrontBaseUrl=${BASE}"
python3 scripts/smoke_test.py --base-url "$BASE"
