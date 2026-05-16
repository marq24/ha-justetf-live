import logging
from dataclasses import dataclass
from typing import Final, Any

from awesomeversion import AwesomeVersion
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
    DEFAULT_QUANTITY, CONF_ETFOBJECT
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtSensorEntityDescription(SensorEntityDescription):
    tag: Tag | None = None
    quantity: float | None = None

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
        native_unit_of_measurement="€"
    ),
    ExtSensorEntityDescription(
        tag=Tag.BID,
        key=Tag.BID.key,
        icon="mdi:briefcase-minus",
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        entity_registry_enabled_default=False
    ),
    ExtSensorEntityDescription(
        tag=Tag.ASK,
        key=Tag.ASK.key,
        icon="mdi:briefcase-plus",
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€",
        entity_registry_enabled_default=False
    ),
    ExtSensorEntityDescription(
        tag=Tag.DTDPRC,
        key=Tag.DTDPRC.key,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE
    ),
    ExtSensorEntityDescription(
        tag=Tag.DTDAMT,
        key=Tag.DTDAMT.key,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€"
    ),
    ExtSensorEntityDescription(
        tag=Tag.QUOTE52WEEKHIGH,
        key=Tag.QUOTE52WEEKHIGH.key,
        icon="mdi:arrow-expand-vertical",
        #device_class = SensorDeviceClass.MONETARY,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€"
    ),
    ExtSensorEntityDescription(
        tag=Tag.QUOTE52WEEKLOW,
        key=Tag.QUOTE52WEEKLOW.key,
        icon="mdi:arrow-expand-vertical",
        #device_class = SensorDeviceClass.MONETARY,
        state_class = SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="€"
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
        _LOGGER.debug(f"_get_name_from_config() caused: {type(ex).__name__} - {ex}")

    return None


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:

    coordinator: JustETFDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    isins: list[str] = config_entry.data.get(CONF_ISINS, [])
    isin_configs: dict[str, dict] = config_entry.data.get(CONF_ISIN_CONFIG, {})

    sensors: list[JustETFBaseEntity] = []

    for isin in isins:
        cfg_for_isin = isin_configs.get(isin, {})
        quantity = _get_quantity_from_config(cfg_for_isin)
        display_name = _get_name_from_config(cfg_for_isin) or isin

        for a_stub in SENSOR_STUBS:
            sensors.append(JustETFBaseEntity(isin=isin, isin_name=display_name, coordinator=coordinator, description=a_stub))

        if quantity > 0:
            a_stub = ExtSensorEntityDescription(
                tag=Tag.POSITIONVALUE,
                key=Tag.POSITIONVALUE.key,
                quantity=quantity,
                icon="mdi:briefcase",
                suggested_display_precision=2,
                device_class=SensorDeviceClass.MONETARY,
                state_class = SensorStateClass.TOTAL,
                native_unit_of_measurement="€",
            )
            sensors.append(JustETFBaseEntity(isin=isin, isin_name=display_name, coordinator=coordinator, description=a_stub))

    async_add_entities(sensors, False)


class CustomFriendlyNameEntity(CoordinatorEntity):

    def __init__(self, *args, **kwargs):
        """Initialize and check if method exists."""
        super().__init__(*args, **kwargs)

    # This is a SYNCHRONOUS method that returns a tuple, not async!
    def _Entity__async_calculate_state(self):
        """Calculate state and override ATTR_FRIENDLY_NAME."""

        # First let the base implementation calculate state (returns a tuple)
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
                _LOGGER.warning(f"Could not find friendly name attribute in state result for {self.entity_id}")
                return result

            # Only modify if we found the attr dict and it differs
            if attr.get(ATTR_FRIENDLY_NAME) != custom_friendly_name:
                attr[ATTR_FRIENDLY_NAME] = custom_friendly_name
                result_list[attr_index] = attr
                return tuple(result_list)

        return result


class JustETFBaseEntity(CustomFriendlyNameEntity, SensorEntity, RestoreEntity):

    _attr_has_entity_name = True

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

    async def async_added_to_hass(self):
        """Connect to dispatcher listening for entity data notifications."""
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))
        await super().async_added_to_hass()

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self.isin)},
            "name": self._isin_name or self.isin,
            "manufacturer": MANUFACTURER,
            "model": self.isin
        }

    @property
    def available(self):
        """Return True if the entity is available."""
        return self.coordinator.last_update_success and self.isin in self.coordinator.data

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{DOMAIN}.jetfuid_{self.entity_id.split('.')[1]}".lower()

    @property
    def native_value(self):
        try:
            data = self.coordinator.data.get(self.isin, {})
            if self.tag.keys is not None:
                key1 = self.tag.keys[0]
                key2 = self.tag.keys[1]
                return data.get(key1, {}).get(key2, None)
            else:
                if self.tag == Tag.POSITIONVALUE:
                    # to calculate position value, we need the mid-price...
                    val = data.get(Tag.MID.key, None)
                else:
                    val = data.get(self.tag.key, None)

                if val is not None and self.entity_description.quantity is not None:
                    val = float(val) * self.entity_description.quantity

                return val

        except BaseException as ex:
            _LOGGER.info(f"Error fetching native value for {self.tag.key} with isin {self.isin}: {type(ex).__name__} - {ex}")

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
                _LOGGER.warning(f"Missing attribute 'use_device_name' for {self.tag.key} - probably translation is missing")
                return self.tag.key

        # check if there is a user specified entity name (overwritten)
        if registry_entry := self.registry_entry:
            if registry_entry.has_entity_name and registry_entry.name is not None:
                name = registry_entry.name

        # we overwrite the default impl here and just return our 'name'
        # return f"{device_name} {name}" if device_name else name
        if device_entry.name_by_user is not None:
            return f"{device_entry.name_by_user} {name}" if device_name else name
        else:
            return name





