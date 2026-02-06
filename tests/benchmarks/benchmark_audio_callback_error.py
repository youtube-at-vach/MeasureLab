import time
import sys
import os

def benchmark_print_vs_pass():
    iterations = 10000

    # Setup dummy callback that raises
    def failing_callback():
        raise RuntimeError("Something went wrong in the callback")

    # 1. Benchmark with print (capturing stdout to avoid spam, but simulating IO cost roughly)
    # Note: capturing stdout with io.StringIO avoids the terminal IO cost, which is the main culprit.
    # To really see the "lock" issue, we should probably output to a file or real stdout, but that's messy.
    # However, even formatting the string and calling print has overhead.

    start_time = time.perf_counter()
    for _ in range(iterations):
        try:
            failing_callback()
        except Exception as e:
            # Current implementation
            # We redirect to devnull to avoid spam but keep the print call overhead
            original_stdout = sys.stdout
            sys.stdout = open(os.devnull, 'w')
            try:
                print(f"Error in audio callback: {e}")
            finally:
                sys.stdout.close()
                sys.stdout = original_stdout
    end_time = time.perf_counter()
    print_duration = end_time - start_time

    # 2. Benchmark with simple pass (baseline for "remove")
    start_time = time.perf_counter()
    for _ in range(iterations):
        try:
            failing_callback()
        except Exception:
            continue
    end_time = time.perf_counter()
    pass_duration = end_time - start_time

    # 3. Benchmark with non-blocking error flag
    # Define variables to avoid F821 (undefined name) but initialize them outside loop
    error_flag = False
    last_error = None

    start_time = time.perf_counter()
    for _ in range(iterations):
        try:
            failing_callback()
        except Exception as e:
            error_flag = True
            last_error = e
            continue
    end_time = time.perf_counter()
    flag_duration = end_time - start_time

    # Use the variables to satisfy linter (F841)
    if error_flag and last_error:
        pass

    print(f"Iterations: {iterations}")
    print(f"With print (redirected to devnull): {print_duration:.6f} s")
    print(f"With pass: {pass_duration:.6f} s")
    print(f"With error flag: {flag_duration:.6f} s")

    if pass_duration > 0:
        print(f"Speedup (print vs pass): {print_duration / pass_duration:.2f}x")
    if flag_duration > 0:
        print(f"Speedup (print vs flag): {print_duration / flag_duration:.2f}x")

if __name__ == "__main__":
    benchmark_print_vs_pass()
