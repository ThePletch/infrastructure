#!/bin/bash

set -euo pipefail
usage () {
    echo "Usage:"
    echo "$0 filename title description [tag] ..."
}

if [ "$#" -lt 3 ]; then
  usage
  exit 2
fi

tags=(${@:4})
filename="$(basename "$1")"
script_dir="$(cd "$(dirname "$0")" && pwd)"
# Bucket, prefix, and region from Terraform state. PHOTO_* overrides live in gallery_config.py.
eval "$(python3 "$script_dir/gallery_config.py" --shell)"
echo "Title: $2"
echo "Description: $3"
echo "Tags: ${@:4}"
"$script_dir/tag_image.py" "$1" --title "$2" --description "$3" ${tags[@]/#/--tag }
echo "Uploading $filename..."
aws s3 cp "$1" "s3://${PHOTO_BUCKET}/${PHOTO_PREFIX}${filename}" --region "$PHOTO_REGION"