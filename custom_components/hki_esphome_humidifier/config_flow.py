"""Config flow for HKI ESPHome Humidifier Converter.

Step 1 — Core:   climate entity + name. Everything else (min/max humidity,
                 hvac_modes, preset_modes) is read directly from the live
                 climate entity — no manual entry required.
Step 2 — Modes:  which preset modes to expose (pre-ticked from the entity).
Step 3 — Extras: all optional companion entities (sensors, binary sensors,
                 switches). Every field is truly optional.

The same three steps are available as an Options flow for reconfiguration.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BEEP_ENTITY,
    CONF_BUCKET_FULL_ENTITY,
    CONF_CLEAN_FILTER_ENTITY,
    CONF_CLIMATE_ENTITY,
    CONF_CURRENT_HUMIDITY_ENTITY,
    CONF_DEFROST_ENTITY,
    CONF_ERROR_ENTITY,
    CONF_IONIZER_ENTITY,
    CONF_MAX_HUMIDITY,
    CONF_MIN_HUMIDITY,
    CONF_MODES,
    CONF_NAME,
    CONF_ON_HVAC_MODE,
    CONF_PM25_ENTITY,
    CONF_PUMP_ENTITY,
    CONF_SLEEP_ENTITY,
    CONF_TANK_LEVEL_ENTITY,
    DEFAULT_MAX_HUMIDITY,
    DEFAULT_MIN_HUMIDITY,
    DEFAULT_NAME,
    DEFAULT_ON_HVAC_MODE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _climate_attr(hass, climate_entity_id: str, attr: str, fallback=None):
    """Read a single attribute from the live climate entity."""
    if not climate_entity_id:
        return fallback
    state = hass.states.get(climate_entity_id)
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return fallback
    return state.attributes.get(attr, fallback)


def _get_hvac_modes(hass, climate_entity_id: str) -> list[str]:
    """Return on-capable hvac_modes (everything except 'off')."""
    modes = _climate_attr(hass, climate_entity_id, "hvac_modes", [])
    return [m for m in modes if m != "off"]


def _get_preset_modes(hass, climate_entity_id: str) -> list[str]:
    return _climate_attr(hass, climate_entity_id, "preset_modes") or []


def _entity_selector(domain: str) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain)
    )


def _clean_data(data: dict) -> dict:
    """Strip None and empty-string values — they mean 'not configured'."""
    return {k: v for k, v in data.items() if v is not None and v != "" and v != []}


def _parse_modes_text(raw: str) -> list[str]:
    return [m.strip() for m in raw.split(",") if m.strip()]


# ─── Step schemas ─────────────────────────────────────────────────────────────

def _step_core_schema(defaults: dict) -> vol.Schema:
    """Step 1: just the climate entity and a friendly name."""
    return vol.Schema(
        {
            vol.Required(
                CONF_CLIMATE_ENTITY,
                default=defaults.get(CONF_CLIMATE_ENTITY, vol.UNDEFINED),
            ): _entity_selector("climate"),
            vol.Optional(
                CONF_NAME,
                default=defaults.get(CONF_NAME, DEFAULT_NAME),
            ): selector.TextSelector(),
        }
    )


def _step_modes_schema(defaults: dict, preset_modes: list[str], hvac_modes: list[str]) -> vol.Schema:
    """Step 2: on-hvac-mode dropdown (auto-populated) + mode multi-select."""
    fields: dict = {}

    # on_hvac_mode — populated from live hvac_modes
    if hvac_modes:
        fields[vol.Optional(
            CONF_ON_HVAC_MODE,
            default=defaults.get(
                CONF_ON_HVAC_MODE,
                hvac_modes[0] if hvac_modes else DEFAULT_ON_HVAC_MODE,
            ),
        )] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=hvac_modes,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    else:
        # Fallback free-text when entity is not yet live
        fields[vol.Optional(
            CONF_ON_HVAC_MODE,
            default=defaults.get(CONF_ON_HVAC_MODE, DEFAULT_ON_HVAC_MODE),
        )] = selector.TextSelector()

    # preset modes — multi-select, pre-ticked from the entity
    if preset_modes:
        fields[vol.Optional(
            CONF_MODES,
            default=defaults.get(CONF_MODES, preset_modes),
        )] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=preset_modes,
                multiple=True,
                mode=selector.SelectSelectorMode.LIST,
            )
        )
    # If no preset_modes exist on the entity we skip this field entirely

    return vol.Schema(fields)


def _step_extras_schema(defaults: dict) -> vol.Schema:
    """Step 3: all optional companion entities.

    Every field uses vol.Optional with no default so HA renders them as
    genuinely optional — the entity picker shows empty and the user can
    leave any field blank.
    """

    def _opt_entity(key: str, domain: str):
        """Return an Optional schema entry with an entity selector.
        
        When the user leaves the field empty, the key is simply absent from
        user_input — we never store None or "" for companion entities.
        """
        current = defaults.get(key)
        if current:
            return vol.Optional(key, default=current)
        return vol.Optional(key)

    return vol.Schema(
        {
            # ── Sensors ──────────────────────────────────────────────────────
            _opt_entity(CONF_CURRENT_HUMIDITY_ENTITY, "sensor"): _entity_selector("sensor"),
            _opt_entity(CONF_TANK_LEVEL_ENTITY, "sensor"): _entity_selector("sensor"),
            _opt_entity(CONF_PM25_ENTITY, "sensor"): _entity_selector("sensor"),
            _opt_entity(CONF_ERROR_ENTITY, "sensor"): _entity_selector("sensor"),
            # ── Binary sensors ───────────────────────────────────────────────
            _opt_entity(CONF_BUCKET_FULL_ENTITY, "binary_sensor"): _entity_selector("binary_sensor"),
            _opt_entity(CONF_CLEAN_FILTER_ENTITY, "binary_sensor"): _entity_selector("binary_sensor"),
            _opt_entity(CONF_DEFROST_ENTITY, "binary_sensor"): _entity_selector("binary_sensor"),
            # ── Switches ─────────────────────────────────────────────────────
            _opt_entity(CONF_IONIZER_ENTITY, "switch"): _entity_selector("switch"),
            _opt_entity(CONF_PUMP_ENTITY, "switch"): _entity_selector("switch"),
            _opt_entity(CONF_SLEEP_ENTITY, "switch"): _entity_selector("switch"),
            _opt_entity(CONF_BEEP_ENTITY, "switch"): _entity_selector("switch"),
        }
    )


# ─── Config Flow ─────────────────────────────────────────────────────────────

class HkiEsphomeHumidifierConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle the initial setup config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # ── Step 1: choose the climate entity ────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            climate_id = user_input[CONF_CLIMATE_ENTITY]

            # Prevent duplicate entries for the same climate entity
            await self.async_set_unique_id(climate_id)
            self._abort_if_unique_id_configured()

            self._data.update(_clean_data(user_input))
            return await self.async_step_modes()

        return self.async_show_form(
            step_id="user",
            data_schema=_step_core_schema(self._data),
            errors=errors,
        )

    # ── Step 2: modes (auto-populated from the entity) ───────────────────────

    async def async_step_modes(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        climate_id = self._data.get(CONF_CLIMATE_ENTITY, "")
        preset_modes = _get_preset_modes(self.hass, climate_id)
        hvac_modes = _get_hvac_modes(self.hass, climate_id)

        if user_input is not None:
            modes = user_input.get(CONF_MODES, [])
            if isinstance(modes, str):
                modes = _parse_modes_text(modes)
            if modes:
                self._data[CONF_MODES] = modes
            on_mode = user_input.get(CONF_ON_HVAC_MODE)
            if on_mode:
                self._data[CONF_ON_HVAC_MODE] = on_mode
            return await self.async_step_extras()

        return self.async_show_form(
            step_id="modes",
            data_schema=_step_modes_schema(self._data, preset_modes, hvac_modes),
            description_placeholders={"climate_entity": climate_id},
        )

    # ── Step 3: optional companion entities ──────────────────────────────────

    async def async_step_extras(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(_clean_data(user_input))
            name = self._data.get(CONF_NAME, DEFAULT_NAME)
            return self.async_create_entry(title=name, data=self._data)

        return self.async_show_form(
            step_id="extras",
            data_schema=_step_extras_schema(self._data),
        )

    # ── Options flow entrypoint ───────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "HkiEsphomeHumidifierOptionsFlow":
        return HkiEsphomeHumidifierOptionsFlow(config_entry)


# ─── Options Flow ─────────────────────────────────────────────────────────────

class HkiEsphomeHumidifierOptionsFlow(config_entries.OptionsFlow):
    """Allow the user to reconfigure an existing entry via the UI."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._data: dict[str, Any] = {
            **config_entry.data,
            **config_entry.options,
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        return await self.async_step_core()

    async def async_step_core(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(_clean_data(user_input))
            return await self.async_step_modes()

        return self.async_show_form(
            step_id="core",
            data_schema=_step_core_schema(self._data),
        )

    async def async_step_modes(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        climate_id = self._data.get(CONF_CLIMATE_ENTITY, "")
        preset_modes = _get_preset_modes(self.hass, climate_id)
        hvac_modes = _get_hvac_modes(self.hass, climate_id)

        if user_input is not None:
            modes = user_input.get(CONF_MODES, [])
            if isinstance(modes, str):
                modes = _parse_modes_text(modes)
            self._data[CONF_MODES] = modes
            on_mode = user_input.get(CONF_ON_HVAC_MODE)
            if on_mode:
                self._data[CONF_ON_HVAC_MODE] = on_mode
            return await self.async_step_extras()

        return self.async_show_form(
            step_id="modes",
            data_schema=_step_modes_schema(self._data, preset_modes, hvac_modes),
            description_placeholders={"climate_entity": climate_id},
        )

    async def async_step_extras(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(_clean_data(user_input))
            return self.async_create_entry(title="", data=self._data)

        return self.async_show_form(
            step_id="extras",
            data_schema=_step_extras_schema(self._data),
        )
