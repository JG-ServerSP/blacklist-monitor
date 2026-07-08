"""Runtime-adjustable logging verbosity, driven by Settings -> Log Level.

Python's logging level is normally fixed at process startup (logging.basicConfig).
This lets the "off/error/info/debug" setting take effect immediately, the same way
dns_resolvers and other runtime settings already do (see app/runtime_settings.py).
"""
import logging

LOG_LEVEL_MAP = {
    "off": logging.CRITICAL + 10,  # above CRITICAL: nothing is emitted
    "error": logging.ERROR,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

# The root logger ("") controls our own modules. uvicorn/apscheduler create
# their own named loggers with an explicit level, so they need to be adjusted
# individually for "off" to actually silence the access log.
CONTROLLED_LOGGERS = ["", "uvicorn", "uvicorn.access", "uvicorn.error", "apscheduler", "apscheduler.executors.default"]


def apply_log_level(level_str: str) -> None:
    level = LOG_LEVEL_MAP.get((level_str or "info").strip().lower(), logging.INFO)
    for name in CONTROLLED_LOGGERS:
        logging.getLogger(name).setLevel(level)
