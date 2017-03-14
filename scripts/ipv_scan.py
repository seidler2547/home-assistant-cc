#!/usr/bin/env python3

import sys
import argparse
import datetime
from time import sleep
from bluepy.btle import Scanner

while True:
    scanner = Scanner()
    try:
        scanner.start()
        for i in range(7):
            scanner.clear()
            scanner.process(3.0)
            for dev in scanner.getDevices():
                scan_data = dev.getScanData()
                scan_map = { d[0]: d[2] for d in scan_data }
                if 255 in scan_map and 8 in scan_map and scan_map[8] == 'IPV':
                    bts = bytes(bytearray.fromhex(scan_map[255]))
                    temp = bts[0] + (bts[1] / 256.0)
                    print("%f" % temp)
                    with open('/tmp/{}.value'.format(dev.addr), 'w') as f:
                        f.write("{}".format(temp))
                    break
    except:
        pass
    try:
        scanner.stop()
    except:
        pass
    sleep(30)
