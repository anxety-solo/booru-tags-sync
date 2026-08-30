""" Data structures shared between fetchers, formatter and merger """

from dataclasses import dataclass, field


@dataclass
class Tag:
    """One normalized tag, source-agnostic.
    `category` is always the source's own raw category id:
        - danbooru: 0/1/3/4/5
        - e621:     0/1/3/4/5/7/8/9
        - gelbooru: 0/1/3/4/5
    Offsetting for the merged list happens later, in utils/merger.py — this object stays a faithful 1:1 record of what the source returned.
    """

    name: str
    category: int
    post_count: int
    aliases: list[str] = field(default_factory=list)

    def alias_field(self) -> str:
        """Aliases as a single comma-separated CSV field. csv.writer already
        quotes fields containing commas, so no manual escaping is needed."""
        return ','.join(self.aliases)