# class INGStockBaseSensor(CoordinatorEntity, SensorEntity):
#     _attr_has_entity_name = True
#
#     def __init__(
#         self,
#         coordinator: JustETFDataUpdateCoordinator,
#         entry: ConfigEntry,
#         isin: str,
#         display_name: str,
#     ):
#         super().__init__(coordinator)
#         self.coordinator = coordinator
#         self.entry = entry
#         self.isin = isin
#         self._display_name = display_name
#
#     @property
#     def available(self) -> bool:
#         return (
#             self.coordinator.last_update_success
#             and len(self.coordinator.data.get(self.isin, {})) > 0
#         )
#
#     @property
#     def device_info(self):
#         d = self.coordinator.data.get(self.isin, {})
#         return {
#             "identifiers": {(DOMAIN, self.isin)},
#             "name": self._display_name or d.get("name") or self.isin,
#             "manufacturer": MANUFACTURER,
#             "model": self.isin
#         }
#
#     async def async_added_to_hass(self) -> None:
#         self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))
#         await super().async_added_to_hass()
#
#
# class INGStockValueSensor(INGStockBaseSensor):
#     def __init__(
#         self,
#         coordinator: JustETFDataUpdateCoordinator,
#         entry: ConfigEntry,
#         isin: str,
#         display_name: str,
#         key: str,
#         unique_suffix: str,
#         device_class: SensorDeviceClass | None,
#         unit: str | None,
#         precision: int | None,
#     ):
#         super().__init__(coordinator, entry, isin, display_name)
#         self.key = key
#         self._precision = precision
#
#         self._attr_translation_key = unique_suffix
#         self._attr_device_class = device_class
#         self._attr_native_unit_of_measurement = unit
#         self._attr_unique_id = f"{DOMAIN}_{self.isin}_{unique_suffix}"
#
#         if device_class == SensorDeviceClass.MONETARY:
#             self._attr_state_class = None
#         else:
#             self._attr_state_class = SensorStateClass.MEASUREMENT
#
#     @property
#     def icon(self) -> str | None:
#         d = self.coordinator.data.get(self.isin, {})
#
#         if self.key == "price":
#             return "mdi:chart-line"
#
#         if self.key in ("change_percent", "change_absolute"):
#             v = None#_safe_float(d.get(self.key))
#             if v is None:
#                 return "mdi:trending-neutral"
#             if v > 0:
#                 return "mdi:trending-up"
#             if v < 0:
#                 return "mdi:trending-down"
#             return "mdi:trending-neutral"
#
#         if self.key == "dividend_yield":
#             return "mdi:cash-percent"
#         if self.key == "dividend_per_share":
#             return "mdi:cash"
#         if self.key == "price_earnings_ratio":
#             return "mdi:calculator-variant"
#         if self.key == "market_capitalization":
#             return "mdi:bank"
#         if self.key in ("52w_low", "52w_high"):
#             return "mdi:arrow-expand-vertical"
#
#         return "mdi:finance"
#
#     # @property
#     # def extra_state_attributes(self):
#     #     d = self.coordinator.data.get(self.isin, {})
#     #     # Read current quantity from entry data (may have changed via reconfigure)
#     #     cfg = self.entry.data.get(CONF_ISIN_CONFIG, {}).get(self.isin, {})
#     #     quantity = _get_quantity_from_config(cfg)
#     #
#     #     return {
#     #         "name": d.get("name"),
#     #         "isin": d.get("isin"),
#     #         "currency": d.get("currency"),
#     #         "change_percent": d.get("change_percent"),
#     #         "change_absolute": d.get("change_absolute"),
#     #         "exchange": d.get("exchange"),
#     #         "last_update": d.get("last_update"),
#     #         "dividend_yield": d.get("dividend_yield"),
#     #         "dividend_per_share": d.get("dividend_per_share"),
#     #         "price_earnings_ratio": d.get("price_earnings_ratio"),
#     #         "market_capitalization": d.get("market_capitalization"),
#     #         "market_cap_currency": d.get("market_cap_currency"),
#     #         "52w_low": d.get("52w_low"),
#     #         "52w_high": d.get("52w_high"),
#     #         "quantity": quantity,
#     #     }
#
#     @property
#     def native_value(self):
#         value = self.coordinator.data.get(self.isin, {}).get(self.key)
#         if value is None:
#             return None
#         if self._precision is not None:
#             f = None#_safe_float(value)
#             if f is not None:
#                 return round(f, self._precision)
#         return value
#
#
# class INGStockTextSensor(INGStockBaseSensor):
#     """Text sensor for values like market_cap_currency to keep entity stable."""
#
#     _attr_device_class = None
#     _attr_state_class = None
#
#     def __init__(
#         self,
#         coordinator: JustETFDataUpdateCoordinator,
#         entry: ConfigEntry,
#         isin: str,
#         display_name: str,
#         key: str,
#         unique_suffix: str,
#     ):
#         super().__init__(coordinator, entry, isin, display_name)
#         self.key = key
#         self._attr_translation_key = unique_suffix
#         self._attr_unique_id = f"{DOMAIN}_{self.isin}_{unique_suffix}"
#
#     @property
#     def icon(self) -> str | None:
#         return "mdi:currency-sign"
#
#     # @property
#     # def extra_state_attributes(self):
#     #     d = self.coordinator.data.get(self.isin, {})
#     #     return {
#     #         "name": d.get("name"),
#     #         "isin": d.get("isin"),
#     #         "exchange": d.get("exchange"),
#     #         "currency": d.get("currency"),
#     #         "last_update": d.get("last_update")
#     #     }
#
#     @property
#     def native_value(self):
#         v = self.coordinator.data.get(self.isin, {}).get(self.key)
#         return str(v) if v is not None else None
#
#
# class INGStockPositionValueSensor(INGStockBaseSensor):
#     """Positionswert (price * quantity)."""
#
#     def __init__(
#         self,
#         coordinator: JustETFDataUpdateCoordinator,
#         entry: ConfigEntry,
#         isin: str,
#         display_name: str,
#         quantity: float,
#         unit: str,
#     ):
#         super().__init__(coordinator, entry, isin, display_name)
#         self._quantity = quantity
#         self._attr_translation_key = "position_value"
#         self._attr_device_class = SensorDeviceClass.MONETARY
#         self._attr_native_unit_of_measurement = unit
#         self._attr_state_class = None
#         self._attr_unique_id = f"{DOMAIN}_{self.isin}_position_value"
#
#     @property
#     def icon(self) -> str | None:
#         return "mdi:briefcase"
#
#     # @property
#     # def extra_state_attributes(self):
#     #     d = self.coordinator.data.get(self.isin, {})
#     #     cfg = self.entry.data.get(CONF_ISIN_CONFIG, {}).get(self.isin, {})
#     #     quantity = _get_quantity_from_config(cfg)
#     #     return {
#     #         "name": d.get("name"),
#     #         "isin": d.get("isin"),
#     #         "exchange": d.get("exchange"),
#     #         "currency": d.get("currency"),
#     #         "last_update": d.get("last_update"),
#     #         "quantity": quantity,
#     #         "unit_price": d.get("price"),
#     #     }
#
#     @property
#     def native_value(self):
#         d = self.coordinator.data.get(self.isin, {})
#         price = None#_safe_float(d.get("price"))
#         cfg = self.entry.data.get(CONF_ISIN_CONFIG, {}).get(self.isin, {})
#         quantity = _get_quantity_from_config(cfg)
#         if price is None or quantity <= 0:
#             return None
#         return round(price * quantity, 2)
#
#
# class INGStockLastUpdateSensor(INGStockBaseSensor):
#     _attr_entity_category = EntityCategory.DIAGNOSTIC
#     _attr_device_class = SensorDeviceClass.TIMESTAMP
#     _attr_translation_key = "last_update"
#     _attr_icon = "mdi:clock-outline"
#
#     def __init__(
#         self,
#         coordinator: JustETFDataUpdateCoordinator,
#         entry: ConfigEntry,
#         isin: str,
#         display_name: str,
#     ):
#         super().__init__(coordinator, entry, isin, display_name)
#         self._attr_unique_id = f"{DOMAIN}_{self.isin}_last_update"
#
#     @property
#     def native_value(self):
#         return self.coordinator.data.get(self.isin, {}).get(Tag.TIMESTAMP.key, None)
#
