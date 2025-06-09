from pyModbusTCP.client import ModbusClient

c = ModbusClient(host="10.4.1.13", port=502, unit_id=1)
regs = c.read_holding_registers(85, 1)

if regs:
    print(regs)
else:
    print("read error")

# if c.write_multiple_registers(10, [44,55, 45, 33, 22, 11, 12]):
#     print("write ok")
# else:
#     print("write error")


# regs = c.read_holding_registers(10, 10)

# if regs:
#     print(regs)
# else:
#     print("read error")