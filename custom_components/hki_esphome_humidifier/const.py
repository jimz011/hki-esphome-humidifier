"""Constants for HKI ESPHome Humidifier Converter."""

DOMAIN = "hki_esphome_humidifier"

# ─── Config-entry / YAML keys ────────────────────────────────────────────────

# Core (required)
CONF_CLIMATE_ENTITY = "climate_entity"

# Core (optional)
CONF_NAME = "name"
CONF_ON_HVAC_MODE = "on_hvac_mode"
CONF_MIN_HUMIDITY = "min_humidity"
CONF_MAX_HUMIDITY = "max_humidity"
CONF_MODES = "modes"

# Optional companion sensor entities
CONF_CURRENT_HUMIDITY_ENTITY = "current_humidity_entity"
CONF_TANK_LEVEL_ENTITY = "tank_level_entity"
CONF_PM25_ENTITY = "pm25_entity"
CONF_ERROR_ENTITY = "error_entity"

# Optional companion binary-sensor entities
CONF_BUCKET_FULL_ENTITY = "bucket_full_entity"
CONF_CLEAN_FILTER_ENTITY = "clean_filter_entity"
CONF_DEFROST_ENTITY = "defrost_entity"

# Optional companion switch entities
CONF_IONIZER_ENTITY = "ionizer_entity"
CONF_PUMP_ENTITY = "pump_entity"
CONF_SLEEP_ENTITY = "sleep_entity"
CONF_BEEP_ENTITY = "beep_entity"

# ─── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_NAME = "HKI Dehumidifier"
DEFAULT_MIN_HUMIDITY = 30
DEFAULT_MAX_HUMIDITY = 80
DEFAULT_ON_HVAC_MODE = "dry"

# ─── Grouped companion keys ──────────────────────────────────────────────────

COMPANION_SENSOR_KEYS = [
    CONF_CURRENT_HUMIDITY_ENTITY,
    CONF_TANK_LEVEL_ENTITY,
    CONF_PM25_ENTITY,
    CONF_ERROR_ENTITY,
]

COMPANION_BINARY_SENSOR_KEYS = [
    CONF_BUCKET_FULL_ENTITY,
    CONF_CLEAN_FILTER_ENTITY,
    CONF_DEFROST_ENTITY,
]

COMPANION_SWITCH_KEYS = [
    CONF_IONIZER_ENTITY,
    CONF_PUMP_ENTITY,
    CONF_SLEEP_ENTITY,
    CONF_BEEP_ENTITY,
]

ALL_COMPANION_KEYS = (
    COMPANION_SENSOR_KEYS
    + COMPANION_BINARY_SENSOR_KEYS
    + COMPANION_SWITCH_KEYS
)

# ─── Extra-state attribute names ─────────────────────────────────────────────

ATTR_BUCKET_FULL = "bucket_full"
ATTR_CLEAN_FILTER = "clean_filter"
ATTR_DEFROST = "defrost"
ATTR_TANK_LEVEL = "tank_level"
ATTR_PM25 = "pm25"
ATTR_ERROR = "error_code"
ATTR_IONIZER = "ionizer"
ATTR_PUMP = "pump"
ATTR_SLEEP = "sleep_mode"
ATTR_BEEP = "beep"

COMPANION_ATTR_MAP = {
    CONF_BUCKET_FULL_ENTITY: ATTR_BUCKET_FULL,
    CONF_CLEAN_FILTER_ENTITY: ATTR_CLEAN_FILTER,
    CONF_DEFROST_ENTITY: ATTR_DEFROST,
    CONF_TANK_LEVEL_ENTITY: ATTR_TANK_LEVEL,
    CONF_PM25_ENTITY: ATTR_PM25,
    CONF_ERROR_ENTITY: ATTR_ERROR,
    CONF_IONIZER_ENTITY: ATTR_IONIZER,
    CONF_PUMP_ENTITY: ATTR_PUMP,
    CONF_SLEEP_ENTITY: ATTR_SLEEP,
    CONF_BEEP_ENTITY: ATTR_BEEP,
}
