"""
Does not work unless HASS is run as root, BLE scanning is restricted to root

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.ipv
"""
import logging
from datetime import timedelta

import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (CONF_MAC, CONF_NAME, TEMP_CELSIUS)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity

REQUIREMENTS = ['bluepy']

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=20)
SCAN_INTERVAL = timedelta(seconds=20)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_MAC): cv.string,
    vol.Optional(CONF_NAME): cv.string,
})

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the IPV sensor."""
    mac = config.get(CONF_MAC)
    name = config.get(CONF_NAME)

    add_devices([IPVSensor(mac, name)])
    return True


class IPVSensor(Entity):
    """Implementation of a IPV sensor."""

    def __init__(self, mac, name):
        """Initialize the sensor."""
        self._name = name
        self._mac = mac
        self._state = None

    @property
    def name(self):
        """The name of the sensor."""
        return self._name

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        return TEMP_CELSIUS

    @property
    def state(self):
        """Return the state of the resources."""
        return self._state

    def update(self):
        """Get the latest data from BLE advertising frames."""
        from bluepy.btle import Scanner

        scanner = Scanner()
        try:
            scanner.start()

            for i in range(12):
                scanner.clear()
                scanner.process(1.0)
                for dev in scanner.getDevices():
                    if dev.addr == self._mac:
                        scan_data = dev.getScanData()
                        scan_map = { d[0]: d[2] for d in scan_data }
                        bts = bytes(bytearray.fromhex(scan_map[255]))
                        self._state = bts[0] + (bts[1] / 256.0)
                        return

        except Exception as e:
            _LOGGER.error("Exception: %s ", str(e))
        finally:
            scanner.stop
