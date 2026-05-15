import logging
from enum import Enum
from typing import (
    NamedTuple
)

# from aenum import Enum, extend_enum

_LOGGER: logging.Logger = logging.getLogger(__package__)


class ApiKey(NamedTuple):
    key: str
    keys: list[str] | None = None

class Tag(ApiKey, Enum):

    def __hash__(self) -> int:
        return hash(self.key)

    def __str__(self):
        return self.key

    TIMESTAMP = ApiKey(key="timestamp")
    MID = ApiKey(key="mid")
    BID = ApiKey(key="bid")
    ASK = ApiKey(key="ask")
    QUOTE52WEEKLOW  = ApiKey(key="quote52WeekLow", keys=["quoteLowHigh", "low"])
    QUOTE52WEEKHIGH = ApiKey(key="quote52WeekHigh", keys=["quoteLowHigh", "high"])

