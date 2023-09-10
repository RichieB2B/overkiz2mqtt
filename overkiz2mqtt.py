#!/usr/bin/env python3

import os
import sys
import time
import json
import jsons
import asyncio
import paho.mqtt.client as mqtt
import argparse

from pyoverkiz.const import SUPPORTED_SERVERS
from pyoverkiz.client import OverkizClient
from pyoverkiz.models import State, EventState
from pyoverkiz.exceptions import OverkizException, TooManyRequestsException

import config

def serialize_state(state, **kwargs):
  if kwargs.get('strip_nulls') and state.value is None:
    return None
  else:
    return({'name': state.name, 'type': state.type.name, 'value': state.value})

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

async def main() -> None:
  jsons.set_serializer(serialize_state, State)
  jsons.set_serializer(serialize_state, EventState)
  async with OverkizClient(config.username, config.password, server=SUPPORTED_SERVERS[config.server]) as client:
    try:
      await client.login()
    except Exception as exception:  # pylint: disable=broad-except
      print(exception)
      return
    devices = await client.get_devices()
    devices_fresh = time.time()
    # Start loop
    fresh = time.time()
    while True:
      data_received = False
      # refresh devices once per day
      if time.time() - devices_fresh >= 3600 * 24:
        try:
          devices = await client.get_devices(refresh=True)
        except TooManyRequestsException as e:
          print(f'{type(e).__name__} during get_devices(): {str(e)}')
          return
        devices_fresh = time.time()
      for device in devices:
        # refresh boiler temperature
        if hasattr(config, 'device_name') and hasattr(config, 'device_command') and device.controllable_name == config.device_name:
          try:
            await client.execute_command(device.device_url, config.device_command)
          except TooManyRequestsException as e:
            print(f'{type(e).__name__} while executing {config.device_command}: {str(e)}')
        # build device dict
        dev = {}
        dev['available'] = device.available
        dev['enabled'] = device.enabled
        dev['type'] = device.type.name
        dev['protocol'] = device.protocol.name
        dev['widget'] = device.widget.name
        dev['ui_class'] = device.ui_class.name
        dev['label'] = device.label
        dev['url'] = device.device_url
        attributes = {}
        for state in device.attributes:
          attributes[state.name] = state.value
        if attributes:
          dev['attributes'] = attributes

        if args.debug:
          print("==== DEVICE ==========")
          print(f'available = {device.available}')
          print(f'enabled = {device.enabled}')
          print(f'type = {device.type}')
          print(f'label = {device.label}')
          print(f'controllable_name = {device.controllable_name}')
          print(f'device_url = {device.device_url}')
          print(f'data_properties = {device.data_properties}')
          print("==== ATTRIBUTES ======")
          for state in device.attributes:
            print(f"{state.name} = {state.value}")
          print("==== DEFINITION ======")
          print(f'qualified_name = f{device.definition.qualified_name}')
          print("==== DEFINITION COMMANDS")
          for command in device.definition.commands:
            print(f"command_name = {command.command_name}, nparams = {command.nparams}")
          print("==== DEFINITION STATES")
          for state in device.definition.states:
            print(f"{state.qualified_name} = {state.values}")
          print("==== DEVICE STATES ===")
          for state in device.states:
            print(f"{state.name} = {state.value}")
          print("==== GET_STATE =======")

        states = dev['states'] = {}
        try:
          newstates = await client.get_state(device.device_url)
        except TooManyRequestsException as e:
          print(f'{type(e).__name__} during get_state(): {str(e)}')
          return
        for state in newstates:
          states[state.name] = state.value
          data_received = True
          if args.debug:
            print(f"{state.name} = {state.value}")

        message = json.dumps(dev, default=str)
        if args.debug:
          print(f'{device.controllable_name} -> {message}')
        mqtt_client.publish(f'{config.mqtt_topic}/{device.controllable_name}', message)

      if data_received:
        fresh = time.time()
      else:
        if time.time() - fresh > 600:
          print(f"Exiting, too long since last state update")
          sys.exit(1)
      # print incoming events while waiting to start next loop iteration
      for i in range(0, getattr(config, 'sleep', 60), 2):
        events = await client.fetch_events()
        for event in events:
          event_string = jsons.dumps(event, strip_nulls=True)
          if args.debug:
            print(f'Event: {event_string}')
          mqtt_client.publish(f'{config.mqtt_topic}/events', event_string)
        time.sleep(2)

if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument("-d", "--debug", help="debug mode", action='store_true')
  args = parser.parse_args()

  mqtt_client = mqtt_init()

  asyncio.run(main())
