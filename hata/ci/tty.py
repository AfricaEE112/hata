"""CI: текст, що зараз на екрані tty1 (те, що побачить людина на ноутбуці)."""
import sys
with open('/dev/vcsa1', 'rb') as f:
    data = f.read()
rows, cols = data[0], data[1]
chars = data[4::2]
for r in range(rows):
    line = chars[r * cols:(r + 1) * cols].decode('cp437', 'replace').rstrip()
    print(line)
