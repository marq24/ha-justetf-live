# const.py
DOMAIN = "ingstocks"

COORDINATOR_KEY = "multi_coordinator"
DELAYED_TASK_KEY = "delayed_task"

CONF_ISIN = "isin"
CONF_ISINS = "isins"
CONF_ISIN_CONFIG = "isin_config"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_QUANTITY = "quantity"

# used internally in config flow
CONF_SELECTED_ISIN = "selected_isin"
ADD_NEW_ISIN = "__add_new__"
DELETE_ISIN = "__delete_isin__"
SAVE_AND_CLOSE = "__save_close__"

DEFAULT_SCAN_INTERVAL = 15
DEFAULT_QUANTITY = 0.0  # 0 = deaktiviert/kein Positionswert
