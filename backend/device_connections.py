from netmiko import ConnectHandler
import json

commands = {
    "Interface Description": "show interfaces description",
    "Device Uptime": "show version | include uptime",
    "System Version": "show version | include Version",
    "Run": "show running-config"
}

devices = {
    "SW1": {
        "device_type": "cisco_ios",
        "host": "10.0.10.99",
        "username": "admin",
        "password": "eve",
        "secret": "eve"
    },

    "RT1": {
        "device_type": "cisco_ios",
        "host": "10.0.10.1",
        "username": "admin",
        "password": "eve",
        "secret": "eve"
    }
}


def parse_interface_description(output):

    interfaces = []

    lines = output.splitlines()

    header = lines[0]

    status_position = header.find("Status")
    protocol_position = header.find("Protocol")
    description_position = header.find("Description")

    for line in lines[1:]:

        if not line.strip():
            continue

        interface = {
            "interface": line[:status_position].strip(),
            "status": line[status_position:protocol_position].strip(),
            "protocol": line[protocol_position:description_position].strip(),
            "description": line[description_position:].strip()
        }

        interfaces.append(interface)

    return interfaces


def parse_device_uptime(output):

    output = output.strip()

    if " uptime is " in output:

        hostname, uptime = output.split(" uptime is ", 1)

        return {
            "hostname": hostname,
            "uptime": uptime
        }

    return output


def parse_system_version(output):

    output = output.strip()

    values = output.split()

    version = ""

    for index, value in enumerate(values):

        if value == "Version":
            version = values[index + 1].rstrip(",")
            break

    return {
        "version": version,
        "full_output": output
    }


network_data = {}

for device_name, device_info in devices.items():

    connection = ConnectHandler(**device_info)
    connection.enable()

    network_data[device_name] = {}

    for command_name, command in commands.items():

        output = connection.send_command(command)

        print(f"{device_name} -- {command_name}\n")
        print(output)

        if command_name == "Interface Description":

            network_data[device_name][command_name] = parse_interface_description(output)

        elif command_name == "Device Uptime":

            network_data[device_name][command_name] = parse_device_uptime(output)

        elif command_name == "System Version":

            network_data[device_name][command_name] = parse_system_version(output)

        else:

            # Store running-config as raw text
            network_data[device_name][command_name] = output

    connection.disconnect()


with open("network_data.json", "w") as json_file:
    json.dump(network_data, json_file, indent=4)

print("\nJSON file created successfully.")
