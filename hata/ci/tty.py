"""CI: текст, що зараз на екрані tty1 (те, що побачить людина на ноутбуці)."""
import struct
with open('/dev/vcsa1', 'rb') as f:
    rows, cols = f.read(2)
with open('/dev/vcsu1', 'rb') as f:      # Юнікод: по 4 байти на символ
    data = f.read()
codes = struct.unpack('<%dI' % (len(data) // 4), data)
for r in range(rows):
    print(''.join(chr(c) if c else ' ' for c in codes[r * cols:(r + 1) * cols]).rstrip())
