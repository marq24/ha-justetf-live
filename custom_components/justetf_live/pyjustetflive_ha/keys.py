import logging
import re
from enum import Enum
from typing import (
    NamedTuple, Final
)

# from aenum import Enum, extend_enum

_LOGGER: logging.Logger = logging.getLogger(__package__)

CC_P1: Final = re.compile(r"(.)([A-Z][a-z]+)")
CC_P2: Final = re.compile(r"([a-z0-9])([A-Z])")

def camel_to_snake(a_key: str):
    if a_key.lower().endswith("kwh"):
        a_key = a_key[:-3] + "_kwh"
    a_key = re.sub(CC_P1, r'\1_\2', a_key)
    return re.sub(CC_P2, r'\1_\2', a_key).lower()


class ApiKey(NamedTuple):
    key: str
    keys: list[str] | None = None
    attribute: str  | None = None

class Tag(ApiKey, Enum):

    def __hash__(self) -> int:
        return hash(self.key)

    def __str__(self):
        return self.key


    # UTC timestamp from websocket/API data
    TIMESTAMP = ApiKey(key="timestamp")

    # The Bid price is the highest price a buyer is currently willing to pay for the ETF. If you own shares and
    # want to sell them immediately, this is the price you will get. (6.47)
    BID = ApiKey(key="bid")

    # The Ask (or Offer) price is the lowest price a seller is currently willing to accept. If you want to buy
    # the ETF right now, this is the price you will pay. (6.66)
    ASK = ApiKey(key="ask")

    # The Mid price is simply the exact midpoint between the bid and the ask price. (6.57)
    MID = ApiKey(key="mid")

    # The Spread Fields (The Cost of Trading)
    # The Spread amount is the difference between the bid and ask prices. (0.19 -> 6.66-6.47)
    SPREADAMT = ApiKey(key="spreadAmt")

    # The Spread Decimal is the spread expressed as a fraction of the price (specifically, the spread amount divided by
    # the mid price).
    SPREADDEC = ApiKey(key="spreadDec")

    # The Spread Percentage is just the decimal format turned into a percentage (2.85%)
    SPREADPRC = ApiKey(key="spreadPrc")

    # The DTD Fields (Day-To-Day Performance)
    # The DTD Amount is the raw price change in currency. (The ETF has dropped by 0.58 since yesterday)
    DTDAMT = ApiKey(key="dtdAmt")

    # The DTD Decimal is the daily change expressed as a decimal fraction (-0.0811)
    DTDDEC = ApiKey(key="dtdDec")

    # The DTD Percentage is the daily change expressed as a percentage (-8.11%)
    DTDPRC = ApiKey(key="dtdPrc")

    QUOTE52WEEKLOW  = ApiKey(key="quote52WeekLow", keys=["quoteLowHigh", "low"])
    QUOTE52WEEKHIGH = ApiKey(key="quote52WeekHigh", keys=["quoteLowHigh", "high"])

    # if a quantity is provided, add a value sensor
    POSITIONVALUE = ApiKey(key="position_value")
    POSITIONDEVELOPMENT = ApiKey(key="position_change")

    # Snapshot keys (derived sensors)
    STARTPRICEDAY = ApiKey(key="start_price_day")
    STARTPRICEMONTH = ApiKey(key="start_price_month")

    # Delta keys (live price vs start-of-day / start-of-month)
    CHANGEDAYAMT = ApiKey(key="change_day_amt")
    CHANGEMONTHAMT = ApiKey(key="change_month_amt")

    CHANGEDAYPRC = ApiKey(key="change_day_prc")
    CHANGEMONTHPRC = ApiKey(key="change_month_prc")

    CHANGEDAYPOSITIONVALUE = ApiKey(key="change_day_position_value")
    CHANGEMONTHPOSITIONVALUE = ApiKey(key="change_month_position_value")

    # the portfolio Tags (...)
    TOTAL_INVESTMENT = ApiKey(key="total_invest", attribute="total_invest")
    TOTAL_VALUE = ApiKey(key="total_value", attribute="total_value")
    TOTAL_CHANGE = ApiKey(key="total_change", attribute="total_change")
    TOTAL_RETURN = ApiKey(key="total_return", attribute="total_return")


