#!/bin/sh

# Copyright (c) 2026 CoverIt Labs. All Rights Reserved.
# Proprietary and confidential. Unauthorized use is strictly prohibited.
# See LICENSE file in the project root for full license information.

# Usage:
#   ./docker.sh up                   → remote image + cloud db/redis
#   ./docker.sh up --local           → local dev build + hot-reload + local db/redis
#   ./docker.sh up --test-prod       → local prod build + cloud db/redis
#   ./docker.sh up --tag latest      → remote image (specific tag) + cloud db/redis

print_help() {
  echo "Usage: $0 [up|down|logs] [--tag <tag>] [--local] [--test-prod]"
}

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export API_DIR="$SCRIPT_DIR"

CMD="${1:-up}"
shift 2>/dev/null || true

# Defaults
export API_TAG="dev"
LOCAL=false
TEST_PROD=false

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) export API_TAG="$2"; shift 2 ;;
    --local) LOCAL=true; shift ;;
    --test-prod) TEST_PROD=true; shift ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

# Only --local uses local db/redis. Everything else connects to cloud.
if [ "$LOCAL" = true ]; then
  echo "Starting DocGen Service in local dev mode (local db + redis)..."
  EXEC_CMD="docker compose -f docker-compose.yml -f overrides/api.dev.yml"
elif [ "$TEST_PROD" = true ]; then
  echo "Starting DocGen Service in Production Test mode (local prod build + cloud)..."
  EXEC_CMD="docker compose -f docker-compose.yml -f overrides/api.cloud.yml -f overrides/api.test.yml"
else
  echo "Starting DocGen Service with remote images (Tag: $API_TAG) + cloud..."
  EXEC_CMD="docker compose -f docker-compose.yml -f overrides/api.cloud.yml"
fi

case "$CMD" in
  up)
    $EXEC_CMD up --build -d
    ;;
  down)
    $EXEC_CMD down
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