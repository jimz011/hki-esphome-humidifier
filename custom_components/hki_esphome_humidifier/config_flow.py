"""Config flow for HKI ESPHome Humidifier Converter.

Step 1 — Core:   climate entity, name, hvac on-mode, humidity range
Step 2 — Modes:  which preset modes to expose (populated from the climate entity)
Step 3 — Extras: all optional companion entities (sensors, binary sensors, switches)

The same three steps are also available as an Options flow so users can
reconfigure a device after the initial setup.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

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

def _get_climate_preset_modes(hass, climate_entity_id: str) -> list[str]:
    """Return the preset_modes list from a live climate entity, if available."""
    if not climate_entity_id:
        return []
    state = hass.states.get(climate_entity_id)
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return []
    return state.attributes.get("preset_modes") or []


def _entity_selector(domain: str) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domain))


def _optional_entity_selector(domain: str) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domain, multiple=False))


# ─── Step schemas ─────────────────────────────────────────────────────────────

def _step_core_schema(defaults: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_CLIMATE_ENTITY,
                default=defaults.get(CONF_CLIMATE_ENTITY, ""),
            ): _entity_selector("climate"),
            vol.Optional(
                CONF_NAME,
                default=defaults.get(CONF_NAME, DEFAULT_NAME),
            ): TextSelector(),
            vol.Optional(
                CONF_ON_HVAC_MODE,
                default=defaults.get(CONF_ON_HVAC_MODE, DEFAULT_ON_HVAC_MODE),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=["dry", "fan_only", "cool", "heat", "auto", "heat_cool"],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="on_hvac_mode",
                )
            ),
            vol.Optional(
                CONF_MIN_HUMIDITY,
                default=defaults.get(CONF_MIN_HUMIDITY, DEFAULT_MIN_HUMIDITY),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_MAX_HUMIDITY,
                default=defaults.get(CONF_MAX_HUMIDITY, DEFAULT_MAX_HUMIDITY),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)
            ),
        }
    )


def _step_modes_schema(defaults: dict, available_modes: list[str]) -> vol.Schema:
    """Build the modes schema. Uses preset_modes from the climate entity when available."""
    if available_modes:
        return vol.Schema(
            {
                vol.Optional(
                    CONF_MODES,
                    default=defaults.get(CONF_MODES, available_modes),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=available_modes,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
    # Fall back to a free-text field when the climate entity isn't live yet
    return vol.Schema(
        {
            vol.Optional(
                CONF_MODES,
                default=", ".join(defaults.get(CONF_MODES, [])),
            ): TextSelector(),
        }
    )


def _step_extras_schema(defaults: dict) -> vol.Schema:
    """Schema for all optional companion entity pickers."""

    def _opt(key, domain):
        return vol.Optional(key, default=defaults.get(key, ""))

    return vol.Schema(
        {
            # ── Sensors ──────────────────────────────────────────────────────
            vol.Optional(
                CONF_CURRENT_HUMIDITY_ENTITY,
                default=defaults.get(CONF_CURRENT_HUMIDITY_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_TANK_LEVEL_ENTITY,
                default=defaults.get(CONF_TANK_LEVEL_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_PM25_ENTITY,
                default=defaults.get(CONF_PM25_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_ERROR_ENTITY,
                default=defaults.get(CONF_ERROR_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            # ── Binary sensors ───────────────────────────────────────────────
            vol.Optional(
                CONF_BUCKET_FULL_ENTITY,
                default=defaults.get(CONF_BUCKET_FULL_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(
                CONF_CLEAN_FILTER_ENTITY,
                default=defaults.get(CONF_CLEAN_FILTER_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(
                CONF_DEFROST_ENTITY,
                default=defaults.get(CONF_DEFROST_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            # ── Switches ─────────────────────────────────────────────────────
            vol.Optional(
                CONF_IONIZER_ENTITY,
                default=defaults.get(CONF_IONIZER_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(
                CONF_PUMP_ENTITY,
                default=defaults.get(CONF_PUMP_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(
                CONF_SLEEP_ENTITY,
                default=defaults.get(CONF_SLEEP_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(
                CONF_BEEP_ENTITY,
                default=defaults.get(CONF_BEEP_ENTITY, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
        }
    )


def _clean_data(data: dict) -> dict:
    """Strip empty strings from form data so they aren't stored as config."""
    return {k: v for k, v in data.items() if v != "" and v != []}


def _parse_modes_text(raw: str) -> list[str]:
    """Parse a comma-separated modes string entered as free text."""
    return [m.strip() for m in raw.split(",") if m.strip()]


# ─── Config Flow ─────────────────────────────────────────────────────────────

class HkiEsphomeHumidifierConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle the initial setup config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # ── Step 1: core ─────────────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            climate_id = user_input[CONF_CLIMATE_ENTITY]

            # Prevent duplicate entries for the same climate entity
            await self.async_set_unique_id(climate_id)
            self._abort_if_unique_id_configured()

            # Validate min < max
            if user_input.get(CONF_MIN_HUMIDITY, 0) >= user_input.get(
                CONF_MAX_HUMIDITY, 100
            ):
                errors["base"] = "humidity_range_invalid"
            else:
                self._data.update(_clean_data(user_input))
                return await self.async_step_modes()

        return self.async_show_form(
            step_id="user",
            data_schema=_step_core_schema(self._data),
            errors=errors,
        )

    # ── Step 2: modes ────────────────────────────────────────────────────────

    async def async_step_modes(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        climate_id = self._data.get(CONF_CLIMATE_ENTITY, "")
        available_modes = _get_climate_preset_modes(self.hass, climate_id)

        if user_input is not None:
            modes = user_input.get(CONF_MODES, [])
            # Handle free-text fallback
            if isinstance(modes, str):
                modes = _parse_modes_text(modes)
            if modes:
                self._data[CONF_MODES] = modes
            return await self.async_step_extras()

        return self.async_show_form(
            step_id="modes",
            data_schema=_step_modes_schema(self._data, available_modes),
            errors=errors,
            description_placeholders={
                "climate_entity": climate_id,
            },
        )

    # ── Step 3: extras ───────────────────────────────────────────────────────

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
    ) -> HkiEsphomeHumidifierOptionsFlow:
        return HkiEsphomeHumidifierOptionsFlow(config_entry)


# ─── Options Flow ─────────────────────────────────────────────────────────────

class HkiEsphomeHumidifierOptionsFlow(config_entries.OptionsFlow):
    """Allow the user to reconfigure an existing entry via the UI."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        # Merge current data + options so defaults reflect the live config
        self._data: dict[str, Any] = {
            **config_entry.data,
            **config_entry.options,
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Options flow starts at the core step."""
        return await self.async_step_core()

    async def async_step_core(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(CONF_MIN_HUMIDITY, 0) >= user_input.get(
                CONF_MAX_HUMIDITY, 100
            ):
                errors["base"] = "humidity_range_invalid"
            else:
                self._data.update(_clean_data(user_input))
                return await self.async_step_modes()

        return self.async_show_form(
            step_id="core",
            data_schema=_step_core_schema(self._data),
            errors=errors,
        )

    async def async_step_modes(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        climate_id = self._data.get(CONF_CLIMATE_ENTITY, "")
        available_modes = _get_climate_preset_modes(self.hass, climate_id)

        if user_input is not None:
            modes = user_input.get(CONF_MODES, [])
            if isinstance(modes, str):
                modes = _parse_modes_text(modes)
            self._data[CONF_MODES] = modes
            return await self.async_step_extras()

        return self.async_show_form(
            step_id="modes",
            data_schema=_step_modes_schema(self._data, available_modes),
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
