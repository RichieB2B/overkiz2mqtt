# overkiz2mqtt
Publish data from OverKiz API to MQTT

Built on the excellent [pyoverkiz library](https://github.com/iMicknl/python-overkiz-api/) this simple script publishes the data from the OverKiz server to MQTT topics.
States are refreshed every minutes, device metadata once per day. This is a limit set by the OverKiz server. set by the OverKiz server.
