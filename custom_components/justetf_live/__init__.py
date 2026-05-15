from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN,
    CONF_ISINS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    COORDINATOR_KEY,
    DELAYED_TASK_KEY,
)
from .coordinator import INGStocksCoordinator

PLATFORMS = ["sensor"]
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (YAML hook, unused)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry (single entry holding all ISINs)."""
    isins: list[str] = entry.data.get(CONF_ISINS, [])
    scan_interval_min = int(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))

    coordinator = INGStocksCoordinator(
        hass=hass,
        update_interval=timedelta(minutes=scan_interval_min),
    )
    for isin in isins:
        coordinator.isin_add(isin)

    hass.data.setdefault(DOMAIN, {})[COORDINATOR_KEY] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    except Exception as err:
        raise ConfigEntryNotReady(str(err)) from err

    _LOGGER.info(
        "ING Stocks setup: ISINs=%s, scan_interval=%s min",
        isins,
        scan_interval_min,
    )

    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN, {})

        # cancel shared delayed task
        task: asyncio.Task[Any] | None = domain_data.pop(DELAYED_TASK_KEY, None)
        if task and not task.done():
            task.cancel()

        domain_data.pop(COORDINATOR_KEY, None)
    return unload_ok