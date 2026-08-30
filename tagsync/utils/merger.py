""" Build the combined tag list (danbooru + e621 + optional gelbooru)

Category-id offsets keep each source's ranges non-overlapping:
e621 +7, gelbooru +17 (see config.py)
Duplicate tag names are merged with priority danbooru > e621 > gelbooru for category/aliases;
Aliases that collide with an existing tag name in the merged list are dropped — a self-referencing alias
entry confuses some autocomplete extensions rather than helping them """

from collections import defaultdict

# === TAGSYNC ===
from ..config import MERGED_E621_CATEGORY_OFFSET, MERGED_GELBOORU_CATEGORY_OFFSET
from ..logging_setup import get_logger
from ..models import Tag

log = get_logger()

_SOURCE_PRIORITY = {'danbooru': 0, 'e621': 1, 'gelbooru': 2}


def build_merged_list(
    danbooru_tags: list[Tag],
    e621_tags: list[Tag],
    gelbooru_tags: list[Tag] = None,
    post_count_strategy: str = 'danbooru',
) -> list[Tag]:
    groups: dict[str, dict] = defaultdict(
        lambda: {'priority': 99, 'category': 0, 'pc_danbooru': 0, 'pc_e621': 0, 'pc': 0, 'aliases': []}
    )

    def add(tags: list[Tag], source: str, offset: int = 0) -> None:
        priority = _SOURCE_PRIORITY[source]
        for tag in tags:
            group = groups[tag.name]
            if source == 'danbooru':
                group['pc_danbooru'] = tag.post_count
            elif source == 'e621':
                group['pc_e621'] = tag.post_count

            if priority < group['priority']:    # first/best-ranked source seen wins category + display count
                group['priority'] = priority
                group['category'] = tag.category + offset
                group['pc'] = tag.post_count
            group['aliases'].extend(tag.aliases)

    add(danbooru_tags, 'danbooru')
    add(e621_tags, 'e621', MERGED_E621_CATEGORY_OFFSET)
    if gelbooru_tags:
        add(gelbooru_tags, 'gelbooru', MERGED_GELBOORU_CATEGORY_OFFSET)

    merged: list[Tag] = []
    for name, group in groups.items():
        if post_count_strategy == 'e621':
            post_count = group['pc_e621'] or group['pc']
        elif post_count_strategy == 'sum':
            post_count = group['pc_danbooru'] + group['pc_e621'] or group['pc']
        else:
            post_count = group['pc']

        merged.append(Tag(name=name, category=group['category'], post_count=post_count, aliases=sorted(set(group['aliases']))))

    log.info(
        f"Merged: {len(merged)} unique tags "
        f"({len(danbooru_tags)} danbooru, {len(e621_tags)} e621, {len(gelbooru_tags or [])} gelbooru; "
        f"pc={post_count_strategy})"
    )

    _drop_self_referencing_aliases(merged)
    return merged


def _drop_self_referencing_aliases(tags: list[Tag]) -> None:
    all_names = {t.name for t in tags}
    for tag in tags:
        tag.aliases = [a for a in tag.aliases if a not in all_names]
