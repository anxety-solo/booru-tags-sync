""" Delete tag-list CSVs older than a configurable age """

import re

from datetime import date, datetime, timedelta
from pathlib import Path

# === TAGSYNC ===
from ..logging_setup import get_logger

log = get_logger()

_DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})')


def _extract_date(filename: str) -> date | None:
    match = _DATE_RE.search(filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), '%Y-%m-%d').date()
    except ValueError:
        return None


def prune_old_csvs(directories: list[Path], max_age_days: int, today: date = None) -> int:
    """Remove *.csv files older than max_age_days in each directory. Never
    deletes the newest file in a directory, even if it's technically past
    the cutoff, so a folder is never left completely empty."""
    today   = today or date.today()
    cutoff  = today - timedelta(days=max_age_days)
    removed = 0

    for directory in directories:
        if not directory.exists():
            continue

        dated_files = []
        for path in directory.glob('*.csv'):
            file_date = _extract_date(path.name)
            if file_date is None:
                log.warning(f"Skipping {path.name}: no date found in filename")
                continue
            dated_files.append((file_date, path))

        if not dated_files:
            continue

        newest = max(file_date for file_date, _ in dated_files)
        for file_date, path in dated_files:
            if file_date < cutoff and file_date != newest:
                path.unlink()
                removed += 1
                log.info(f"Removed stale tag list: {path.name} (dated {file_date})")

    log.info(f"Cleanup: removed {removed} file(s) older than {max_age_days} days")
    return removed
