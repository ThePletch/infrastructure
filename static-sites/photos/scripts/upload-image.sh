#!/bin/bash

set -euo pipefail

usage () {
    echo "Usage:"
    echo "  $0 filename title description [tag] ..."
    echo "  $0 --crop parent filename label"
    echo
    echo "A crop is stored at _crops/<parent>/<label>.<ext>."
    echo "It is left out of the gallery and sold with that photo."
}

script_dir="$(cd "$(dirname "$0")" && pwd)"

load_config () {
    # Bucket, prefix, and region from Terraform state. PHOTO_* overrides live in gallery_config.py.
    eval "$(python3 "$script_dir/gallery_config.py" --shell)"
}

is_image_name () {
    local name="${1##*/}"
    local ext
    ext="$(printf '%s' "${name##*.}" | tr '[:upper:]' '[:lower:]')"
    if [ "$name" = "$ext" ]; then
        return 1
    fi
    case "$ext" in
        jpg|jpeg|png|gif|webp|avif) return 0 ;;
        *) return 1 ;;
    esac
}

require_relative () {
    local value="$1"
    local what="$2"
    local rest="$value"
    local part
    if [ -z "$value" ] || [ "${value#/}" != "$value" ] || [ "${value%/}" != "$value" ]; then
        echo "$what must be a relative key" >&2
        exit 2
    fi
    while [ -n "$rest" ]; do
        part="${rest%%/*}"
        if [ -z "$part" ] || [ "$part" = "." ] || [ "$part" = ".." ]; then
            echo "$what must not contain empty or .. segments" >&2
            exit 2
        fi
        case "$part" in
            *\\*)
                echo "$what must not contain backslashes" >&2
                exit 2
                ;;
        esac
        if [ "$part" = "$rest" ]; then
            rest=""
        else
            rest="${rest#*/}"
        fi
    done
}

prepare_crop () {
    local parent="$1"
    local source="$2"
    local label="$3"
    local base ext ext_lower dot_ext label_lower suffix

    require_relative "$parent" "parent"
    case "$parent" in
        _crops|_crops/*|_thumbs|_thumbs/*|_lightbox|_lightbox/*|_index.json)
            echo "parent must be a gallery photo, not ${parent}" >&2
            exit 2
            ;;
    esac
    if ! is_image_name "$parent"; then
        echo "parent must be an image filename" >&2
        exit 2
    fi
    if [ ! -f "$source" ]; then
        echo "no file named ${source}" >&2
        exit 2
    fi
    base="$(basename "$source")"
    if ! is_image_name "$base"; then
        echo "expected a JPEG, PNG, GIF, WebP, or AVIF file" >&2
        exit 2
    fi
    label="${label#"${label%%[![:space:]]*}"}"
    label="${label%"${label##*[![:space:]]}"}"
    case "$label" in
        ""|.*|*/*|*\\*)
            echo "label must be a single file name" >&2
            exit 2
            ;;
    esac
    ext="${base##*.}"
    ext_lower="$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')"
    dot_ext=".${ext}"
    label_lower="$(printf '%s' "$label" | tr '[:upper:]' '[:lower:]')"
    suffix=".${ext_lower}"
    case "$label_lower" in
        *"$suffix")
            label="${label:0:${#label}-${#suffix}}"
            ;;
    esac
    if [ -z "$label" ] || [ "$label" = "." ] || [ "$label" = ".." ]; then
        echo "label must be a single file name" >&2
        exit 2
    fi
    CROP_LABEL="$label"
    CROP_OBJECT="${label}${dot_ext}"
}

upload_crop () {
    local parent="$1"
    local source="$2"
    local key="${PHOTO_PREFIX}_crops/${parent}/${CROP_OBJECT}"
    if ! aws s3api head-object \
        --bucket "$PHOTO_BUCKET" \
        --key "${PHOTO_PREFIX}${parent}" \
        --region "$PHOTO_REGION" \
        >/dev/null 2>&1; then
        echo "no gallery photo named ${parent} under s3://${PHOTO_BUCKET}/${PHOTO_PREFIX}" >&2
        exit 1
    fi
    echo "Crop of: $parent"
    echo "Label: $CROP_LABEL"
    "$script_dir/tag_image.py" "$source" --title "$CROP_LABEL"
    echo "Uploading ${key}..."
    aws s3 cp "$source" "s3://${PHOTO_BUCKET}/${key}" --region "$PHOTO_REGION"
}

if [ "${1:-}" = "--crop" ]; then
    if [ "$#" -ne 4 ]; then
        usage
        exit 2
    fi
    prepare_crop "$2" "$3" "$4"
    load_config
    upload_crop "$2" "$3"
    exit 0
fi

if [ "$#" -lt 3 ]; then
    usage
    exit 2
fi

filename="$(basename "$1")"
load_config
echo "Title: $2"
echo "Description: $3"
echo "Tags: ${*:4}"
tag_args=()
for tag in "${@:4}"; do
    tag_args+=(--tag "$tag")
done
if [ "${#tag_args[@]}" -gt 0 ]; then
    "$script_dir/tag_image.py" "$1" --title "$2" --description "$3" "${tag_args[@]}"
else
    "$script_dir/tag_image.py" "$1" --title "$2" --description "$3"
fi
echo "Uploading $filename..."
aws s3 cp "$1" "s3://${PHOTO_BUCKET}/${PHOTO_PREFIX}${filename}" --region "$PHOTO_REGION"
