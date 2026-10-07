from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"reveal\s+(the\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+(chatgpt|an?\s+ai|the\s+assistant)", re.IGNORECASE),
    re.compile(r"developer\s+message", re.IGNORECASE),
)

class BrowserUnavailable(RuntimeError):
    pass

class BrowserReferenceError(LookupError):
    pass

class BrowserNavigationError(ValueError):
    pass


class BrowserDownloadError(RuntimeError):
    pass

def validate_navigation_url(url: str) -> str:
    candidate = url.strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise BrowserNavigationError("Browser navigation is limited to HTTP and HTTPS")
    if not parsed.hostname:
        raise BrowserNavigationError("Browser navigation requires a valid host")
    if parsed.username is not None or parsed.password is not None:
        raise BrowserNavigationError("Credentials are not allowed in browser navigation URLs")
    return candidate

class BrowserProvider:
    def __init__(
        self,
        profile_dir: Path,
        *,
        channel: str = "msedge",
        headless: bool = False,
    ):
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.channel = channel
        self.headless = headless
        self._playwright: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None

    async def start(self) -> None:
        if self._context is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserUnavailable("Playwright is not installed") from exc

        self._playwright = await async_playwright().start()
        kwargs: dict[str, Any] = {
            "user_data_dir": str(self.profile_dir),
            "headless": self.headless,
        }
        if self.channel and self.channel != "chromium":
            kwargs["channel"] = self.channel
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            await self._playwright.stop()
            self._playwright = None
            raise BrowserUnavailable(str(exc)) from exc
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

    def status(self) -> dict[str, Any]:
        return {
            "started": self._context is not None,
            "url": self._page.url if self._page is not None else None,
            "profile_dir": str(self.profile_dir),
            "channel": self.channel,
            "headless": self.headless,
        }

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
            self._page = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def navigate(self, url: str) -> dict[str, Any]:
        safe_url = validate_navigation_url(url)
        page = await self._ensure_page()
        response = await page.goto(
            safe_url,
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        return {
            "url": page.url,
            "title": await page.title(),
            "status": response.status if response else None,
            "domain": urlparse(page.url).hostname,
        }

    async def snapshot(self, *, max_text: int = 30_000) -> dict[str, Any]:
        page = await self._ensure_page()
        await self._annotate(page)
        body = page.locator("body")
        try:
            aria = await body.aria_snapshot(timeout=5_000)
        except Exception:  # noqa: BLE001
            aria = None
        text = (await body.inner_text(timeout=10_000))[:max_text]
        controls = await page.locator("[data-homuncula-ref]").evaluate_all(
            """
            (nodes) => nodes.slice(0, 300).map((node) => ({
              ref: node.getAttribute('data-homuncula-ref'),
              tag: node.tagName.toLowerCase(),
              role: node.getAttribute('role'),
              name: node.getAttribute('aria-label') || node.innerText || node.value || '',
              type: node.getAttribute('type'),
              href: node.getAttribute('href'),
              download: node.hasAttribute('download'),
              disabled: Boolean(node.disabled)
            }))
            """
        )
        flags = [pattern.pattern for pattern in INJECTION_PATTERNS if pattern.search(text)]
        return {
            "url": page.url,
            "title": await page.title(),
            "domain": urlparse(page.url).hostname,
            "text": text,
            "aria": aria,
            "controls": controls,
            "prompt_injection_risk": bool(flags),
            "prompt_injection_signals": flags,
        }

    async def click(self, reference: str) -> dict[str, Any]:
        locator = await self._locator(reference)
        await locator.click(timeout=15_000)
        if self._page is None:
            raise BrowserUnavailable("Browser page disappeared")
        return {"ref": reference, "clicked": True, "url": self._page.url}

    async def fill(self, reference: str, value: str) -> dict[str, Any]:
        locator = await self._locator(reference)
        await locator.fill(value, timeout=15_000)
        return {"ref": reference, "characters": len(value)}

    async def press(self, reference: str, key: str) -> dict[str, Any]:
        locator = await self._locator(reference)
        await locator.press(key, timeout=15_000)
        return {"ref": reference, "key": key}

    async def select_option(self, reference: str, value: str) -> dict[str, Any]:
        locator = await self._locator(reference)
        selected = await locator.select_option(value, timeout=15_000)
        return {"ref": reference, "selected": selected}

    async def upload_file(self, reference: str, path: Path) -> dict[str, Any]:
        locator = await self._locator(reference)
        await locator.set_input_files(str(path), timeout=15_000)
        return {"ref": reference, "path": path.name}

    async def download(
        self,
        reference: str,
        destination_dir: Path,
        *,
        max_bytes: int = 250 * 1024 * 1024,
    ) -> dict[str, Any]:
        locator = await self._locator(reference)
        destination_dir = Path(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)

        page = await self._ensure_page()
        async with page.expect_download(timeout=45_000) as download_info:
            await locator.click(timeout=15_000)
        download = await download_info.value

        suggested = Path(download.suggested_filename or "download").name
        if not suggested or suggested in {".", ".."}:
            suggested = "download"

        target = destination_dir / suggested
        stem = target.stem
        suffix = target.suffix
        counter = 1
        while target.exists():
            target = destination_dir / f"{stem}-{counter}{suffix}"
            counter += 1

        await download.save_as(str(target))
        size = target.stat().st_size
        if size > max(1, max_bytes):
            target.unlink(missing_ok=True)
            raise BrowserDownloadError(
                f"Download exceeded the configured size limit ({size} bytes)"
            )
        return {
            "ref": reference,
            "filename": target.name,
            "bytes": size,
        }

    async def _ensure_page(self) -> Any:
        if self._page is None:
            await self.start()
        if self._page is None:
            raise BrowserUnavailable("Browser page could not be created")
        return self._page

    async def _annotate(self, page: Any) -> None:
        await page.locator(
            "a,button,input,textarea,select,[role=button],[role=link],[contenteditable=true]"
        ).evaluate_all(
            """
            (nodes) => nodes.forEach((node, index) => {
              node.setAttribute('data-homuncula-ref', 'web_' + index);
            })
            """
        )

    async def _locator(self, reference: str) -> Any:
        if not reference.startswith("web_"):
            raise BrowserReferenceError(reference)
        page = await self._ensure_page()
        locator = page.locator('[data-homuncula-ref="' + reference + '"]')
        if await locator.count() != 1:
            await self._annotate(page)
            locator = page.locator('[data-homuncula-ref="' + reference + '"]')
        if await locator.count() != 1:
            raise BrowserReferenceError(reference)
        return locator
