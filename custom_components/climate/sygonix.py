"""
Support for EUROtronic Comet Blue thermostats.
Might also work with other thermostats based on the Sygonix firmware,
like Sygonix HT100 BT or Xavax bluetooth thermostat
(In fact, in the Xavax manual on page 4 they forgot to replace "Comet Blue"
with "Wireless Radiator Controller".)

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/climate.sygonix/
"""
import logging
import asyncio
import json

from datetime import (timedelta, datetime)

import voluptuous as vol

from homeassistant.components.climate import (
    ClimateDevice,
    PLATFORM_SCHEMA,
    STATE_AUTO,
    STATE_ON,
    STATE_OFF,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_OPERATION_MODE,
)
from homeassistant.const import (
    CONF_MAC,
    CONF_NAME,
    CONF_PIN,
    TEMP_CELSIUS,
    CONF_DEVICES,
    PRECISION_HALVES,
    ATTR_TEMPERATURE)

from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
import homeassistant.components.mqtt as mqtt

from homeassistant.util import Throttle

REQUIREMENTS = ['paho-mqtt']
DEPENDENCIES = ['mqtt']

_LOGGER = logging.getLogger(__name__)

STATE_AUTO_LOCKED = "auto_locked"
STATE_MANUAL = "manual"
STATE_MANUAL_LOCKED = "manual_locked"


ATTR_VENDOR_NAME = 'vendor_name'
ATTR_MODEL = 'model'
ATTR_FIRMWARE = 'firmware'
ATTR_VERSION = 'version'
ATTR_TARGET = 'target_temp'
ATTR_BATTERY = 'battery_level'
ATTR_WINDOW = 'window_open'

UUID_DATETIME = '47e9ee01-47e9-11e4-8939-164230d1df67'
UUID_MODE =     '47e9ee2a-47e9-11e4-8939-164230d1df67'
UUID_TEMP =     '47e9ee2b-47e9-11e4-8939-164230d1df67'
UUID_BATTERY =  '47e9ee2c-47e9-11e4-8939-164230d1df67'
UUID_PIN =      '47e9ee30-47e9-11e4-8939-164230d1df67'
UUID_MODEL =    '00002a24-0000-1000-8000-00805f9b34fb'
UUID_FIRMWARE = '00002a26-0000-1000-8000-00805f9b34fb'
UUID_SOFTWARE = '00002a28-0000-1000-8000-00805f9b34fb'
UUID_MANU =     '00002a29-0000-1000-8000-00805f9b34fb'

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=300)
SCAN_INTERVAL = timedelta(seconds=300)

