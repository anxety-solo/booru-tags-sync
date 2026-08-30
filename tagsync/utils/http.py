""" Shared HTTP GET with retry/backoff, used by every scrapper module """

import asyncio
import aiohttp

# === TAGSYNC ===
from ..logging_setup import get_logger
from ..config import USER_AGENT

log = get_logger()

DEFAULT_HEADERS = {'User-Agent': USER_AGENT}


async def get_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    params: dict[str, str] = None,
    headers: dict[str, str] = None,
    max_retries: int = 5,
    timeout: int = 30,
    soft_stop_statuses: frozenset[int] = frozenset(),
    fatal_statuses: dict[int, str] = None,
):
    """GET url and parse the response as JSON.

    - 429 is always retried with exponential backoff.
    - A status in `soft_stop_statuses` (e.g. Danbooru's 410 offset-pagination
      ceiling) logs a warning and returns None — there's simply no more data.
    - A status in `fatal_statuses` raises RuntimeError immediately, no retry
      (e.g. Gelbooru's 401 when no API key is configured).
    - Any other network error (including DNS failures, which aiohttp raises
      as a ClientError subclass) or timeout is retried with backoff, then
      raises RuntimeError once max_retries is exhausted.
    """
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    fatal_statuses = fatal_statuses or {}

    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(
                url, params=params, headers=merged_headers, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status in fatal_statuses:
                    raise RuntimeError(fatal_statuses[resp.status])
                if resp.status in soft_stop_statuses:
                    log.warning(f"{url} returned HTTP {resp.status} — treating as end of data")
                    return None
                if resp.status == 429:
                    wait = 2**attempt
                    log.warning(f"Rate limited by {url}, backing off {wait}s")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            wait = min(2**attempt, 30)
            log.warning(f"Request to {url} failed ({exc}), retry in {wait}s")
            await asyncio.sleep(wait)

    raise RuntimeError(f"Giving up on {url} after {max_retries} tries")
