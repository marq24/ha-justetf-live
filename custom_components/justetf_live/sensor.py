from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.justetf_live.pyjustetflive_ha.keys import Tag
from . import JustETFDataUpdateCoordinator
from .const import (
    DOMAIN,
    MANUFACTURER,
    CONF_ISINS,
    CONF_ISIN_CONFIG,
    CONF_NAME,
    CONF_QUANTITY,
    DEFAULT_QUANTITY
)

_LOGGER = logging.getLogger(__name__)


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _get_quantity_from_config(cfg: dict) -> float:
    try:
        qf = float(cfg.get(CONF_QUANTITY, DEFAULT_QUANTITY))
        return qf if qf >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:

    coordinator: JustETFDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    isins: list[str] = entry.data.get(CONF_ISINS, [])
    isin_config: dict[str, dict] = entry.data.get(CONF_ISIN_CONFIG, {})

    sensors: list[SensorEntity] = []

    for isin in isins:
        cfg = isin_config.get(isin, {})
        custom_name = cfg.get(CONF_NAME, "")
        quantity = _get_quantity_from_config(cfg)
        display_name = custom_name or (coordinator.data or {}).get(isin, {}).get("name") or isin
        monetary_unit = "€"

        sensors.extend([
            INGStockValueSensor(
                coordinator, entry, isin, display_name,
                key="price", unique_suffix="price",
                device_class=SensorDeviceClass.MONETARY, unit=monetary_unit, precision=2,
            ),
            INGStockValueSensor(
                coordinator, entry, isin, display_name,
                key="change_percent", unique_suffix="change_percent",
                device_class=None, unit="%", precision=2,
            ),
            INGStockValueSensor(
                coordinator, entry, isin, display_name,
                key="change_absolute", unique_suffix="change_absolute",
                device_class=SensorDeviceClass.MONETARY, unit=monetary_unit, precision=3,
            ),
            INGStockLastUpdateSensor(coordinator, entry, isin, display_name),
        ])

        if quantity > 0:
            sensors.append(
                INGStockPositionValueSensor(
                    coordinator=coordinator, entry=entry, isin=isin,
                    display_name=display_name,
                    quantity=quantity, unit=monetary_unit,
                )
            )

        sensors.extend([
            INGStockValueSensor(
                coordinator, entry, isin, display_name,
                key="dividend_yield", unique_suffix="dividend_yield",
                device_class=None, unit="%", precision=4,
            ),
            INGStockValueSensor(
                coordinator, entry, isin, display_name,
                key="dividend_per_share", unique_suffix="dividend_per_share",
                device_class=SensorDeviceClass.MONETARY, unit=monetary_unit, precision=3,
            ),
            INGStockValueSensor(
                coordinator, entry, isin, display_name,
                key="price_earnings_ratio", unique_suffix="price_earnings_ratio",
                device_class=None, unit=None, precision=2,
            ),
            INGStockValueSensor(
                coordinator, entry, isin, display_name,
                key="market_capitalization", unique_suffix="market_capitalization",
                device_class=None, unit=None, precision=0,
            ),
            INGStockTextSensor(
                coordinator, entry, isin, display_name,
                key="market_cap_currency", unique_suffix="market_cap_currency",
            ),
            INGStockValueSensor(
                coordinator, entry, isin, display_name,
                key="52w_low", unique_suffix="week52_low",
                device_class=SensorDeviceClass.MONETARY, unit=monetary_unit, precision=3,
            ),
            INGStockValueSensor(
                coordinator, entry, isin, display_name,
                key="52w_high", unique_suffix="week52_high",
                device_class=SensorDeviceClass.MONETARY, unit=monetary_unit, precision=3,
            ),
        ])

    async_add_entities(sensors, False)


class INGStockBaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: JustETFDataUpdateCoordinator,
        entry: ConfigEntry,
        isin: str,
        display_name: str,
    ):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.entry = entry
        self.isin = isin
        self._display_name = display_name

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and len(self.coordinator.data.get(self.isin, {})) > 0
        )

    @property
    def device_info(self):
        d = self.coordinator.data.get(self.isin, {})
        return {
            "identifiers": {(DOMAIN, self.isin)},
            "name": self._display_name or d.get("name") or self.isin,
            "manufacturer": MANUFACTURER,
            "model": self.isin
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))
        await super().async_added_to_hass()


