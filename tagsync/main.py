""" CLI entrypoint: fetch, format, merge, and prune tag lists """

import argparse
import asyncio
import json
import sys
import os

# === TAGSYNC ===
from .config import (
    BLACKLIST_FILE,
    DANBOORU_DIR,
    E621_DIR,
    GELBOORU_API_KEY,
    GELBOORU_DIR,
    GELBOORU_USER_ID,
    KRITA_DIR,
    MERGED_DIR,
    MIN_POST_THRESHOLD,
    WILDCARD_DIR,
    RunConfig,
)
from .utils.formatter import build_filename, write_csv, write_krita_csv
from .scrapper import danbooru, e621, gelbooru
from .utils import wildcard as wildcard_util
from .utils.cleanup import prune_old_csvs
from .logging_setup import get_logger
from .utils import merger
from .models import Tag

log = get_logger()


def _attach_aliases(tags: list[Tag], alias_map: dict[str, list[str]]) -> None:
    """Populate each tag's aliases list from {consequent_name: [antecedents...]}, in-place."""
    for tag in tags:
        if tag.name in alias_map:
            tag.aliases = sorted(set(alias_map[tag.name]))


def _env_flag(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _load_blacklist(source: str) -> set[str]:
    if not BLACKLIST_FILE.exists():
        return set()
    try:
        return set(json.loads(BLACKLIST_FILE.read_text(encoding='utf-8')).get(source, []))
    except (ValueError, OSError) as exc:
        log.warning(f"Could not read {BLACKLIST_FILE} ({exc}), skipping blacklist")
        return set()


def _apply_blacklist(tags: list[Tag], source: str) -> list[Tag]:
    blacklist = _load_blacklist(source)
    if not blacklist:
        return tags
    filtered = [t for t in tags if t.name not in blacklist]
    if len(filtered) != len(tags):
        log.info(f"{source}: dropped {len(tags) - len(filtered)} blacklisted tag(s)")
    return filtered


def _threshold_type(raw: str) -> int:
    """argparse type= for threshold flags — rejects a value below
    MIN_POST_THRESHOLD outright instead of silently clamping it."""
    value = int(raw)
    if value < MIN_POST_THRESHOLD:
        raise argparse.ArgumentTypeError(f"must be >= {MIN_POST_THRESHOLD} (got {value})")
    return value


def _make_parser() -> argparse.ArgumentParser:
    """Colored --help output needs Python 3.14+ (argparse's `color` kwarg);
    older interpreters fall back to plain formatting automatically."""
    try:
        return argparse.ArgumentParser(description='Fetch & build Danbooru/e621/Gelbooru tag lists', color=True)
    except TypeError:
        return argparse.ArgumentParser(description='Fetch & build Danbooru/e621/Gelbooru tag lists')


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = _make_parser()

    p.add_argument('--threshold', '--post-threshold', type=_threshold_type, default=20, help=f"min post_count for all sources, >= {MIN_POST_THRESHOLD} (overridable per source below)")
    p.add_argument('--danbooru-threshold', type=_threshold_type, default=None, help='override --threshold for danbooru')
    p.add_argument('--e621-threshold', type=_threshold_type, default=None, help='override --threshold for e621')
    p.add_argument('--gelbooru-threshold', type=_threshold_type, default=None, help='override --threshold for gelbooru')

    p.add_argument('--no-aliases', action='store_true', help="don't include the aliases column")
    p.add_argument('--no-deleted-aliases', action='store_false', dest='include_deleted_aliases', default=True, help='exclude deleted/inactive aliases (included by default)')
    p.add_argument('--include-pending-aliases', action='store_true', help='include e621 pending aliases (e621-only)')

    p.add_argument('--merged-post-count', choices=['danbooru', 'e621', 'sum', 'none'], default='sum', help="post_count for duplicate tags in the merged list ('none' skips the merged list entirely)")

    p.add_argument('--skip-danbooru', action='store_true')
    p.add_argument('--skip-e621', action='store_true')
    p.add_argument('--include-gelbooru', action='store_true', default=_env_flag('TAGSYNC_INCLUDE_GELBOORU'), help='also fetch Gelbooru — opt-in, can take a long time, needs API credentials')

    p.add_argument('--krita-output', action='store_true', help='also write Krita AI Diffusion-compatible CSVs')
    p.add_argument('--wildcards', choices=['none', 'danbooru', 'e621', 'both'], default='none', help='generate ComfyUI wildcard files (YAML + TXT)')

    p.add_argument('--max-age-days', type=int, default=180, help='prune CSVs older than this (0 = never)')
    p.add_argument('--no-cleanup', action='store_true', help='skip old-CSV pruning entirely')

    return p.parse_args(argv)


def _resolve_threshold(override: int | None, fallback: int) -> int:
    """override is None when the flag wasn't passed, distinguishing 'not
    passed' from any low-but-valid value a future override might allow."""
    return override if override is not None else fallback


def _settings_rows(cfg: RunConfig) -> list[tuple[str, object]]:
    """What this run is about to do. Credential *presence* is included (so
    a misconfigured run is obvious at a glance) but never the actual
    key/id values."""
    gelbooru_creds = 'configured' if (GELBOORU_API_KEY and GELBOORU_USER_ID) else 'not configured'
    return [
        ('Danbooru threshold', cfg.danbooru_post_threshold),
        ('e621 threshold', cfg.e621_post_threshold),
        ('Gelbooru threshold', cfg.gelbooru_post_threshold if cfg.include_gelbooru else '-'),
        ('Include aliases', cfg.include_aliases),
        ('Include deleted aliases', cfg.include_deleted_aliases),
        ('Include pending aliases (e621)', cfg.include_pending_aliases),
        ('Merged list', cfg.merged_post_count),
        ('Include Gelbooru', cfg.include_gelbooru),
        ('Gelbooru credentials', gelbooru_creds if cfg.include_gelbooru else '-'),
        ('Krita output', cfg.krita_output),
        ('Wildcards', cfg.wildcards),
        ('Max age (days)', cfg.max_age_days),
        ('Run date', cfg.run_date),
    ]


def _render_ascii_table(rows: list[tuple[str, object]]) -> str:
    label_width = max(len(label) for label, _ in rows)
    value_width = max(max(len(str(value)) for _, value in rows), len('Value'))
    border = f"+{'-' * (label_width + 2)}+{'-' * (value_width + 2)}+"

    lines = [border, f"| {'Setting'.ljust(label_width)} | {'Value'.ljust(value_width)} |", border]
    lines += [f"| {label.ljust(label_width)} | {str(value).ljust(value_width)} |" for label, value in rows]
    lines.append(border)
    return '\n'.join(lines)


def _render_markdown_table(rows: list[tuple[str, object]]) -> str:
    lines = ['| Setting | Value |', '|---|---|']
    lines += [f"| {label} | {value} |" for label, value in rows]
    return '\n'.join(lines)


def _print_settings_table(cfg: RunConfig) -> None:
    """Print the settings table to the console, and — when running inside
    GitHub Actions — also append it to the job summary, so it's visible on
    the run's summary page rather than buried in the raw log."""
    rows = _settings_rows(cfg)
    print(_render_ascii_table(rows))

    summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_path:
        with open(summary_path, 'a', encoding='utf-8') as fh:
            fh.write(f"### tagsync run settings\n\n{_render_markdown_table(rows)}\n\n")


async def run(args: argparse.Namespace) -> None:
    cfg = RunConfig(
        danbooru_post_threshold=_resolve_threshold(args.danbooru_threshold, args.threshold),
        e621_post_threshold=_resolve_threshold(args.e621_threshold, args.threshold),
        gelbooru_post_threshold=_resolve_threshold(args.gelbooru_threshold, args.threshold),
        include_aliases=not args.no_aliases,
        include_deleted_aliases=args.include_deleted_aliases,
        include_pending_aliases=args.include_pending_aliases,
        merged_post_count=args.merged_post_count,
        include_gelbooru=args.include_gelbooru,
        krita_output=args.krita_output,
        wildcards=args.wildcards,
        max_age_days=args.max_age_days,
    )
    _print_settings_table(cfg)

    danbooru_tags: list[Tag] = []
    e621_tags: list[Tag] = []
    gelbooru_tags: list[Tag] = []

    merged_pc_suffix = {'danbooru': None, 'e621': 'epc', 'sum': 'spc'}.get(cfg.merged_post_count)

    if not args.skip_danbooru:
        danbooru_tags = _apply_blacklist(await danbooru.fetch_tags(cfg.danbooru_post_threshold), 'danbooru')
        if cfg.include_aliases and danbooru_tags:
            _attach_aliases(danbooru_tags, await danbooru.fetch_aliases(cfg.include_deleted_aliases))
        if danbooru_tags:
            filename = build_filename(
                'danbooru', cfg.run_date, str(cfg.danbooru_post_threshold),
                include_aliases=cfg.include_aliases, include_danbooru_deleted=cfg.include_deleted_aliases,
            )
            write_csv(danbooru_tags, DANBOORU_DIR / filename, cfg.include_aliases)
        else:
            log.warning('No danbooru tags fetched — skipping file write')
    else:
        log.info('Skipping danbooru (--skip-danbooru)')

    if not args.skip_e621:
        e621_tags = _apply_blacklist(await e621.fetch_tags(cfg.e621_post_threshold), 'e621')
        if cfg.include_aliases and e621_tags:
            _attach_aliases(e621_tags, await e621.fetch_aliases(cfg.include_deleted_aliases, cfg.include_pending_aliases))
        if e621_tags:
            filename = build_filename(
                'e621', cfg.run_date, str(cfg.e621_post_threshold),
                include_aliases=cfg.include_aliases, include_e621_deleted=cfg.include_deleted_aliases,
                include_e621_pending=cfg.include_pending_aliases,
            )
            write_csv(e621_tags, E621_DIR / filename, cfg.include_aliases)
        else:
            log.warning('No e621 tags fetched — skipping file write')
    else:
        log.info('Skipping e621 (--skip-e621)')

    if cfg.include_gelbooru:
        gelbooru_tags = _apply_blacklist(await gelbooru.fetch_tags(cfg.gelbooru_post_threshold), 'gelbooru')
        if gelbooru_tags:
            filename = build_filename('gelbooru', cfg.run_date, str(cfg.gelbooru_post_threshold))
            write_csv(gelbooru_tags, GELBOORU_DIR / filename, include_aliases=False)
        else:
            log.warning('No gelbooru tags fetched — skipping file write')

    if cfg.build_merged and danbooru_tags and e621_tags:
        merged = merger.build_merged_list(danbooru_tags, e621_tags, gelbooru_tags or None, post_count_strategy=cfg.merged_post_count)
        threshold_label = str(cfg.danbooru_post_threshold)
        if cfg.e621_post_threshold != cfg.danbooru_post_threshold:
            threshold_label += f"-{cfg.e621_post_threshold}"
        if gelbooru_tags and cfg.gelbooru_post_threshold != cfg.danbooru_post_threshold:
            threshold_label += f"-{cfg.gelbooru_post_threshold}"

        filename = build_filename(
            'danbooru_e621_merged', cfg.run_date, threshold_label,
            include_aliases=cfg.include_aliases, include_danbooru_deleted=cfg.include_deleted_aliases,
            include_e621_deleted=cfg.include_deleted_aliases, include_e621_pending=cfg.include_pending_aliases,
            merged_pc_suffix=merged_pc_suffix,
        )
        write_csv(merged, MERGED_DIR / filename, cfg.include_aliases)
    elif cfg.build_merged:
        log.warning('Not building merged list — need both danbooru and e621 tags fetched this run')

    if cfg.krita_output:
        if danbooru_tags:
            write_krita_csv(danbooru_tags, KRITA_DIR / 'Danbooru NSFW.csv')
        if e621_tags:
            write_krita_csv(e621_tags, KRITA_DIR / 'e621 NSFW.csv')

    if cfg.wildcards != 'none':
        wildcard_util.generate(
            danbooru_tags if cfg.wildcards in ('danbooru', 'both') else None,
            e621_tags if cfg.wildcards in ('e621', 'both') else None,
            gelbooru_tags if cfg.include_gelbooru else None,
            WILDCARD_DIR,
        )

    if not args.no_cleanup and cfg.max_age_days > 0:
        dirs = [DANBOORU_DIR, E621_DIR, MERGED_DIR]
        if cfg.include_gelbooru:
            dirs.append(GELBOORU_DIR)
        prune_old_csvs(dirs, cfg.max_age_days)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log.warning('Interrupted by user')
        return 1
    except Exception:
        log.exception('tagsync run failed')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
