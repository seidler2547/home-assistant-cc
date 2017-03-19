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

from datetime import (timedelta, datetime)

import voluptuous as vol

from homeassistant.components.climate import (
    ClimateDevice,
    PLATFORM_SCHEMA,
    PRECISION_HALVES,
    STATE_AUTO,
    STATE_ON,
    STATE_OFF,
)
from homeassistant.const import (
    CONF_MAC,
    CONF_NAME,
    CONF_PIN,
    TEMP_CELSIUS,
    CONF_DEVICES,
    ATTR_TEMPERATURE)

import homeassistant.helpers.config_validation as cv

from homeassistant.util import Throttle

REQUIREMENTS = ['bluepy']

_LOGGER = logging.getLogger(__name__)

STATE_AUTO_LOCKED = "auto_locked"
STATE_MANUAL = "manual"
STATE_MANUAL_LOCKED = "manual_locked"

MODE_TO_CODE = {
    STATE_AUTO: 0x00,
    STATE_AUTO_LOCKED: 0x80,
    STATE_MANUAL: 0x01,
    STATE_MANUAL_LOCKED: 0x81 }
CODE_TO_MODE = {
    0x00: STATE_AUTO,
    0x80: STATE_AUTO_LOCKED,
    0x01: STATE_MANUAL,
    0x81: STATE_MANUAL_LOCKED }



ATTR_VENDOR_NAME = 'vendor_name'
ATTR_MODEL = 'model'
ATTR_FIRMWARE = 'firmware'
ATTR_VERSION = 'version'
ATTR_TARGET = 'target_temp'
ATTR_BATTERY = 'battery_level'

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=10)
SCAN_INTERVAL = timedelta(seconds=10)
READ_UPDATE_FACTOR = 6

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


# pylint: disable=import-error
class SygonixBTThermostat(ClimateDevice):
    """Representation of a Sygonix-compatible Bluetooth thermostat."""

    def __init__(self, mac, pin, name):
        """Initialize the thermostat."""
        self.modes = [ STATE_AUTO, STATE_AUTO_LOCKED, STATE_MANUAL, STATE_MANUAL_LOCKED ]

        self._mac = mac
        self._name = name
        self._model = 1
        self._pin = pin
        self._target = None
        self._state = None
        self._temp = None
        self._vname = None
        self._model = None
        self._firmw = None
        self._versn = None
        self._batty = None
        self._opmod = None
        self._updates = {}
        self._lastupdate = 0

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
    def current_temperature(self):
        """Return current temperature."""
        return self._temp

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if  temperature < self.min_temp:
            temperature = self.min_temp
        if  temperature > self.max_temp:
            temperature = self.max_temp
        self._target = temperature
        self._updates[0x3f] = bytes([128,int(self._target*2),128,128,128,128,128])

    @property
    def current_operation(self):
        """Current mode."""
        return self._opmod

    @property
    def operation_list(self):
        """List of available operation modes."""
        return self.modes

    def set_operation_mode(self, operation_mode):
        """Set operation mode."""
        if not operation_mode in MODE_TO_CODE:
            return
        self._opmod = operation_mode
        self._updates[0x3d] = bytes([MODE_TO_CODE[self._opmod],0,0])

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return 8.0

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return 30.0


    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        if self._lastupdate < -10:
            return 'mdi:bluetooth-off'
        if self._batty is None:
            return 'mdi:bluetooth-off'
        if self._batty == 100:
            return 'mdi:battery'
        if self._batty == 0:
            return 'mdi:battery-alert'
        if self._batty < 10:
            return 'mdi:battery-outline'
        if 10 <= self._batty <= 99:
            return 'mdi:battery-{}0'.format(int(self._batty/10))
        return None

    @property
    def device_state_attributes(self):
        """Return the device specific state attributes."""
        return {
            ATTR_VENDOR_NAME: self._vname,
            ATTR_MODEL:       self._model,
            ATTR_FIRMWARE:    self._firmw,
            ATTR_VERSION:     self._versn,
            ATTR_BATTERY:     self._batty,
            ATTR_TARGET:      self._state,
        }

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Update the data from the thermostat."""
        from bluepy.btle import Peripheral

        _LOGGER.info("Update called, lastupdate = {} and updates = {}".format(self._lastupdate, self._updates))

        if self._updates:
            self._lastupdate = 0
        else:
            self._lastupdate -= 1

        if self._lastupdate < 1:
            device = None
            try:
                # connect to device
                device = Peripheral(self._mac)
                # send PIN code auth
                device.writeCharacteristic(0x47, self._pin.to_bytes(4, byteorder = 'little'), True)
                _LOGGER.info("Auth success for {}".format(self._mac))

                # set date+time
                now = datetime.now()
                device.writeCharacteristic(0x1d, bytes([now.minute, now.hour, now.day, now.month, now.year - 2000]))

                # handle any outstanding value updates
                for handle, values in list(self._updates.items()):
                    device.writeCharacteristic(handle, values, True)
                    _LOGGER.info("Updated handle {}".format(handle))
                    del self._updates[handle]

                # read current and target temp
                data = device.readCharacteristic(0x3f)
                self._temp = (data[0])/2
                self._state = (data[1])/2

                # if target temp is unkown to hass, use current value from device
                if self._target is None:
                    self._target = self._state

                # Read OP-Mode
                opmode = device.readCharacteristic(0x3d)[0]
                if (opmode in CODE_TO_MODE):
                    self._opmod = CODE_TO_MODE[opmode]
                else:
                    _LOGGER.error("OP-Mode {:02x} unknown!".format(opmode))

                if self._opmod == STATE_MANUAL_LOCKED and self._state != self._target:
                    self.set_temperature(ATTR_TEMPERATURE=self._target)

                # battery value in percent
                self._batty = device.readCharacteristic(0x41)[0]

                # some string descriptors
                if (self._vname is None):
                    self._vname = device.readCharacteristic(0x1a).decode('utf-8')
                if (self._model is None):
                    self._model = device.readCharacteristic(0x14).decode('utf-8')
                if (self._firmw is None):
                    self._firmw = device.readCharacteristic(0x18).decode('utf-8')
                if (self._versn is None):
                    self._versn = device.readCharacteristic(0x16).decode('utf-8')

                # successful update, schedule next in 6*10 seconds
                self._lastupdate = READ_UPDATE_FACTOR
            except Exception as e:
                _LOGGER.error("Exception: %s ", str(e))
            finally:
                if device is not None:
                    device.disconnect()
