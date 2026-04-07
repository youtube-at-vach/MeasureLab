import os

def replace_in_file(filepath, old, new):
    with open(filepath, 'r') as f:
        content = f.read()
    content = content.replace(old, new)
    with open(filepath, 'w') as f:
        f.write(content)

# tests/hardware/test_linearity.py
old_code_1 = """            for avg_idx in range(averaging_count):
                if avg_idx > 0:
                    time.sleep(wait_for_new_data)

                # Get Data
                buffer = np.zeros_like(self.input_data)
                self.get_latest_buffer_into(buffer)"""

new_code_1 = """            buffer = np.empty_like(self.input_data)
            for avg_idx in range(averaging_count):
                if avg_idx > 0:
                    time.sleep(wait_for_new_data)

                # Get Data
                self.get_latest_buffer_into(buffer)"""

replace_in_file('tests/hardware/test_linearity.py', old_code_1, new_code_1)

# tests/hardware/test_crosstalk.py
old_code_2 = """            for avg_idx in range(averaging_count):
                if avg_idx > 0:
                    time.sleep(wait_for_new_data)

                # Get Data
                buffer = np.zeros_like(self.input_data)
                self.get_latest_buffer_into(buffer)"""

new_code_2 = """            buffer = np.empty_like(self.input_data)
            for avg_idx in range(averaging_count):
                if avg_idx > 0:
                    time.sleep(wait_for_new_data)

                # Get Data
                self.get_latest_buffer_into(buffer)"""

replace_in_file('tests/hardware/test_crosstalk.py', old_code_2, new_code_2)

print("Patching complete.")
