# overkiz2mqtt
Publish data from Overkiz API to MQTT

Built on the excellent [pyoverkiz library](https://github.com/iMicknl/python-overkiz-api/) this simple script publishes the data from the Overkiz server to MQTT topics.
States are refreshed every minute, device metadata once per day. This is a limit set by the Overkiz server.

I use this together with [simple-mqtt-exporter](https://github.com/RichieB2B/simple-mqtt-exporter/blob/main/examples/config-cozytouch.py) to export the Overkiz states to a Prometheus database.

It is now possible to send commands to the Overkiz device using MQTT. The message should be published to the '/commands' subtopic as a JSON string containing at least a `device` name and `command` name.
If the command requires one or more parameters set them as a JSON list in `params`. Example:

```
mosquitto_pub -u username -P secret -t 'cozytouch/commands' -m '{"device": "io:AtlanticDomesticHotWaterProductionV2_CV4E_IOComponent", "command": "setTargetTemperature", "params": [50]}'
```

Each Overkiz device publishes the command definitions it excepts regularly.
You can inspect them in the MQTT topics of the specifice devices, i.e.  `cozytouch/io:AtlanticDomesticHotWaterProductionV2_CV4E_IOComponent`
```
{
  "attributes": [
    {
      "name": "core:FirmwareRevision",
      "type": "STRING",
      "value": "B668008"
    },
    {
      "name": "core:Manufacturer",
      "type": "STRING",
      "value": "Atlantic Group"
    }
  ],
  "available": true,
  "controllable_name": "io:AtlanticDomesticHotWaterProductionV2_CV4E_IOComponent",
  "data_properties": null,
  "definition": {
    "commands": [
      {
        "command_name": "addLockLevel",
        "nparams": 2
      },
      {
        "command_name": "advancedRefresh",
        "nparams": 2
      },
      {
        "command_name": "delayedStopIdentify",
        "nparams": 1
      },
      {
        "command_name": "getName",
        "nparams": 0
      },
      {
        "command_name": "identify",
        "nparams": 0
      },
```
