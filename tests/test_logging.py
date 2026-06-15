import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.core.logging import setup_logging


class LoggingTests(unittest.TestCase):
    def test_setup_logging_creates_and_writes_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = SimpleNamespace(
                debug=False,
                environment="test",
            )
            log_file = setup_logging(settings, Path(temp_dir) / "nested")
            logging.getLogger("test.logger").info("file logging works")
            for handler in logging.getLogger().handlers:
                handler.flush()

            try:
                self.assertTrue(log_file.exists())
                self.assertIn(
                    "file logging works",
                    log_file.read_text(encoding="utf-8"),
                )
            finally:
                root = logging.getLogger()
                for handler in root.handlers[:]:
                    handler.close()
                    root.removeHandler(handler)

    def test_neo4j_debug_noise_is_suppressed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = SimpleNamespace(
                debug=True,
                environment="test",
            )
            log_file = setup_logging(settings, Path(temp_dir) / "nested")

            logging.getLogger("src.test").debug("application debug message")
            logging.getLogger("neo4j.io").debug("neo4j debug message")
            logging.getLogger("neo4j.pool").info("neo4j info message")
            logging.getLogger("neo4j.routing").warning(
                "neo4j warning message"
            )

            root = logging.getLogger()
            neo4j_logger = logging.getLogger("neo4j")
            for handler in [*root.handlers, *neo4j_logger.handlers]:
                handler.flush()

            try:
                content = log_file.read_text(encoding="utf-8")
                self.assertIn("application debug message", content)
                self.assertNotIn("neo4j debug message", content)
                self.assertNotIn("neo4j info message", content)
                self.assertIn("neo4j warning message", content)
            finally:
                for logger in (neo4j_logger, root):
                    for handler in logger.handlers[:]:
                        handler.close()
                        logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
