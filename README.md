# tag-lists-sync

> [!note]
> Source from [DraconicDragon/danbooru-e621-tag-list-processor](https://github.com/DraconicDragon/danbooru-e621-tag-list-processor)</br>
> The logic was written from scratch, and the CSV format is compatible.

Self-updating tag archive for **Danbooru**, **e621**, and optionally **Gelbooru** in CSV format, for autocomplete in Stable Diffusion tooling:</br>
sd-webui-tagcomplete, ComfyUI-Custom-Scripts, Krita AI Diffusion, SwarmUI, etc.

> By default this fetches **Danbooru + e621 + their merged list**.</br>
> Gelbooru, Krita-specific CSVs, and ComfyUI wildcard files are all opt-in.


## Layout

```
.
├── .github/workflows/update-tag-lists.yml  # runs on the 1st of every month
├── tagsync/
│   ├── main.py               # CLI entrypoint
│   ├── config.py             # constants, category maps, RunConfig
│   ├── models.py             # Tag dataclass
│   ├── logging_setup.py      # colored logger
│   ├── scrapper/             # one module per source
│   │   ├── danbooru.py
│   │   ├── e621.py
│   │   └── gelbooru.py
│   └── utils/
│       ├── http.py           # shared retry/backoff HTTP client
│       ├── formatter.py      # CSV writing
│       ├── merger.py         # combined-list logic
│       ├── cleanup.py        # old-CSV pruning
│       └── wildcard.py       # ComfyUI wildcard file generation
├── tag-lists/                # output (created automatically)
├── blacklisted_tags.json     # tags to always exclude
├── run.py                    # shortcut for `python -m tagsync.main`
└── requirements.txt
```


## Setup

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m tagsync.main    # or: python run.py
```


## Data sources

### Danbooru

`tags.json` is requested with `search[order]=count`, so pages arrive sorted by `post_count` descending.</br>
`fetch_tags()` stops as soon as an entire page's keepable-category rows fall below the threshold — anything past that point is guaranteed to be even less popular.</br>
Pagination is plain offset (`page=N`); the API returns HTTP 410 once its depth limit is reached, which is treated as a normal end of data.

Aliases `tag_aliases.json` are fetched as a separate, unfiltered pass across all pages.

### e621

There's no paginated tag endpoint for a bulk export — instead e621 publishes a JSON index of currently-available database dumps at [`db_exports.json`](https://e621.net/db_exports.json)</br>
Each entry looks like:

```json
{
  "name": "tags",
  "file_name": "tags.csv.gz",
  "checksum": "<sha256>",
  "updated_at": "2026-xx-xxT01:00:00.244-04:00",
  "url": "https://static1.e621.net/data/db_export/tags.csv.gz"
}
```

The right entry is found by its `name` field (`"tags"`, `"tag_aliases"`), and the file itself is served from a different host (`static1.e621.net`)
than the index (`e621.net`) — both are requested and handled independently, including the case where only one of them is reachable.

After download, the gzip is verified against the index's `checksum` (sha256), which rules out silently processing a truncated transfer.

### Gelbooru (optional)

`page=dapi&s=tag&q=index` has a hard 100-tags-per-page limit and no reliable server-side `post_count` filter, so a full scrape walks every page in order — this can take a while.
Requires an API key + user id *(free, from your Gelbooru account settings)* — without them every request returns 401.

Progress is checkpointed to `.cache/gelbooru_checkpoint.json` so an interrupted run resumes instead of restarting from page 0.

Enabled with `--include-gelbooru`


## CSV format

No header, as expected by every listed extension:

```
tag_name,category,post_count,alias1,alias2,...
```

> _Gelbooru and Krita-specific files omit the aliases column._

**Categories by source:**

| Source   | 0       | 1      | 3         | 4         | 5        | 6                      | 7    | 8    | 9           |
| -------- | ------- | ------ | --------- | --------- | -------- | ---------------------- | ---- | ---- | ----------- |
| Danbooru | general | artist | copyright | character | meta     | —                      | —    | —    | —           |
| e621     | general | artist | copyright | character | species  | *invalid (skipped)*    | meta | lore | contributor |
| Gelbooru | general | artist | copyright | character | metadata | *deprecated (skipped)* | —    | —    | —           |

In the merged list (`danbooru_e621_merged`), e621 categories are offset by **+7** and Gelbooru by **+17**, so no range overlaps danbooru's own (0-5) or each other's.</br>
For a tag present in multiple sources, category and aliases follow priority **danbooru > e621 > gelbooru**;</br>
`post_count` follows `--merged-post-count` (`sum` by default: danbooru + e621 counts added together; or `danbooru` / `e621` to use only that source's count)

### Filenames

`<source>_<date>_pt<threshold>[-suffixes].csv`

| Suffix                   | Meaning                                          |
| ------------------------ | ------------------------------------------------ |
| `-ia`                    | aliases column included                          |
| `-dd`                    | danbooru: all alias statuses, not just active    |
| `-ed`                    | e621: deleted/retired aliases included           |
| `-ep`                    | e621: pending aliases included                   |
| `-dpc` / `-epc` / `-spc` | merged: post_count from danbooru / e621 / summed |

Example: `danbooru_e621_merged_2026-xx-xx_pt20-ia-dd-ed-spc.csv`


## Minimum threshold

`post_threshold` cannot go below **5** (`MIN_POST_THRESHOLD` in `config.py`) — not the shared `--threshold`,
nor any of `--danbooru-threshold` / `--e621-threshold` / `--gelbooru-threshold` Gelbooru has no server-side count filter,
so an unbounded threshold would turn its scrape into an effectively endless run.</br>
A value below 5 is rejected immediately at startup with a clear error.


## CLI flags

```
python -m tagsync.main --help
```

| Flag                                           | Default                     | Description                                                      |
| ---------------------------------------------- | --------------------------- | ---------------------------------------------------------------- |
| `--threshold N`                                | `20`                        | `post_count` floor for every source at once (minimum 5)          |
| `--danbooru-threshold N`                       | inherits `--threshold`      | override just for Danbooru                                       |
| `--e621-threshold N`                           | inherits `--threshold`      | override just for e621                                           |
| `--gelbooru-threshold N`                       | inherits `--threshold`      | override just for Gelbooru                                       |
| `--no-aliases`                                 | off                         | don't include the aliases column                                 |
| `--no-deleted-aliases`                         | off (aliases on by default) | exclude inactive/deleted aliases                                 |
| `--include-pending-aliases`                    | off                         | include e621 pending aliases                                     |
| `--merged-post-count {danbooru,e621,sum,none}` | `sum`                       | post_count strategy for duplicates; `none` skips the merged list |
| `--skip-danbooru` / `--skip-e621`              | off                         | skip a source for this run                                       |
| `--include-gelbooru`                           | off                         | enable Gelbooru (needs `GELBOORU_API_KEY`/`GELBOORU_USER_ID`)    |
| `--krita-output`                               | off                         | also write Krita AI Diffusion-compatible CSVs                    |
| `--wildcards {none,danbooru,e621,both}`        | `none`                      | generate ComfyUI wildcard files                                  |
| `--max-age-days N`                             | `180`                       | delete CSVs older than N days (`0` = never)                      |
| `--no-cleanup`                                 | off                         | skip pruning entirely for this run                               |

A per-source override is tracked by whether the flag was passed at all, not by its value — so `--danbooru-threshold` works independently of `--threshold` regardless of what either is set to.


## Environment variables

| Variable                               | Purpose                                                           |
| -------------------------------------- | ----------------------------------------------------------------- |
| `GELBOORU_API_KEY`, `GELBOORU_USER_ID` | required when `--include-gelbooru` is used                        |
| `GELBOORU_MAX_PAGES`                   | safety cap for a Gelbooru scrape (default 5000)                   |
| `GELBOORU_CHECKPOINT_DIR`              | where the Gelbooru resume file is stored (default `.cache`)       |
| `DANBOORU_MAX_PAGES`                   | safety cap for Danbooru pagination (default 2000)                 |
| `TAGSYNC_USER_AGENT`                   | User-Agent sent with every request                                |
| `TAGSYNC_LOG_LEVEL`                    | log level (default `INFO`)                                        |
| `TAGSYNC_INCLUDE_GELBOORU`             | `1`/`true` enables Gelbooru without the `--include-gelbooru` flag |


## GitHub Actions

`.github/workflows/update-tag-lists.yml` runs on **the 1st of every month at 03:00 UTC**.
The scheduled trigger and a manual `workflow_dispatch` run use identical defaults — running it by hand with nothing changed behaves exactly like the automated run.

Every CLI flag is exposed as a `workflow_dispatch` input (GitHub Actions → select the workflow → Run workflow),
including `dry_run` (run the pipeline without committing — the result still lands in the run's artifacts for 14 days).

Requirements:

- Settings → Actions → General → Workflow permissions → **Read and write permissions** (otherwise `git push` from the workflow fails);
- `GELBOORU_API_KEY` / `GELBOORU_USER_ID` secrets (Settings → Secrets and variables → Actions) — only needed for `include_gelbooru`

Old CSVs are pruned automatically (`--max-age-days`); the newest file in each directory is never deleted, even if it's technically past the cutoff.


## Tag blacklist

`blacklisted_tags.json` — tags always excluded after fetching, before CSV writing and before the merged list is built:

```json
{
  "danbooru": ["artist_request", "commentary", "..."],
  "e621": ["conditional_dnp", "..."],
  "gelbooru": []
}
```
