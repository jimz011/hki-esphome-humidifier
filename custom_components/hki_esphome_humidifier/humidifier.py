"""HKI ESPHome Humidifier Converter — humidifier platform.

Attribute mapping (verified against live midea_dehum state)
────────────────────────────────────────────────────────────────────────────
  target_humidity  ← climate.humidity             (the % setpoint)
  current_humidity ← climate.current_humidity     (measured room humidity)
                   ← current_humidity_entity       (override if configured)
  current_temp     ← climate.current_temperature  (exposed as extra attr)
  humidity range   ← climate.min_humidity / max_humidity
  mode             ← climate.preset_mode
  is_on            ← climate.state != "off"
  fan_mode         → handled by HkiEsphomeFanModeSelect in select.py
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
    PLATFORM_SCHEMA as HUMIDIFIER_PLATFORM_SCHEMA,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    ALL_COMPANION_KEYS,
    COMPANION_ATTR_MAP,
    COMPANION_BINARY_SENSOR_KEYS,
    COMPANION_SENSOR_KEYS,
    COMPANION_SWITCH_KEYS,
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

# ─── Legacy YAML schema ──────────────────────────────────────────────────────

PLATFORM_SCHEMA = HUMIDIFIER_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_CLIMATE_ENTITY): cv.entity_id,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_ON_HVAC_MODE, default=DEFAULT_ON_HVAC_MODE): cv.string,
        vol.Optional(CONF_MIN_HUMIDITY): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional(CONF_MAX_HUMIDITY): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional(CONF_MODES, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_CURRENT_HUMIDITY_ENTITY): cv.entity_id,
        vol.Optional(CONF_TANK_LEVEL_ENTITY): cv.entity_id,
        vol.Optional(CONF_PM25_ENTITY): cv.entity_id,
        vol.Optional(CONF_ERROR_ENTITY): cv.entity_id,
        vol.Optional(CONF_BUCKET_FULL_ENTITY): cv.entity_id,
        vol.Optional(CONF_CLEAN_FILTER_ENTITY): cv.entity_id,
        vol.Optional(CONF_DEFROST_ENTITY): cv.entity_id,
        vol.Optional(CONF_IONIZER_ENTITY): cv.entity_id,
        vol.Optional(CONF_PUMP_ENTITY): cv.entity_id,
        vol.Optional(CONF_SLEEP_ENTITY): cv.entity_id,
        vol.Optional(CONF_BEEP_ENTITY): cv.entity_id,
    }
)


# ─── Platform setup ───────────────────────────────────────────────────────────

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up via configuration.yaml (legacy path)."""
    async_add_entities([HkiEsphomeHumidifier(hass, config)], update_before_add=True)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up from a config entry (UI path)."""
    config = {**entry.data, **entry.options}
    async_add_entities([HkiEsphomeHumidifier(hass, config)], update_before_add=True)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    f = _safe_float(value)
    return int(f) if f is not None else None


# ─── Entity ──────────────────────────────────────────────────────────────────

class HkiEsphomeHumidifier(HumidifierEntity, RestoreEntity):
    """Humidifier entity wrapping an ESPHome climate entity."""

    _attr_has_entity_name = False
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass

        self._climate_entity_id: str = config[CONF_CLIMATE_ENTITY]
        self._on_hvac_mode: str = config.get(CONF_ON_HVAC_MODE, DEFAULT_ON_HVAC_MODE)
        self._attr_name: str = config.get(CONF_NAME, DEFAULT_NAME)
        self._attr_unique_id: str = f"{DOMAIN}_{self._climate_entity_id}"

        # min/max humidity — prefer explicit YAML override, else auto-read from entity
        self._yaml_min: int | None = _safe_int(config.get(CONF_MIN_HUMIDITY))
        self._yaml_max: int | None = _safe_int(config.get(CONF_MAX_HUMIDITY))
        self._attr_min_humidity: int = self._yaml_min or DEFAULT_MIN_HUMIDITY
        self._attr_max_humidity: int = self._yaml_max or DEFAULT_MAX_HUMIDITY

        # Modes
        modes: list[str] = config.get(CONF_MODES) or []
        self._configured_modes: list[str] = modes
        if modes:
            self._attr_available_modes = modes
            self._attr_supported_features = HumidifierEntityFeature.MODES
        else:
            self._attr_available_modes = None
            self._attr_supported_features = HumidifierEntityFeature(0)

        # Companion entity IDs
        self._companion: dict[str, str | None] = {
            key: config.get(key) or None for key in ALL_COMPANION_KEYS
        }

        # Runtime state
        self._attr_is_on: bool = False
        self._attr_target_humidity: int | None = None
        self._attr_current_humidity: float | None = None
        self._attr_mode: str | None = None
        self._attr_available: bool = False
        self._current_temperature: float | None = None
        self._companion_values: dict[str, Any] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._climate_entity_id], self._async_climate_changed
            )
        )

        companion_ids = [eid for eid in self._companion.values() if eid]
        if companion_ids:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, companion_ids, self._async_companion_changed
                )
            )

        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._attr_is_on = last_state.state != STATE_OFF

        self._sync_from_climate()
        self._sync_all_companions()

    # ── State listeners ──────────────────────────────────────────────────────

    @callback
    def _async_climate_changed(self, event) -> None:
        self._sync_from_climate()
        self.async_write_ha_state()

    @callback
    def _async_companion_changed(self, event) -> None:
        new_state = event.data.get("new_state")
        entity_id = event.data.get("entity_id")
        if new_state and entity_id:
            self._sync_companion(entity_id, new_state)
            self.async_write_ha_state()

    # ── Sync from climate entity ──────────────────────────────────────────────

    def _sync_from_climate(self) -> None:
        """Read all relevant data from the live climate entity."""
        state = self.hass.states.get(self._climate_entity_id)

        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._attr_available = False
            return

        self._attr_available = True
        attrs = state.attributes

        # on/off
        self._attr_is_on = state.state != STATE_OFF

        # ── Humidity range ← min_humidity / max_humidity ─────────────────────
        if self._yaml_min is None:
            v = _safe_int(attrs.get("min_humidity"))
            if v is not None:
                self._attr_min_humidity = v
        if self._yaml_max is None:
            v = _safe_int(attrs.get("max_humidity"))
            if v is not None:
                self._attr_max_humidity = v

        # ── Target humidity ← climate.humidity ───────────────────────────────
        # midea_dehum stores the humidity setpoint in the `humidity` attribute.
        # `temperature` is null on dehumidifiers and must not be used.
        v = _safe_int(attrs.get("humidity"))
        if v is not None:
            self._attr_target_humidity = v

        # ── Current humidity ← climate.current_humidity ──────────────────────
        # Only use the climate entity when no dedicated sensor is configured.
        # Note: `humidity` = target setpoint, `current_humidity` = measured value.
        if not self._companion.get(CONF_CURRENT_HUMIDITY_ENTITY):
            v = _safe_float(attrs.get("current_humidity"))
            if v is not None:
                self._attr_current_humidity = v

        # ── Current temperature ← climate.current_temperature ────────────────
        # Not a standard humidifier field — exposed as an extra state attribute
        # so automations and custom cards can use it.
        self._current_temperature = _safe_float(attrs.get("current_temperature"))

        # ── Mode ← preset_mode ───────────────────────────────────────────────
        preset = attrs.get("preset_mode")
        entity_presets: list[str] = attrs.get("preset_modes") or []

        if not self._configured_modes and entity_presets:
            self._attr_available_modes = entity_presets
            self._attr_supported_features = HumidifierEntityFeature.MODES

        if self._attr_available_modes and preset in self._attr_available_modes:
            self._attr_mode = preset

    # ── Sync companion entities ───────────────────────────────────────────────

    def _sync_all_companions(self) -> None:
        for conf_key, entity_id in self._companion.items():
            if not entity_id:
                continue
            state = self.hass.states.get(entity_id)
            if state:
                self._sync_companion(entity_id, state)

    def _sync_companion(self, entity_id: str, state) -> None:
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        for conf_key, eid in self._companion.items():
            if eid != entity_id:
                continue
            attr_name = COMPANION_ATTR_MAP.get(conf_key)
            if attr_name is None:
                continue

            if conf_key == CONF_CURRENT_HUMIDITY_ENTITY:
                v = _safe_float(state.state)
                if v is not None:
                    self._attr_current_humidity = v
                else:
                    _LOGGER.warning(
                        "HKI Humidifier: could not parse humidity sensor '%s'",
                        state.state,
                    )
            elif conf_key in COMPANION_BINARY_SENSOR_KEYS:
                self._companion_values[attr_name] = state.state == STATE_ON
            elif conf_key in COMPANION_SENSOR_KEYS:
                v = _safe_float(state.state)
                self._companion_values[attr_name] = v if v is not None else state.state
            elif conf_key in COMPANION_SWITCH_KEYS:
                self._companion_values[attr_name] = state.state == STATE_ON

            break

    # ── Commands ─────────────────────────────────────────────────────────────

    async def async_turn_on(self, **kwargs: Any) -> None:
        _LOGGER.debug("HKI [%s]: turn_on → %s", self._climate_entity_id, self._on_hvac_mode)
        await self.hass.services.async_call(
            "climate", "set_hvac_mode",
            {ATTR_ENTITY_ID: self._climate_entity_id, "hvac_mode": self._on_hvac_mode},
            blocking=True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        _LOGGER.debug("HKI [%s]: turn_off", self._climate_entity_id)
        await self.hass.services.async_call(
            "climate", "set_hvac_mode",
            {ATTR_ENTITY_ID: self._climate_entity_id, "hvac_mode": "off"},
            blocking=True,
        )

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the target humidity — forwarded as climate.set_humidity."""
        _LOGGER.debug("HKI [%s]: set_humidity(%d)", self._climate_entity_id, humidity)
        await self.hass.services.async_call(
            "climate", "set_humidity",
            {ATTR_ENTITY_ID: self._climate_entity_id, "humidity": humidity},
            blocking=True,
        )

    async def async_set_mode(self, mode: str) -> None:
        if self._attr_available_modes and mode not in self._attr_available_modes:
            _LOGGER.error(
                "HKI Humidifier: mode '%s' not in %s", mode, self._attr_available_modes
            )
            return
        _LOGGER.debug("HKI [%s]: set_mode(%s)", self._climate_entity_id, mode)
        await self.hass.services.async_call(
            "climate", "set_preset_mode",
            {ATTR_ENTITY_ID: self._climate_entity_id, "preset_mode": mode},
            blocking=True,
        )

    # ── Extra state attributes ────────────────────────────────────────────────

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "source_climate_entity": self._climate_entity_id,
            "on_hvac_mode": self._on_hvac_mode,
        }
        if self._current_temperature is not None:
            attrs["current_temperature"] = self._current_temperature
        attrs.update(self._companion_values)
        return attrs
