import uuid
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    Playwright,
)


class PlaywrightManager:
    """
    Persistent Playwright browser manager.
    """

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def start(self):
        """Start Playwright and launch browser once."""
        if self._browser is not None:
            return

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

    async def stop(self):
        """Close browser and stop Playwright."""
        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def resolve_locator(
        self,
        html: str,
        locator: str,
    ) -> tuple[str, str]:
        """Mark the first Playwright locator match and return the updated HTML.

        Args:
            html: Complete origin-page HTML.
            locator: Playwright locator expression for the interacted element.

        Returns:
            A tuple containing serialized HTML and the temporary marker value.

        Raises:
            ValueError: If HTML or locator metadata is missing.
            playwright.async_api.Error: If the locator cannot be evaluated.
        """

        if not html.strip():
            raise ValueError("Origin state HTML is empty")

        if not locator or not locator.strip():
            raise ValueError("Transition locator is empty")

        if self._browser is None:
            raise RuntimeError("Playwright browser not started. Call start() first.")

        page = await self._browser.new_page()

        try:
            await page.set_content(html)

            element = page.locator(locator).first

            if await element.count() == 0:
                raise ValueError(f"Transition locator did not match: {locator}")

            unique_id = f"pw-bridge-{uuid.uuid4().hex[:8]}"

            await element.evaluate(
                "(node, marker) => " 'node.setAttribute("data-pw-locator", marker)',
                unique_id,
            )

            return await page.content(), unique_id

        finally:
            await page.close()


playwright_manager = PlaywrightManager()
