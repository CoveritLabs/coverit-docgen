## Project Overview
- `coverit-docgen` is a background document-generation and semantic-labeling service.
- Its primary implemented workflow incrementally labels UI states and transitions stored as a session graph in Neo4j.
- It generates human-readable page names, descriptions, element names, and action descriptions from recorded URLs, HTML snapshots, geometry, and Playwright locators.

## Tech Stack
- Python 3.10+; production image uses Python 3.11.
- ARQ async worker and cron scheduling over Redis.
- Neo4j async driver for session graphs and labeling status.
- Pydantic and `pydantic-settings` for data models and environment configuration.
- Beautiful Soup for HTML parsing.
- Playwright Chromium for resolving transition locators.
- Docker and Docker Compose.
- Standard-library `unittest`.

## Contract Types
- Install the generated Python package with `uv` using the `coverit-contracts` distribution name.
- Import protobuf modules from the generated `contracts` namespace, for example `from contracts.crawler.v1 import crawler_pb2`.

## Current Architecture
- `src/worker.py`: ARQ entry point, lifecycle hooks, task registration, cron configuration, and early logging setup.
- `src/tasks/poller.py`: atomically claims eligible Neo4j records and enqueues one graph-labeling job per session.
- `src/tasks/labeling.py`: single-state, single-transition, and session-graph tasks with per-item failure isolation.
- `src/repositories/labeling_repo.py`: Neo4j persistence boundary.
- `src/models/queries.py`: centralized Cypher statements.
- `src/services/labeling/`: page analysis, element naming, action descriptions, and Playwright-based transition labeling.
- `src/core/`: settings, logging, Neo4j, Redis, and Playwright lifecycle management.
- `src/services/video`: live-URL MP4 walkthrough generation using Playwright screenshots, composited cursor/zoom effects, optional audio, and ffmpeg encoding.

## Existing Data Models
- Neo4j `State` node:
  - `session_id`: owning recorded session.
  - `url`, `html`: page snapshot inputs.
  - `name`, `description`: generated labels.
  - `labeling_status`: `PENDING`, `QUEUED`, `COMPLETED`, or absent.
  - `labeling_claim_id`: temporary poll-specific ownership token.
- Neo4j `TRANSITION` relationship connects two `State` nodes:
  - `locator_value`: Playwright locator for the interacted element.
  - `name`, `action`: generated semantic labels.
  - Same status and claim fields as states.
- Pydantic models:
  - `CrawlerState`, `CrawlerTransition`, `CrawlerGraph`.
  - `LabeledState`, `LabeledTransition`, `LabeledGraph`.
  - `CrawlerGraph.skip_states` identifies origin states loaded only as transition context.
- The active labeling workflow reads and writes labels directly in Neo4j.

## Features Already Implemented
- Incremental graph polling:
  - Claims only absent/`PENDING` records and changes them to `QUEUED`.
  - Uses a unique UUID claim token generated once per poll query.
- Session-isolated processing:
  - State and transition graph fetches are scoped by `session_id`.
  - Transitions require both endpoint states to belong to the session.
- Fault-tolerant ARQ dispatch:
  - Claims occur before enqueueing.
  - Enqueue failure returns exactly the claimed IDs to `PENDING`.
- Per-item graph labeling:
  - Successful records are immediately saved as `COMPLETED`.
  - A failed record alone returns to `PENDING`; processing continues.
- Single-item rollback:
  - States and transitions are identified by Neo4j `elementId`; no redundant session lookup is performed.
- Page analysis:
  - Combines semantic URL paths, selected query parameters, fragments, title, `h1`, Open Graph tags, metadata, active navigation, and domain fallback.
  - Filters numeric IDs, UUIDs, tokens, filenames, tracking parameters, pagination, and sorting.
  - Produces deterministic names and descriptions capped at 160 characters.
- Element contextual naming:
  - Uses nearby meaningful elements when within a normalized `0.40` distance threshold.
  - Uses one of nine absolute screen regions for distant or absent neighbors.
- Transition labeling:
  - Uses Playwright Chromium to resolve and mark the locator in page HTML.
  - Generates an element name, cleaned HTML snippet, and action description.
- Logging:
  - Console and rotating `/app/logs/worker.log` handlers.
  - Application debug logging remains available.
  - Neo4j debug/info output is suppressed; warnings and errors remain.
- Container support:
  - Non-root production worker.
  - Chromium and system dependencies installed.
  - Persistent Compose volume for logs.
- Automated coverage for query invariants, rollback behavior, async transitions, page analysis, contextual naming, logging, and enqueue failures.

## Local Worker
- Start API, frontend, Postgres, Redis, and Neo4j from `coverit-frontend`:
  ```sh
  ./docker.sh up --local --app-only --no-build
  ```
- Copy `.env.example` to `.env`, then run DocGen locally with file watching:
  ```sh
  python scripts/run_local_worker.py
  ```

## Important Design Decisions
- Neo4j is the source of truth for graph topology and labeling lifecycle.
- Status lifecycle is `NULL/PENDING -> QUEUED -> COMPLETED`, with failures returning only the affected item to `PENDING`.
- Claiming and status mutation happen in one Cypher query before ARQ dispatch.
- A dynamic `labeling_claim_id` distinguishes records claimed by concurrent poll runs.
- Neo4j `elementId` is the authoritative identifier for individual state and transition operations.
- Graph-session boundaries remain mandatory for graph fetches, claims, and transition endpoint validation.
- Labeling is deterministic and local; it does not call an external AI service.
- Logging must be initialized before importing modules that create loggers.

