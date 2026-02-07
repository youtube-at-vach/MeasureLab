import sounddevice as sd

def check_sample_rates(device_id, is_input=False):
    rates = [44100, 48000, 88200, 96000, 192000]
    supported = []
    print(f"Checking {'input' if is_input else 'output'} rates for device {device_id}...")

    for r in rates:
        try:
            if is_input:
                sd.check_input_settings(device=device_id, samplerate=r)
            else:
                sd.check_output_settings(device=device_id, samplerate=r)
            print(f"  {r}: Supported")
            supported.append(r)
        except Exception as e:
            print(f"  {r}: Not supported ({e})")

    return supported

def main():
    print("Querying devices...")
    devices = sd.query_devices()
    print(devices)

    default_in = sd.default.device[0]
    default_out = sd.default.device[1]

    print(f"\nDefault Input Device: {default_in}")
    if default_in >= 0:
        check_sample_rates(default_in, is_input=True)

    print(f"\nDefault Output Device: {default_out}")
    if default_out >= 0:
        check_sample_rates(default_out, is_input=False)

if __name__ == "__main__":
    main()
