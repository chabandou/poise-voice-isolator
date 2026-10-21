#!/usr/bin/env bash
# Attach one workflow's files to the tag's GitHub Release.
#
#   tools/release_upload.sh vX.Y.Z FILE...
#
# build-linux.yml and build-windows.yml each publish part of a release.
# The release stays a draft until every file below is attached, and the
# workflow that completes the set publishes it: a release that went
# public with the first platform's files would be offered to Windows
# users (in-app updates, stream_denoiser/updates.py) before it had
# PoiseCore.exe to install.
#
# Needs GH_TOKEN and GH_REPO (set by the workflows).
set -euo pipefail

EXPECTED=(poise Poise_Setup.exe PoiseCore.exe PoiseCore.exe.sha256)

tag="$1"
shift

if ! gh release view "$tag" >/dev/null 2>&1; then
    # The other workflow may create it at the same moment: then use its.
    gh release create "$tag" --draft --verify-tag --generate-notes \
        --title "$tag" \
        || gh release view "$tag" >/dev/null
fi

gh release upload "$tag" "$@" --clobber

assets=$(gh release view "$tag" --json assets --jq '.assets[].name')
for name in "${EXPECTED[@]}"; do
    if ! grep -qxF "$name" <<<"$assets"; then
        echo "$tag: waiting for $name, the release stays a draft"
        exit 0
    fi
done

if [ "$(gh release view "$tag" --json isDraft --jq .isDraft)" = "true" ]; then
    gh release edit "$tag" --draft=false
    echo "$tag: every file is attached, release published"
else
    echo "$tag: already published"
fi
