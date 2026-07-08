"""Runtime-adjustable logging verbosity, driven by Configurações -> Nível de Log.

Python's logging level is normally fixed at process startup (logging.basicConfig).
This lets the "nada/erro/info/log" setting take effect immediately, the same way
dns_resolvers and other runtime settings already do (see app/runtime_settings.py).
"""
import logging

LOG_LEVEL_MAP = {
    "nada": logging.CRITICAL + 10,  # acima de CRITICAL: nada é emitido
    "erro": logging.ERROR,
    "info": logging.INFO,
    "log": logging.DEBUG,
}

# Root logger ("") controla nossos próprios módulos. uvicorn/apscheduler criam
# seus próprios loggers nomeados com nível explícito, então precisam ser
# ajustados individualmente para "nada" realmente silenciar o access log.
CONTROLLED_LOGGERS = ["", "uvicorn", "uvicorn.access", "uvicorn.error", "apscheduler", "apscheduler.executors.default"]


def apply_log_level(level_str: str) -> None:
    level = LOG_LEVEL_MAP.get((level_str or "info").strip().lower(), logging.INFO)
    for name in CONTROLLED_LOGGERS:
        logging.getLogger(name).setLevel(level)
