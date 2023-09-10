# overkiz2mqtt
Publish data from Overkiz API to MQTT

Built on the excellent [pyoverkiz library](https://github.com/iMicknl/python-overkiz-api/) this simple script publishes the data from the Overkiz server to MQTT topics.
States are refreshed every minute, device metadata once per day. This is a limit set by the Overkiz server.

I use this together with [simple-mqtt-exporter](https://github.com/RichieB2B/simple-mqtt-exporter/blob/main/examples/config-cozytouch.py) to export the Overkiz states to a Prometheus database.
