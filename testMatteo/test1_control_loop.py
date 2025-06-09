#!/usr/bin/env python

import sys
import time

sys.path.append("/home/ubuntu/RTDE_Python_Client_Library") # path di rtde.rtde ed rtde.rtde_config
import logging

import rtde.rtde as rtde
import rtde.rtde_config as rtde_config

# ------------- robot communication stuff -----------------
print("\tSetting up initial configuration...")
ROBOT_HOST = "10.4.1.13"
ROBOT_PORT = 30004 
config_filename = "/home/ubuntu/RTDE_Python_Client_Library/testMatteo/control_loop_configuration.xml" # file xml di configurazione (per sincronizzazione dati)

keep_running = True

logging.getLogger().setLevel(logging.INFO)

conf = rtde_config.ConfigFile(config_filename)
state_names, state_types = conf.get_recipe("state")  # Define recipe for access to robot output ex. joints,tcp etc.
print("> Initial configuration done!")

# -------------------- Establish connection--------------------
print("\tConnecting...")
con = rtde.RTDE(ROBOT_HOST, ROBOT_PORT)
connection_state = con.connect()

# check connection
while connection_state == 0:
    time.sleep(0.5)
    print("\tTrying to connect to host again...")
    connection_state = con.connect()

if con.is_connected():
    print("> Succesfully connected to robot!")
else:
    exit(-2)

# get controller version
con.get_controller_version()

# ------------------- setup recipes ----------------------------
print("\tSetting up recipes...")
FREQUENCY = 3 # frequenza di ricezione dati (Hz), default 125 (8ms)
con.send_output_setup(state_names, state_types, FREQUENCY)

# setting up initial inputs values
print("\tSetting up initial inputs...")

# start data synchronization
if not con.send_start():
    sys.exit()
print("> Synchronization started, starting loop...")
# control loop
while keep_running:
    # receive the current state
    state = con.receive()
    print("\tReceiving current robot state...")

    if state is None:
        break
    print("> Results:")
    print("\tActual TCP speed: ", state.actual_TCP_speed, "\n\tTarget TCP speed: ", state.target_TCP_speed)

    #keep_running = False

print("\tPausing...")
con.send_pause()

con.disconnect()

print("> Connection closed")