DEVICE_SCHEMA = vol.Schema({
    vol.Required(CONF_MAC): cv.string,
    vol.Optional(CONF_PIN, default=0): cv.positive_int,
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_DEVICES):
        vol.Schema({cv.string: DEVICE_SCHEMA}),
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the Sygonix-compatible thermostats."""
    devices = []

    for name, device_cfg in config[CONF_DEVICES].items():
        devices.append(SygonixBTThermostat(device_cfg[CONF_MAC], device_cfg[CONF_PIN], name))

    add_devices(devices)

class SygonixState():
    BIT_MANUAL = 0x01
    BIT_LOCKED = 0x80
    BIT_WINDOW = 0x10

    def __init__(self):
        self.temperature = None
        self.target_temp = None
        self.manual = None
        self.locked = None
        self.window = None
        self._battery_level = None
        self.manufacturer = None
        self.software_rev = None
        self.firmware_rev = None
        self.model_no = None
        self.name = None
        self.last_seen = None
        self.last_talked = None

    @property
    def mode_value(self):
        val = 0
        if self.manual:
            val |= self.BIT_MANUAL
        if self.window:
            val |= self.BIT_WINDOW
        if self.locked:
            val |= self.BIT_LOCKED
        return val

    @mode_value.setter
    def mode_value(self, value):
        self.manual = (value & self.BIT_MANUAL) > 0
        self.window = (value & self.BIT_WINDOW) > 0
        self.locked = (value & self.BIT_LOCKED) > 0

    @property
    def mode_code(self):
        if self.manual is None or self.locked is None:
            return None
        if self.manual:
            if self.locked:
                return STATE_MANUAL_LOCKED
            else:
                return STATE_MANUAL
        else:
            if self.locked:
                return STATE_AUTO_LOCKED
            else:
                return STATE_AUTO

    @mode_code.setter
    def mode_code(self, value):
        if value == STATE_MANUAL:
            self.manual = True
            self.locked = False
        elif value == STATE_MANUAL_LOCKED:
            self.manual = True
            self.locked = True
        elif value == STATE_AUTO:
            self.manual = False
            self.locked = False
        elif value == STATE_AUTO_LOCKED:
            self.manual = False
            self.locked = True

    @property
    def battery_level(self):
        return self._battery_level

    @battery_level.setter
    def battery_level(self, value):
        if value is not None and 0 <= value <= 100:
            self._battery_level = value

    def parse_adv_msg(self, payload):
        data = bytes(bytearray.fromhex(payload))
        self.temperature = float(data[0])/2.0
        self.target_temp = float(data[1])/2.0
        self.battery_level = int(data[2])
        self.mode_value = int(data[3])
        self.last_seen = datetime.now()

    def parse_data(self, handle, payload):
        data = json.loads(payload)
        if handle == UUID_MODEL:
            self.model_no = bytes(data).decode('utf-8')
        elif handle == UUID_FIRMWARE:
            self.firmware_rev = bytes(data).decode('utf-8')
        elif handle == UUID_SOFTWARE:
            self.software_rev = bytes(data).decode('utf-8')
        elif handle == UUID_MANU:
            self.manufacturer = bytes(data).decode('utf-8')
        elif handle == UUID_BATTERY:
            self.battery_level = data[0]
        elif handle == UUID_MODE:
            self.mode_value = data[0]
        elif handle == UUID_TEMP:
            self.temperature = float(data[0])/2.0
            self.target_temp = float(data[1])/2.0
        self.last_talked = datetime.now()

class SygonixBTThermostat(ClimateDevice):
    """Representation of a Sygonix-compatible Bluetooth thermostat."""

    def __init__(self, mac, pin, name):
        """Initialize the thermostat."""
        self.modes = [ STATE_AUTO, STATE_AUTO_LOCKED, STATE_MANUAL, STATE_MANUAL_LOCKED ]

        self._mac = mac.lower()
        self._name = name
        self._pin = pin
        self._current = SygonixState()
        self._target = SygonixState()

    @property
    def available(self) -> bool:
        """Return if thermostat is available."""
        return True

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement that is used."""
        return TEMP_CELSIUS

    @property
    def precision(self):
        """Return precision 0.5."""
        return PRECISION_HALVES

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return (SUPPORT_TARGET_TEMPERATURE | SUPPORT_OPERATION_MODE);

    @property
    def current_temperature(self):
        """Return current temperature."""
        return self._current.temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target.target_temp

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if  temperature < self.min_temp:
            temperature = self.min_temp
        if  temperature > self.max_temp:
            temperature = self.max_temp
        self._target.target_temp = temperature

    @property
    def current_operation(self):
        """Current mode."""
        return self._current.mode_code

    @property
    def operation_list(self):
        """List of available operation modes."""
        return self.modes

    def set_operation_mode(self, operation_mode):
        """Set operation mode."""
        self._target.mode_code = operation_mode

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return 8.0

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return 28.0

    def is_stale(self):
        _LOGGER.info("{} last seen {} last talked {}".format(self._mac, self._current.last_seen, self._current.last_talked))
        now = datetime.now()
        if self._current.last_seen is not None and (now - self._current.last_seen).total_seconds() < 600:
            return False
        if self._current.last_talked is not None and (now - self._current.last_talked).total_seconds() < 600:
            return False
        return True

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        if self.is_stale():
            return 'mdi:bluetooth-off'
        if self._current.battery_level is None:
            return 'mdi:bluetooth-off'
        if self._current.battery_level == 100:
            return 'mdi:battery'
        if self._current.battery_level == 0:
            return 'mdi:battery-alert'
        if self._current.battery_level < 10:
            return 'mdi:battery-outline'
        if 10 <= self._current.battery_level <= 99:
            return 'mdi:battery-{}0'.format(int(self._current.battery_level/10))
        return None

    @property
    def device_state_attributes(self):
        """Return the device specific state attributes."""
        return {
            ATTR_VENDOR_NAME: self._current.manufacturer,
            ATTR_MODEL:       self._current.model_no,
            ATTR_FIRMWARE:    self._current.firmware_rev,
            ATTR_VERSION:     self._current.software_rev,
            ATTR_BATTERY:     self._current.battery_level,
            ATTR_TARGET:      self._current.target_temp,
            ATTR_WINDOW:      self._current.window,
        }

    def async_added_to_hass(self):
        """Subscribe mqtt events.
        This method must be run in the event loop and returns a coroutine.
        """
        @callback
        def adv_received(topic, payload, qos):
            """A new MQTT message has been received."""
            self._current.parse_adv_msg(payload)
            if self._current.target_temp is not None:
                self._target.target_temp = self._current.target_temp
            self.hass.async_add_job(self.async_update_ha_state())

        @callback
        def data_received(topic, payload, qos):
            """A new MQTT message has been received."""
            self._current.parse_data(topic.split('/')[3], payload)
            #self._current.mode_code = self._target.mode_code
            #self._current.target_temp = self._target.target_temp
            self.hass.async_add_job(self.async_update_ha_state())

        yield from mqtt.async_subscribe(self.hass, 'ble/{}/advertisement/ff'.format(self._mac), adv_received, 1)
        yield from mqtt.async_subscribe(self.hass, 'ble/{}/data/+'.format(self._mac), data_received, 1)
        now = datetime.now()
        cmds = { 'tries': 10,
                 'commands': [
                    { 'action': 'readCharacteristic', 'uuid': UUID_MODEL },
                    { 'action': 'readCharacteristic', 'uuid': UUID_FIRMWARE },
                    { 'action': 'readCharacteristic', 'uuid': UUID_SOFTWARE },
                    { 'action': 'readCharacteristic', 'uuid': UUID_MANU },
                    { 'action': 'writeCharacteristic', 'uuid': UUID_PIN, 'value': [ 0, 0, 0, 0 ], 'ignoreError': '1' }, # try PIN 000000 first, in case the thermostat was reset
                    { 'action': 'writeCharacteristic', 'uuid': UUID_PIN, 'value': [ int(x) for x in self._pin.to_bytes(4, byteorder = 'little') ] }, # send real/desired PIN
                    { 'action': 'writeCharacteristic', 'uuid': UUID_DATETIME, 'value': [ now.minute, now.hour, now.day, now.month, now.year - 2000 ] },
                    { 'action': 'readCharacteristic', 'uuid': UUID_MODE },
                    { 'action': 'readCharacteristic', 'uuid': UUID_TEMP },
                    { 'action': 'readCharacteristic', 'uuid': UUID_BATTERY },
                  ]
               }
        mqtt.async_publish(self.hass, 'ble/{}/commands'.format(self._mac), json.dumps(cmds), 1, False)

    def update(self):
        """Update the data from the thermostat."""

        _LOGGER.info("Update called {}".format(self._mac))
        # send update request
        cmds = { 'tries': 5,
                 'commands': [
                    { 'action': 'writeCharacteristic', 'uuid': UUID_PIN, 'value': [ int(x) for x in self._pin.to_bytes(4, byteorder = 'little') ] },
                  ]
               }
        if self._current.mode_code != self._target.mode_code and self._target.manual is not None:
            cmds['commands'].append({ 'action': 'writeCharacteristic', 'uuid': UUID_MODE, 'value': [ self._target.mode_value, 0, 0 ] })

        if self._current.target_temp != self._target.target_temp and self._target.target_temp is not None:
            cmds['commands'].append({ 'action': 'writeCharacteristic', 'uuid': UUID_TEMP, 'value': [ 128, int(self._target.target_temp * 2), 128, 128, 128, 128, 128 ] })

        if len(cmds['commands']) > 1:
            cmds['commands'].append({ 'action': 'readCharacteristic', 'uuid': UUID_MODE })
            cmds['commands'].append({ 'action': 'readCharacteristic', 'uuid': UUID_TEMP })
            cmds['commands'].append({ 'action': 'readCharacteristic', 'uuid': UUID_BATTERY })
            if self._current.model_no is None:
                cmds['commands'].append({ 'action': 'readCharacteristic', 'uuid': UUID_MODEL })
                cmds['commands'].append({ 'action': 'readCharacteristic', 'uuid': UUID_FIRMWARE })
                cmds['commands'].append({ 'action': 'readCharacteristic', 'uuid': UUID_SOFTWARE })
                cmds['commands'].append({ 'action': 'readCharacteristic', 'uuid': UUID_MANU })

            mqtt.publish(self.hass, 'ble/{}/commands'.format(self._mac), json.dumps(cmds), 1, False)
