#!/usr/bin/env python3

import os
import sys
import time
import json
import jsons
import logging
import asyncio
import aiohttp
import paho.mqtt.client as mqtt
import argparse
import requests

from pyoverkiz.const import SUPPORTED_SERVERS
from pyoverkiz.client import OverkizClient
from pyoverkiz.models import Command, State, EventState
from pyoverkiz.exceptions import OverkizException, TooManyRequestsException, BadCredentialsException, NotAuthenticatedException
from aiohttp.client_exceptions import ServerDisconnectedError, ClientOSError, ClientConnectorError
from aiohttp.http_exceptions import BadHttpMessage
catch_exceptions = (
  TooManyRequestsException,
  NotAuthenticatedException,
  ServerDisconnectedError,
  ClientOSError,
  ClientConnectorError,
  BadHttpMessage,
  TimeoutError,
  asyncio.TimeoutError,
)

import config

def serialize_state(state, **kwargs):
  if kwargs.get('strip_nulls') and state.value is None:
    return None
  else:
    return({'name': state.name, 'type': state.type.name, 'value': state.value})

def publish_states(device_name, states):
  message = jsons.dumps({s.name: s.value for s in states})
  logging.debug(f'Publishing {config.mqtt_topic}/{device_name}/states -> {message}')
  mqtt_client.publish(f'{config.mqtt_topic}/{device_name}/states', message)

def on_connect(client, userdata, flags, rc, properties=None):
  codes = [
    'Connection successful',
    'Connection refused – incorrect protocol version',
    'Connection refused – invalid client identifier',
    'Connection refused – server unavailable',
    'Connection refused – bad username or password',
    'Connection refused – not authorised',
  ]
  if rc!=0:
    if hasattr(mqtt, 'CallbackAPIVersion'):
      logging.error(rc)
    elif rc > 0 and rc < 6:
      logging.error(codes[rc])
    else:
      logging.error(f'Bad connection, unknown return code: {rc}')
    os._exit(1)

mqtt_command = {}
def on_message(client, userdata, msg):
  global mqtt_command
  logging.debug(f'MQTT message received {msg.topic}: {msg.payload}')
  try:
    payload = str(msg.payload.decode("utf-8","strict"))
    content = json.loads(payload)
  except Exception as e:
    logging.error(f'{type(e)}: {str(e)} while decoding topic {msg.topic}')
    return
  mqtt_command = content

def mqtt_init():
  if hasattr(mqtt, 'CallbackAPIVersion'):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
  else:
    client = mqtt.Client()
  if hasattr(config, 'mqtt_username') and hasattr(config, 'mqtt_password'):
    client.username_pw_set(config.mqtt_username, config.mqtt_password)
  client.on_connect=on_connect
  client.on_message=on_message
  client.connect(config.mqtt_broker)
  client.subscribe(config.mqtt_topic + '/commands')
  client.loop_start()
  return client

async def on_request_start(session, context, params):
  logging.getLogger('aiohttp.client').debug(f'Starting request <{params}>')

async def on_request_end(session, context, params):
  logging.getLogger('aiohttp.client').debug(f'Request end <{params}>')
  logging.getLogger('aiohttp.client').debug(await params.response.text())

async def execute_overkiz_command(client, url, command, params=[]):
  if not url or not command:
    logging.error(f'No device_url ({url}) or command ({command}) given')
    return
  if not isinstance(params, list):
    logging.error(f'params for command {command} should be a list, not {type(params).__name__}: {params}')
    return
  parameters = [param for param in params if param is not None]
  logging.debug(f'Executing command {command} with parameters {parameters}')
  try:
    await client.execute_command(url, Command(command, parameters), "overkiz2mqtt")
  except catch_exceptions as e:
    logging.error(f'{type(e).__name__} while executing {command}{parameters}: {str(e)}')
    if isinstance(e, TooManyRequestsException):
        logging.error(f'Exiting')
        sys.exit(0)
  return

