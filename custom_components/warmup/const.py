"""Constants for the Warmup integration."""

from datetime import timedelta

DOMAIN = "warmup"

SCAN_INTERVAL = timedelta(seconds=60)

CONF_OVERRIDE_MINUTES = "override_minutes"
DEFAULT_OVERRIDE_MINUTES = 60

MANUFACTURER = "Warmup"

# Room.type as reported by the API -> marketing name.
MODELS = {
    "4ie": "4iE",
    "5ie": "5iE",
    "6ie": "6iE",
    "7ie": "7iE",
}

# Address.currency index (Currency4iE enum order). Krone is ambiguous, so it
# is left out and falls back to the Home Assistant currency.
CURRENCIES = {0: "GBP", 1: "EUR", 2: "USD", 3: "CNY", 4: "PLN", 6: "HRK"}

SERVICE_SET_OVERRIDE = "set_override"
SERVICE_CANCEL_OVERRIDE = "cancel_override"
SERVICE_SET_SCHEDULE = "set_schedule"

ATTR_DURATION = "duration"
ATTR_SCHEDULE = "schedule"
ATTR_START = "start"
ATTR_END = "end"
