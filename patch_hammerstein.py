with open("src/gui/widgets/hammerstein_analyzer.py", "r") as f:
    content = f.read()

# Instead of blindly replacing the patterns, we will find all occurrences of `np.interp(*, self.cached_freqs, np.real(H_dict[p]))`
import re

# Match real_val_all = np.interp(..., self.cached_freqs, np.real(H_dict[p]))
# and imag_val_all = np.interp(..., self.cached_freqs, np.imag(H_dict[p]))
pattern = re.compile(r'(\s*)([a-zA-Z0-9_]+) = np\.interp\(([^,]+), self\.cached_freqs, np\.real\(H_dict\[p\]\)\)\s*([a-zA-Z0-9_]+) = np\.interp\([^,]+, self\.cached_freqs, np\.imag\(H_dict\[p\]\)\)')

def replacer(match):
    indent = match.group(1)
    real_var = match.group(2)
    arg1 = match.group(3)
    imag_var = match.group(4)
    return f"{indent}Hp = H_dict[p]\n{indent}{real_var} = np.interp({arg1}, self.cached_freqs, np.real(Hp))\n{indent}{imag_var} = np.interp({arg1}, self.cached_freqs, np.imag(Hp))"

new_content = pattern.sub(replacer, content)

with open("src/gui/widgets/hammerstein_analyzer.py", "w") as f:
    f.write(new_content)
