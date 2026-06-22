import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from pydantic import ValidationError

from src.models.manual_bug import ManualBugReportInput
from src.models.video import VideoGenerationResult
from src.services.video.encoder import resolve_ffmpeg_path
from src.tasks.manual_bug import task_generate_manual_bug_report
from src.worker import WorkerSettings


class AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class Driver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return AsyncContext(self._session)


class ManualBugTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_generates_video_and_uploads_to_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            artifact_path = Path(temp) / "session-video.mp4"
            artifact_path.write_bytes(b"fake mp4")

            video_repo = Mock()
            video_repo.resolve_flows = AsyncMock(return_value=[Mock()])
            generator = Mock()
            generator.generate = AsyncMock(
                return_value=VideoGenerationResult(
                    status="success",
                    session_id="session-1",
                    artifact_path=str(artifact_path),
                    duration_seconds=1.0,
                    resolution="1280x720",
                    fps=30,
                    flow_count=1,
                )
            )
            report_client = Mock()
            report_client.get_context = AsyncMock(
                return_value={
                    "report": {
                        "id": "report-1",
                        "externalIssueKey": None,
                        "externalIssueUrl": None,
                        "attachedArtifactIds": [],
                    },
                    "structuredDescription": {"summary": "Checkout button fails"},
                }
            )
            report_client.patch_report = AsyncMock()
            issue = SimpleNamespace(key="COV-1", id="10001", url="https://site.test/browse/COV-1")
            provider = Mock()
            provider.create_issue = AsyncMock(return_value=issue)
            provider.upload_attachment = AsyncMock()

            with (
                patch("src.tasks.manual_bug.neo_manager.driver", Driver(Mock())),
                patch("src.tasks.manual_bug.VideoRepository", return_value=video_repo),
                patch("src.tasks.manual_bug.VideoGenerator", return_value=generator),
                patch("src.tasks.manual_bug._report_client", report_client),
                patch("src.tasks.manual_bug.get_provider", return_value=provider),
            ):
                result = await task_generate_manual_bug_report(
                    {},
                    {
                        "report_id": "report-1",
                        "provider": "jira",
                        "session_id": "session-1",
                        "flow_id": "flow-1",
                        "checkpoint_hash": "state-1",
                        "transition_ids": ["transition-1"],
                        "summary": "Checkout button fails",
                        "severity": "high",
                        "current_url": "https://app.test/cart",
                        "recorded_events": [{"action": "click"}],
                    },
                )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["report_id"], "report-1")
        provider.create_issue.assert_awaited_once()
        provider.upload_attachment.assert_has_awaits(
            [
                call(
                    report_client.get_context.return_value,
                    "COV-1",
                    "manual-bug-flow-1.mp4",
                    b"fake mp4",
                    "video/mp4",
                ),
                call(
                    report_client.get_context.return_value,
                    "COV-1",
                    "manual-bug-flow-1-recorded-events.json",
                    b'[\n  {\n    "action": "click"\n  }\n]',
                    "application/json",
                ),
            ]
        )
        report_client.patch_report.assert_any_await(
            "report-1",
            {
                "status": "created",
                "attachedArtifactIds": ["manual-bug-recorded-events:flow-1", "manual-bug-video:flow-1"],
                "externalIssueKey": "COV-1",
                "externalIssueUrl": "https://site.test/browse/COV-1",
                "lastError": None,
            },
        )

    async def test_rejects_missing_transition_ids(self):
        with self.assertRaises(ValidationError):
            await task_generate_manual_bug_report(
                {},
                {
                    "report_id": "report-1",
                    "session_id": "session-1",
                    "flow_id": "flow-1",
                    "checkpoint_hash": "state-1",
                    "transition_ids": [],
                    "summary": "Checkout button fails",
                    "severity": "high",
                },
            )

    def test_worker_registers_manual_bug_task(self):
        functions_by_name = {
            getattr(function, "name", getattr(function, "__name__", "")): function
            for function in WorkerSettings.functions
        }
        names = set(functions_by_name)
        self.assertIn("task_generate_manual_bug_report", names)
        self.assertEqual(functions_by_name["task_generate_manual_bug_report"].timeout_s, 900)

    def test_model_rejects_blank_transition_ids(self):
        with self.assertRaises(ValidationError):
            ManualBugReportInput.model_validate(
                {
                    "report_id": "report-1",
                    "session_id": "session-1",
                    "flow_id": "flow-1",
                    "checkpoint_hash": "state-1",
                    "transition_ids": [""],
                    "summary": "Checkout button fails",
                    "severity": "high",
                }
            )

    def test_ffmpeg_resolver_accepts_configured_path(self):
        self.assertEqual(
            resolve_ffmpeg_path("C:/tools/ffmpeg.exe"),
            str(Path("C:/tools/ffmpeg.exe")),
        )


if __name__ == "__main__":
    unittest.main()
