import random
from dataclasses import dataclass


@dataclass(frozen=True)
class TypedTextFrame:
    text: str
    at_seconds: float
    caret_visible: bool


def typing_frames(
    value: str,
    seed: int,
    base_delay: float = 0.07,
    jitter: float = 0.022,
    speed: float = 1.0,
    pause_every: int = 4,
    pause_extra: float = 0.08,
) -> list[TypedTextFrame]:
    """Produce per-keystroke animation frames for ``value``.

    The cadence mimics a real typist: each character lands with a
    small random jitter, and every ``pause_every`` characters there is
    an extra micro-pause (as if the typist briefly collected their
    thoughts).  This is what makes the typed text feel natural and
    smooth on screen instead of metronomic.
    """
    rng = random.Random(seed)
    speed = max(0.1, speed)
    frames: list[TypedTextFrame] = []
    elapsed = 0.0
    text = ""

    for index, char in enumerate(value):
        delay = (base_delay + rng.uniform(-jitter, jitter)) / speed
        # Occasional micro-pause for naturalism.
        if index > 0 and index % pause_every == 0:
            delay += pause_extra / speed
        elapsed += max(0.025, delay)
        text += char
        frames.append(
            TypedTextFrame(
                text=text,
                at_seconds=elapsed,
                caret_visible=True,
            )
        )

    # Final frame with the caret hidden so the typed value settles.
    elapsed += 0.22 / speed
    frames.append(
        TypedTextFrame(
            text=text,
            at_seconds=elapsed,
            caret_visible=False,
        )
    )
    return frames