#!/usr/bin/env bash
# Plan the synthetic root in isolation: no existing state, backend or AWS account.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo 'Usage: tools/plan.sh <terraform dir> <out.json>' >&2
  exit 2
fi

terraform_dir=$(cd "$1" && pwd)
output_dir=$(cd "$(dirname "$2")" && pwd)
output="$output_dir/$(basename "$2")"
work=$(mktemp -d)
json_tmp=""
trap 'rm -rf "$work"; rm -f "$json_tmp"' EXIT
json_tmp=$(mktemp "$output_dir/.theseus-plan.XXXXXX")

# Copy configuration only; previous local state must never trigger refresh calls.
shopt -s nullglob
sources=("$terraform_dir"/*.tf "$terraform_dir"/*.tf.json)
if [[ ${#sources[@]} -eq 0 ]]; then
  echo "No Terraform configuration in $terraform_dir" >&2
  exit 2
fi
cp "${sources[@]}" "$work/"
export TF_DATA_DIR="$work/.terraform"
export TF_IN_AUTOMATION=1
export CHECKPOINT_DISABLE=1
export AWS_EC2_METADATA_DISABLED=true
# A developer's profile or session must not change the mock-only provider configuration.
unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
export AWS_CONFIG_FILE="$work/aws-config"
export AWS_SHARED_CREDENTIALS_FILE="$work/aws-credentials"
: > "$AWS_CONFIG_FILE"
: > "$AWS_SHARED_CREDENTIALS_FILE"

terraform -chdir="$work" init -backend=false -input=false -no-color >&2
terraform -chdir="$work" plan -refresh=false -input=false -lock=false -no-color -out=tfplan >&2
terraform -chdir="$work" show -json tfplan > "$json_tmp"
mv "$json_tmp" "$output"
