"""HKI ESPHome Humidifier Converter — select platform (fan mode).

Creates a Select entity for fan speed control when the underlying climate
entity advertises fan_modes. No user configuration is required — the entity
appears automatically if fan_modes exist, and disappears if they don't.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_CLIMATE_ENTITY, CONF_NAME, DEFAULT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up fan mode select entity from a config entry."""
    config = {**entry.data, **entry.options}
    climate_id: str = config[CONF_CLIMATE_ENTITY]

    # Only create the select entity if the climate entity actually has fan modes
    state = hass.states.get(climate_id)
    fan_modes: list[str] = []
    if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        fan_modes = state.attributes.get("fan_modes") or []

    if fan_modes:
        async_add_entities(
            [HkiEsphomeFanModeSelect(hass, config, fan_modes)],
            update_before_add=True,
        )
    else:
        # Entity might appear later when the device comes online — register a
        # one-shot listener that creates the entity on first valid state.
        _LOGGER.debug(
            "HKI FanMode: no fan_modes yet for %s — will retry on first state update",
            climate_id,
        )

        @callback
        def _on_climate_first_state(event) -> None:
            new_state = event.data.get("new_state")
            if new_state is None or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                return
            modes = new_state.attributes.get("fan_modes") or []
            if modes:
                async_add_entities(
                    [HkiEsphomeFanModeSelect(hass, config, modes)],
                    update_before_add=True,
                )
                # Unsubscribe after first successful creation
                cancel()

        cancel = hass.bus.async_listen(
            "state_changed",
            lambda event: (
                _on_climate_first_state(event)
                if event.data.get("entity_id") == climate_id
                else None
            ),
        )


class HkiEsphomeFanModeSelect(SelectEntity, RestoreEntity):
    """Select entity that mirrors and controls the fan_mode on the climate entity."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_icon = "mdi:fan"

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict,
        fan_modes: list[str],
    ) -> None:
        self.hass = hass
        self._climate_entity_id: str = config[CONF_CLIMATE_ENTITY]
        base_name: str = config.get(CONF_NAME, DEFAULT_NAME)

        self._attr_name = f"{base_name} Fan Speed"
        self._attr_unique_id = f"{DOMAIN}_{self._climate_entity_id}_fan_mode"
        self._attr_options = fan_modes
        self._attr_current_option: str | None = None
        self._attr_available: bool = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._climate_entity_id],
                self._async_climate_changed,
            )
        )

        # Restore last known selection so it doesn't flash "unknown" on restart
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            if last_state.state in self._attr_options:
                self._attr_current_option = last_state.state

        self._sync_from_climate()

    # ── State listener ───────────────────────────────────────────────────────

    @callback
    def _async_climate_changed(self, event) -> None:
        self._sync_from_climate()
        self.async_write_ha_state()

    def _sync_from_climate(self) -> None:
        state = self.hass.states.get(self._climate_entity_id)

        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._attr_available = False
            return

        self._attr_available = True

        # Keep options list in sync (device could add modes dynamically)
        live_modes: list[str] = state.attributes.get("fan_modes") or []
        if live_modes:
            self._attr_options = live_modes

        current = state.attributes.get("fan_mode")
        if current and current in self._attr_options:
            self._attr_current_option = current

    # ── Command ──────────────────────────────────────────────────────────────

    async def async_select_option(self, option: str) -> None:
        """Change the fan speed on the underlying climate entity."""
        _LOGGER.debug(
            "HKI FanMode [%s]: set_fan_mode(%s)", self._climate_entity_id, option
        )
        await self.hass.services.async_call(
            "climate",
            "set_fan_mode",
            {ATTR_ENTITY_ID: self._climate_entity_id, "fan_mode": option},
            blocking=True,
        )
