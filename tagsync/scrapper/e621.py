""" Fetch tags from e621's database export.

e621 publishes a JSON index of its currently-available database dumps at E621_EXPORTS_INDEX.

A sha256 checksum is included in the index for free, so downloads are
verified against it — cheap insurance against a truncated transfer
silently producing a garbage tag list.

Columns (subject to change without notice — _row_to_tag and the alias
status filtering below are the only things that would need updating):
  tags.csv.gz:        id,name,category,post_count
  tag_aliases.csv.gz: id,antecedent_name,consequent_name,created_at,status """

import hashlib
import gzip
import csv
import io

import aiohttp

# === TAGSYNC ===
from ..config import E621_EXPORTS_INDEX, E621_SKIP_CATEGORIES
from ..utils.http import DEFAULT_HEADERS, get_json
from ..logging_setup import get_logger
from ..models import Tag


log = get_logger()

_PROGRESS_EVERY = 200_000   # rows — tags.csv can run past a million at low thresholds


class ExportEntry:
    """One entry from db_exports.json"""

    __slots__ = ('name', 'file_name', 'url', 'checksum', 'updated_at', 'file_size')

    def __init__(self, data: dict):
        for key in self.__slots__:
            setattr(self, key, data.get(key))


async def _find_export(session: aiohttp.ClientSession, name: str) -> ExportEntry:
    data = await get_json(session, E621_EXPORTS_INDEX, headers={'Accept': 'application/json,*/*'})
    if not isinstance(data, list):
        raise RuntimeError(f"{E621_EXPORTS_INDEX} returned {type(data).__name__} — expected a list of entries")

    entries = [ExportEntry(item) for item in data if isinstance(item, dict)]
    for entry in entries:
        if entry.name == name and entry.url:
            log.info(f"e621 export '{name}' -> {entry.url} (updated_at={entry.updated_at})")
            return entry

    available = sorted({e.name for e in entries if e.name})
    raise RuntimeError(f"No export named '{name}' with a url found in {E621_EXPORTS_INDEX}. Available: {available}")


def _verify_checksum(raw: bytes, expected_hex: str | None, label: str) -> None:
    if not expected_hex:
        return
    actual = hashlib.sha256(raw).hexdigest()
    if actual.lower() != expected_hex.lower():
        raise RuntimeError(f"Checksum mismatch for {label}: expected {expected_hex}, got {actual}")


async def _download_gzip_csv(session: aiohttp.ClientSession, entry: ExportEntry) -> csv.DictReader:
    try:
        async with session.get(entry.url, headers=DEFAULT_HEADERS, timeout=aiohttp.ClientTimeout(total=600)) as resp:
            resp.raise_for_status()
            raw = await resp.read()
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise RuntimeError(f"Failed to download {entry.url}: {exc}") from exc

    _verify_checksum(raw, entry.checksum, entry.file_name or entry.name)
    text = gzip.decompress(raw).decode('utf-8', errors='replace')
    return csv.DictReader(io.StringIO(text))


def _row_to_tag(row: dict, post_threshold: int) -> Tag | None:
    """Only the explicitly unusable 'invalid' category is excluded — any
    other category id is kept even if it isn't in E621_CATEGORIES, so a
    new category e621 adds later doesn't silently vanish from the output"""
    try:
        category   = int(row['category'])
        post_count = int(row['post_count'])
    except (KeyError, ValueError):
        return None

    if category in E621_SKIP_CATEGORIES:
        return None
    if post_count <= 0 or post_count < post_threshold:
        return None

    return Tag(name=row['name'], category=category, post_count=post_count)


async def fetch_tags(post_threshold: int) -> list[Tag]:
    tags: list[Tag] = []
    try:
        async with aiohttp.ClientSession() as session:
            entry  = await _find_export(session, 'tags')
            reader = await _download_gzip_csv(session, entry)

            for rows_seen, row in enumerate(reader, start=1):
                tag = _row_to_tag(row, post_threshold)
                if tag is not None:
                    tags.append(tag)
                if rows_seen % _PROGRESS_EVERY == 0:
                    log.info(f"e621: processed {rows_seen} rows, {len(tags)} tags kept so far...")
    except RuntimeError as exc:
        log.error(f"e621 tag fetch failed, skipping it for this run: {exc}")
        return []

    log.info(f"e621: fetched {len(tags)} tags (post_count >= {post_threshold})")
    return tags


async def fetch_aliases(include_deleted: bool = False, include_pending: bool = False) -> dict[str, list[str]]:
    """Return {consequent_name: [antecedent_names...]} for e621 aliases"""
    wanted_statuses = {'active'}
    if include_deleted:
        wanted_statuses |= {'deleted', 'retired'}
    if include_pending:
        wanted_statuses.add('pending')

    aliases: dict[str, list[str]] = {}
    try:
        async with aiohttp.ClientSession() as session:
            entry  = await _find_export(session, 'tag_aliases')
            reader = await _download_gzip_csv(session, entry)

            for row in reader:
                if row.get('status') not in wanted_statuses:
                    continue
                antecedent, consequent = row.get('antecedent_name'), row.get('consequent_name')
                if antecedent and consequent:
                    aliases.setdefault(consequent, []).append(antecedent)
    except RuntimeError as exc:
        log.error(f"e621 alias fetch failed, skipping aliases: {exc}")

    total = sum(len(v) for v in aliases.values())
    log.info(f"e621: fetched {total} aliases (deleted={include_deleted}, pending={include_pending})")
    return aliases