## Existing Constraints
- Labeling operations and Neo4j access are asynchronous.
- Playwright-dependent transition labeling must be awaited.
- Missing transition HTML, locator metadata, locator matches, names, or actions are failures and must not be saved as completed.
- Completed records must never be reclaimed or relabeled.
- One failing item must not roll back successful or unrelated items.
- ARQ enqueue failure must not leave records permanently `QUEUED`.
- Neo4j indexes are recommended for `State(session_id)`, `State(labeling_status)`, composite state session/status lookup, and transition status.
- `max_sessions_per_poll` and `context_distance_threshold` are settings; the current defaults are `5` and `0.40`.

## Coding Conventions In This Project
- Use async functions for Neo4j, ARQ, and Playwright workflows.
- Keep Cypher in `src/models/queries.py`.
- Keep Neo4j access behind `LabelingRepository`.
- Keep orchestration in `src/tasks` and semantic logic in `src/services`.
- Use Pydantic models at service boundaries.
- Use `logging.getLogger(...)`; do not call `basicConfig`.
- Use parameterized logging rather than interpolated strings where practical.
- Raise explicit errors for invalid labeling inputs so callers can perform status rollback.
- Tests use `unittest`, `IsolatedAsyncioTestCase`, and `unittest.mock`.

## Things Future Features Must Be Compatible With
- Preserve `get_page_info(url, soup) -> {"name": ..., "description": ...}`.
- Preserve uppercase Neo4j status values and their lifecycle.
- Preserve dynamic UUID claim ownership; never replace `$claim_id` with a fixed value.
- Preserve queued-only completion and rollback guards.
- Preserve per-item failure isolation.
- Preserve Neo4j `elementId` identifiers for individual state and transition operations.
- Preserve session scoping for graph-level operations and transition endpoint validation.
- Preserve ARQ task names registered in `WorkerSettings`.
- Preserve early logging initialization, Neo4j warning-level filtering, rotating file logging, and `/app/logs` persistence.
- Production images must include Playwright Chromium and run as the non-root `docgen` user.

## Video Generation Task

`task_generate_video` creates an MP4 product walkthrough from the same flow input shape used by BDD:

```json
{
  "session_id": "session-id",
  "flows": [
    {
      "checkpoint_hash": "start-state-hash",
      "transition_ids": ["transition-1"]
    }
  ]
}
```

The task waits for labeling completion just like BDD, opens the checkpoint/start URL in Playwright, performs the recorded actions on the live page, and renders a reference-style walkthrough: the app appears as a smaller floating window with shadow on a neutral background, with smooth zoom, cursor movement, typing, and UI sounds.

```json
{
  "status": "success",
  "session_id": "session-id",
  "artifact_path": "artifacts/videos/session-id-video.mp4",
  "duration_seconds": 4.2,
  "resolution": "1280x720",
  "fps": 30,
  "flow_count": 1
}
```

By default, Docker mounts container output from `/app/artifacts` to the host project folder `artifacts/`, so generated videos are visible at `artifacts/videos/<session-id>-video.mp4`. Set `DOCGEN_ARTIFACTS_DIR` to mount a different host directory.

Runtime requirements:
- Playwright Chromium for live-page rendering. The checkpoint URL must be reachable from inside the DocGen container.
- Pillow for frame compositing.
- `ffmpeg` for MP4/H.264 encoding and optional audio muxing.

Rendering notes:
- The renderer does not use a spotlight/dim mask around target elements.
- The click pulse animation is intentionally omitted.
- Higher `VIDEO_ACTION_SPEED` values make transitions faster; lower values make them slower.
- Audio uses click and keypress sounds only, then normalizes the WAV mix before ffmpeg muxes it into the MP4.

Environment defaults:
- `VIDEO_MAX_RETRIES`
- `VIDEO_RETRY_DELAY_SECONDS`
- `VIDEO_OUTPUT_DIR`
- `VIDEO_DEFAULT_WIDTH`
- `VIDEO_DEFAULT_HEIGHT`
- `VIDEO_DEFAULT_FPS`
- `VIDEO_DEFAULT_AUDIO_ENABLED`
- `VIDEO_DEFAULT_AUDIO_VOLUME`
- `VIDEO_AUDIO_GAIN`
- `VIDEO_AUDIO_NORMALIZE_PEAK`
- `VIDEO_ACTION_SPEED`
- `VIDEO_WINDOW_SCALE`
- `VIDEO_WINDOW_BACKGROUND_COLOR`
- `VIDEO_WINDOW_SHADOW_STRENGTH`
- `VIDEO_WINDOW_BORDER_RADIUS`
- `VIDEO_PRE_ACTION_HOLD_SECONDS`
- `VIDEO_ZOOM_SECONDS`
- `VIDEO_CURSOR_TRAVEL_SECONDS`
- `VIDEO_ACTION_HOLD_SECONDS`
- `VIDEO_PAGE_SETTLE_SECONDS`
- `VIDEO_RELEASE_SECONDS`
- `VIDEO_TYPING_FRAME_SECONDS`
- `VIDEO_RANDOM_SEED`
