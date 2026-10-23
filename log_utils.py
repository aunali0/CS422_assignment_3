import json
import logging
from typing import Literal

LogLevel = Literal["control", "data", "test", "error"]
logger = logging.getLogger(__name__)

LOG_LEVELS: dict[LogLevel, int] = {
    "control": logging.DEBUG,
    "data": logging.DEBUG,
    "test": logging.INFO,
    "error": logging.ERROR,
}


def log_message(level: LogLevel, msg: str) -> None:
    logger.log(LOG_LEVELS[level], "[%s] %s", level, msg)


def log_json(level: LogLevel, action: str, payload: object) -> None:
    if not logger.isEnabledFor(LOG_LEVELS[level]):
        return

    payload_str = json.dumps(payload, indent=2, ensure_ascii=False)
    indent = " " * len(f"[{level}] ")
    indented_json = "\n".join(f"{indent}{line}" for line in payload_str.splitlines())
    log_message(level, f"{action} JSON:\n{indented_json}")
