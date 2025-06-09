
import sys
import time


sys.path.append("/home/ubuntu/RTDE_Python_Client_Library") # path di rtde.rtde ed rtde.rtde_config
# import logging
import rtde.rtde as rtde
import rtde.rtde_config as rtde_config
import time

print("\tSetting up initial configuration...")
ROBOT_HOST = "10.4.1.87"
ROBOT_PORT = 30004 
CONFIG_XML = '/home/ubuntu/RTDE_Python_Client_Library/dtazzioli/control_loop_configuration.xml'

conf = rtde_config.ConfigFile(CONFIG_XML)
# output_names, output_types = conf.get_recipe('setp')
input_names, input_types = conf.get_recipe('in')
output_names, output_types = conf.get_recipe('out')

con = rtde.RTDE(ROBOT_HOST, ROBOT_PORT)
con.connect()


print(output_names)
print(output_types)
print(input_names)
print(input_types)
# Setup input/output


# con.send_output_setup(output_names, output_types)
con.send_input_setup(input_names, input_types)

# Avvia lo streaming
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
print("\tSetting up recipes...")
FREQUENCY = 3 # frequenza di ricezione dati (Hz), default 125 (8ms)
con.send_output_setup(output_names, output_types, FREQUENCY)


print("\tSetting up initial inputs...")

# start data synchronization
if not con.send_start():
    sys.exit()
print("> Synchronization started, starting loop...")
# Crea pacchetto input
state = con.receive()
print(state.actual_TCP_speed)
if state:
    input_data = con.send_input_setup(input_names, input_types)
    input_data.speed_slider_mask = 1  # bitmask per abilitare lo speed_slider_fraction
    input_data.speed_slider_fraction = 0.2  # ad esempio 50% della velocità
    con.send(input_data)

state = con.receive()
print(state.actual_TCP_speed)

time.sleep(1)
con.disconnect()

