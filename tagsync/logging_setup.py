""" Colored console logger """

import logging
import sys
import os

_RESET = '\033[0m'
_GRAY  = '\033[90m'

_LEVEL_COLORS = {
    'INFO':     '\033[36m',
    'WARNING':  '\033[33m',
    'ERROR':    '\033[31m',
    'CRITICAL': '\033[31;1m',
    'DEBUG':    '\033[35m',
}


class _ColorFormatter(logging.Formatter):
    """Colors the level name by severity and prefixes the module name"""
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelname, '')
        record.levelname = f"{color}{record.levelname:<7}{_RESET}"
        record.name = f"{_GRAY}|{_RESET} {color}{record.name}{_RESET}"
        return super().format(record)


def get_logger(name: str | None = None) -> logging.Logger:
    """Logger for the calling module"""
    if name is None:
        caller_globals = sys._getframe(1).f_globals
        spec = caller_globals.get('__spec__')
        name = spec.name if spec else caller_globals.get('__name__', '?')

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level   = os.environ.get('TAGSYNC_LOG_LEVEL', 'INFO').upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ColorFormatter('[%(asctime)s] %(levelname)s %(name)s: %(message)s', '%H:%M:%S'))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
