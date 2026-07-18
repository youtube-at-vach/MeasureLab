import re

with open("src/gui/widgets/lock_in_modeler.py", "r") as f:
    code = f.read()

old_code = """            avg_quality = np.zeros(len(valid_indices))
            avg_quality[pos] = self.raw_quality[amp_idx, valid_indices[pos]] / counts[pos]
            self.quality_curve.setData(x_data, avg_quality * 100.0)"""

new_code = """            avg_quality = np.zeros(len(valid_indices))
            avg_quality[pos] = self.raw_quality[amp_idx, valid_indices[pos]] / counts[pos]

            # Use sort_idx to order by frequency when plotting
            sort_idx = np.argsort(x_data)
            self.quality_curve.setData(x_data[sort_idx], avg_quality[sort_idx] * 100.0)"""

code = code.replace(old_code, new_code)

old_code2 = """        counts = self.block_counts[valid_indices]
        avg_quality = self.accumulated_quality[valid_indices] / counts
        self.quality_curve.setData(x_data, avg_quality * 100.0)"""

new_code2 = """        counts = self.block_counts[valid_indices]
        avg_quality = self.accumulated_quality[valid_indices] / counts
        sort_idx = np.argsort(x_data)
        self.quality_curve.setData(x_data[sort_idx], avg_quality[sort_idx] * 100.0)"""

code = code.replace(old_code2, new_code2)

with open("src/gui/widgets/lock_in_modeler.py", "w") as f:
    f.write(code)
