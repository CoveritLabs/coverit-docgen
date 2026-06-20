#!/bin/sh

# Copyright (c) 2026 CoverIt Labs. All Rights Reserved.
# Proprietary and confidential. Unauthorized use is strictly prohibited.
# See LICENSE file in the project root for full license information.

# Usage:
#   ./docker.sh up                   -> remote image + external Redis/API
#   ./docker.sh up --local           -> local dev build + shared/fallback Redis
#   ./docker.sh up --test-prod       -> local prod build + external Redis/API
#   ./docker.sh up --tag latest      -> remote image with specific tag

print_help() {
  echo "Usage: $0 [up|down|logs] [--tag <tag>] [--local] [--test-prod]"
}

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export DOCGEN_DIR="$SCRIPT_DIR"

CMD="${1:-up}"
shift 2>/dev/null || true

export DOCGEN_TAG="dev"
LOCAL=false
TEST_PROD=false

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) export DOCGEN_TAG="$2"; shift 2 ;;
    --local) LOCAL=true; shift ;;
    --test-prod) TEST_PROD=true; shift ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

ENV_FILE_ARG=""
if [ -f "$DOCGEN_DIR/.env" ]; then
  ENV_FILE_ARG="--env-file $DOCGEN_DIR/.env"
fi

host_redis_exists() {
  if docker ps --filter "name=^/coverit-redis$" --format "{{.Names}}" 2>/dev/null | grep -qx "coverit-redis"; then
    return 0
  fi

  if docker ps --filter "publish=6379" --format "{{.Names}}" 2>/dev/null | grep -q .; then
    return 0
  fi

  if command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 6379 >/dev/null 2>&1; then
    return 0
  fi

  return 1
}

EXEC_CMD="docker compose $ENV_FILE_ARG -f $DOCGEN_DIR/docker-compose.yml"

if [ "$LOCAL" = true ]; then
  echo "Starting DocGen in local dev mode..."

  if [ -z "$API_BASE_URL" ]; then
    export API_BASE_URL="http://host.docker.internal:3000/api/v1"
  fi

  if [ "$CMD" = "down" ]; then
    EXEC_CMD="$EXEC_CMD -f $DOCGEN_DIR/docker-compose.redis.yml"
  elif [ -n "$REDIS_URL" ]; then
    echo "Using REDIS_URL from environment."
  elif host_redis_exists; then
    export REDIS_URL="redis://host.docker.internal:6379"
    echo "Using existing Redis on host port 6379."
  else
    echo "No existing Redis detected; starting DocGen internal Redis."
    EXEC_CMD="$EXEC_CMD -f $DOCGEN_DIR/docker-compose.redis.yml"
  fi

  EXEC_CMD="$EXEC_CMD -f $DOCGEN_DIR/overrides/standalone.local.yml -f $DOCGEN_DIR/overrides/api.dev.yml"
elif [ "$TEST_PROD" = true ]; then
  echo "Starting DocGen in Production Test mode (local prod build + external Redis/API)..."
  EXEC_CMD="$EXEC_CMD -f $DOCGEN_DIR/overrides/api.cloud.yml -f $DOCGEN_DIR/overrides/api.test.yml"
else
  echo "Starting DocGen with remote image (DOCGEN_TAG=$DOCGEN_TAG) + external Redis/API..."
  EXEC_CMD="$EXEC_CMD -f $DOCGEN_DIR/overrides/api.cloud.yml"
fi

case "$CMD" in
  up)
    $EXEC_CMD up -d --build --remove-orphans
    ;;
  down)
    $EXEC_CMD down --remove-orphans
    ;;
  logs)
    $EXEC_CMD logs -f
    ;;
  *)
    echo "Unknown command: $CMD"
    print_help
    exit 1
    ;;
esac
