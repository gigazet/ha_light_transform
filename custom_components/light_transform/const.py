"""Integration constants."""

from homeassistant.const import Platform

DOMAIN = "light_transform"
PLATFORMS = [Platform.LIGHT]
CHANNELS = ("red", "green", "blue")
RGB_MODES = {"rgb", "hs", "xy"}
ACK_TIMEOUT = 5.0
