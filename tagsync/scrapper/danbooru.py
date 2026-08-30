""" Fetch tags from the Danbooru API.

Pages are requested with search[order]=count, so results arrive sorted by
post_count descending. fetch_tags() stops as soon as every kept-category
row on a page falls below the threshold — everything past that point is
guaranteed to be even less popular, so there's no need to keep paging """

import asyncio
import aiohttp

# === TAGSYNC ===
from ..config import DANBOORU_ALIASES_ENDPOINT, DANBOORU_CATEGORIES, DANBOORU_MAX_PAGES, DANBOORU_PAGE_LIMIT, DANBOORU_TAGS_ENDPOINT
from ..logging_setup import get_logger
from ..utils.http import get_json
from ..models import Tag

log = get_logger()

REQUEST_DELAY_SECONDS = 0.2 # keep request rate polite — this is a shared free API


async def fetch_tags(post_threshold: int) -> list[Tag]:
    """Fetch danbooru tags with post_count >= threshold, sorted count-desc"""
    params_base = {
        'search[order]': 'count',
        'search[hide_empty]': 'true',
        'search[is_deprecated]': 'no',
        'limit': str(DANBOORU_PAGE_LIMIT),
    }

    tags: list[Tag] = []
    try:
        async with aiohttp.ClientSession() as session:
            for page in range(1, DANBOORU_MAX_PAGES + 1):
                batch = await get_json(
                    session, DANBOORU_TAGS_ENDPOINT,
                    params={**params_base, 'page': str(page)},
                    soft_stop_statuses=frozenset({410}),    # offset-pagination ceiling
                )
                if not batch:
                    break

                # `processed` counts only rows in a keepable category — a page mixing
                # a few unrelated categories with mostly below-threshold rows must
                # still trigger the stop, so the count compares against rows that
                # were actually eligible, not the raw page size.
                processed = 0
                below_threshold = 0
                for row in batch:
                    category = row.get('category')
                    if category not in DANBOORU_CATEGORIES:
                        continue
                    processed += 1
                    post_count = row.get('post_count', 0)
                    if post_count < post_threshold:
                        below_threshold += 1
                        continue
                    tags.append(Tag(name=row['name'], category=category, post_count=post_count))

                log.info(f"Danbooru page {page}: {len(batch)} tags ({len(tags)} kept so far)")

                if processed and below_threshold == processed:
                    log.info(f"Danbooru: page {page} entirely below threshold {post_threshold} — stopping")
                    break

                await asyncio.sleep(REQUEST_DELAY_SECONDS)
            else:
                log.warning(f"Danbooru: hit the {DANBOORU_MAX_PAGES}-page safety cap before running out of data")
    except RuntimeError as exc:
        log.error(f"Danbooru tag fetch failed, skipping it for this run: {exc}")
        return []

    log.info(f"Danbooru: fetched {len(tags)} tags (post_count >= {post_threshold})")
    return tags


async def fetch_aliases(include_deleted: bool = True) -> dict[str, list[str]]:
    """Return {consequent_name: [antecedent_names...]} for danbooru aliases.
    include_deleted=True (default) fetches every alias status; False keeps only currently-active ones"""
    params_base = {'search[order]': 'id', 'limit': '1000'}
    if not include_deleted:
        params_base['search[status]'] = 'active'

    aliases: dict[str, list[str]] = {}
    try:
        async with aiohttp.ClientSession() as session:
            for page in range(1, 1001):     # danbooru's offset pagination caps out at page 1000
                batch = await get_json(session, DANBOORU_ALIASES_ENDPOINT, params={**params_base, 'page': str(page)})
                if not batch:
                    break

                for row in batch:
                    consequent, antecedent = row.get('consequent_name'), row.get('antecedent_name')
                    if consequent and antecedent:
                        aliases.setdefault(consequent, []).append(antecedent)

                log.info(f"Danbooru aliases page {page}: {len(batch)} rows")
                if len(batch) < 1000:
                    break
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
            else:
                log.warning('Danbooru alias pagination hit the offset ceiling, stopping early')
    except RuntimeError as exc:
        log.error(f"Danbooru alias fetch failed, skipping aliases: {exc}")

    return aliases
