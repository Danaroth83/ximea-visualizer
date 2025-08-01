import imagingcontrol4 as ic4


def format_device_info(device_info: ic4.DeviceInfo) -> str:
    return f"Model: {device_info.model_name} Serial: {device_info.serial}"


def print_device_list():
    print("Enumerating all attached video capture devices...")

    device_list = ic4.DeviceEnum.devices()

    if len(device_list) == 0:
        print("No devices found")
        return

    print(f"Found {len(device_list)} devices:")

    for device_info in device_list:
        print(format_device_info(device_info))


def print_interface_device_tree():
    print("Enumerating video capture devices by interface...")

    interface_list = ic4.DeviceEnum.interfaces()

    if len(interface_list) == 0:
        print("No interfaces found")
        return

    for itf in interface_list:
        print(f"Interface: {itf.display_name}")
        print(f"\tProvided by {itf.transport_layer_name} [TLType: {str(itf.transport_layer_type)}]")

        device_list = itf.devices

        if len(device_list) == 0:
            print("\tNo devices found")
            continue

        print(f"\tFound {len(device_list)} devices:")

        for device_info in device_list:
            print(f"\t\t{format_device_info(device_info)}")


def handle_device_list_changed(device_enum: ic4.DeviceEnum):
    print("Device list changed!")

    print(f"Found {len(ic4.DeviceEnum.devices())} devices")

    print(ic4.DeviceEnum.devices())


def example_device_list_changed():
    enumerator = ic4.DeviceEnum()

    token = enumerator.event_add_device_list_changed(handle_device_list_changed)

    print("Waiting for DeviceListChanged event")
    print("Press Enter to exit")
    input()

    # Technically, this is not necessary, because the enumerator object is deleted when the function is exited
    # But for demonstration purposes, the event handler is removed:
    enumerator.event_remove_device_list_changed(token)


def main():
    ic4.Library.init()

    print_device_list()
    print_interface_device_tree()
    example_device_list_changed()


if __name__ == "__main__":
    main()