async def main() -> None:
  global mqtt_command
  jsons.set_serializer(serialize_state, State)
  jsons.set_serializer(serialize_state, EventState)
  if args.debug:
    trace_config = aiohttp.TraceConfig()
    trace_config.on_request_start.append(on_request_start)
    trace_config.on_request_end.append(on_request_end)
    trace_configs = [trace_config]
  else:
    trace_configs = []

  async with OverkizClient(config.username,
                           config.password,
                           server=SUPPORTED_SERVERS[config.server],
                           session=aiohttp.ClientSession(trace_configs=trace_configs)) as client:
    try:
      await client.login()
    except Exception as e:  # pylint: disable=broad-except
      logging.error(f'{type(e).__name__} during login: {str(e)}')
      # Sleep for a while before retrying credentials
      if isinstance(e, BadCredentialsException):
        time.sleep(300)
      return
    devices_fresh = 0
    device_urls = {}
    # Start loop
    fresh = time.time()
    while True:
      data_received = False
      # refresh devices once per day
      if time.time() - devices_fresh >= 3600 * 24:
        try:
          devices = await client.get_devices(refresh=True)
          for device in devices:
            message = jsons.dumps(device)
            logging.debug(f'Publishing {config.mqtt_topic}/{device.controllable_name} -> {message}')
            mqtt_client.publish(f'{config.mqtt_topic}/{device.controllable_name}', message, retain=True)
            publish_states(device.controllable_name, device.states)
        except catch_exceptions as e:
          logging.error(f'{type(e).__name__} during get_devices(): {str(e)}')
          return
        devices_fresh = time.time()
      for device in devices:
        device_urls[device.controllable_name] = device.device_url
        # execute command every sleep cycle
        if hasattr(config, 'device_name') and hasattr(config, 'device_command') and device.controllable_name == config.device_name:
          await execute_overkiz_command(client, device.device_url, config.device_command, getattr(config, 'device_command_params', []))

        # get current states
        try:
          states = await client.get_state(device.device_url)
          data_received = True
        except catch_exceptions as e:
          logging.error(f'{type(e).__name__} during get_state(): {str(e)}')
          return
        if states:
          publish_states(device.controllable_name, states)

      if data_received:
        fresh = time.time()
      else:
        if time.time() - fresh > 600:
          logging.error(f"Exiting, too long since last state update")
          sys.exit(1)

      #  while waiting to start next loop iteration
      for i in range(0, getattr(config, 'sleep', 60), 2):
        # execute command received from mqtt if device name matches
        if mqtt_command and mqtt_command.get('device', '') in device_urls:
          await execute_overkiz_command(client, device_urls[mqtt_command['device']], mqtt_command.get('command', None), mqtt_command.get('params', []))
          mqtt_command = {}

        # print incoming events
        try:
          events = await client.fetch_events()
        except catch_exceptions as e:
          logging.error(f'{type(e).__name__} during fetch_events(): {str(e)}')
          return
        for event in events:
          event_string = jsons.dumps(event, strip_nulls=True)
          logging.debug(f'Publishing {config.mqtt_topic}/events -> {event_string}')
          mqtt_client.publish(f'{config.mqtt_topic}/events', event_string)
        await asyncio.sleep(2)

def cozytouch_maintenance():
  try:
    response = requests.get('https://azfun-messconsapi-prod-001.azurewebsites.net/api/GetMaintenanceMessages?code=8u2u6Xh81oivTob0pxClHA5LaJp3tx-Ah9mg9o3a5BIAAzFuaKoRCw%3D%3D&application=gacoma&environment=production&appversion=3.7.10&lang=en_GB', timeout=30)
  except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
    logging.error(f'{type(e).__name__} during cozytouch_maintenance(): {str(e)}')
    sys.exit(1)
  logging.debug(response.content)
  try:
    result = response.json()
  except:
    return False
  return result.get('forceMaintenance', False)

if __name__ == '__main__':
  sys.stdout.reconfigure(line_buffering=True)
  sys.stderr.reconfigure(line_buffering=True)
  parser = argparse.ArgumentParser()
  parser.add_argument("-d", "--debug", help="debug mode", action='store_true')
  args = parser.parse_args()

  if args.debug:
    level=logging.DEBUG
  else:
    level=logging.INFO
  logging.basicConfig(level=level)

  if config.server == 'atlantic_cozytouch' and cozytouch_maintenance():
    logging.warning('Cozytouch API is in maintenance: exiting')
    sys.exit(0)

  mqtt_client = mqtt_init()

  asyncio.run(main())
