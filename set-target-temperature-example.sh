#!/bin/sh

mosquitto_pub -u username -P secret -t 'cozytouch/commands' -m '{"device": "io:AtlanticDomesticHotWaterProductionV2_CV4E_IOComponent", "command": "setTargetTemperature", "params": [50]}'
