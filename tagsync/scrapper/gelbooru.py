""" Fetch tags from Gelbooru's DAPI — opt-in, slow, no server-side count filter.

Gelbooru's tag API (page=dapi&s=tag&q=index) enforces a hard 100-tags-per-page
ceiling and has no reliable post_count filter, so a full scrape walks every
page in order — potentially tens of thousands of requests. A checkpoint file
lets an interrupted run resume instead of restarting from page 0.

Gelbooru requires API credentials (api_key + user_id, free with an account)
on every request, including tag listing — without them every call returns
401. Set GELBOORU_API_KEY / GELBOORU_USER_ID as environment variables
(or repo secrets for the GitHub Actions workflow) """

import asyncio
import aiohttp
import html
import json
import os

from pathlib import Path

# === TAGSYNC ===
from ..config import GELBOORU_API_KEY, GELBOORU_API_URL, GELBOORU_CATEGORIES, GELBOORU_MAX_PAGES, GELBOORU_PAGE_LIMIT, GELBOORU_SKIP_CATEGORIES, GELBOORU_USER_ID
from ..logging_setup import get_logger
from ..utils.http import get_json
from ..models import Tag

log = get_logger()

REQUEST_DELAY_SECONDS = 0.3
CHECKPOINT_PATH = Path(os.environ.get('GELBOORU_CHECKPOINT_DIR', '.cache')) / 'gelbooru_checkpoint.json'

_UNAUTHORIZED_MESSAGE = (
    "Gelbooru returned 401 Unauthorized. Requests need GELBOORU_API_KEY and "
    "GELBOORU_USER_ID set (from your account's API Access settings page)"
)


def _save_checkpoint(pid: int) -> None:
    """Write-then-rename so a crash mid-write can't corrupt the checkpoint"""
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps({'last_pid': pid}), encoding='utf-8')
    tmp.rename(CHECKPOINT_PATH)


def _load_checkpoint() -> int:
    try:
        return json.loads(CHECKPOINT_PATH.read_text(encoding='utf-8')).get('last_pid', 0)
    except (FileNotFoundError, ValueError):
        return 0


def _row_to_tag(row: dict, post_threshold: int) -> Tag | None:
    try:
        category   = int(row['type'])
        post_count = int(row['count'])
    except (KeyError, ValueError, TypeError):
        return None

    if category in GELBOORU_SKIP_CATEGORIES or category not in GELBOORU_CATEGORIES:
        return None
    if post_count < post_threshold or int(row.get('ambiguous', 0)) != 0:
        return None

    name = row.get('name', '')
    if not name:
        return None
    return Tag(name=html.unescape(name), category=category, post_count=post_count)


async def fetch_tags(post_threshold: int) -> list[Tag]:
    if not GELBOORU_API_KEY or not GELBOORU_USER_ID:
        log.error('Gelbooru API credentials not configured — set GELBOORU_API_KEY and GELBOORU_USER_ID')
        return []

    log.warning(f"Gelbooru: walking every tag page (up to {GELBOORU_MAX_PAGES} pages of {GELBOORU_PAGE_LIMIT}). This can take a while.")

    start_pid = _load_checkpoint()
    if start_pid:
        log.info(f"Gelbooru: resuming from checkpoint pid={start_pid}")

    params_base = {
        'page': 'dapi', 's': 'tag', 'q': 'index', 'json': '1',
        'limit': str(GELBOORU_PAGE_LIMIT), 'orderby': 'count',
        'api_key': GELBOORU_API_KEY, 'user_id': GELBOORU_USER_ID,
    }

    tags: list[Tag] = []
    try:
        async with aiohttp.ClientSession() as session:
            pid = start_pid
            while pid < GELBOORU_MAX_PAGES:
                data = await get_json(
                    session, GELBOORU_API_URL,
                    params={**params_base, 'pid': str(pid)},
                    fatal_statuses={401: _UNAUTHORIZED_MESSAGE},
                )
                # DAPI wraps results as {'tag': [...]}; a lone match comes back as a bare dict.
                batch = (data.get('tag', []) if isinstance(data, dict) else data) if data else []
                if isinstance(batch, dict):
                    batch = [batch]
                if not batch:
                    break

                for row in batch:
                    tag = _row_to_tag(row, post_threshold)
                    if tag is not None:
                        tags.append(tag)

                if pid % 100 == 0:
                    log.info(f"Gelbooru pid={pid}: {len(tags)} tags kept so far")
                    _save_checkpoint(pid)

                if len(batch) < GELBOORU_PAGE_LIMIT:
                    break
                pid += 1
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
            else:
                log.warning(f"Gelbooru: hit the {GELBOORU_MAX_PAGES}-page safety cap before running out of data")
    except RuntimeError as exc:
        # A fatal status (401/etc.) or exhausted retries — every other source has
        # already been fetched by the time this runs, so skip rather than crash.
        log.error(f"Gelbooru failed, skipping it for this run: {exc}")
        return []

    _save_checkpoint(0) # completed cleanly — clear the resume point
    log.info(f"Gelbooru: fetched {len(tags)} tags (post_count >= {post_threshold})")
    return tags
