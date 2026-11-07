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

  # Dependabot cannot sign off. Its commits are exempt; any human commit added
  # to a Dependabot branch is still checked.
  if [[ "$(git log -1 --format='%an <%ae>|%cn <%ce>' "$sha")" == \
    'dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>|GitHub <noreply@github.com>' ]]; then
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
