#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Profile: optional CLI arg, else AWS_PROFILE, else default credential chain (no --profile).
profile="${1:-${AWS_PROFILE:-}}"
region="${2:-${AWS_REGION:-us-east-1}}"
stack="${3:-resolveqa-frontend}"
if [[ -n "$profile" ]]; then
  aws_cmd=(aws --profile "$profile" --region "$region" --no-cli-pager)
else
  aws_cmd=(aws --region "$region" --no-cli-pager)
fi
test -f out/index.html || { echo 'Run npm run build:aws first.' >&2; exit 1; }
# Validate credentials without printing Account/Arn identity metadata.
"${aws_cmd[@]}" sts get-caller-identity >/dev/null
echo 'AWS credentials validated.'
"${aws_cmd[@]}" cloudformation deploy \
  --template-file infra/aws/frontend.json --stack-name "$stack" \
  --no-fail-on-empty-changeset --tags Project=ResolveQA Component=frontend
bucket="$("${aws_cmd[@]}" cloudformation describe-stacks --stack-name "$stack" --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue | [0]' --output text)"
distribution="$("${aws_cmd[@]}" cloudformation describe-stacks --stack-name "$stack" --query 'Stacks[0].Outputs[?OutputKey==`DistributionId`].OutputValue | [0]' --output text)"
url="$("${aws_cmd[@]}" cloudformation describe-stacks --stack-name "$stack" --query 'Stacks[0].Outputs[?OutputKey==`SiteUrl`].OutputValue | [0]' --output text)"
[[ "$bucket" != None && "$distribution" != None && "$url" == https://* ]] || { echo 'Missing stack outputs.' >&2; exit 1; }
"${aws_cmd[@]}" s3 sync out/ "s3://$bucket/" --exclude '*.html' --exclude '_next/static/*' --cache-control 'public,max-age=300' --only-show-errors
"${aws_cmd[@]}" s3 cp out/_next/static/ "s3://$bucket/_next/static/" --recursive --cache-control 'public,max-age=31536000,immutable' --only-show-errors
"${aws_cmd[@]}" s3 cp out/ "s3://$bucket/" --recursive --exclude '*' --include '*.html' --cache-control 'no-cache,max-age=0,must-revalidate' --only-show-errors
invalidation="$("${aws_cmd[@]}" cloudfront create-invalidation --distribution-id "$distribution" --paths '/*' --query Invalidation.Id --output text)"
"${aws_cmd[@]}" cloudfront wait invalidation-completed --distribution-id "$distribution" --id "$invalidation"
printf 'Site: %s\nStack: %s\nDistribution: %s\n' "$url" "$stack" "$distribution"
