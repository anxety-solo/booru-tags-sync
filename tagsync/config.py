""" Central configuration: paths, network settings, category maps, run options """

import os

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# --- Paths ---

REPO_ROOT = Path(__file__).resolve().parents[1]

OUTPUT_DIR   = REPO_ROOT / 'tag-lists'
DANBOORU_DIR = OUTPUT_DIR / 'danbooru'
E621_DIR     = OUTPUT_DIR / 'e621'
GELBOORU_DIR = OUTPUT_DIR / 'gelbooru'
MERGED_DIR   = OUTPUT_DIR / 'danbooru_e621_merged'
KRITA_DIR    = OUTPUT_DIR / 'krita_ai_compatible'
WILDCARD_DIR = OUTPUT_DIR / 'wildcard'

BLACKLIST_FILE = REPO_ROOT / 'blacklisted_tags.json'

# --- Network ---

USER_AGENT = os.environ.get(
    'TAGSYNC_USER_AGENT',
    'tagsync/1.0 (+https://github.com/; contact via repo issues)',
)

DANBOORU_BASE_URL         = 'https://danbooru.donmai.us'
DANBOORU_TAGS_ENDPOINT    = f"{DANBOORU_BASE_URL}/tags.json"
DANBOORU_ALIASES_ENDPOINT = f"{DANBOORU_BASE_URL}/tag_aliases.json"
DANBOORU_PAGE_LIMIT       = 1000    # max page size the API allows
DANBOORU_MAX_PAGES        = int(os.environ.get('DANBOORU_MAX_PAGES', '2000'))  # safety cap, see scrapper/danbooru.py

# Index of e621's currently-available database dumps. Each entry identifies
# a dump by its `name` field ('tags', 'tag_aliases', ...) and gives a direct
# download `url` plus a sha256 `checksum` for integrity verification.
E621_EXPORTS_INDEX = 'https://e621.net/db_exports.json'

GELBOORU_API_URL    = 'https://gelbooru.com/index.php'
GELBOORU_API_KEY    = os.environ.get('GELBOORU_API_KEY', '')
GELBOORU_USER_ID    = os.environ.get('GELBOORU_USER_ID', '')
GELBOORU_PAGE_LIMIT = 100   # hard cap enforced by the API
GELBOORU_MAX_PAGES  = int(os.environ.get('GELBOORU_MAX_PAGES', '5000'))  # safety cap for a full scrape

# Lowest post-count threshold accepted for any source. Gelbooru has
# no server-side count filter, so a threshold that's too low turns its
# per-page scrape into an effectively unbounded run.
MIN_POST_THRESHOLD = 5

# --- Category Maps ---

# https://danbooru.donmai.us/wiki_pages/help:tags#category
DANBOORU_CATEGORIES = {0: 'general', 1: 'artist', 3: 'copyright', 4: 'character', 5: 'meta'}

# https://e621.net/help/tags#category
E621_CATEGORIES = {
    0: 'general', 1: 'artist', 3: 'copyright', 4: 'character',
    5: 'species', 6: 'invalid', 7: 'meta', 8: 'lore', 9: 'contributor',
}
E621_SKIP_CATEGORIES = {6}  # 'invalid' — not useful for autocomplete

# Gelbooru's DAPI calls this field 'type'.
GELBOORU_CATEGORIES = {0: 'general', 1: 'artist', 3: 'copyright', 4: 'character', 5: 'metadata'}
GELBOORU_SKIP_CATEGORIES = {6}  # 'deprecated'

# Category-id offsets applied when building the merged list, so e621/gelbooru
# categories never collide with danbooru's own 0-5 range or with each other:
#   e621     -> 7, 8, 10, 11, 12, 14, 15, 16
#   gelbooru -> 17, 18, 20, 21, 22
MERGED_E621_CATEGORY_OFFSET = 7
MERGED_GELBOORU_CATEGORY_OFFSET = 17


@dataclass
class RunConfig:
    """Resolved options for a single pipeline run"""

    danbooru_post_threshold: int = 20
    e621_post_threshold: int = 20
    gelbooru_post_threshold: int = 20

    include_aliases: bool = True
    include_deleted_aliases: bool = True    # danbooru: all statuses; e621: adds deleted/retired
    include_pending_aliases: bool = False   # e621-only

    merged_post_count: str = 'sum'  # 'danbooru' | 'e621' | 'sum' | 'none' (none = skip merged list)
    include_gelbooru: bool = False  # opt-in: slow, needs API credentials
    krita_output: bool = False      # opt-in: also write Krita AI Diffusion-compatible CSVs
    wildcards: str = 'none'         # 'none' | 'danbooru' | 'e621' | 'both'

    max_age_days: int = 180

    run_date: str = field(default_factory=lambda: date.today().isoformat())

    @property
    def build_merged(self) -> bool:
        return self.merged_post_count != 'none'
