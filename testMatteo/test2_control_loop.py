#!/usr/bin/env python

import sys
import time

sys.path.append("/home/ubuntu/RTDE_Python_Client_Library") # path di rtde.rtde ed rtde.rtde_config
import logging

import rtde.rtde as rtde
import rtde.rtde_config as rtde_config

# ------------------------ classes -----------------------------
# Crea un oggetto da inviare (sempre lo stesso)
class SetpPacket:
    def __init__(self): # valori default
        self.speed_slider_mask = 1
        self.speed_slider_fraction = 0.4 

# ---------------- robot communication stuff -------------------
print("\tSetting up initial configuration...")
ROBOT_HOST = "10.4.1.13"
ROBOT_PORT = 30004 
config_filename = "/home/ubuntu/RTDE_Python_Client_Library/testMatteo/control_loop_configuration.xml" # file xml di configurazione (per sincronizzazione dati)

keep_running = True

logging.getLogger().setLevel(logging.INFO)

conf = rtde_config.ConfigFile(config_filename)
state_names, state_types = conf.get_recipe("state")  # Define recipe for access to robot output ex. joints,tcp etc.
setp_names, setp_types = conf.get_recipe("setp") # Define recipe for access to robot input
print("\tSetp names:", setp_names)
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
FREQUENCY = 125 # frequenza di invio dati (Hz), default 125 (8ms)
con.send_output_setup(state_names, state_types, FREQUENCY)
# Prova a fare setup degli input (critico)
try:
    setp = con.send_input_setup(setp_names, setp_types) # Configure an input package that the external application will send to the robot controller
    print("Input setup completato.")
    use_manual_setp = False
except ValueError as e:
    print("Input già usati nel robot:", e)
    use_manual_setp = True

# setting up initial inputs values
print("\tSetting up initial inputs...")
#setp.speed_slider_mask = 0 # disabilito slider mask 
#setp.speed_slider_fraction = 0 # imposto slider fraction ad 1 (se viene attivata la mask mantiene la velocità di default)

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

    # invio pacchetto
    if use_manual_setp:
        setp_packet = SetpPacket()
    
    con.send(setp_packet)


    keep_running = False

    '''
    # do something...
    if move_completed and state.output_int_register_0 == 1:
        move_completed = False
        new_setp = setp1 if setp_to_list(setp) == setp2 else setp2
        list_to_setp(setp, new_setp)
        print("New pose = " + str(new_setp))
        # send new setpoint
        con.send(setp)
        watchdog.input_int_register_0 = 1
    elif not move_completed and state.output_int_register_0 == 0:
        print("Move to confirmed pose = " + str(state.target_q))
        move_completed = True
        watchdog.input_int_register_0 = 0
    '''

    
    time.sleep(0.006)

print("\tPausing...")
con.send_pause()

con.disconnect()

print("> Connection closed")