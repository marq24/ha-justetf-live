import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.translation import async_get_translations

from custom_components.justetf_live.const import (
    DOMAIN,
    CONF_ISIN,
    CONF_ISINS,
    CONF_ISIN_CONFIG,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_QUANTITY,
    CONF_INVEST,
    CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE,
    CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START,
    CONF_ETFOBJECT,
    CONF_SELECTED_ISIN,
    ADD_NEW_ISIN,
    DELETE_ISIN,
    SAVE_AND_CLOSE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_QUANTITY,
    DEFAULT_INVEST,
    DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE,
    DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START,
    PRICE_TO_USE_AS_SOURCE_OPTIONS,
)
from custom_components.justetf_live.pyjustetflive_ha import JustETFBridge
from custom_components.justetf_live.pyjustetflive_ha.keys import Tag

_LOGGER = logging.getLogger(__name__)


async def _async_position_value_price_selector(hass) -> SelectSelector:
    translations = await async_get_translations(
        hass, hass.config.language, "selector", {DOMAIN}
    )

    def translate_option(tag: Tag, fallback: str) -> str:
        return translations.get(
            f"component.{DOMAIN}.selector.position_value_price.options.{tag.key}",
            fallback,
        )

    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=Tag.BID.key, label=translate_option(Tag.BID, "Bid")),
                SelectOptionDict(value=Tag.ASK.key, label=translate_option(Tag.ASK, "Ask")),
                SelectOptionDict(value=Tag.MID.key, label=translate_option(Tag.MID, "Mid")),
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _get_valid_source_value_price(value: Any) -> str:
    if value in PRICE_TO_USE_AS_SOURCE_OPTIONS:
        return value
    return DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._existing_entry: config_entries.ConfigEntry | None = None
        self._editing_isin: str | None = None
        self._is_reconfigure: bool = False

    # ------------------------------------------------------------------
    # STEP: user  (initial add or redirect to select_isin)
    # ------------------------------------------------------------------
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entries = self._async_current_entries()
        if entries:
            # Integration already set up → manage ISINs on existing entry
            self._existing_entry = entries[0]
            if self._is_reconfigure:
                return await self.async_step_select_isin()
            else:
                return await self.async_step_add_isin()

        # First-time setup: ISIN + global scan_interval
        if user_input is not None:
            isin = user_input[CONF_ISIN].strip().upper()
            name = (user_input.get(CONF_NAME) or "").strip()
            scan_interval = int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            quantity = float(user_input.get(CONF_QUANTITY, DEFAULT_QUANTITY))
            invest = float(user_input.get(CONF_INVEST, DEFAULT_INVEST))
            start_value_price = _get_valid_source_value_price(user_input.get(CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START))
            position_value_price = _get_valid_source_value_price(user_input.get(CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE))

            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            is_ok, default_name, etf_obj = await self.verify_isin(isin)
            if is_ok:
                return self.async_create_entry(
                    title="justETF live",
                    data={
                        CONF_SCAN_INTERVAL: scan_interval,
                        CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START: start_value_price,
                        CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE: position_value_price,
                        CONF_ISINS: [isin],
                        CONF_ISIN_CONFIG: {
                            isin: {
                                CONF_NAME: name if len(name) > 0 else default_name,
                                CONF_QUANTITY: quantity,
                                CONF_INVEST: invest,
                                CONF_ETFOBJECT: etf_obj,
                            }
                        },
                    },
                )
            else:
                errors[CONF_ISIN] = "invalid_isin"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ISIN): str,
                vol.Optional(CONF_NAME, default=""): str,
                vol.Required(CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START, default=DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START): await _async_position_value_price_selector(self.hass),
                vol.Required(CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE, default=DEFAULT_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE): await _async_position_value_price_selector(self.hass),
                vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(int, vol.Range(min=1, max=360)),
                vol.Optional(CONF_QUANTITY, default=DEFAULT_QUANTITY): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Optional(CONF_INVEST, default=DEFAULT_INVEST): vol.All(vol.Coerce(float), vol.Range(min=0)),
            }),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # STEP: reconfigure  (entry menu → select_isin)
    # ------------------------------------------------------------------
    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._existing_entry = self._get_reconfigure_entry()
        self._is_reconfigure = True
        return await self.async_step_select_isin()

    # ------------------------------------------------------------------
    # STEP: select_isin  (list existing ISINs + "Add new")
    # ------------------------------------------------------------------
    async def async_step_select_isin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._existing_entry is not None
        entry_data = self._existing_entry.data
        isins: list[str] = list(entry_data.get(CONF_ISINS, []))
        isin_config: dict[str, dict] = entry_data.get(CONF_ISIN_CONFIG, {})

        # Load translated action labels
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "config", {DOMAIN}
        )

        def translate_key(key: str, fallback: str) -> str:
            return translations.get(
                f"component.{DOMAIN}.selector.actions.options.{key}",
                fallback,
            )

        def create_isin_label(isin: str) -> str:
            name = isin_config.get(isin, {}).get(CONF_NAME)
            return f"{isin} – {name}" if name else isin


        edit_label = translate_key("edit_isin", "✏️ edit '{label}'")
        options = [
            SelectOptionDict(value=ADD_NEW_ISIN, label=translate_key("add_new", "➕ Add new ISIN")),
            SelectOptionDict(value=DELETE_ISIN, label=translate_key("delete_isin", "🗑️ Delete ISIN")),
            *[
                SelectOptionDict(
                    value=isin,
                    label=edit_label.replace("{label}", create_isin_label(isin)),
                )
                for isin in isins
            ],
            SelectOptionDict(value=SAVE_AND_CLOSE, label=translate_key("save_close", "💾 Save interval & close")),
        ]

        if user_input is None:
            current_scan = int(entry_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            current_start_value_price = _get_valid_source_value_price(entry_data.get(CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START))
            current_position_value_price = _get_valid_source_value_price(entry_data.get(CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE))
            return self.async_show_form(
                step_id="select_isin",
                data_schema=vol.Schema({
                    vol.Required(CONF_SELECTED_ISIN): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST if len(options) < 15 else SelectSelectorMode.DROPDOWN
                        )),
                    vol.Required(CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START, default=current_start_value_price): await _async_position_value_price_selector(self.hass),
                    vol.Required(CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE, default=current_position_value_price): await _async_position_value_price_selector(self.hass),
                    vol.Required(CONF_SCAN_INTERVAL, default=current_scan): vol.All(int, vol.Range(min=1, max=360)),
                }),
            )

        # Save potentially updated global options (reconfigure only)
        if self._is_reconfigure and CONF_SCAN_INTERVAL in user_input:
            new_scan = int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            new_start_value_price = _get_valid_source_value_price(user_input.get(CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START))
            new_position_value_price = _get_valid_source_value_price(user_input.get(CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE))
            if (
                    new_scan != int(entry_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
                    or new_start_value_price != _get_valid_source_value_price(entry_data.get(CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START))
                    or new_position_value_price != _get_valid_source_value_price(entry_data.get(CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE))
            ):
                new_data = dict(entry_data)
                new_data[CONF_SCAN_INTERVAL] = new_scan
                new_data[CONF_PRICE_TO_USE_AS_SOURCE_FOR_DAY_MONTH_START] = new_start_value_price
                new_data[CONF_PRICE_TO_USE_AS_SOURCE_FOR_POSITION_VALUE] = new_position_value_price

                self.hass.config_entries.async_update_entry(self._existing_entry, data=new_data)

        selected = user_input[CONF_SELECTED_ISIN]

        if selected == SAVE_AND_CLOSE:
            await self.hass.config_entries.async_reload(
                self._existing_entry.entry_id
            )
            return self.async_abort(reason="reconfigured")

        if selected == ADD_NEW_ISIN:
            return await self.async_step_add_isin()

        if selected == DELETE_ISIN:
            return await self.async_step_delete_isin()

        self._editing_isin = selected
        return await self.async_step_edit_isin()

    # ------------------------------------------------------------------
    # STEP: delete_isin
    # ------------------------------------------------------------------
    async def async_step_delete_isin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._existing_entry is not None
        entry_data = self._existing_entry.data
        isins: list[str] = list(entry_data.get(CONF_ISINS, []))
        isin_config: dict[str, dict] = entry_data.get(CONF_ISIN_CONFIG, {})

        options: dict[str, str] = {}
        for isin in isins:
            cfg = isin_config.get(isin, {})
            label = cfg.get(CONF_NAME) or isin
            if label != isin:
                label = f"{isin} – {label}"
            options[isin] = label

        if user_input is None:
            return self.async_show_form(
                step_id="delete_isin",
                data_schema=vol.Schema({
                    vol.Required(CONF_SELECTED_ISIN): vol.In(options),
                }),
            )

        to_delete = user_input[CONF_SELECTED_ISIN]
        device_reg = dr.async_get(self.hass)
        entity_reg = er.async_get(self.hass)
        device = device_reg.async_get_device({(DOMAIN, to_delete)}, set())
        if device is not None:
            for ent in er.async_entries_for_device(
                entity_reg, device.id, include_disabled_entities=True
            ):
                entity_reg.async_remove(ent.entity_id)
            device_reg.async_remove_device(device.id)

        new_data = dict(entry_data)
        new_data[CONF_ISINS] = [i for i in isins if i != to_delete]
        new_data[CONF_ISIN_CONFIG] = dict(isin_config)
        new_data[CONF_ISIN_CONFIG].pop(to_delete, None)

        self.hass.config_entries.async_update_entry(
            self._existing_entry, data=new_data
        )
        await self.hass.config_entries.async_reload(
            self._existing_entry.entry_id
        )
        return self.async_abort(reason="reconfigured")

    # ------------------------------------------------------------------
    # STEP: add_isin
    # ------------------------------------------------------------------
    async def async_step_add_isin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._existing_entry is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            isin = user_input[CONF_ISIN].strip().upper()
            existing_isins = list(self._existing_entry.data.get(CONF_ISINS, []))

            if isin in existing_isins:
                errors[CONF_ISIN] = "isin_already_configured"
            else:
                is_ok, default_name, etf_obj = await self.verify_isin(isin)
                if is_ok:
                    name = (user_input.get(CONF_NAME) or "").strip()
                    quantity = float(user_input.get(CONF_QUANTITY, DEFAULT_QUANTITY))
                    invest = float(user_input.get(CONF_INVEST, DEFAULT_INVEST))

                    new_data = dict(self._existing_entry.data)
                    new_data[CONF_ISINS] = existing_isins + [isin]
                    new_data[CONF_ISIN_CONFIG] = dict(new_data.get(CONF_ISIN_CONFIG, {}))
                    new_data[CONF_ISIN_CONFIG][isin] = {
                        CONF_NAME: name if len(name) > 0 else default_name,
                        CONF_QUANTITY: quantity,
                        CONF_INVEST: invest,
                        CONF_ETFOBJECT: etf_obj
                    }

                    self.hass.config_entries.async_update_entry(
                        self._existing_entry, data=new_data
                    )
                    await self.hass.config_entries.async_reload(
                        self._existing_entry.entry_id
                    )
                    return self.async_abort(reason="reconfigured")
                else:
                    errors[CONF_ISIN] = "invalid_isin"

        return self.async_show_form(
            step_id="add_isin",
            data_schema=vol.Schema({
                vol.Required(CONF_ISIN): str,
                vol.Optional(CONF_NAME, default=""): str,
                vol.Optional(CONF_QUANTITY, default=DEFAULT_QUANTITY): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Optional(CONF_INVEST, default=DEFAULT_INVEST): vol.All(vol.Coerce(float), vol.Range(min=0)),
            }),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # STEP: edit_isin  (ISIN is read-only, shown in description)
    # ------------------------------------------------------------------
    async def async_step_edit_isin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._existing_entry is not None
        assert self._editing_isin is not None
        isin = self._editing_isin
        isin_config = self._existing_entry.data.get(CONF_ISIN_CONFIG, {})
        cfg = isin_config.get(isin, {})

        if user_input is not None:
            name = (user_input.get(CONF_NAME) or "").strip()
            quantity = float(user_input.get(CONF_QUANTITY, DEFAULT_QUANTITY))
            invest = float(user_input.get(CONF_INVEST, DEFAULT_INVEST))

            new_data = dict(self._existing_entry.data)
            new_data[CONF_ISIN_CONFIG] = dict(new_data.get(CONF_ISIN_CONFIG, {}))
            new_data[CONF_ISIN_CONFIG][isin] = {
                CONF_NAME: name,
                CONF_QUANTITY: quantity,
                CONF_INVEST: invest,
            }

            self.hass.config_entries.async_update_entry(
                self._existing_entry, data=new_data
            )
            await self.hass.config_entries.async_reload(
                self._existing_entry.entry_id
            )
            return self.async_abort(reason="reconfigured")

        return self.async_show_form(
            step_id="edit_isin",
            data_schema=vol.Schema({
                vol.Optional(CONF_NAME, default=cfg.get(CONF_NAME, "")): str,
                vol.Optional(CONF_QUANTITY, default=float(cfg.get(CONF_QUANTITY, DEFAULT_QUANTITY)),): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Optional(CONF_INVEST, default=float(cfg.get(CONF_INVEST, DEFAULT_INVEST)),): vol.All(vol.Coerce(float), vol.Range(min=0)),
            }),
            description_placeholders={CONF_ISIN: isin},
        )

    async def verify_isin(self, isin):
        if len(isin) == 12:
            bridge = JustETFBridge(web_session=async_create_clientsession(self.hass), isins=[isin])
            data = await bridge._read_meta(isin)
            _LOGGER.debug(f"Verifying ISIN {isin}: Found {data} ETF-data")
            return data is not None and len(data) > 0, data[isin].get("name", None), data[isin]
        return False, {}
