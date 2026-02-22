"""HKI ESPHome Humidifier Converter — humidifier platform.

Translates an ESPHome climate entity (as exposed by midea_dehum and similar
custom ESPHome components) into a proper HA humidifier / dehumidifier entity.

Companion entities (sensors, binary sensors, switches) are optionally tracked
and surfaced as extra state attributes on the humidifier entity, giving the
full feature set of the underlying device in one place.

Climate → Humidifier mapping
─────────────────────────────────────────────────────────────────────────────
  climate.state == "off"           →  is_on = False
  climate.state == <on_hvac_mode>  →  is_on = True
  climate attr temperature         →  target_humidity
  climate attr current_temperature →  current_humidity (fallback)
  current_humidity_entity          →  current_humidity (preferred)
  climate attr preset_mode         →  mode
─────────────────────────────────────────────────────────────────────────────
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

# ─── Legacy YAML schema (kept for backward compatibility) ─────────────────────

PLATFORM_SCHEMA = HUMIDIFIER_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_CLIMATE_ENTITY): cv.entity_id,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_ON_HVAC_MODE, default=DEFAULT_ON_HVAC_MODE): cv.string,
        vol.Optional(CONF_MIN_HUMIDITY, default=DEFAULT_MIN_HUMIDITY): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional(CONF_MAX_HUMIDITY, default=DEFAULT_MAX_HUMIDITY): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional(CONF_MODES, default=[]): vol.All(cv.ensure_list, [cv.string]),
        # Optional companion entities
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


# ─── YAML platform setup ──────────────────────────────────────────────────────

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up via configuration.yaml (legacy path)."""
    async_add_entities(
        [HkiEsphomeHumidifier(hass, config)],
        update_before_add=True,
    )


# ─── Config-entry platform setup ─────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up from a config entry (UI/config-flow path)."""
    # Merge entry.data with entry.options so options always win
    config = {**entry.data, **entry.options}
    async_add_entities(
        [HkiEsphomeHumidifier(hass, config)],
        update_before_add=True,
    )


# ─── Entity ──────────────────────────────────────────────────────────────────

