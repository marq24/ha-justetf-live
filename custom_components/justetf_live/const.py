from typing import Final

DOMAIN = "justetf_live"

CONF_ISIN = "isin"
CONF_ISINS = "isins"
CONF_ISIN_CONFIG = "isin_config"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_QUANTITY = "quantity"
CONF_INVEST = "invest"
CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE = "position_value_price"
CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START = "day_month_start_price"
CONF_ETFOBJECT = "etfobject"


# used internally in config flow
CONF_SELECTED_ISIN = "selected_isin"
ADD_NEW_ISIN = "__add_new__"
DELETE_ISIN = "__delete_isin__"
SAVE_AND_CLOSE = "__save_close__"

DEFAULT_SCAN_INTERVAL = 15
DEFAULT_QUANTITY = 0.0  # 0 = deaktiviert/kein Positionswert
DEFAULT_INVEST = 0.0  # 0 = deaktiviert/kein investierter €
DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE = "bid"
DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START = "bid"
PRICE_TO_USE_AS_SOURCE_OPTIONS: Final = ("bid", "ask", "mid")


NAME = "ha-justetf-live"
ISSUE_URL = "https://github.com/JustETF/ha-justetf-live/issues"
MANUFACTURER = "JustETF live (https://www.justetf.com/)"
STARTUP_MESSAGE: Final = f"""
-------------------------------------------------------------------
{NAME} - v%s
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""
