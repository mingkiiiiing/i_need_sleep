import json
import struct
from pathlib import Path

base = Path('data-cleaning/storage/raw/geo/hydrolakes/asia')
dbf = base / 'HydroLAKES_Asia.dbf'
shp = base / 'HydroLAKES_Asia.shp'
raw = dbf.read_bytes()
count = struct.unpack_from('<I', raw, 4)[0]
header_len = struct.unpack_from('<H', raw, 8)[0]
record_len = struct.unpack_from('<H', raw, 10)[0]
fields = []
pos = 32
while raw[pos] != 0x0D:
    name = raw[pos:pos + 11].split(b'\0', 1)[0].decode('ascii', 'ignore')
    fields.append((name, raw[pos + 16]))
    pos += 32
target_field = [name for name, _ in fields].index('Hylak_id')
target_record = None
for index in range(count):
    record = raw[header_len + index * record_len:header_len + (index + 1) * record_len]
    offset = 1
    values = []
    for _, length in fields:
        values.append(record[offset:offset + length].decode('latin1').strip())
        offset += length
    if values[target_field] and int(float(values[target_field])) == 148:
        target_record = index
        break
if target_record is None:
    raise RuntimeError('HydroLAKES Hylak_id=148 not found')

data = shp.read_bytes()
offset = 100
for index in range(target_record + 1):
    _, words = struct.unpack_from('>2i', data, offset)
    offset += 8
    content_size = words * 2
    content = data[offset:offset + content_size]
    offset += content_size
shape_type = struct.unpack_from('<i', content, 0)[0]
if shape_type != 5:
    raise RuntimeError(f'Unexpected shape type: {shape_type}')
parts_count, points_count = struct.unpack_from('<2i', content, 36)
parts = struct.unpack_from(f'<{parts_count}i', content, 44)
points_start = 44 + 4 * parts_count
points = [struct.unpack_from('<2d', content, points_start + i * 16) for i in range(points_count)]

def simplify(values, tolerance):
    if len(values) <= 2:
        return values
    ax, ay = values[0]
    bx, by = values[-1]
    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy
    best_distance = -1
    best_index = 0
    for index, (x, y) in enumerate(values[1:-1], 1):
        ratio = ((x - ax) * dx + (y - ay) * dy) / denominator if denominator else 0
        ratio = max(0, min(1, ratio))
        qx, qy = ax + ratio * dx, ay + ratio * dy
        distance = (x - qx) ** 2 + (y - qy) ** 2
        if distance > best_distance:
            best_distance, best_index = distance, index
    if best_distance > tolerance * tolerance:
        return simplify(values[:best_index + 1], tolerance)[:-1] + simplify(values[best_index:], tolerance)
    return [values[0], values[-1]]

rings = []
for part_index in range(parts_count):
    start = parts[part_index]
    end = parts[part_index + 1] if part_index + 1 < parts_count else points_count
    ring = simplify(points[start:end], 0.00008)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    rings.append([[round(lon, 6), round(lat, 6)] for lon, lat in ring])

feature = {
    'type': 'Feature',
    'properties': {'source': 'HydroLAKES', 'hylak_id': 148, 'name': 'Taihu'},
    'geometry': {'type': 'MultiPolygon', 'coordinates': [[[[x, y] for x, y in ring]] for ring in rings]},
}
output = Path('src/data/taihuBoundary.geojson')
output.write_text(json.dumps({'type': 'FeatureCollection', 'features': [feature]}, separators=(',', ':')), encoding='utf-8')
print(output, output.stat().st_size, 'points', sum(len(ring) for ring in rings))
