""" Generate wildcard files (YAML + TXT) for ComfyUI from fetched tags.

YAML — one file per source (danbooru_wildcards.yaml, e621_wildcards.yaml):
    artists: ["name1", "name2", ...]
    characters: ["name3", ...]
    copyrights: ["name4", ...]

TXT — one file per category per source (danbooru_artists.txt, etc.), one
tag per line, for simpler wildcard extensions.

Tag formatting: underscores become spaces, parentheses are backslash-escaped """

import json

from pathlib import Path

# === TAGSYNC ===
from ..logging_setup import get_logger
from ..config import WILDCARD_DIR
from ..models import Tag

log = get_logger()

WILDCARD_CATEGORIES: dict[str, set[int]] = {
    'artists':    {1},
    'characters': {4},
    'copyrights': {3},
}


def _format_name(name: str) -> str:
    return name.replace('_', ' ').replace('(', r'\(').replace(')', r'\)')


def _build_data(tags: list[Tag]) -> dict[str, list[str]]:
    return {
        key: [_format_name(t.name) for t in sorted(
            (t for t in tags if t.category in categories), key=lambda t: t.post_count, reverse=True
        )]
        for key, categories in WILDCARD_CATEGORIES.items()
    }


def _write_yaml(data: dict[str, list[str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as fh:
        for key, names in data.items():
            fh.write(f"{key}:\n")
            for name in names:
                fh.write(f"  - {json.dumps(name)}\n")
    log.info(f"Wildcard YAML -> {path} ({len(data)} keys)")


def _write_txt(data: dict[str, list[str]], directory: Path, prefix: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for key, names in data.items():
        path = directory / f"{prefix}_{key}.txt"
        path.write_text('\n'.join(names) + ('\n' if names else ''), encoding='utf-8')
        log.info(f"Wildcard TXT -> {path} ({len(names)} entries)")


def generate(
    danbooru_tags: list[Tag] = None,
    e621_tags: list[Tag] = None,
    gelbooru_tags: list[Tag] = None,
    output_dir: str | Path = WILDCARD_DIR,
) -> None:
    sources = {'danbooru': danbooru_tags, 'e621': e621_tags}
    if gelbooru_tags:
        sources['gelbooru'] = gelbooru_tags

    output = Path(output_dir)
    for source, tags in sources.items():
        if not tags:
            continue
        data = _build_data(tags)
        _write_yaml(data, output / f"{source}_wildcards.yaml")
        _write_txt(data, output, source)
