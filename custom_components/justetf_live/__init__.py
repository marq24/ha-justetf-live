
import asyncio
import copy
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Final

from aiohttp import ClientConnectionError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, CoreState, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    device_registry as device_reg
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.event import async_track_time_interval, async_track_utc_time_change, async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.loader import async_get_integration

from custom_components.justetf_live.const import (
    DOMAIN,
    CONF_ISINS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    STARTUP_MESSAGE,
    MANUFACTURER,
    CONF_ISIN_CONFIG,
    CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE,
    DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE
)
from custom_components.justetf_live.pyjustetflive_ha import JustETFBridge, STOCK_EXCHANGE_TZ
from custom_components.justetf_live.pyjustetflive_ha.const import TRANSLATIONS

PLATFORMS = ["sensor"]
_LOGGER = logging.getLogger(__name__)
WEBSOCKET_WATCHDOG_INTERVAL_DAY: Final = timedelta(minutes=0, seconds=30)
WEBSOCKET_WATCHDOG_INTERVAL_NIGHT: Final = timedelta(hours=1, minutes=0, seconds=0)

async def async_setup(hass: HomeAssistant, config: dict):  # pylint: disable=unused-argument
    """Set up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    if DOMAIN not in hass.data:
        the_integration = await async_get_integration(hass, DOMAIN)
        intg_version = the_integration.version if the_integration is not None else "UNKNOWN"
        _LOGGER.info(STARTUP_MESSAGE % intg_version)
        hass.data.setdefault(DOMAIN, {"manifest_version": intg_version})

    coordinator = JustETFDataUpdateCoordinator(hass, config_entry)
    backup_key = f"BACKUP_{config_entry.entry_id}"
    if backup_key in hass.data[DOMAIN]:
        restore_data_dict = hass.data[DOMAIN].get(backup_key, {})

        # we must check if the count of the new isins (that are configured) is the same as the
        # ones that we just have restored from the "backup"...
        last_count = restore_data_dict.get("count", 0) if restore_data_dict is not None else 0
        if last_count == coordinator.isin_count:
            coordinator.init_bridge(restore_data_dict)

        hass.data[DOMAIN].pop(backup_key)

    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][config_entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    # right now we don't need any cleanup (yet)...
    #asyncio.create_task(coordinator.cleanup_device_registry(hass))

    # ws watchdog...
    if hass.state is CoreState.running:
        _LOGGER.debug(f"starting watchdog INSTANTLY")
        await coordinator.start_watchdog()
    else:
        _LOGGER.debug(f"starting watchdog delayed... (when EVENT_HOMEASSISTANT_STARTED is fired)")
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, coordinator.start_watchdog)

    config_entry.async_on_unload(config_entry.add_update_listener(entry_update_listener))
    # ok we are done...
    return True


# def check_unload_services(hass: HomeAssistant):
#     active_integration_configs = hass.config_entries.async_entries(domain=DOMAIN, include_disabled=False, include_ignore=False)
#     if active_integration_configs is not None and len(active_integration_configs) > 0:
#         return False
#     else:
#         return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)

    if unload_ok:
        if DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]:
            coordinator: JustETFDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
            coordinator.stop_watchdog()
            # creating a local backup of the data (so we have faster restarts)...
            hass.data[DOMAIN][f"BACKUP_{config_entry.entry_id}"] = copy.deepcopy(coordinator.bridge.get_backup_data())
            coordinator.clear_data()
            hass.data[DOMAIN].pop(config_entry.entry_id)

        # # ONLY remove the SERVICES if this is the LAST ACTIVE config_entry that will be unloaded!
        # if check_unload_services(hass):
        #     hass.services.async_remove(DOMAIN, SERVICE_SET_PV_DATA)
        #     hass.services.async_remove(DOMAIN, SERVICE_STOP_CHARGING)

    return unload_ok


async def entry_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    _LOGGER.debug(f"entry_update_listener() called for entry: {config_entry.entry_id}")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_remove_config_entry_device(hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry) -> bool:
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    # Only handle devices belonging to this integration/config entry
    if config_entry.entry_id not in device_entry.config_entries:
        return False

    if not any(identifier[0] == DOMAIN for identifier in device_entry.identifiers):
        return False

    # Allow removing dynamic child devices like vehicles/loadpoints.
    return coordinator is not None


# right now no device-cleanup needed (yet)
# @staticmethod
# async def check_device_registry(hass: HomeAssistant):
#     _LOGGER.info(f"check device registry...")
#     if hass is not None:
#         a_device_reg = device_reg.async_get(hass)
#         if a_device_reg is not None:
#             key_list = []
#             for a_device_entry in list(a_device_reg.devices.values()):
#                 if hasattr(a_device_entry, "identifiers"):
#                     ident_value = a_device_entry.identifiers
#                     if f"{ident_value}".__contains__(DOMAIN) and len(next(iter(ident_value))) != 4:
#                         _LOGGER.debug(f"found a OLD {DOMAIN} DeviceEntry: {a_device_entry}")
#                         key_list.append(a_device_entry.id)
#
#             if len(key_list) > 0:
#                 _LOGGER.info(f"NEED TO DELETE old {DOMAIN} DeviceEntries: {key_list}")
#                 for a_device_entry_id in key_list:
#                     a_device_reg.async_remove_device(device_id=a_device_entry_id)


class JustETFDataUpdateCoordinator(DataUpdateCoordinator):

    _watchdog = None
    _watchdog_time = None
    _watchdog_5min = None
    _active_watchdog_interval = None
    _ws_start_task: asyncio.Task | None = None

    def __init__(self, hass: HomeAssistant, config_entry):
        self._config_entry = config_entry
        self._watchdog = None
        self._watchdog_time = None
        self._watchdog_5min = None
        self._active_watchdog_interval = None
        self._ws_start_task = None

        lang = hass.config.language.lower()
        self.bridge: JustETFBridge = JustETFBridge(
            web_session=async_get_clientsession(hass),
            isins=config_entry.data.get(CONF_ISINS, None),
            lang=lang)

        self.lang_map = None
        if lang in TRANSLATIONS:
            self.lang_map = TRANSLATIONS[lang]
        else:
            self.lang_map = TRANSLATIONS["en"]

        self.name = config_entry.title

        # if config_entry.data.get(CONF_DELAY, False):
        #     self._ws_data_update_notify_interval_in_seconds = SCAN_INTERVAL.seconds
        # else:
        #     # minimum update interval - no matter how fast the websocket will push the
        #     # data, we only update HA only every second...
        #     self._ws_data_update_notify_interval_in_seconds = 1
        self._ws_data_update_notify_interval_in_seconds = 1

        update_interval = timedelta(minutes=config_entry.data.get(CONF_SCAN_INTERVAL, 5))

        # calculating the overall investment for the whole portfolio...
        isin_configs: dict[str, dict] = config_entry.data.get(CONF_ISIN_CONFIG, {})

        self.isin_count = len(isin_configs.keys())
        self.invested_isins = {}
        self.price_to_use = config_entry.data.get(CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE, DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE)

        self.total_invest: float= 0.0
        self.total_value: float= 0.0
        self.total_change: float= 0.0
        self.total_return: float= 0.0

        for a_isin in isin_configs.keys():
            if "quantity" not in isin_configs[a_isin]:
                continue
            try:
                quantity = float(isin_configs[a_isin].get("quantity", 0.0))
                if quantity > 0.0:
                    self.invested_isins[a_isin] = {"quantity": quantity}
                    if "invest" not in isin_configs[a_isin]:
                        continue
                    invest = float(isin_configs[a_isin].get("invest", 0.0))
                    if invest > 0.0:
                        self.total_invest += invest
                        self.invested_isins[a_isin] = {"quantity": quantity, "invest": invest}

            except Exception as ex:
                _LOGGER.info(f"__init__(): {a_isin} - {isin_configs[a_isin]} caused: {type(ex).__name__} - {ex}")

        # try:
        #     self.total_invest: float = sum([float(a_isin_config.get("invest", 0.0)) for a_isin_config in isin_configs.values()])
        # except Exception as ex:
        #     self.total_invest = 0.0
        #     _LOGGER.info(f"__init__(): could not calculate overall investment: {type(ex).__name__} - {ex}")

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

        @callback
        def global_data_update_listener() -> None:
            """Logic to execute when the coordinator updates."""
            self.total_return = None
            self.total_value = None
            self.total_change = None

            if self.data is not None:
                self.total_value = 0.0
                self.total_change = -self.total_invest

                for a_isin in self.invested_isins.keys():
                    if a_isin not in self.data:
                        continue

                    a_isin_quantity = self.invested_isins[a_isin].get("quantity", 0.0)
                    a_isin_value = self.data.get(a_isin, {})
                    if self.price_to_use in a_isin_value:

                        a_isin_invest = self.invested_isins[a_isin].get("invest", 0.0)
                        if a_isin_invest > 0.0:
                            position_value = float(a_isin_value[self.price_to_use]) * a_isin_quantity
                            self.total_value += position_value
                            self.total_change += position_value

                if self.total_value > 0.0:
                    self.total_return = self.total_change / self.total_value * 100.0

                # we calculate the current values OF ALL ISIN's
                _LOGGER.debug("Coordinator data has updated: %s", self.total_value)

        self.unsub = self.async_add_listener(global_data_update_listener)


    def init_bridge(self, backup_data:dict):
        _LOGGER.debug(f"init_bridge(): will restore previous data... {backup_data}")
        self.bridge.init_bridge(backup_data)


    async def call_later_update_device_registry(self, now:Any):
        _LOGGER.debug(f"call_later_update_device_registry(): called with '{now}'")
        if self.hass is not None:
            a_device_reg = device_reg.async_get(self.hass)
            is_connected = self.bridge.ws_connected and self.bridge.ws_check_last_update()
            if a_device_reg is not None:
                devices = [
                    device
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                    for device in device_reg.async_entries_for_config_entry(a_device_reg, entry.entry_id)
                ]
                for device in devices:
                    _LOGGER.info(f"call_later_update_device_registry(): device registry update triggered for device {device.name} {'✅' if is_connected else '⛔'}")
                    if is_connected:
                        f_model_id = f"{self.lang_map['websocket_connected']}: ✅"
                    else:
                        f_model_id = f"{self.lang_map['websocket_not_connected']}: ⛔"

                    a_device_reg.async_update_device(
                        device.id,
                        model_id=f_model_id
                    )


    async def start_watchdog(self, event=None):
        """Start websocket watchdog."""
        _LOGGER.debug("start_watchdog() initializing the watchdogs - should only happen once!")

        # when we start the watchdog - we must for sure establish a websocket connection...
        await self._start_ws_connection()

        # starting our INTERVAL-based watchdog...
        if self.bridge.is_out_of_stock_exchange_operating_hours():
            self._set_watchdog_interval(WEBSOCKET_WATCHDOG_INTERVAL_NIGHT)
        else:
            self._set_watchdog_interval(WEBSOCKET_WATCHDOG_INTERVAL_DAY)

        # make sure that every workday day at ~7:30 (Berlin TZ) we ensure that the websocket is up and running
        from datetime import timezone, time
        berlin_7 = datetime.combine(
            datetime.now(STOCK_EXCHANGE_TZ).date(),
            time(7, 0),
            tzinfo=STOCK_EXCHANGE_TZ,
        )
        self._watchdog_time = async_track_utc_time_change(
            self.hass,
            self._async_watchdog_check,
            hour = berlin_7.astimezone(timezone.utc).hour,
            minute = random.randint(27, 29),
            second = random.randint(0, 59)
        )

        # run a check if we should set a new watchdog interval every 5 minutes
        self._watchdog_5min = async_track_utc_time_change(
            self.hass,
            self._async_check_watchdog_interval,
            minute=range(0, 60, 5),
            second = random.randint(10, 49)
        )


    async def _async_check_watchdog_interval(self, *_):
        _LOGGER.debug("_async_check_watchdog_interval()")
        if self.bridge.is_out_of_stock_exchange_operating_hours():
            if self._active_watchdog_interval != WEBSOCKET_WATCHDOG_INTERVAL_NIGHT:
                self._set_watchdog_interval(WEBSOCKET_WATCHDOG_INTERVAL_NIGHT)
        else:
            if self._active_watchdog_interval != WEBSOCKET_WATCHDOG_INTERVAL_DAY:
                self._set_watchdog_interval(WEBSOCKET_WATCHDOG_INTERVAL_DAY)


    def _set_watchdog_interval(self, interval: timedelta) -> None:
        _LOGGER.debug(f"_set_watchdog_interval(): {interval}")
        if hasattr(self, "_watchdog") and self._watchdog is not None:
            self._watchdog()
            self._watchdog = None

        self._active_watchdog_interval = interval
        self._watchdog = async_track_time_interval(
            self.hass,
            self._async_watchdog_check,
            interval,
            cancel_on_shutdown=True,
        )


    def stop_watchdog(self):
        if hasattr(self, "_watchdog_time") and self._watchdog_time is not None:
            self._watchdog_time()
            self._watchdog_time = None

        if hasattr(self, "_watchdog_5min") and self._watchdog_5min is not None:
            self._watchdog_5min()
            self._watchdog_5min = None

        if hasattr(self, "_watchdog") and self._watchdog is not None:
            self._watchdog()
            self._watchdog = None
            async_call_later(self.hass, 5, self.call_later_update_device_registry)


    def _check_for_ws_task_and_cancel_if_running(self):
        if self._ws_start_task is not None and not self._ws_start_task.done():
            _LOGGER.debug(f"Watchdog: WebSocket connect task is still running - canceling it...")
            try:
                canceled = self._ws_start_task.cancel()
                _LOGGER.debug(f"Watchdog: WebSocket connect task was CANCELED? {canceled}")
            except BaseException as ex:
                _LOGGER.info(f"Watchdog: WebSocket connect task cancel failed: {type(ex).__name__} - {ex}")

            self._ws_start_task = None


    async def _async_watchdog_check(self, *_):
        if not self.bridge.ws_connected:
            self._check_for_ws_task_and_cancel_if_running()
            if self.bridge.is_out_of_stock_exchange_operating_hours():
                _LOGGER.debug(f"Watchdog: WebSocket is not running, but the stock market is closed -> no call for action, all is fine")
            else:
                _LOGGER.info(f"Watchdog: WebSocket connect required")
                await self._start_ws_connection()
        else:
            _LOGGER.debug(f"Watchdog: WebSocket is connected")
            if not self.bridge.ws_check_last_update():
                self._check_for_ws_task_and_cancel_if_running()
                async_call_later(self.hass, 5, self.call_later_update_device_registry)


    async def _start_ws_connection(self):
        self.bridge.ws_set_coordinator(coordinator=self)
        self._ws_start_task = self._config_entry.async_create_background_task(self.hass, self.bridge.ws_connect(), "ws_connection")
        if self._ws_start_task is not None:
            _LOGGER.debug(f"Watchdog: task created {self._ws_start_task.get_coro()}")
            async_call_later(self.hass, 10, self.call_later_update_device_registry)


    def clear_data(self):
        _LOGGER.debug(f"clear_data called...")
        self._check_for_ws_task_and_cancel_if_running()
        self.bridge.clear_data()
        if self.data is not None:
            self.data.clear()


    # async def trigger_restart_delayed(self) -> None:
    #     # Generate a random sleep time between 5 and 10 minutes (300 and 600 seconds)
    #     random_seconds = random.uniform(300, 600)
    #     # random_seconds = random.uniform(60, 120)
    #     _LOGGER.info(f"trigger_restart_delayed(): Sleeping for {random_seconds:.2f} seconds...")
    #     await asyncio.sleep(random_seconds)
    #     _LOGGER.info(f"trigger_restart_delayed(): --- RELOAD INTEGRATION NOW ---")
    #     await self.hass.config_entries.async_reload(self._config_entry.entry_id)


    async def _async_update_data(self) -> dict:
        """Update data via library."""
        _LOGGER.debug(f"_async_update_data()")
        if self.bridge.ws_connected:
            _LOGGER.debug(f"_async_update_data(): called (but WebSocket is active - no data will be requested!)")
            return self.bridge._ws_data
        else:
            try:
                new_data = await self.bridge.read_all()
                if new_data is not None and len(new_data) > 0:
                    return new_data

            except ClientConnectionError as exception:
                self._handle_client_connection_error("_async_update_data()", exception)
                raise UpdateFailed(f"Error while fetching data: {exception}") from exception
            except UpdateFailed as exception:
                raise UpdateFailed() from exception
            except Exception as other:
                _LOGGER.error(f"_async_update_data(): unexpected: {other}")
                raise UpdateFailed() from other


    # right now we don't need any cleanup (yet)...
    # async def cleanup_device_registry(self, hass: HomeAssistant):
    #     _LOGGER.debug(f"check device registry for orphan {DOMAIN} entries... in 20sec")
    #     await asyncio.sleep(20)
    #     _LOGGER.debug(f"check device registry for orphan {DOMAIN} entries NOW!")
    #     await check_device_registry(hass=hass)