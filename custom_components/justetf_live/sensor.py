import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, time, timezone, timedelta
from typing import Final, Any

from awesomeversion import AwesomeVersion
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass, SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, ATTR_FRIENDLY_NAME, __version__ as HA_VERSION, Platform, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import UNDEFINED, UndefinedType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.justetf_live.pyjustetflive_ha.keys import Tag, camel_to_snake
from . import JustETFDataUpdateCoordinator
from .const import (
    DOMAIN,
    MANUFACTURER,
    CONF_ISINS,
    CONF_ISIN_CONFIG,
    CONF_NAME,
    CONF_QUANTITY,
    CONF_INVEST,
    CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE,
    CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START,
    DEFAULT_QUANTITY,
    DEFAULT_INVEST,
    CONF_ETFOBJECT,
    DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE,
    DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START,
    PRICE_TO_USE_AS_SOURCE_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

SNAPSHOT_ATTR_PERIOD_ID: Final = "snapshot_period_id"
SNAPSHOT_ATTR_CAPTURED_AT: Final = "snapshot_captured_at"
INVALID_STATES: Final = {"unknown", "unavailable", "None", None}
SNAPSHOT_HISTORY_LOOKBACK: Final = timedelta(hours = 24)

@dataclass(frozen=True)
class ExtSensorEntityDescription(SensorEntityDescription):
    tag: Tag | None = None
    quantity: float | None = None
    invest: float | None = None
    price_source_to_use: str | None = None

SENSOR_STUBS: Final = [
    ExtSensorEntityDescription(
        tag=Tag.TIMESTAMP,
        key=Tag.TIMESTAMP.key,
        icon="mdi:clock-outline",
        entity_category = EntityCategory.DIAGNOSTIC,
        device_class = SensorDeviceClass.TIMESTAMP,
    ),
    ExtSensorEntityDescription(
        tag=Tag.MID,
        key=Tag.MID.key,
        icon="mdi:chart-line",
        #device_class = SensorDeviceClass.MONETARY,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    ),
    ExtSensorEntityDescription(
        tag=Tag.BID,
        key=Tag.BID.key,
        icon="mdi:briefcase-minus",
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2,
        entity_registry_enabled_default=False
    ),
    ExtSensorEntityDescription(
        tag=Tag.ASK,
        key=Tag.ASK.key,
        icon="mdi:briefcase-plus",
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2,
        entity_registry_enabled_default=False
    ),
    ExtSensorEntityDescription(
        tag=Tag.DTDPRC,
        key=Tag.DTDPRC.key,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=2
    ),
    ExtSensorEntityDescription(
        tag=Tag.DTDAMT,
        key=Tag.DTDAMT.key,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    ),
    ExtSensorEntityDescription(
        tag=Tag.QUOTE52WEEKHIGH,
        key=Tag.QUOTE52WEEKHIGH.key,
        icon="mdi:arrow-expand-vertical",
        #device_class = SensorDeviceClass.MONETARY,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    ),
    ExtSensorEntityDescription(
        tag=Tag.QUOTE52WEEKLOW,
        key=Tag.QUOTE52WEEKLOW.key,
        icon="mdi:arrow-expand-vertical",
        #device_class = SensorDeviceClass.MONETARY,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    )
]
VALUE_SENSOR_STUBS: Final = [
    ExtSensorEntityDescription(
        tag=Tag.POSITIONVALUE,
        key=Tag.POSITIONVALUE.key,
        icon="mdi:briefcase",
        device_class=SensorDeviceClass.MONETARY,
        state_class = SensorStateClass.TOTAL,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    ),
    ExtSensorEntityDescription(
        tag=Tag.CHANGEDAYPOSITIONVALUE,
        key=Tag.CHANGEDAYPOSITIONVALUE.key,
        icon="mdi:cash",
        state_class = SensorStateClass.TOTAL,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    ),
    ExtSensorEntityDescription(
        tag=Tag.CHANGEMONTHPOSITIONVALUE,
        key=Tag.CHANGEMONTHPOSITIONVALUE.key,
        icon="mdi:cash-multiple",
        state_class = SensorStateClass.TOTAL,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    ),
    ExtSensorEntityDescription(
        tag=Tag.POSITIONDEVELOPMENT,
        key=Tag.POSITIONDEVELOPMENT.key,
        icon="mdi:briefcase-check",
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    )
]
SNAPSHOT_SENSOR_STUBS: Final = [
    ExtSensorEntityDescription(
        tag=Tag.STARTPRICEDAY,
        key=Tag.STARTPRICEDAY.key,
        icon="mdi:calendar-today-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2,
    ),
    ExtSensorEntityDescription(
        tag=Tag.STARTPRICEMONTH,
        key=Tag.STARTPRICEMONTH.key,
        icon="mdi:calendar-month-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2,
    ),
]
CHANGE_SENSOR_STUBS: Final = [
    ExtSensorEntityDescription(
        tag=Tag.CHANGEDAYAMT,
        key=Tag.CHANGEDAYAMT.key,
        icon="mdi:calendar-today-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2,
    ),
    ExtSensorEntityDescription(
        tag=Tag.CHANGEDAYPRC,
        key=Tag.CHANGEDAYPRC.key,
        icon="mdi:calendar-today-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=2,
    ),
    ExtSensorEntityDescription(
        tag=Tag.CHANGEMONTHAMT,
        key=Tag.CHANGEMONTHAMT.key,
        icon="mdi:calendar-month-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2,
    ),
    ExtSensorEntityDescription(
        tag=Tag.CHANGEMONTHPRC,
        key=Tag.CHANGEMONTHPRC.key,
        icon="mdi:calendar-month-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=2,
    ),
]

PORTFOLIO_SENSORS_STUB: Final =[
    ExtSensorEntityDescription(
        tag=Tag.TOTAL_INVESTMENT,
        key=Tag.TOTAL_INVESTMENT.key,
        icon="mdi:cash-multiple",
        #device_class = SensorDeviceClass.MONETARY,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    ),
    ExtSensorEntityDescription(
        tag=Tag.TOTAL_VALUE,
        key=Tag.TOTAL_VALUE.key,
        icon="mdi:briefcase",
        #device_class = SensorDeviceClass.MONETARY,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    ),
    ExtSensorEntityDescription(
        tag=Tag.TOTAL_CHANGE,
        key=Tag.TOTAL_CHANGE.key,
        icon="mdi:chart-line",
        #device_class = SensorDeviceClass.MONETARY,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        suggested_display_precision=2
    ),
    ExtSensorEntityDescription(
        tag=Tag.TOTAL_RETURN,
        key=Tag.TOTAL_RETURN.key,
        icon="mdi:percent-box-outline",
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=2
    )
]

USE_NEW_FRIENDLY_NAME = AwesomeVersion(HA_VERSION) >= AwesomeVersion("2026.2.0")

_LOGGER = logging.getLogger(__name__)
#_LOGGER.debug(f"HA Version: {HA_VERSION}, USE_NEW_FRIENDLY_NAME: {USE_NEW_FRIENDLY_NAME}")


def _get_quantity_from_config(cfg: dict) -> float:
    try:
        qf = float(cfg.get(CONF_QUANTITY, DEFAULT_QUANTITY))
        return qf if qf >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0

def _get_invest_from_config(cfg: dict) -> float:
    try:
        qf = float(cfg.get(CONF_INVEST, DEFAULT_INVEST))
        return qf if qf >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0

def _get_name_from_config(cfg: dict) -> str:
    try:
        a_name = cfg.get(CONF_NAME, None)
        if a_name is not None and len(a_name) > 0:
            return a_name
        else:
            etf_meta_data = cfg.get(CONF_ETFOBJECT, None)
            if etf_meta_data is not None and isinstance(etf_meta_data, dict) and "name" in etf_meta_data:
                return etf_meta_data.get("name", None)

    except (TypeError, ValueError) as ex:
        _LOGGER.debug(f"_get_name_from_config(): caused {type(ex).__name__} - {ex}")

    return None

def _get_price_source_to_use_key_from_config(config_entry: ConfigEntry, key, default) -> str:
    price_source_to_use = config_entry.data.get(key, default)
    if price_source_to_use in PRICE_TO_USE_AS_SOURCE_OPTIONS:
        return price_source_to_use
    return default

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:

    coordinator: JustETFDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    isins: list[str] = config_entry.data.get(CONF_ISINS, [])
    isin_configs: dict[str, dict] = config_entry.data.get(CONF_ISIN_CONFIG, {})
    price_source_to_use_for_starts_key = _get_price_source_to_use_key_from_config(config_entry, key=CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START, default=DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START)
    price_source_to_use_for_position_key = _get_price_source_to_use_key_from_config(config_entry, key=CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE, default=DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE)

    sensors: list[JustETFBaseEntity] = []

    for isin in isins:
        cfg_for_isin = isin_configs.get(isin, {})
        quantity = _get_quantity_from_config(cfg_for_isin)
        invest = _get_invest_from_config(cfg_for_isin)
        display_name = _get_name_from_config(cfg_for_isin) or isin
        _LOGGER.info(f"Creating sensors for isin {isin}, quantity:{quantity}, invested: {invest}")
        for a_stub in SENSOR_STUBS:
            sensors.append(JustETFBaseEntity(isin=isin, isin_name=display_name, coordinator=coordinator, description=a_stub))

        for a_stub in SNAPSHOT_SENSOR_STUBS:
            a_stub = replace(a_stub, price_source_to_use=price_source_to_use_for_starts_key)
            sensors.append(JustETFSnapshotValueEntity(isin=isin, isin_name=display_name, coordinator=coordinator, description=a_stub))

        for a_stub in CHANGE_SENSOR_STUBS:
            a_stub = replace(a_stub, price_source_to_use=price_source_to_use_for_starts_key)
            sensors.append(JustETFDeltaSensorEntity(isin=isin, isin_name=display_name, coordinator=coordinator, description=a_stub))

        if quantity > 0:
            for a_stub in VALUE_SENSOR_STUBS:
                if a_stub.tag == Tag.POSITIONDEVELOPMENT and invest <= 0.0:
                    continue

                a_stub = replace(a_stub,
                                 quantity=quantity,
                                 invest=invest,
                                 price_source_to_use=price_source_to_use_for_position_key,
                                 )
                sensors.append(JustETFBaseEntity(isin=isin, isin_name=display_name, coordinator=coordinator, description=a_stub))

    # should ve create global portfolio sensors... ?!
    if len(isins) > 1:
        # creating overall portfolio sensors...
        for a_stub in PORTFOLIO_SENSORS_STUB:
            sensors.append(JustETFPortfolioEntity(coordinator=coordinator, description=a_stub))

    async_add_entities(sensors, False)


class CustomFriendlyNameEntity(CoordinatorEntity):

    def __init__(self, *args, **kwargs):
        """Initialize and check if method exists."""
        super().__init__(*args, **kwargs)

    # This is a SYNCHRONOUS method that returns a tuple, not async!
    def _Entity__async_calculate_state(self):
        """Calculate state and override ATTR_FRIENDLY_NAME."""

        # First, let the base implementation calculate state (returns a tuple)
        result = super()._Entity__async_calculate_state()

        if not USE_NEW_FRIENDLY_NAME or self._attr_has_entity_name == False:
            return result

        # Check if child class implements _friendly_name_internal
        if not hasattr(self, '_friendly_name_internal') or not callable(getattr(self, '_friendly_name_internal', None)):
            return result

        # Check if we have a cached friendly name that matches what we would generate
        custom_friendly_name = self._friendly_name_internal()

        # Only modify if we have a custom name and it differs from cache
        if custom_friendly_name is not None:
            result_list = list(result)
            attr = None
            attr_index = None

            for i, item in enumerate(result_list):
                if isinstance(item, dict) and ATTR_FRIENDLY_NAME in item:
                    attr = item
                    attr_index = i
                    break

            if attr is None:
                _LOGGER.warning(f"_Entity__async_calculate_state(): Could not find friendly name attribute in state result for {self.entity_id}")
                return result

            # Only modify if we found the attr dict and it differs
            if attr.get(ATTR_FRIENDLY_NAME) != custom_friendly_name:
                attr[ATTR_FRIENDLY_NAME] = custom_friendly_name
                result_list[attr_index] = attr
                return tuple(result_list)

        return result


class JustETFCoreEntity(CustomFriendlyNameEntity, SensorEntity, RestoreEntity):

    _attr_has_entity_name = True

    def __init__(self, coordinator: JustETFDataUpdateCoordinator, description: ExtSensorEntityDescription) -> None:
        super().__init__(coordinator, description)

    async def async_added_to_hass(self):
        """Connect to a dispatcher listening for entity data notifications."""
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))
        await super().async_added_to_hass()

    def _name_internal(self, device_class_name: str | None, platform_translations: dict[str, Any]) -> str | UndefinedType | None:
        # no need to "optional" patch internal (we might like to insert here the base currency later)
        return super()._name_internal(device_class_name, platform_translations)

    def _friendly_name_internal(self) -> str | None:
        """Return the friendly name.
        If has_entity_name is False, this returns self.name
        If has_entity_name is True, this returns device.name + self.name
        """
        name = self.name
        if name is UNDEFINED:
            name = None

        if not self.has_entity_name or not (device_entry := self.device_entry):
            return name

        device_name = device_entry.name_by_user or device_entry.name
        if name is None:
            if hasattr(self, 'use_device_name') and self.use_device_name:
                return device_name
            else:
                _LOGGER.warning(f"_friendly_name_internal(): Missing attribute 'use_device_name' for {self.tag.key} - probably translation is missing")
                return self.tag.key

        # check if there is a user has specified entity name (overwritten)
        if registry_entry := self.registry_entry:
            if registry_entry.has_entity_name and registry_entry.name is not None:
                name = registry_entry.name

        # we overwrite the default impl here and just return our 'name'
        # return f"{device_name} {name}" if device_name else name
        if device_entry.name_by_user is not None:
            return f"{device_entry.name_by_user} {name}" if device_name else name
        else:
            return name


class JustETFPortfolioEntity(JustETFCoreEntity):

    def __init__(self, coordinator: JustETFDataUpdateCoordinator, description: ExtSensorEntityDescription) -> None:
        super().__init__(coordinator, description)

        # this is our MAIN identifier...
        self.tag = description.tag

        if hasattr(description, "translation_key") and description.translation_key is not None:
            self._attr_translation_key = description.translation_key.lower()
        else:
            self._attr_translation_key = description.key.lower()

        self.entity_description: ExtSensorEntityDescription = description
        self.coordinator = coordinator
        self.entity_id = f"{Platform.SENSOR}.jetf_portfolio_{camel_to_snake(description.key)}".lower()

    @property
    def available(self):
        """Return True if the entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.coordinator._config_entry.entry_id)},
            "name": "ETF Portfolio",
            "manufacturer": MANUFACTURER
        }

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{DOMAIN}.jetfuid_portfolio_{camel_to_snake(self.entity_description.key)}".lower()

    @property
    def native_value(self):
        try:
            if hasattr(self.tag, "attribute"):
                return getattr(self.coordinator, self.tag.attribute)

        except BaseException as ex:
            _LOGGER.info(f"JustETFPortfolioEntity:native_value(): Error fetching native value for {self.tag.key}: {type(ex).__name__} - {ex}")

        return None


class JustETFBaseEntity(JustETFCoreEntity):

    def __init__(self, isin:str, isin_name:str, coordinator: JustETFDataUpdateCoordinator, description: ExtSensorEntityDescription) -> None:
        super().__init__(coordinator, description)

        # this is our MAIN identifier...
        self.tag = description.tag
        self.isin = isin
        self._isin_name = isin_name

        if hasattr(description, "translation_key") and description.translation_key is not None:
            self._attr_translation_key = description.translation_key.lower()
        else:
            self._attr_translation_key = description.key.lower()

        self.entity_description: ExtSensorEntityDescription = description
        self.coordinator = coordinator
        self.entity_id = f"{Platform.SENSOR}.jetf_{self.isin}_{camel_to_snake(description.key)}".lower()

    @property
    def available(self):
        """Return True if the entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None and self.isin in self.coordinator.data

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.isin)},
            "name": self._isin_name or self.isin,
            "manufacturer": MANUFACTURER,
            "model": self.isin
        }

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{DOMAIN}.jetfuid_{self.entity_id.split('.')[1]}".lower()

    @property
    def native_value(self):
        try:
            if self.coordinator.data is not None:
                data = self.coordinator.data.get(self.isin, {})
                if self.tag.keys is not None:
                    key1 = self.tag.keys[0]
                    key2 = self.tag.keys[1]
                    return data.get(key1, {}).get(key2, None)
                else:
                    if self.tag == Tag.POSITIONVALUE or self.tag == Tag.POSITIONDEVELOPMENT:
                        val = data.get(self.entity_description.price_source_to_use, None)

                    elif self.tag in (Tag.CHANGEDAYPOSITIONVALUE, Tag.CHANGEMONTHPOSITIONVALUE):
                        # we need the DAY/MONTH change amount value (to be able to calculate the position value)
                        if self.tag == Tag.CHANGEDAYPOSITIONVALUE:
                            a_entity_id = f"{Platform.SENSOR}.jetf_{self.isin}_{camel_to_snake(Tag.CHANGEDAYAMT.key)}".lower()
                        else:
                            a_entity_id = f"{Platform.SENSOR}.jetf_{self.isin}_{camel_to_snake(Tag.CHANGEMONTHAMT.key)}".lower()

                        price_change_amount_state = self.hass.states.get(a_entity_id)
                        if price_change_amount_state is None or price_change_amount_state.state in INVALID_STATES:
                            return None
                        try:
                            val = float(price_change_amount_state.state)
                        except (TypeError, ValueError):
                            return None
                        #_LOGGER.debug(f"Retrieved price change amount for {self.tag.key} with isin {self.isin}: {val}")
                    else:
                        val = data.get(self.tag.key, None)

                    if val is not None and self.entity_description.quantity is not None:
                        val = float(val) * self.entity_description.quantity
                        if self.tag == Tag.POSITIONDEVELOPMENT and self.entity_description.invest is not None and self.entity_description.invest > 0:
                            val = val - self.entity_description.invest

                    return val

        except BaseException as ex:
            _LOGGER.info(f"native_value(): Error fetching native value for {self.tag.key} with isin {self.isin}: {type(ex).__name__} - {ex}")

        return None

    @property
    def icon(self) -> str | None:
        if self.tag in (Tag.DTDPRC, Tag.DTDAMT, Tag.DTDDEC):
            if self.coordinator.data is not None:
                v = self.coordinator.data.get(self.isin, {}).get(self.tag.key, None)
                if v is None:
                    return "mdi:trending-neutral"
                if v > 0:
                    return "mdi:trending-up"
                if v < 0:
                    return "mdi:trending-down"

            return "mdi:trending-neutral"
        else:
            return super().icon


class JustETFSnapshotValueEntity(JustETFBaseEntity):
    """Stores bid snapshots for UTC 00:00 daily/monthly periods and restores on restart."""

    def __init__(
        self,
        isin: str,
        isin_name: str,
        coordinator: JustETFDataUpdateCoordinator,
        description: ExtSensorEntityDescription,
    ) -> None:
        super().__init__(isin=isin, isin_name=isin_name, coordinator=coordinator, description=description)
        if description.tag == Tag.STARTPRICEMONTH:
            self._monthly = True
        else:
            self._monthly = False

        self._snapshot_value: float | None = None
        self._snapshot_period_id: str | None = None
        self._snapshot_captured_at: str | None = None
        self._snapshot_update_task: asyncio.Task | None = None

        if hasattr(description, "price_source_to_use") and description.price_source_to_use is not None:
            self._price_source_entity_id = f"{Platform.SENSOR}.jetf_{self.isin}_{description.price_source_to_use}".lower()
            self._period_id_key = f"{description.price_source_to_use}"
        else:
            self._price_source_entity_id = f"{Platform.SENSOR}.jetf_{self.isin}_{Tag.BID.key}".lower()
            self._period_id_key = f"{Tag.BID.key}"


    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()

        if last_state is not None:
            if last_state.state not in INVALID_STATES:
                try:
                    self._snapshot_value = float(last_state.state)
                except (TypeError, ValueError):
                    self._snapshot_value = None

            if last_state.attributes is not None:
                self._snapshot_period_id = last_state.attributes.get(SNAPSHOT_ATTR_PERIOD_ID)
                self._snapshot_captured_at = last_state.attributes.get(SNAPSHOT_ATTR_CAPTURED_AT)

        await self._async_update_snapshot_from_history_if_needed()

    @property
    def available(self):
        return self._snapshot_value is not None or super().available

    @property
    def native_value(self):
        return self._snapshot_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._snapshot_period_id is not None:
            attrs[SNAPSHOT_ATTR_PERIOD_ID] = self._snapshot_period_id
        if self._snapshot_captured_at is not None:
            attrs[SNAPSHOT_ATTR_CAPTURED_AT] = self._snapshot_captured_at
        return attrs

    def _handle_coordinator_update(self) -> None:
        self._request_snapshot_update_if_needed()
        super()._handle_coordinator_update()

    def _request_snapshot_update_if_needed(self) -> None:
        if not self._snapshot_needs_update():
            return

        if self._snapshot_update_task is not None and not self._snapshot_update_task.done():
            return

        self._snapshot_update_task = self.hass.async_create_task(
            self._async_update_snapshot_from_history_if_needed()
        )

    def _snapshot_needs_update(self) -> bool:
        now_utc = datetime.now(timezone.utc)
        target = self._target_period_for_now(now_utc)
        if target is None:
            return False

        period_id, period_start_utc = target
        return now_utc > period_start_utc and (
            self._snapshot_period_id != period_id or self._snapshot_value is None
        )

    async def _async_update_snapshot_from_history_if_needed(self) -> None:
        now_utc = datetime.now(timezone.utc)
        target = self._target_period_for_now(now_utc)
        if target is None:
            return

        period_id, period_start_utc = target
        if self._snapshot_period_id == period_id and self._snapshot_value is not None:
            return

        if now_utc <= period_start_utc:
            return

        recorder = get_instance(self.hass)
        history_start = period_start_utc - SNAPSHOT_HISTORY_LOOKBACK
        _LOGGER.debug(f"_async_update_snapshot_from_history_if_needed(): backfill for {self.entity_id} ({period_id}) for period-ts: {period_start_utc} history_lookback: {history_start}")

        try:
            history = await recorder.async_add_executor_job(
                state_changes_during_period,
                self.hass,
                history_start,
                now_utc,
                self._price_source_entity_id,
                True,
                False,
            )
        except BaseException as ex:
            _LOGGER.debug(f"_async_update_snapshot_from_history_if_needed(): backfill failed for {self.entity_id} ({period_id}): {type(ex).__name__} - {ex}")
            return

        states = []
        if isinstance(history, dict):
            states = history.get(self._price_source_entity_id, []) or []
        elif isinstance(history, list):
            states = history

        selected_state = None
        selected_distance = None
        for a_state in states:
            if a_state.state in INVALID_STATES:
                continue

            changed = a_state.last_changed
            if changed is None:
                continue
            changed_utc = changed.astimezone(timezone.utc)
            distance = abs((changed_utc - period_start_utc).total_seconds())

            if selected_distance is None or distance < selected_distance:
                selected_state = a_state
                selected_distance = distance

        if selected_state is None:
            return

        try:
            a_value = float(selected_state.state)
        except (TypeError, ValueError):
            return

        changed = selected_state.last_changed
        if changed is None:
            changed = period_start_utc
        changed_utc = changed.astimezone(timezone.utc)
        self._snapshot_value = a_value
        self._snapshot_period_id = period_id
        self._snapshot_captured_at = changed_utc.isoformat()

        if self.hass is not None:
            self.async_write_ha_state()

    def _target_period_for_now(self, now_utc: datetime) -> tuple[str, datetime] | None:
        if self._monthly:
            target_year = now_utc.year
            target_month = now_utc.month
            period_id = f"spid.{self._period_id_key}-{target_year:04d}-{target_month:02d}"
            period_start = datetime(target_year, target_month, 1, 0, 0, tzinfo=timezone.utc)
            return period_id, period_start
        else:
            target_date = now_utc.date()
            period_id = f"spid.{self._period_id_key}-{target_date.isoformat()}"
            period_start = datetime.combine(target_date, time(0, 0), tzinfo=timezone.utc)
            return period_id, period_start


class JustETFDeltaSensorEntity(JustETFBaseEntity):

    def __init__(
        self,
        isin: str,
        isin_name: str,
        coordinator: JustETFDataUpdateCoordinator,
        description: ExtSensorEntityDescription,
    ) -> None:
        super().__init__(isin=isin, isin_name=isin_name, coordinator=coordinator, description=description)
        if description.price_source_to_use is not None:
            self._price_source_key = description.price_source_to_use
        else:
            self._price_source_key = Tag.BID.key

        if description.tag in (Tag.CHANGEDAYAMT, Tag.CHANGEDAYPRC):
            self._start_entity_id = f"{Platform.SENSOR}.jetf_{isin}_{camel_to_snake(Tag.STARTPRICEDAY.key)}".lower()
            self._is_percentage = description.tag == Tag.CHANGEDAYPRC
        else:
            self._start_entity_id = f"{Platform.SENSOR}.jetf_{isin}_{camel_to_snake(Tag.STARTPRICEMONTH.key)}".lower()
            self._is_percentage = description.tag == Tag.CHANGEMONTHPRC

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None

        current_price_value = self.coordinator.data.get(self.isin, {}).get(self._price_source_key)
        if current_price_value is None:
            return None

        baseline_price_state = self.hass.states.get(self._start_entity_id)
        if baseline_price_state is None or baseline_price_state.state in INVALID_STATES:
            return None

        try:
            current_value_f = float(current_price_value)
            baseline_value_f = float(baseline_price_state.state)
        except (TypeError, ValueError):
            return None

        delta = current_value_f - baseline_value_f
        if not self._is_percentage:
            return delta

        if baseline_value_f == 0:
            return None

        return (delta / baseline_value_f) * 100

    @property
    def icon(self) -> str | None:
        v = self.native_value
        if v is None:
            return "mdi:trending-neutral"
        if v > 0:
            return "mdi:trending-up"
        if v < 0:
            return "mdi:trending-down"
        return "mdi:trending-neutral"
