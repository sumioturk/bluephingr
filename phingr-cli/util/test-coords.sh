#!/bin/bash
# test-coords.sh — Test coordinate mapping through screen handles
#
# Usage:
#   bash util/test-coords.sh http://phingr-e825.local:8080
#   bash util/test-coords.sh http://phingr-e825.local:8080 0.45 0.52

set -euo pipefail

DEVICE_URL="${1:-http://localhost:8080}"
TEST_X="${2:-0.5}"
TEST_Y="${3:-0.5}"

echo "Device: $DEVICE_URL"
echo "Test point: ($TEST_X, $TEST_Y)"
echo ""

curl -s "$DEVICE_URL/api/calib/handles" | python3 -c "
import json, sys

data = json.load(sys.stdin)
handles = data.get('handles')
if not handles:
    print('ERROR: No handles set on device')
    sys.exit(1)

print('Screen handles:')
labels = ['TL', 'TR', 'BR', 'BL']
for i, h in enumerate(handles):
    print(f'  {labels[i]}: ({h[\"x\"]:.4f}, {h[\"y\"]:.4f})')

# Bounding box
xs = [h['x'] for h in handles]
ys = [h['y'] for h in handles]
print(f'  Bbox: ({min(xs):.4f}, {min(ys):.4f}) to ({max(xs):.4f}, {max(ys):.4f})')
print(f'  Size: {max(xs)-min(xs):.4f} x {max(ys)-min(ys):.4f}')
print()

# Bilinear inverse mapping
cx, cy = float('$TEST_X'), float('$TEST_Y')
quad = handles
u, v = 0.5, 0.5
for _ in range(20):
    qx = (1-u)*(1-v)*quad[0]['x'] + u*(1-v)*quad[1]['x'] + u*v*quad[2]['x'] + (1-u)*v*quad[3]['x']
    qy = (1-u)*(1-v)*quad[0]['y'] + u*(1-v)*quad[1]['y'] + u*v*quad[2]['y'] + (1-u)*v*quad[3]['y']
    ex, ey = cx - qx, cy - qy
    if abs(ex) < 0.0001 and abs(ey) < 0.0001: break
    dxdu = -(1-v)*quad[0]['x'] + (1-v)*quad[1]['x'] + v*quad[2]['x'] - v*quad[3]['x']
    dxdv = -(1-u)*quad[0]['x'] - u*quad[1]['x'] + u*quad[2]['x'] + (1-u)*quad[3]['x']
    dydu = -(1-v)*quad[0]['y'] + (1-v)*quad[1]['y'] + v*quad[2]['y'] - v*quad[3]['y']
    dydv = -(1-u)*quad[0]['y'] - u*quad[1]['y'] + u*quad[2]['y'] + (1-u)*quad[3]['y']
    det = dxdu*dydv - dxdv*dydu
    if abs(det) < 1e-10: break
    u += (dydv*ex - dxdv*ey) / det
    v += (dxdu*ey - dydu*ex) / det

u = max(0, min(1, u))
v = max(0, min(1, v))
print(f'Bilinear mapping:')
print(f'  Camera ({cx:.4f}, {cy:.4f}) → Screen ({u:.4f}, {v:.4f})')
print()

# Simple bbox mapping for comparison
sx = (cx - min(xs)) / (max(xs) - min(xs))
sy = (cy - min(ys)) / (max(ys) - min(ys))
print(f'Simple bbox mapping (for comparison):')
print(f'  Camera ({cx:.4f}, {cy:.4f}) → Screen ({sx:.4f}, {sy:.4f})')
print()
print(f'Difference: dx={abs(u-sx):.4f}, dy={abs(v-sy):.4f}')
"
