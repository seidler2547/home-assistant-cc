# Comet Blue thermostats

 - reads beacons sent out by devices to find out about current state, thus no polling
 - active connection is only made to change settings
 - MQQT bridge automatically retries BTLE connections
 - indicates connection failures/no beacons using icon
 - sets correct time/date and desired PIN if not already set

__Working features:__
 - set desired temp
 - show measured temp
 - read battery level (show using icon)
 - set mode (auto, manual, manual_locked, auto_locked)

Also possible, but not implemented, partially because no HA support:
 - set timer plan
 - detect "window open" state
 - set warm/cold temperature
