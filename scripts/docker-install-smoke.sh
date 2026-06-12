#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

ENGINE=${AMBARA_CONTAINER_ENGINE:-}
if [ -z "$ENGINE" ]; then
  if command -v docker >/dev/null 2>&1; then
    ENGINE=docker
  elif command -v podman >/dev/null 2>&1; then
    ENGINE=podman
  else
    echo "Docker or Podman is required for the container install smoke." >&2
    exit 127
  fi
fi

IMAGE=${AMBARA_DOCKER_IMAGE:-ambara:local-preview}
WORK_ROOT=${AMBARA_DOCKER_SMOKE_ROOT:-/tmp/ambara-docker-install-smoke}

case "$WORK_ROOT" in
  /tmp/*) ;;
  *)
    echo "AMBARA_DOCKER_SMOKE_ROOT must be under /tmp for this smoke harness." >&2
    exit 2
    ;;
esac

rm -rf "$WORK_ROOT"
mkdir -p "$WORK_ROOT"
chmod 777 "$WORK_ROOT"

cd "$REPO_ROOT"

echo "[1/4] build local Ambara image"
"$ENGINE" build -t "$IMAGE" -f "$REPO_ROOT/Dockerfile" "$REPO_ROOT"

echo "[2/4] smoke container CLI"
"$ENGINE" run --rm "$IMAGE" --version
"$ENGINE" run --rm "$IMAGE" --help >/dev/null
"$ENGINE" run --rm "$IMAGE" explain >/dev/null
if "$ENGINE" run --rm "$IMAGE" serve --check \
  > "$WORK_ROOT/serve-check.out" \
  2> "$WORK_ROOT/serve-check.err"; then
  echo "container serve --check should fail without AMBARA_KNOWLEDGE_REMOTE" >&2
  exit 1
fi
grep -q "AMBARA_KNOWLEDGE_REMOTE is required" "$WORK_ROOT/serve-check.err"

echo "[3/4] run demo proof inside container"
"$ENGINE" run --rm \
  -v "$WORK_ROOT:/workspace" \
  "$IMAGE" demo --path /workspace/demo --force
"$ENGINE" run --rm \
  -v "$WORK_ROOT:/workspace" \
  --entrypoint /bin/bash \
  "$IMAGE" -lc "/workspace/demo/run-proof.sh"

echo "[4/4] smoke fixture-backed preview sources inside container"
cat > "$WORK_ROOT/linear.json" <<'JSON'
{
  "issues": [
    {
      "id": "LIN-12",
      "url": "https://linear.app/acme/issue/LIN-12/auth-rollout",
      "title": "Auth rollout handoff",
      "description_excerpt": "Coordinate token rollout with web.",
      "state": "completed",
      "labels": ["ambara", "auth"],
      "project": "Auth Platform",
      "team": "Eng",
      "updated_at": "2026-06-05T10:30:00Z",
      "completed_at": "2026-06-05T10:45:00Z",
      "subject_refs": ["src/auth/tokens.py"],
      "subject_areas": ["src/auth"]
    }
  ]
}
JSON
"$ENGINE" run --rm \
  -v "$WORK_ROOT:/workspace" \
  "$IMAGE" source-smoke \
    --provider linear \
    --fixture /workspace/linear.json \
    --project "Auth Platform" \
    --json > "$WORK_ROOT/linear-source-smoke.json"
grep -q '"provider_id": "linear"' "$WORK_ROOT/linear-source-smoke.json"
grep -q '"category": "work_tracker"' "$WORK_ROOT/linear-source-smoke.json"

cat > "$WORK_ROOT/confluence.json" <<'JSON'
{
  "pages": [
    {
      "id": "98765",
      "url": "https://wiki.example.com/spaces/ENG/pages/98765/Auth",
      "title": "Auth token rotation runbook",
      "excerpt": "Current operator steps for token rotation.",
      "status": "current",
      "labels": ["ambara", "auth"],
      "space": "ENG",
      "updated_at": "2026-06-05T10:30:00Z",
      "subject_areas": ["auth"],
      "subject_refs_status": "unavailable"
    }
  ]
}
JSON
"$ENGINE" run --rm \
  -v "$WORK_ROOT:/workspace" \
  "$IMAGE" source-smoke \
    --provider confluence \
    --fixture /workspace/confluence.json \
    --project ENG \
    --json > "$WORK_ROOT/confluence-source-smoke.json"
grep -q '"provider_id": "confluence"' "$WORK_ROOT/confluence-source-smoke.json"
grep -q '"category": "docs"' "$WORK_ROOT/confluence-source-smoke.json"

echo "Docker install smoke passed: $WORK_ROOT"
