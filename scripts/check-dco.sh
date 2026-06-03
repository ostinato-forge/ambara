#!/usr/bin/env bash
set -euo pipefail

range="${1:-}"

if [[ -z "$range" ]]; then
  echo "usage: scripts/check-dco.sh <base..head>" >&2
  exit 2
fi

missing=0

while IFS= read -r sha; do
  if [[ -z "$sha" ]]; then
    continue
  fi

  if ! git log -1 --format=%B "$sha" \
    | git interpret-trailers --parse \
    | grep -Eiq '^Signed-off-by: [^<]+ <[^@<>]+@[^<>]+>$'; then
    echo "::error title=Missing DCO sign-off::Commit ${sha} is missing Signed-off-by: Name <email>"
    missing=1
  fi
done < <(git rev-list --no-merges --reverse "$range")

exit "$missing"
