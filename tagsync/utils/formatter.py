""" Write tag lists as CSVs compatible with sd-webui-tagcomplete,
ComfyUI-Custom-Scripts, Krita AI Diffusion, SwarmUI, etc """

import csv

from pathlib import Path

# === TAGSYNC ===
from ..logging_setup import get_logger
from ..models import Tag

log = get_logger()


def build_filename(
    prefix: str,
    run_date: str,
    post_threshold: str,
    *,
    include_aliases: bool = False,
    include_danbooru_deleted: bool = False,
    include_e621_deleted: bool = False,
    include_e621_pending: bool = False,
    merged_pc_suffix: str = None,
) -> str:
    """Build a filename like `danbooru_2026-xx-xx_pt20-ia-dd-ed.csv`"""
    suffix_flags = (
        ('ia', include_aliases),
        ('dd', include_danbooru_deleted),
        ('ed', include_e621_deleted),
        ('ep', include_e621_pending),
    )
    parts = [tag for tag, enabled in suffix_flags if enabled]
    if merged_pc_suffix:
        parts.append(merged_pc_suffix)

    suffix = ('-' + '-'.join(parts)) if parts else ''
    return f"{prefix}_{run_date}_pt{post_threshold}{suffix}.csv"


def write_csv(tags: list[Tag], path: Path, include_aliases: bool) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(tags, key=lambda t: t.post_count, reverse=True)

    with path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        for tag in ordered:
            row = [tag.name, tag.category, tag.post_count]
            if include_aliases:
                row.append(tag.alias_field())
            writer.writerow(row)

    log.info(f"Wrote {len(ordered)} tags -> {path}")
    return path


def write_krita_csv(tags: list[Tag], path: Path) -> Path:
    """Krita AI Diffusion's own tag files use this exact same plain
    format, just without the aliases column — a copy dropped into
    tag-lists/krita_ai_compatible/ needs no schema changes."""
    return write_csv(tags, path, include_aliases=False)