class HkiEsphomeHumidifier(HumidifierEntity, RestoreEntity):
    """A humidifier entity that wraps an ESPHome climate entity.

    The underlying climate entity is the source of truth. This entity
    subscribes to state changes across the climate entity and any optional
    companion entities, then mirrors/proxies everything through HA services.
    """

    _attr_has_entity_name = False
    _attr_device_class = HumidifierDeviceClass.DEHUMIDIFIER
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass

        # ── Core config ──────────────────────────────────────────────────────
        self._climate_entity_id: str = config[CONF_CLIMATE_ENTITY]
        self._on_hvac_mode: str = config.get(CONF_ON_HVAC_MODE, DEFAULT_ON_HVAC_MODE)
        self._attr_name: str = config.get(CONF_NAME, DEFAULT_NAME)
        self._attr_unique_id: str = f"{DOMAIN}_{self._climate_entity_id}"
        self._attr_min_humidity: int = int(
            config.get(CONF_MIN_HUMIDITY, DEFAULT_MIN_HUMIDITY)
        )
        self._attr_max_humidity: int = int(
            config.get(CONF_MAX_HUMIDITY, DEFAULT_MAX_HUMIDITY)
        )

        # ── Mode support ─────────────────────────────────────────────────────
        modes: list[str] = config.get(CONF_MODES) or []
        if modes:
            self._attr_available_modes = modes
            self._attr_supported_features = HumidifierEntityFeature.MODES
        else:
            self._attr_available_modes = None
            self._attr_supported_features = HumidifierEntityFeature(0)

        # ── Companion entity IDs (None when not configured) ──────────────────
        self._companion: dict[str, str | None] = {
            key: config.get(key) or None for key in ALL_COMPANION_KEYS
        }

        # ── Runtime state ────────────────────────────────────────────────────
        self._attr_is_on: bool = False
        self._attr_target_humidity: int | None = None
        self._attr_current_humidity: float | None = None
        self._attr_mode: str | None = None
        self._attr_available: bool = False

        # Companion attribute values (keyed by COMPANION_ATTR_MAP value)
        self._companion_values: dict[str, Any] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Register state listeners once added to HA."""
        await super().async_added_to_hass()

        # Subscribe to the core climate entity
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._climate_entity_id],
                self._async_climate_changed,
            )
        )

        # Subscribe to every configured companion entity
        companion_ids = [eid for eid in self._companion.values() if eid]
        if companion_ids:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    companion_ids,
                    self._async_companion_changed,
                )
            )

        # Restore previous on/off so HA doesn't flash "unknown" on restart
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._attr_is_on = last_state.state != STATE_OFF

        # Sync immediately from current live states
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
        if new_state is None or entity_id is None:
            return
        self._sync_companion(entity_id, new_state)
        self.async_write_ha_state()

    # ── Internal sync helpers ─────────────────────────────────────────────────

    def _sync_from_climate(self) -> None:
        """Read the climate entity and update our attributes."""
        state = self.hass.states.get(self._climate_entity_id)

        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._attr_available = False
            return

        self._attr_available = True
        self._attr_is_on = state.state != STATE_OFF

        # Target humidity from climate target_temperature
        raw = state.attributes.get("temperature")
        if raw is not None:
            try:
                self._attr_target_humidity = int(float(raw))
            except (ValueError, TypeError):
                pass

        # Current humidity — only use climate fallback when no sensor configured
        if not self._companion.get(CONF_CURRENT_HUMIDITY_ENTITY):
            raw_cur = state.attributes.get("current_temperature")
            if raw_cur is not None:
                try:
                    self._attr_current_humidity = float(raw_cur)
                except (ValueError, TypeError):
                    pass

        # Mode from preset_mode
        if self._attr_available_modes:
            preset = state.attributes.get("preset_mode")
            if preset in self._attr_available_modes:
                self._attr_mode = preset

    def _sync_all_companions(self) -> None:
        """Read all companion entities at startup."""
        for conf_key, entity_id in self._companion.items():
            if not entity_id:
                continue
            state = self.hass.states.get(entity_id)
            if state:
                self._sync_companion(entity_id, state)

    def _sync_companion(self, entity_id: str, state) -> None:
        """Update the cached value for one companion entity."""
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        # Find which conf_key maps to this entity_id
        for conf_key, eid in self._companion.items():
            if eid != entity_id:
                continue
            attr_name = COMPANION_ATTR_MAP.get(conf_key)
            if attr_name is None:
                continue

            if conf_key in COMPANION_BINARY_SENSOR_KEYS:
                # Binary sensors: store as bool
                self._companion_values[attr_name] = state.state == STATE_ON

            elif conf_key in COMPANION_SENSOR_KEYS:
                # Numeric sensors: store as float (or raw string for error codes)
                if conf_key == CONF_CURRENT_HUMIDITY_ENTITY:
                    try:
                        self._attr_current_humidity = float(state.state)
                    except (ValueError, TypeError):
                        _LOGGER.warning(
                            "HKI Humidifier: could not parse current_humidity '%s'",
                            state.state,
                        )
                else:
                    try:
                        self._companion_values[attr_name] = float(state.state)
                    except (ValueError, TypeError):
                        # For error codes / text values keep as-is
                        self._companion_values[attr_name] = state.state

            elif conf_key in COMPANION_SWITCH_KEYS:
                # Switches: store as bool
                self._companion_values[attr_name] = state.state == STATE_ON

            break

    # ── Commands ─────────────────────────────────────────────────────────────

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the dehumidifier on."""
        _LOGGER.debug(
            "HKI Humidifier [%s]: turn_on → set_hvac_mode(%s)",
            self._climate_entity_id,
            self._on_hvac_mode,
        )
        await self.hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {ATTR_ENTITY_ID: self._climate_entity_id, "hvac_mode": self._on_hvac_mode},
            blocking=True,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the dehumidifier off."""
        _LOGGER.debug("HKI Humidifier [%s]: turn_off", self._climate_entity_id)
        await self.hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {ATTR_ENTITY_ID: self._climate_entity_id, "hvac_mode": "off"},
            blocking=True,
        )

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the target humidity (forwarded as target_temperature)."""
        _LOGGER.debug(
            "HKI Humidifier [%s]: set_humidity(%d)", self._climate_entity_id, humidity
        )
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {ATTR_ENTITY_ID: self._climate_entity_id, "temperature": humidity},
            blocking=True,
        )

    async def async_set_mode(self, mode: str) -> None:
        """Set the operating mode (forwarded as preset_mode)."""
        if self._attr_available_modes and mode not in self._attr_available_modes:
            _LOGGER.error(
                "HKI Humidifier: mode '%s' not in available modes %s",
                mode,
                self._attr_available_modes,
            )
            return
        _LOGGER.debug(
            "HKI Humidifier [%s]: set_mode(%s)", self._climate_entity_id, mode
        )
        await self.hass.services.async_call(
            "climate",
            "set_preset_mode",
            {ATTR_ENTITY_ID: self._climate_entity_id, "preset_mode": mode},
            blocking=True,
        )

    # ── Extra state attributes ────────────────────────────────────────────────

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose companion entity states plus diagnostic info."""
        attrs: dict[str, Any] = {
            "source_climate_entity": self._climate_entity_id,
            "on_hvac_mode": self._on_hvac_mode,
        }
        # Add every companion value that has been received
        attrs.update(self._companion_values)
        return attrs
