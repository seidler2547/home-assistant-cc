"""
Support for Progtime Blue

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/switch.progtime/
"""
import logging
import platform
import json
from datetime import datetime
from random import randint

import voluptuous as vol

from homeassistant.components.switch import (SwitchDevice, PLATFORM_SCHEMA)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.script import Script
from homeassistant.const import (CONF_MAC, CONF_PIN, CONF_NAME)
import homeassistant.components.mqtt as mqtt
from homeassistant.core import callback

REQUIREMENTS = ['paho-mqtt']
DEPENDENCIES = ['mqtt']

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
        """Initialize the switch."""
        self._name = name
        self._mac = mac.lower()
        self._pin = pin
        self._state = None

    @property
    def should_poll(self):
        """Poll for status regularly."""
        return False

    @property
    def assumed_state(self):
        """Return if the state is based on assumptions."""
        return False

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
        self.write_state()
        self.schedule_update_ha_state()

    def turn_off(self):
        """Turn the device off if an off action is present."""
        self._state = False
        self.write_state()
        self.schedule_update_ha_state()

    def async_added_to_hass(self):
        """Subscribe mqtt events.
        This method must be run in the event loop and returns a coroutine.
        """
        @callback
        def adv_received(topic, payload, qos):
            """A new MQTT message has been received."""
            onoff = payload[7:8]
            if onoff == '1':
                self._state = False
            if onoff == '9':
                self._state = True
            # 01 = remote off
            # f9 = local on
            # e1 = local off
            # 19 = remote on
            self.hass.async_add_job(self.async_update_ha_state())

        yield from mqtt.async_subscribe(self.hass, 'ble/{}/advertisement/ff'.format(self._mac), adv_received, 1)
        #yield from mqtt.async_subscribe(self.hass, 'ble/{}/data/+'.format(self._mac), data_received, 1)

    def write_state(self):
        cmds = { 'tries': 5,
                 'commands': [
                    { 'action': 'writeCharacteristic', 'handle': 0x3c, 'value': [ int(x) for x in self._pin.to_bytes(4, byteorder = 'little') ] },
                  ]
               }
        now = datetime.now()
        cmds['commands'].append({ 'action': 'writeCharacteristic', 'handle': 0x25, 'value': [ now.minute, now.hour, now.day, now.month, now.year - 2000 ] })
        if self._state:
            cmds['commands'].append({ 'action': 'writeCharacteristic', 'handle': 0x35, 'value': [ 9 ] })
        else:
            cmds['commands'].append({ 'action': 'writeCharacteristic', 'handle': 0x35, 'value': [ 1 ] })
        cmds['commands'].append({ 'action': 'writeCharacteristic', 'handle': 0x3a, 'value': [ randint(0,255) ] })
        mqtt.publish(self.hass, 'ble/{}/commands'.format(self._mac), json.dumps(cmds), 1, False)