class INGStockValueSensor(INGStockBaseSensor):
    def __init__(
        self,
        coordinator: JustETFDataUpdateCoordinator,
        entry: ConfigEntry,
        isin: str,
        display_name: str,
        key: str,
        unique_suffix: str,
        device_class: SensorDeviceClass | None,
        unit: str | None,
        precision: int | None,
    ):
        super().__init__(coordinator, entry, isin, display_name)
        self.key = key
        self._precision = precision

        self._attr_translation_key = unique_suffix
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = f"{DOMAIN}_{self.isin}_{unique_suffix}"

        if device_class == SensorDeviceClass.MONETARY:
            self._attr_state_class = None
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def icon(self) -> str | None:
        d = self.coordinator.data.get(self.isin, {})

        if self.key == "price":
            return "mdi:chart-line"

        if self.key in ("change_percent", "change_absolute"):
            v = _safe_float(d.get(self.key))
            if v is None:
                return "mdi:trending-neutral"
            if v > 0:
                return "mdi:trending-up"
            if v < 0:
                return "mdi:trending-down"
            return "mdi:trending-neutral"

        if self.key == "dividend_yield":
            return "mdi:cash-percent"
        if self.key == "dividend_per_share":
            return "mdi:cash"
        if self.key == "price_earnings_ratio":
            return "mdi:calculator-variant"
        if self.key == "market_capitalization":
            return "mdi:bank"
        if self.key in ("52w_low", "52w_high"):
            return "mdi:arrow-expand-vertical"

        return "mdi:finance"

    # @property
    # def extra_state_attributes(self):
    #     d = self.coordinator.data.get(self.isin, {})
    #     # Read current quantity from entry data (may have changed via reconfigure)
    #     cfg = self.entry.data.get(CONF_ISIN_CONFIG, {}).get(self.isin, {})
    #     quantity = _get_quantity_from_config(cfg)
    #
    #     return {
    #         "name": d.get("name"),
    #         "isin": d.get("isin"),
    #         "currency": d.get("currency"),
    #         "change_percent": d.get("change_percent"),
    #         "change_absolute": d.get("change_absolute"),
    #         "exchange": d.get("exchange"),
    #         "last_update": d.get("last_update"),
    #         "dividend_yield": d.get("dividend_yield"),
    #         "dividend_per_share": d.get("dividend_per_share"),
    #         "price_earnings_ratio": d.get("price_earnings_ratio"),
    #         "market_capitalization": d.get("market_capitalization"),
    #         "market_cap_currency": d.get("market_cap_currency"),
    #         "52w_low": d.get("52w_low"),
    #         "52w_high": d.get("52w_high"),
    #         "quantity": quantity,
    #     }

    @property
    def native_value(self):
        value = self.coordinator.data.get(self.isin, {}).get(self.key)
        if value is None:
            return None
        if self._precision is not None:
            f = _safe_float(value)
            if f is not None:
                return round(f, self._precision)
        return value


class INGStockTextSensor(INGStockBaseSensor):
    """Text sensor for values like market_cap_currency to keep entity stable."""

    _attr_device_class = None
    _attr_state_class = None

    def __init__(
        self,
        coordinator: JustETFDataUpdateCoordinator,
        entry: ConfigEntry,
        isin: str,
        display_name: str,
        key: str,
        unique_suffix: str,
    ):
        super().__init__(coordinator, entry, isin, display_name)
        self.key = key
        self._attr_translation_key = unique_suffix
        self._attr_unique_id = f"{DOMAIN}_{self.isin}_{unique_suffix}"

    @property
    def icon(self) -> str | None:
        return "mdi:currency-sign"

    # @property
    # def extra_state_attributes(self):
    #     d = self.coordinator.data.get(self.isin, {})
    #     return {
    #         "name": d.get("name"),
    #         "isin": d.get("isin"),
    #         "exchange": d.get("exchange"),
    #         "currency": d.get("currency"),
    #         "last_update": d.get("last_update")
    #     }

    @property
    def native_value(self):
        v = self.coordinator.data.get(self.isin, {}).get(self.key)
        return str(v) if v is not None else None


class INGStockPositionValueSensor(INGStockBaseSensor):
    """Positionswert (price * quantity)."""

    def __init__(
        self,
        coordinator: JustETFDataUpdateCoordinator,
        entry: ConfigEntry,
        isin: str,
        display_name: str,
        quantity: float,
        unit: str,
    ):
        super().__init__(coordinator, entry, isin, display_name)
        self._quantity = quantity
        self._attr_translation_key = "position_value"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = None
        self._attr_unique_id = f"{DOMAIN}_{self.isin}_position_value"

    @property
    def icon(self) -> str | None:
        return "mdi:briefcase"

    # @property
    # def extra_state_attributes(self):
    #     d = self.coordinator.data.get(self.isin, {})
    #     cfg = self.entry.data.get(CONF_ISIN_CONFIG, {}).get(self.isin, {})
    #     quantity = _get_quantity_from_config(cfg)
    #     return {
    #         "name": d.get("name"),
    #         "isin": d.get("isin"),
    #         "exchange": d.get("exchange"),
    #         "currency": d.get("currency"),
    #         "last_update": d.get("last_update"),
    #         "quantity": quantity,
    #         "unit_price": d.get("price"),
    #     }

    @property
    def native_value(self):
        d = self.coordinator.data.get(self.isin, {})
        price = _safe_float(d.get("price"))
        cfg = self.entry.data.get(CONF_ISIN_CONFIG, {}).get(self.isin, {})
        quantity = _get_quantity_from_config(cfg)
        if price is None or quantity <= 0:
            return None
        return round(price * quantity, 2)


class INGStockLastUpdateSensor(INGStockBaseSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_update"
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: JustETFDataUpdateCoordinator,
        entry: ConfigEntry,
        isin: str,
        display_name: str,
    ):
        super().__init__(coordinator, entry, isin, display_name)
        self._attr_unique_id = f"{DOMAIN}_{self.isin}_last_update"

    @property
    def native_value(self):
        return self.coordinator.data.get(self.isin, {}).get(Tag.TIMESTAMP.key, None)

