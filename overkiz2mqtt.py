#!/usr/bin/env python3

import os
import sys
import time
import jsons
import logging
import asyncio
import aiohttp
import paho.mqtt.client as mqtt
import argparse

from pyoverkiz.const import SUPPORTED_SERVERS
from pyoverkiz.client import OverkizClient
from pyoverkiz.models import State, EventState
from pyoverkiz.exceptions import OverkizException, TooManyRequestsException, BadCredentialsException, NotAuthenticatedException
from aiohttp.client_exceptions import ServerDisconnectedError, ClientOSError
catch_exceptions = (TooManyRequestsException, NotAuthenticatedException, ServerDisconnectedError, ClientOSError)

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

def on_connect(client, userdata, flags, rc):
  codes = [
    'Connection successful',
    'Connection refused – incorrect protocol version',
    'Connection refused – invalid client identifier',
    'Connection refused – server unavailable',
    'Connection refused – bad username or password',
    'Connection refused – not authorised',
  ]
  if rc!=0:
    if rc > 0 and rc < 6:
      print(codes[rc])
    else:
      print(f'Bad connection, unknown return code: {rc}')
    os._exit(1)

def mqtt_init():
  client = mqtt.Client()
  if hasattr(config, 'mqtt_username') and hasattr(config, 'mqtt_password'):
    client.username_pw_set(config.mqtt_username, config.mqtt_password)
  client.on_connect=on_connect
  client.connect(config.mqtt_broker)
  client.loop_start()
  return client

async def on_request_start(session, context, params):
  logging.getLogger('aiohttp.client').debug(f'Starting request <{params}>')

async def on_request_end(session, context, params):
  logging.getLogger('aiohttp.client').debug(f'Request end <{params}>')
  logging.getLogger('aiohttp.client').debug(await params.response.text())

async def main() -> None:
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
      print(f'{type(e).__name__} during login: {str(e)}')
      # Sleep for a while before retrying credentials
      if isinstance(e, BadCredentialsException):
        time.sleep(300)
      return
    devices_fresh = 0
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
          print(f'{type(e).__name__} during get_devices(): {str(e)}')
          return
        devices_fresh = time.time()
      for device in devices:
        # execute command every sleep cycle
        if hasattr(config, 'device_name') and hasattr(config, 'device_command') and device.controllable_name == config.device_name:
          try:
            await client.execute_command(device.device_url, config.device_command)
          except catch_exceptions as e:
            print(f'{type(e).__name__} while executing {config.device_command}: {str(e)}')
            return

        # get current states
        try:
          states = await client.get_state(device.device_url)
          data_received = True
        except catch_exceptions as e:
          print(f'{type(e).__name__} during get_state(): {str(e)}')
          return
        if states:
          publish_states(device.controllable_name, states)

      if data_received:
        fresh = time.time()
      else:
        if time.time() - fresh > 600:
          print(f"Exiting, too long since last state update")
          sys.exit(1)

      # print incoming events while waiting to start next loop iteration
      for i in range(0, getattr(config, 'sleep', 60), 2):
        try:
          events = await client.fetch_events()
        except catch_exceptions as e:
          print(f'{type(e).__name__} during fetch_events(): {str(e)}')
          return
        for event in events:
          event_string = jsons.dumps(event, strip_nulls=True)
          logging.debug(f'Publishing {config.mqtt_topic}/events -> {event_string}')
          mqtt_client.publish(f'{config.mqtt_topic}/events', event_string)
        await asyncio.sleep(2)

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

  mqtt_client = mqtt_init()

  asyncio.run(main())
