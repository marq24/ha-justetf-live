import asyncio
import json
import logging
import random
import time
from datetime import date, datetime, timezone
from typing import Final
from zoneinfo import ZoneInfo

import aiohttp

from custom_components.justetf_live.pyjustetflive_ha.const import (
    TRANSLATIONS,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


WS_BASE: Final = "api.mobile.stock-data-subscriptions.justetf.com"
REQ_BASE: Final = "www.justetf.com/api/etfs"
A_ISIN_PLACEHOLDER: Final = "@AISIN@"
KEYS_TO_IGNORE: Final = ["isin", "stockExchange", "quoteType", "currency", "last", "trend"]
META_KEYS_TO_REMOVE: Final = ["isin", "ter", "quote", "latestQuote", "latestQuoteDate", "previousQuoteDate", "availableChartPeriods", "icons", "badges", "shareText"]
KEY_52WEEK_HIGHLOW: Final = "quoteLowHigh"

USER_AGENT: Final = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
STOCK_EXCHANGE_TZ: Final = ZoneInfo("Europe/Berlin")


def reduce_raw_values(value):
    if isinstance(value, dict):
        if "raw" in value:
            return value["raw"]

        return {
            key: reduce_raw_values(inner_value)
            for key, inner_value in value.items()
        }

    if isinstance(value, list):
        return [reduce_raw_values(item) for item in value]

    return value


class JustETFBridge:

    def __init__(self, web_session, isins: list[str], lang: str = "en") -> None:
        self.coordinator = None
        self.web_session = web_session
        self.lang_map = None
        # EUR, USD, CHF, GBR
        CURRENCY = "EUR"
        if lang in TRANSLATIONS:
            self.lang_map = TRANSLATIONS[lang]
        else:
            self.lang_map = TRANSLATIONS["en"]

        if isins is not None:
            self.ws_url = f"wss://{WS_BASE}/?subscription=trend&parameters=isins:{','.join(isins)}/currency:{CURRENCY}/language:{lang.lower()}"
        else:
            _LOGGER.error("JustETFBridge(): no ISINs provided!")
            return

        self.req_url_meta = f"https://{REQ_BASE}/cards?locale={lang.lower()}&currency={CURRENCY}&isin={A_ISIN_PLACEHOLDER}"
        self.req_url_details = f"https://{REQ_BASE}/{A_ISIN_PLACEHOLDER}/quote?currency={CURRENCY}&locale={lang.lower()}"
        self.headers = {
            "User-Agent": USER_AGENT,
        }

        self.isin_list = isins

        self.ws_connected = False
        self._ws_LAST_UPDATE = 0
        self._ws_LAST_NEW_DATA_NOTIFY = 0
        self._ws_data = {}
        self._ws_connection = None
        self._ws_message_count = {isin: 0 for isin in self.isin_list}
        self._ws_debounced_update_task = None
        self._DETAILS_LAST_UPDATE = 0
        self._DETAILS_RUN_DATE: date = datetime.now(timezone.utc).date()
        self._details_data = {}


    def init_bridge(self, data:dict):
        if data is None:
            self._details_data = data.get("details", {})
            self._DETAILS_LAST_UPDATE = data.get("last_update", 0)
            self._DETAILS_RUN_DATE = data.get("run_date", None)

    def get_backup_data(self):
        return {
            "details": self._details_data,
            "last_update": self._DETAILS_LAST_UPDATE,
            "run_date": self._DETAILS_RUN_DATE,
            "count": len(self._details_data.keys()) if self._details_data is not None else 0,
        }


    def available_fields(self) -> int:
        return len(self._ws_data)


    def clear_data(self):
        self._ws_LAST_UPDATE = 0
        self._ws_LAST_NEW_DATA_NOTIFY = 0
        self._ws_data = {}
        self._DETAILS_LAST_UPDATE = 0
        self._DETAILS_RUN_DATE = None
        self._details_data = {}


    async def read_all(self) -> dict:
        now_date = datetime.now(timezone.utc).date()
        now_time = time.time()

        is_next_day = (now_date != self._DETAILS_RUN_DATE)

        # 1 day = 24h * 60min * 60sec = 86400 sec
        # 1 hour = 60min * 60sec = 3600 sec
        are_24_hours_passed = ((self._DETAILS_LAST_UPDATE + 86400 + random.randint(-3600, 3600))  < now_time)

        if is_next_day or are_24_hours_passed:
            self._details_data = await asyncio.create_task(self._read_all_details())
            self._DETAILS_LAST_UPDATE = now_time
            self._DETAILS_RUN_DATE = now_date

            # need to insert the 52week high/low data into the details data...
            for isin in self._details_data:
                if isin in self._ws_data:
                    self._ws_data[isin][KEY_52WEEK_HIGHLOW] = self._details_data[isin][KEY_52WEEK_HIGHLOW]

        return self._ws_data


    async def _read_all_details(self, do_quick:bool=False) -> dict:
        _LOGGER.info(f"_read_all_details(): called")
        data = {}
        for isin in self.isin_list:
            # sleep for the 0.1 - 1.2 second and all following isin's...
            if len(data) > 0:
                if do_quick:
                    await asyncio.sleep(random.uniform(0.1, 1.2))
                else:
                    await asyncio.sleep(random.uniform(1, 3.5))

            async with self.web_session.get(self.req_url_details.replace(A_ISIN_PLACEHOLDER, isin), headers=self.headers) as res:
                try:
                    if 199 < res.status < 300:
                        try:
                            r_json = await res.json()
                            if r_json is not None and len(r_json) > 0:
                                if r_json.get("latestQuote", None) is not None:
                                    data[isin] = reduce_raw_values(r_json)

                        except json.JSONDecodeError as json_exc:
                            _LOGGER.warning(f"_read_all_details(): JSONDecodeError while 'await res.json(): {json_exc}")

                        except aiohttp.ClientResponseError as io_exc:
                            _LOGGER.warning(f"_read_all_details(): ClientResponseError while 'await res.json(): {io_exc}")

                    else:
                        _LOGGER.warning(f"_read_all_details(): REQ_ALL failed with http-status {res.status} {res.request_info.url}")

                except aiohttp.ClientResponseError as io_exc:
                    _LOGGER.warning(f"_read_all_details(): REQ_ALL failed cause: {io_exc}")
                except BaseException as err:
                    _LOGGER.warning(f"_read_all_details(): BaseException: {type(err).__name__}: {err}")

        return data

    async def _read_meta(self, isin) -> dict:
        _LOGGER.info(f"_read_all_deatils(): called")
        data = {}
        async with self.web_session.get(self.req_url_meta.replace(A_ISIN_PLACEHOLDER, isin), headers=self.headers) as res:
            try:
                if 199 < res.status < 300:
                    try:
                        r_json = await res.json()
                        _LOGGER.debug(f"_read_meta(): {r_json}")
                        if r_json is not None and len(r_json) > 0:
                            if r_json.get("etfs", None) is not None:
                                r_json = r_json["etfs"][0]

                                # removed unnecessary meta data content...
                                for key in META_KEYS_TO_REMOVE:
                                    r_json.pop(key, None)

                                data[isin] = reduce_raw_values(r_json)

                    except json.JSONDecodeError as json_exc:
                        _LOGGER.warning(f"_read_all_data(): JSONDecodeError while 'await res.json(): {json_exc}")

                    except aiohttp.ClientResponseError as io_exc:
                        _LOGGER.warning(f"_read_all_data(): ClientResponseError while 'await res.json(): {io_exc}")

                else:
                    _LOGGER.warning(f"_read_all_data(): REQ_ALL failed with http-status {res.status} {res.request_info.url}")

            except aiohttp.ClientResponseError as io_exc:
                _LOGGER.warning(f"_read_all_data(): REQ_ALL failed cause: {io_exc}")
            except BaseException as err:
                _LOGGER.warning(f"_read_all_data(): BaseException: {type(err).__name__}: {err}")

        return data


    #######################
    ###### WEBSOCKET ######
    #######################
    def ws_set_coordinator(self, coordinator):
        self.coordinator = coordinator
        self._ws_debounced_update_task = None

    def ws_check_last_update(self) -> bool:
        # we expect at least every 60-second data from the websocket...
        if (self._ws_LAST_UPDATE + 60) > time.time():
            _LOGGER.debug(f"ws_check_last_update(): all good! [last update: {int(time.time()-self._ws_LAST_UPDATE)} sec ago]")
            return True
        else:
            if self.is_out_of_stock_exchange_operating_hours():
                return False
            else:
                _LOGGER.info(f"ws_check_last_update(): force reconnect...")
                return False

    async def ws_close(self, ws):
        """Close the WebSocket connection cleanly."""
        _LOGGER.debug(f"ws_close(): for '{self.ws_url}' called")

        self.ws_connected = False
        if ws is not None:
            try:
                await ws.close()
                _LOGGER.debug(f"ws_close(): connection closed successfully")
            except BaseException as e:
                _LOGGER.info(f"ws_close(): Error closing WebSocket connection: {type(e).__name__} - {e}")
            finally:
                ws = None
        else:
            _LOGGER.debug(f"ws_close(): No active WebSocket connection to close (ws is None)")

    def _ws_notify_for_new_data(self):
        if self._ws_debounced_update_task is not None and not self._ws_debounced_update_task.done():
            self._ws_debounced_update_task.cancel()

        async def _ws_debounce_coordinator_update():
            if hasattr(self, "coordinator"):
                # sleeping before we notify for updated data
                if self.coordinator is not None:
                    elapsed = time.time() - self._ws_LAST_NEW_DATA_NOTIFY
                    if elapsed < self.coordinator._ws_data_update_notify_interval_in_seconds:
                        sec_to_sleep = self.coordinator._ws_data_update_notify_interval_in_seconds - elapsed
                        _LOGGER.debug(f"_ws_debounce_coordinator_update(): sleeping for {sec_to_sleep} seconds before notifying for updated data")
                        await asyncio.sleep(sec_to_sleep)
                    else:
                        await asyncio.sleep(0.2)

                if self.coordinator is not None:
                    self.coordinator.async_set_updated_data(self._ws_data)
                    self._ws_LAST_NEW_DATA_NOTIFY = time.time()
                else:
                    #_LOGGER.debug(f"_ws_debounce_coordinator_update(): coordinator is None or not initialized")
                    pass

        self._ws_debounced_update_task = asyncio.create_task(_ws_debounce_coordinator_update())

    async def ws_connect(self):
        """Connect to WebSocket with full authentication and message handling"""
        _LOGGER.debug(f"ws_connect() STARTED...")
        self.ws_connected = False
        self._ws_connect_start_time = time.time()

        if self.ws_url is None:
            _LOGGER.warning("ws_connect(): WebSocket URL not configured")
            return None

        self._ws_message_count = {isin: 0 for isin in self.isin_list}

        # make sure we have some high/low 52 week data...
        if not self._details_data and len(self._details_data) == 0:
            self._details_data = await self._read_all_details(do_quick=True)
            self._DETAILS_LAST_UPDATE = time.time()

        # finally, establish out websocket connection - look like that there is no message limit
        # at the backend side - no clue why the regular web access stops after ~1000 received
        # messages...
        try:
            async with (self.web_session.ws_connect(url=self.ws_url, headers=self.headers) as ws):
                self._ws_connection = ws
                _LOGGER.info(f"ws_connect(): Connected to WebSocket: {self.ws_url}")

                # Handle incoming messages
                async for msg in ws:
                    if not self.ws_connected:
                        self.ws_connected = True

                    new_data_arrived = False

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                            new_data_arrived = self.extract_ws_message_data(data)

                        except Exception as e:
                            _LOGGER.warning(f"ws_connect(): Error processing TEXT message: {type(e).__name__} - {e}")

                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        _LOGGER.info(f"ws_connect(): WebSocket closed or error: {msg}")
                        break

                    else:
                        _LOGGER.warning(f"ws_connect(): Unknown message type: {msg.type}")

                    # Notify coordinator if new data arrived
                    if new_data_arrived:
                        # Store the last time we heard from the websocket
                        self._ws_LAST_UPDATE = time.time()
                        self._ws_notify_for_new_data()

        except aiohttp.ClientConnectionError as err:
            _LOGGER.error(f"ws_connect(): Could not connect to websocket: {type(err).__name__} - {err}")
        except asyncio.TimeoutError as time_exc:
            _LOGGER.debug(f"ws_connect(): TimeoutError: No WebSocket message received within timeout period")
        except asyncio.CancelledError as canceled:
            _LOGGER.info(f"ws_connect(): Terminated - {type(canceled).__name__}")
        except BaseException as x:
            _LOGGER.error(f"ws_connect(): Error: {type(x).__name__} - {x}")

        max_key = max(self._ws_message_count, key=self._ws_message_count.get)
        max_value = self._ws_message_count[max_key]
        duration = int(time.time() - self._ws_connect_start_time)
        hours = duration // 3600
        minutes = (duration % 3600) // 60

        _LOGGER.debug(f"ws_connect() ENDED - after {hours:02d}h {minutes:02d}m - {max_value}: {max_key} messages - {self._ws_message_count}")

        if False:
            if hasattr(self, "coordinator") and self.coordinator is not None:
                async def launch_ws_check():
                    _LOGGER.info(f"ws_connect(): will launch_ws_check()...")
                    await asyncio.sleep(2)
                    self.coordinator._async_watchdog_check()

                asyncio.create_task(launch_ws_check())
            else:
                _LOGGER.info(f"ws_connect(): coordinator is None or not initialized")
                pass

        try:
            await self.ws_close(ws)
        except UnboundLocalError:
            _LOGGER.debug(f"ws_connect(): Skipping ws_close() (ws_connection is unbound)")
        except BaseException as e:
            _LOGGER.error(f"ws_connect(): Error in ws_close(): {type(e).__name__} - {e}")

        self.ws_connected = False
        self._ws_connection = None
        self._ws_LAST_UPDATE = 0
        self._ws_LAST_NEW_DATA_NOTIFY = 0

        return None

    def extract_ws_message_data(self, msg_data:dict):
        # {   "isin": "IE000UQND7H4",
        #     "timestamp": "2026-05-15T05:30:53.165Z",
        #     "trend": "N",
        #     "ask": {"raw": 40.03, "localized": "40,03"},
        #     "bid": {"raw": 39.79, "localized": "39,79"},
        #     "mid": {"raw": 39.91, "localized": "39,91"},
        #     "last": {"raw": 39.71, "localized": "39,71"},
        #     "currency": "EUR",
        #     "dtdDec": {"raw": 0.0050, "localized": "0,0050"},
        #     "dtdPrc": {"raw": 0.50, "localized": "0,50"},
        #     "dtdAmt": {"raw": 0.20, "localized": "0,20"},
        #     "spreadAmt": {"raw": 0.24, "localized": "0,24"},
        #     "spreadDec": {"raw": 0.0060, "localized": "0,0060"},
        #     "spreadPrc": {"raw": 0.60, "localized": "0,60"},
        #     "stockExchange": "gettex",
        #     "quoteType": "R"
        # }
        isin = msg_data.get("isin", "unknown")
        if isin == "unknown" or isin not in self.isin_list:
            return False

        self._ws_message_count[isin] += 1

        reduced = {
            key: datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
            if key == "timestamp" and isinstance(value, str)
            else value["raw"]
            if isinstance(value, dict) and "raw" in value
            else value
            for key, value in msg_data.items()
            if key not in KEYS_TO_IGNORE
        }

        # setting the 'KEY_52WEEK_HIGHLOW' data to the self._ws_data
        if self._details_data:
            if isin in self._details_data:
                reduced[KEY_52WEEK_HIGHLOW] = self._details_data[isin][KEY_52WEEK_HIGHLOW]

        self._ws_data[isin] = reduced
        _LOGGER.debug(f"{isin} - {self._ws_message_count[isin]:04d} - {reduced}")
        return True

    def is_out_of_stock_exchange_operating_hours(self):
        exchange_now = datetime.now(STOCK_EXCHANGE_TZ)
        is_quiet = (
                exchange_now.weekday() >= 5  # 5=Saturday, 6=Sunday
                or exchange_now.hour >= 24
                # some stock exchanges are open till 22:59 (Berlin TZ)
                or (exchange_now.hour == 23 and exchange_now.minute >= 5)
                or exchange_now.hour <= 6
                # trading starts at 7:30 (Berlin TZ)
                or (exchange_now.hour == 7 and exchange_now.minute <= 25)
        )
        return is_quiet
