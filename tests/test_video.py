import shutil
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from arq import Retry

from src.models.bdd import BddFlowInput
from src.models.queries import RESOLVE_VIDEO_FLOWS
from src.models.video import (
    VideoGenerationResult,
    parse_video_action_values,
)
from src.repositories.video_repo import VideoRepository
from src.services.video.config import VideoRenderConfig, get_video_render_config
from src.services.video.encoder import FfmpegEncoder
from src.services.video.effects import (
    Point,
    Rect,
    camera_for_target,
    curved_cursor_path,
    ease_out_cubic,
)
from src.services.video.renderer import BrowserFrameRenderer
from src.services.video.timeline import VideoFlowTimeline, VideoShot, build_timelines
from src.services.video.typing import typing_frames
from src.tasks.video import task_generate_video


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

class FakeKeyboard:
    def __init__(self):
        self.typed = ""

    async def type(self, text: str):
        self.typed += text


class FakeLocator:
    def __init__(self):
        self.first = self
        self.count = AsyncMock(return_value=1)
        self.scroll_into_view_if_needed = AsyncMock()
        self.bounding_box = AsyncMock(
            return_value={"x": 80, "y": 45, "width": 80, "height": 32}
        )
        self.click = AsyncMock()
        self.fill = AsyncMock()
        self.select_option = AsyncMock()


class FakePage:
    def __init__(self):
        self.goto = AsyncMock()
        self.close = AsyncMock()
        self.wait_for_load_state = AsyncMock()
        self.keyboard = FakeKeyboard()
        self._locators: dict[str, FakeLocator] = {}

    def locator(self, selector: str) -> FakeLocator:
        self._locators.setdefault(selector, FakeLocator())
        return self._locators[selector]

    async def screenshot(self, full_page: bool = False):
        from PIL import Image

        image = Image.new("RGB", (320, 180), (245, 245, 245))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()


class VideoModelTests(unittest.TestCase):
    def test_internal_config_defaults_are_valid(self):
        config = get_video_render_config()
        self.assertEqual(config.width, 1280)
        self.assertEqual(config.height, 720)
        self.assertEqual(config.action_speed, 1.0)
        self.assertEqual(config.window_scale, 0.86)

    def test_action_value_normalizes_crawler_shorthand(self):
        actions = parse_video_action_values(
            '[{"s":"#email","t":"fill","v":"user@example.com"}]',
            "#fallback",
            "click",
        )
        self.assertEqual(actions[0].selector, "#email")
        self.assertEqual(actions[0].action_type, "fill")
        self.assertEqual(actions[0].value, "user@example.com")

    def test_action_value_falls_back_to_locator(self):
        actions = parse_video_action_values([], "#submit", "click")
        self.assertEqual(actions[0].selector, "#submit")
        self.assertEqual(actions[0].action_type, "click")


class VideoEffectTests(unittest.TestCase):
    def test_ease_out_cubic_decelerates(self):
        self.assertEqual(ease_out_cubic(0), 0)
        self.assertEqual(ease_out_cubic(1), 1)
        self.assertGreater(ease_out_cubic(0.5), 0.5)

    def test_curved_cursor_path_stays_subtle_and_reaches_target(self):
        start = Point(0, 0)
        end = Point(100, 0)
        middle = curved_cursor_path(start, end, 0.5)
        self.assertLess(middle.y, 0)
        self.assertEqual(curved_cursor_path(start, end, 1), end)

    def test_camera_keeps_crop_inside_viewport(self):
        camera = camera_for_target(1280, 720, Rect(1200, 650, 40, 40), 1.2)
        self.assertGreaterEqual(camera.crop_x, 0)
        self.assertGreaterEqual(camera.crop_y, 0)
        self.assertLessEqual(camera.crop_x + camera.crop_width, 1280)
        self.assertLessEqual(camera.crop_y + camera.crop_height, 720)


class VideoTypingTests(unittest.TestCase):
    def test_typing_frames_are_seeded(self):
        first = typing_frames("abc", seed=7)
        second = typing_frames("abc", seed=7)
        self.assertEqual(first, second)
        self.assertEqual(first[-1].text, "abc")
        self.assertFalse(first[-1].caret_visible)

    def test_action_speed_shortens_typing_timeline(self):
        normal = typing_frames("abc", seed=7, speed=1.0)
        fast = typing_frames("abc", seed=7, speed=2.0)
        self.assertLess(fast[-1].at_seconds, normal[-1].at_seconds)


class VideoRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_returns_checkpoint_url_and_no_html_render_fields(self):
        self.assertIn("checkpoint.url AS checkpoint_url", RESOLVE_VIDEO_FLOWS)
        self.assertIn("transition.action_value AS action_value", RESOLVE_VIDEO_FLOWS)
        self.assertNotIn("checkpoint.html AS checkpoint_html", RESOLVE_VIDEO_FLOWS)
        self.assertNotIn("from.html AS from_html", RESOLVE_VIDEO_FLOWS)
        self.assertNotIn("to.html AS to_html", RESOLVE_VIDEO_FLOWS)
        self.assertNotIn("transition.name AS transition_name", RESOLVE_VIDEO_FLOWS)
        self.assertNotIn("from.description AS from_description", RESOLVE_VIDEO_FLOWS)

    async def test_disconnected_flow_is_rejected(self):
        result = Mock()
        result.data = AsyncMock(
            return_value=[
                {
                    "flow_index": 0,
                    "transition_index": 0,
                    "checkpoint_hash": "start",
                    "checkpoint_url": "https://example.test/start",
                    "transition_id": "go",
                    "action_type": "click",
                    "locator_value": "#go",
                    "action_value": '[{"s":"#go","t":"click"}]',
                    "from_hash": "wrong",
                    "to_hash": "end",
                }
            ]
        )
        session = Mock()
        session.run = AsyncMock(return_value=result)

        with self.assertRaisesRegex(ValueError, "does not continue"):
            await VideoRepository(session).resolve_flows(
                "graph-1",
                [BddFlowInput(checkpoint_hash="start", transition_ids=["go"])],
            )


class VideoTimelineTests(unittest.TestCase):
    def test_multistep_transition_expands_to_shots(self):
        from src.models.video import (
            VideoActionValue,
            VideoResolvedFlow,
            VideoResolvedTransition,
        )

        flow = VideoResolvedFlow(
            start_url="https://example.test/start",
            transitions=[
                VideoResolvedTransition(
                    transition_id="go",
                    action_value=[
                        VideoActionValue(selector="#email", action_type="fill", value="a"),
                        VideoActionValue(selector="#submit", action_type="click"),
                    ],
                )
            ],
        )

        timelines = build_timelines([flow])
        self.assertEqual(timelines[0].start_url, "https://example.test/start")
        self.assertEqual([shot.selector for shot in timelines[0].shots], ["#email", "#submit"])
        self.assertTrue(timelines[0].shots[0].has_typing)
        self.assertFalse(timelines[0].shots[1].has_typing)


class VideoRendererTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_renderer_goto_uses_bounding_box_and_clicks(self):
        page = FakePage()
        browser = Mock()
        browser.new_page = AsyncMock(return_value=page)

        config = VideoRenderConfig(
            width=320,
            height=180,
            fps=10,
            action_speed=4.0,
            random_seed=42,
        )

        timeline = VideoFlowTimeline(
            start_url="https://example.test/start",
            shots=[
                VideoShot(
                    transition_id="go",
                    selector="#go",
                    action_type="click",
                    value=None,
                )
            ],
        )

        from PIL import Image

        with tempfile.TemporaryDirectory() as temp:
            with (
                patch("src.services.video.renderer.playwright_manager._browser", browser),
                patch(
                    "src.services.video.renderer.load_cursor_image",
                    return_value=(Image.new("RGBA", (12, 12), (0, 0, 0, 255)), (0, 0)),
                ),
            ):
                output = await BrowserFrameRenderer(config).render(
                    [timeline],
                    Path(temp),
                )
                self.assertGreater(len(output.frame_paths), 0)
                first_frame = Image.open(output.frame_paths[0]).convert("RGB")

        page.goto.assert_awaited_once_with(
            "https://example.test/start",
            wait_until="load",
            timeout=30000,
        )
        page.locator("#go").first.bounding_box.assert_awaited()
        page.locator("#go").first.click.assert_awaited()
        self.assertNotEqual(first_frame.getpixel((0, 0)), first_frame.getpixel((160, 90)))
        self.assertGreaterEqual(min(first_frame.getpixel((160, 90))), 240)

    async def test_live_renderer_selects_and_types_real_page_actions(self):
        page = FakePage()
        browser = Mock()
        browser.new_page = AsyncMock(return_value=page)
        config = VideoRenderConfig(
            width=320,
            height=180,
            fps=10,
            action_speed=5.0,
            random_seed=42,
        )
        timeline = VideoFlowTimeline(
            start_url="https://example.test/start",
            shots=[
                VideoShot("choose", "#plan", "select", "pro"),
                VideoShot("name", "#name", "fill", "Al"),
            ],
        )

        from PIL import Image

        with tempfile.TemporaryDirectory() as temp:
            with (
                patch("src.services.video.renderer.playwright_manager._browser", browser),
                patch(
                    "src.services.video.renderer.load_cursor_image",
                    return_value=(Image.new("RGBA", (12, 12), (0, 0, 0, 255)), (0, 0)),
                ),
            ):
                await BrowserFrameRenderer(config).render([timeline], Path(temp))

        page.locator("#plan").first.select_option.assert_awaited_once_with(
            "pro",
            timeout=5000,
        )
        page.locator("#name").first.fill.assert_awaited_once_with("", timeout=3000)
        self.assertEqual(page.keyboard.typed, "Al")

    async def test_action_speed_changes_stage_frame_counts(self):
        slow = BrowserFrameRenderer(
            VideoRenderConfig(
                width=320,
                height=180,
                fps=10,
                action_speed=0.5,
                random_seed=42,
            )
        )
        fast = BrowserFrameRenderer(
            VideoRenderConfig(
                width=320,
                height=180,
                fps=10,
                action_speed=2.0,
                random_seed=42,
            )
        )
        self.assertGreater(
            slow._scaled_frame_count(1.0),
            fast._scaled_frame_count(1.0),
        )


class VideoEncoderTests(unittest.TestCase):
    def test_encoder_uses_video_only_command(self):
        with tempfile.TemporaryDirectory() as temp:
            frame = Path(temp) / "frame_00001.png"
            output = Path(temp) / "out.mp4"
            with patch("src.services.video.encoder.subprocess.run") as run:
                run.return_value = Mock(returncode=0, stdout="", stderr="")
                FfmpegEncoder(ffmpeg_path="ffmpeg").encode(
                    [frame],
                    30,
                    output,
                )

        command = run.call_args.args[0]
        self.assertIn("-c:v", command)
        self.assertIn("libx264", command)
        self.assertNotIn("-map", command)
        self.assertNotIn("-c:a", command)


class VideoTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_labeling_is_claimed_enqueued_and_deferred(self):
        repo = Mock()
        repo.get_labeling_status = AsyncMock(
            return_value={
                "state_count": 1,
                "transition_count": 1,
                "pending_states": 1,
                "pending_transitions": 0,
                "queued_states": 0,
                "queued_transitions": 0,
                "invalid_states": 0,
                "invalid_transitions": 0,
            }
        )
        repo.claim_unlabeled = AsyncMock(return_value={"state_ids": ["s1"], "transition_ids": []})
        repo.rollback_claim = AsyncMock()
        redis = Mock()
        redis.enqueue_job = AsyncMock(return_value=Mock())

        with (
            patch("src.tasks.video.neo_manager.driver", Driver(Mock())),
            patch("src.tasks.video.BddRepository", return_value=repo),
        ):
            with self.assertRaises(Retry):
                await task_generate_video(
                    {"redis": redis, "job_try": 1},
                    {
                        "graph_id": "graph-1",
                        "flows": [{"checkpoint_hash": "start", "transition_ids": ["go"]}],
                    },
                )

        redis.enqueue_job.assert_awaited_once_with("task_label_graph", "graph-1")
        repo.rollback_claim.assert_not_awaited()

    async def test_enqueue_failure_rolls_back_and_skips_rendering(self):
        repo = Mock()
        repo.get_labeling_status = AsyncMock(
            return_value={
                "state_count": 1,
                "transition_count": 1,
                "pending_states": 1,
                "pending_transitions": 0,
                "queued_states": 0,
                "queued_transitions": 0,
                "invalid_states": 0,
                "invalid_transitions": 0,
            }
        )
        repo.claim_unlabeled = AsyncMock(
            return_value={"state_ids": ["s1"], "transition_ids": []}
        )
        repo.rollback_claim = AsyncMock()
        redis = Mock()
        redis.enqueue_job = AsyncMock(side_effect=RuntimeError("down"))

        with (
            patch("src.tasks.video.neo_manager.driver", Driver(Mock())),
            patch("src.tasks.video.BddRepository", return_value=repo),
            patch("src.tasks.video.VideoRepository") as video_repo,
            patch("src.tasks.video.VideoGenerator") as generator,
        ):
            result = await task_generate_video(
                {"redis": redis, "job_try": 1},
                {
                    "graph_id": "graph-1",
                    "flows": [{"checkpoint_hash": "start", "transition_ids": ["go"]}],
                },
            )

        repo.rollback_claim.assert_awaited_once_with("graph-1", ["s1"], [])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["graph_id"], "graph-1")
        self.assertEqual(result["lastError"], "down")
        video_repo.assert_not_called()
        generator.assert_not_called()

    async def test_success_returns_artifact_metadata(self):
        repo = Mock()
        repo.get_labeling_status = AsyncMock(
            return_value={
                "state_count": 1,
                "transition_count": 1,
                "pending_states": 0,
                "pending_transitions": 0,
                "queued_states": 0,
                "queued_transitions": 0,
                "invalid_states": 0,
                "invalid_transitions": 0,
            }
        )
        video_repo = Mock()
        video_repo.resolve_flows = AsyncMock(return_value=[Mock()])
        generator = Mock()
        generator.generate = AsyncMock(
            return_value=VideoGenerationResult(
                status="success",
                graph_id="graph-1",
                artifact_path="artifacts/videos/graph-1-video.mp4",
                duration_seconds=1.0,
                resolution="1280x720",
                fps=30,
                flow_count=1,
            )
        )

        with (
            patch("src.tasks.video.neo_manager.driver", Driver(Mock())),
            patch("src.tasks.video.BddRepository", return_value=repo),
            patch("src.tasks.video.VideoRepository", return_value=video_repo),
            patch("src.tasks.video.VideoGenerator", return_value=generator),
        ):
            result = await task_generate_video(
                {"redis": Mock(), "job_try": 1},
                {
                    "graph_id": "graph-1",
                    "flows": [{"checkpoint_hash": "start", "transition_ids": ["go"]}],
                },
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["artifact_path"], "artifacts/videos/graph-1-video.mp4")

    async def test_payload_config_is_not_forwarded_to_generator(self):
        repo = Mock()
        repo.get_labeling_status = AsyncMock(
            return_value={
                "state_count": 1,
                "transition_count": 1,
                "pending_states": 0,
                "pending_transitions": 0,
                "queued_states": 0,
                "queued_transitions": 0,
                "invalid_states": 0,
                "invalid_transitions": 0,
            }
        )
        video_repo = Mock()
        video_repo.resolve_flows = AsyncMock(return_value=[Mock()])
        generator = Mock()
        generator.generate = AsyncMock(
            return_value=VideoGenerationResult(
                status="success",
                graph_id="graph-1",
                artifact_path="artifacts/videos/graph-1-video.mp4",
                duration_seconds=1.0,
                resolution="1280x720",
                fps=30,
                flow_count=1,
            )
        )

        with (
            patch("src.tasks.video.neo_manager.driver", Driver(Mock())),
            patch("src.tasks.video.BddRepository", return_value=repo),
            patch("src.tasks.video.VideoRepository", return_value=video_repo),
            patch("src.tasks.video.VideoGenerator", return_value=generator) as factory,
        ):
            await task_generate_video(
                {"redis": Mock(), "job_try": 1},
                {
                    "graph_id": "graph-1",
                    "flows": [{"checkpoint_hash": "start", "transition_ids": ["go"]}],
                    "config": {"width": 320},
                },
            )

        config = factory.call_args.args[0]
        self.assertEqual(config.width, 1280)


class VideoIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_encoder_dependency_is_optional_for_ci(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is not available")
        self.assertTrue(shutil.which("ffmpeg"))


if __name__ == "__main__":
    unittest.main()
