import sys
import time
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

app = QApplication(sys.argv)
table = QTableWidget(100, 4)

for r in range(100):
    for c in range(4):
        table.setItem(r, c, QTableWidgetItem("Init"))

# Benchmark 1: setItem with new QTableWidgetItem
start = time.time()
for _ in range(1000):
    for r in range(100):
        for c in range(4):
            table.setItem(r, c, QTableWidgetItem("New"))
end = time.time()
print(f"setItem + new QTableWidgetItem: {end - start:.4f} s")

# Benchmark 2: item(r, c).setText()
start = time.time()
for _ in range(1000):
    for r in range(100):
        for c in range(4):
            if item := table.item(r, c):
                item.setText("Update")
            else:
                table.setItem(r, c, QTableWidgetItem("Update"))
end = time.time()
print(f"item().setText(): {end - start:.4f} s")
