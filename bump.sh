#!/usr/bin/env bash
# Bumps the version number: creates and pushes a tag

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 {major|minor|patch}"
    exit 1
fi

part="$1"

if [[ "$part" != "major" && "$part" != "minor" && "$part" != "patch" ]]; then
    echo "Error: argument must be one of: major, minor, patch"
    exit 1
fi

# Get latest tag (strip leading v)
current=$(git describe --tags --abbrev=0 2>/dev/null | sed 's/^v//')

if [ -z "$current" ]; then
    current="0.0.0"
fi

IFS='.' read -r major minor patch <<< "$current"

case "$part" in
    major)
        major=$((major + 1))
        minor=0
        patch=0
        ;;
    minor)
        minor=$((minor + 1))
        patch=0
        ;;
    patch)
        patch=$((patch + 1))
        ;;
esac

new="v${major}.${minor}.${patch}"

echo "Tagging $new"

git commit --allow-empty -m "Release $new"
git tag "$new"
git push --tags
