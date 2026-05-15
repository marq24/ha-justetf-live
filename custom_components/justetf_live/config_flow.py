import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode
from homeassistant.helpers.translation import async_get_translations

from custom_components.justetf_live.pyjustetflive_ha import JustETFBridge
from .const import (
    DOMAIN,
    CONF_ISIN,
    CONF_ISINS,
    CONF_ISIN_CONFIG,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_QUANTITY,
    CONF_ETFOBJECT,
    CONF_SELECTED_ISIN,
    ADD_NEW_ISIN,
    DELETE_ISIN,
    SAVE_AND_CLOSE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_QUANTITY
)

_LOGGER = logging.getLogger(__name__)

JUSTETF_CONF_ISIN = "isin"
JUSTETF_CONF_NAME = "name"
JUSTETF_CONF_QUANTITY = "quantity"
JUSTETF_CONF_SCAN_INTERVAL = "scan_interval"

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

        # WE DON't import any other integration ISIN's...
        # ingstocks_entries = self.hass.config_entries.async_entries("ingstocksplus")
        # _LOGGER.debug(f"ingstocks_entries: {ingstocks_entries}")
        # _LOGGER.debug(f"ingstocks_entries: {self.hass}")
        #
        # if ingstocks_entries and len(ingstocks_entries) > 0:
        #     imported_list = []
        #     imported_dict = {}
        #     imported_interval = None
        #     for a_justetf_entry in ingstocks_entries:
        #         if a_justetf_entry.state ==  ConfigEntryState.LOADED:
        #             conf_obj = a_justetf_entry.data
        #             if conf_obj and conf_obj.get(JUSTETF_CONF_ISIN, None) is not None:
        #                 a_isin = conf_obj.get(JUSTETF_CONF_ISIN, None)
        #                 a_name = conf_obj.get(JUSTETF_CONF_NAME, None)
        #                 a_quantity = conf_obj.get(JUSTETF_CONF_QUANTITY, 0)
        #
        #                 if imported_interval is None:
        #                     imported_interval = conf_obj.get(JUSTETF_CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        #
        #                 if a_isin is not None:
        #                     imported_list.append(a_isin)
        #                     imported_dict[a_isin] = {
        #                         CONF_NAME: a_name,
        #                         CONF_QUANTITY: a_quantity
        #                     }
        #     if len(imported_list) > 0:
        #         await self.async_set_unique_id(DOMAIN)
        #         self._abort_if_unique_id_configured()
        #         return self.async_create_entry(
        #             title="ING Stocks",
        #             data={
        #                 CONF_SCAN_INTERVAL: imported_interval,
        #                 CONF_ISINS: imported_list,
        #                 CONF_ISIN_CONFIG: imported_dict,
        #             },
        #         )

        # First-time setup: ISIN + global scan_interval
        if user_input is not None:
            isin = user_input[CONF_ISIN].strip().upper()
            name = (user_input.get(CONF_NAME) or "").strip()
            scan_interval = int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            quantity = float(user_input.get(CONF_QUANTITY, DEFAULT_QUANTITY))

            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            is_ok, default_name, etf_obj = await self.verify_isin(isin)
            if is_ok:
                return self.async_create_entry(
                    title="justETF live",
                    data={
                        CONF_SCAN_INTERVAL: scan_interval,
                        CONF_ISINS: [isin],
                        CONF_ISIN_CONFIG: {
                            isin: {
                                CONF_NAME: name if len(name) > 0 else default_name,
                                CONF_QUANTITY: quantity,
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
                vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(int, vol.Range(min=1, max=360)),
                vol.Optional(CONF_QUANTITY, default=DEFAULT_QUANTITY): vol.All(vol.Coerce(float), vol.Range(min=0)),
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

        options: dict[str, str] = {}
        # Load translated action labels
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "config", {DOMAIN}
        )
        add_label = translations.get(
            f"component.{DOMAIN}.config.step.select_isin.actions.add_new",
            "➕ Add new ISIN",
        )
        options[ADD_NEW_ISIN] = add_label
        delete_label = translations.get(
            f"component.{DOMAIN}.config.step.select_isin.actions.delete_isin",
            "🗑️ Delete ISIN",
        )
        options[DELETE_ISIN] = delete_label

        # Build selectable options: "ISIN - Name" for each existing + add-new
        edit_label = translations.get(
            f"component.{DOMAIN}.config.step.select_isin.actions.edit_isin",
            "✏️ edit '{label}'",
        )
        for isin in isins:
            cfg = isin_config.get(isin, {})
            label = cfg.get(CONF_NAME) or isin
            if label != isin:
                label = f"{isin} – {label}"
            options[isin] = edit_label.replace('{label}', label)

        save_label = translations.get(
            f"component.{DOMAIN}.config.step.select_isin.actions.save_close",
            "💾 Save interval & close",
        )
        options[SAVE_AND_CLOSE] = save_label

        if user_input is None:
            current_scan = int(
                entry_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            )
            return self.async_show_form(
                step_id="select_isin",
                data_schema=vol.Schema({
                    vol.Required(CONF_SELECTED_ISIN): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST if len(options) < 15 else SelectSelectorMode.DROPDOWN
                        )),
                    vol.Required(CONF_SCAN_INTERVAL, default=current_scan): vol.All(int, vol.Range(min=1, max=360)),
                }),
            )

        # Save potentially updated scan_interval (reconfigure only)
        if self._is_reconfigure and CONF_SCAN_INTERVAL in user_input:
            new_scan = int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            if new_scan != int(entry_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
                new_data = dict(entry_data)
                new_data[CONF_SCAN_INTERVAL] = new_scan
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

                    new_data = dict(self._existing_entry.data)
                    new_data[CONF_ISINS] = existing_isins + [isin]
                    new_data[CONF_ISIN_CONFIG] = dict(new_data.get(CONF_ISIN_CONFIG, {}))
                    new_data[CONF_ISIN_CONFIG][isin] = {
                        CONF_NAME: name if len(name) > 0 else default_name,
                        CONF_QUANTITY: quantity,
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

            new_data = dict(self._existing_entry.data)
            new_data[CONF_ISIN_CONFIG] = dict(new_data.get(CONF_ISIN_CONFIG, {}))
            new_data[CONF_ISIN_CONFIG][isin] = {
                CONF_NAME: name,
                CONF_QUANTITY: quantity
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