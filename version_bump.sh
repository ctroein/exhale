#!/usr/bin/env bash
# Bumps the version number: creates an empty release commit, tags it, and pushes it.

set -euo pipefail

usage() {
    echo "Usage: $0 {major|minor|patch}" >&2
    exit 1
}

die() {
    echo "Error: $*" >&2
    exit 1
}

[ "$#" -eq 1 ] || usage

part="$1"
case "$part" in
    major|minor|patch) ;;
    *) usage ;;
esac

git rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
    die "not inside a git repository"

[ -z "$(git status --porcelain)" ] ||
    die "working tree has uncommitted or untracked changes"

current=$(git describe --tags --abbrev=0 2>/dev/null || true)
current="${current#v}"

if [ -z "$current" ]; then
    current="0.0.0"
fi

case "$current" in
    *.*.*) ;;
    *) die "latest tag '$current' is not of form vX.Y.Z or X.Y.Z" ;;
esac

IFS='.' read -r major minor patch <<EOF
$current
EOF

case "$major$minor$patch" in
    *[!0-9]*) die "latest tag '$current' contains non-numeric version parts" ;;
esac

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

git rev-parse "$new" >/dev/null 2>&1 &&
    die "tag already exists: $new"

echo "Creating release commit and tag: $new"

git commit --allow-empty -m "Release $new"
git tag "$new"

branch=$(git branch --show-current)
[ -n "$branch" ] || die "not on a branch"

git push origin "$branch"
git push origin "$new"

echo "Released $new"
