"""
Support for Progtime Blue

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/switch.progtime/
"""
import logging
import platform
from datetime import datetime
from random import randint

import voluptuous as vol

from homeassistant.components.switch import (SwitchDevice, PLATFORM_SCHEMA)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.script import Script
from homeassistant.const import (CONF_MAC, CONF_PIN, CONF_NAME)

REQUIREMENTS = ['bluepy']

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_MAC): cv.string,
    vol.Optional(CONF_PIN, default=0): cv.positive_int,
    vol.Optional(CONF_NAME): cv.string,
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Bluetooth switchable outlet."""
    name = config.get(CONF_NAME)
    mac = config.get(CONF_MAC)
    pin = config.get(CONF_PIN)

    add_devices([ProgtimeSwitch(mac, pin, name)])


class ProgtimeSwitch(SwitchDevice):
    """Representation of a Progtime Blue switch."""

    def __init__(self, mac, pin, name):
        """Initialize the WOL switch."""
        self._name = name
        self._mac = mac
        self._pin = pin
        self._state = None
        self.update()

    @property
    def should_poll(self):
        """Poll for status regularly."""
        return False

    @property
    def assumed_state(self):
        """Return if the state is based on assumptions."""
        # Progtime Blue does NOT update the handles when the manual
        # switch button is pressed, so the state may be wrong!
        return True

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._state

    @property
    def name(self):
        """The name of the switch."""
        return self._name

    def turn_on(self):
        """Turn the device on."""
        self._state = True
        self.write_state(bytes([9]))
        self.schedule_update_ha_state()

    def turn_off(self):
        """Turn the device off."""
        self._state = False
        self.write_state(bytes([1]))
        self.schedule_update_ha_state()

    def update(self):
        """Check if device is on and update the state."""
        self.write_state(bytes([]))

    def write_state(self, value):
        from bluepy.btle import Peripheral
        device = None
        try:
            # connect to device
            device = Peripheral(self._mac)
            # send PIN code auth
            device.writeCharacteristic(0x3c, self._pin.to_bytes(4, byteorder = 'little'), True)
            _LOGGER.info("Auth success for {}".format(self._mac))

            # set date+time
            now = datetime.now()
            device.writeCharacteristic(0x25, bytes([now.minute, now.hour, now.day, now.month, now.year - 2000]))

            # handle any outstanding value updates
            if value:
                device.writeCharacteristic(0x35, value, True)
                # writing something here does a "commit"
                device.writeCharacteristic(0x3a, bytes([randint(0,255)]))
                _LOGGER.info("Updated switch to {}".format(value[0]))

            self._state = (device.readCharacteristic(0x35)[0] & 8 > 0)

        except Exception as e:
            _LOGGER.error("Exception: %s ", str(e))
        finally:
            if device is not None:
                device.disconnect()
