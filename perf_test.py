import timeit

setup = """
class Trace:
    def __init__(self, x_data):
        self.x_data = x_data

traces = [Trace(list(range(i))) for i in range(100)]
"""

gen_expr = "max(len(t.x_data) for t in traces)"
list_comp = "max([len(t.x_data) for t in traces])"

print("Gen Expr:", timeit.timeit(gen_expr, setup=setup, number=100000))
print("List Comp:", timeit.timeit(list_comp, setup=setup, number=100000))
