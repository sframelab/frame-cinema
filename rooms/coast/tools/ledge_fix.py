"""Stop the middle ledge poking through the pebble beds around the seat.

The middle-ledge scan and the near rock/pebble parts overlap within a few
centimetres; where the ledge's smooth pale surface rises through a pebble bed it
shows as pale patches with pebble outlines. Ledge vertices that lie within the
poke-through band of a pebble surface (from 3 cm below to 10 cm above it) are
lowered to 3 cm below it; a ledge that is clearly higher (a real rim) or lower
is untouched. Usage: ledge_fix.py <coast dir in> <out middle-ledge.bin>
"""
import struct
import sys
from pathlib import Path
import numpy as np

src = Path(sys.argv[1])
CELL, BELOW, ABOVE = 0.02, 0.025, 0.10


def read(name):
    b = (src / f'{name}.bin').read_bytes()
    magic, count, indices = struct.unpack('<III', b[:12])
    assert magic == 0x524F434B
    return b, count, np.frombuffer(b, np.float32, count * 3, 12).reshape(-1, 3).copy(), \
        np.frombuffer(b, np.int32, indices, 12 + count * 48).reshape(-1, 3)


def top_heights(parts):
    """Max height of the pebble/rock parts on a 2 cm XZ grid, sampled densely over their triangles."""
    pts = []
    for name in parts:
        _, _, v, tri = read(name)
        a, b, c = v[tri[:, 0]], v[tri[:, 1]], v[tri[:, 2]]
        for u, w in [(1/3, 1/3), (0.6, 0.2), (0.2, 0.6), (0.2, 0.2), (0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.5, 0.5), (0.5, 0.0), (0.0, 0.5)]:
            pts.append(a * (1 - u - w) + b * u + c * w)
    p = np.concatenate(pts)
    lo = p[:, [0, 2]].min(0) - 0.1
    ij = np.floor((p[:, [0, 2]] - lo) / CELL).astype(np.int64)
    shape = tuple(ij.max(0) + 2)
    grid = np.full(shape, -np.inf, np.float32)
    np.maximum.at(grid, (ij[:, 0], ij[:, 1]), p[:, 1])
    # Fill one-cell holes between samples (max over a 3x3 neighbourhood).
    padded = np.pad(grid, 1, constant_values=-np.inf)
    grid = np.max([padded[1 + dy:padded.shape[0] - 1 + dy, 1 + dx:padded.shape[1] - 1 + dx]
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=0)
    return grid, lo


raw, count, ledge, _ = read('middle-ledge')
grid, lo = top_heights(['near-rear-rocks', 'near-left-rocks', 'seat-ledge'])
ij = np.floor((ledge[:, [0, 2]] - lo) / CELL).astype(np.int64)
inside = (ij[:, 0] >= 0) & (ij[:, 1] >= 0) & (ij[:, 0] < grid.shape[0]) & (ij[:, 1] < grid.shape[1])
h = np.full(count, -np.inf, np.float32)
h[inside] = grid[ij[inside, 0], ij[inside, 1]]
covered = np.isfinite(h)
# Only well inside solid pebble coverage (6 cm margin): lowering the ledge at a
# pebble bed's ragged edge or over its holes opened gaps to the void below.
solid = np.isfinite(grid)
pad = np.pad(solid, 3, constant_values=False)
solid = np.min([pad[3 + dy:pad.shape[0] - 3 + dy, 3 + dx:pad.shape[1] - 3 + dx] for dy in range(-3, 4) for dx in range(-3, 4)], axis=0)
covered &= np.zeros(count, bool) | (inside & solid[np.clip(ij[:, 0], 0, grid.shape[0] - 1), np.clip(ij[:, 1], 0, grid.shape[1] - 1)])
poke = covered & (ledge[:, 1] > h - BELOW) & (ledge[:, 1] < h + ABOVE)
moved = ledge[:, 1].copy()
moved[poke] = h[poke] - BELOW
delta = ledge[:, 1] - moved
ledge[:, 1] = moved
out = bytearray(raw)
out[12:12 + count * 12] = ledge.astype(np.float32).tobytes()
Path(sys.argv[2]).write_bytes(bytes(out))
print(f'middle-ledge: {poke.sum()} of {count} vertices lowered (under pebble beds: {covered.sum()}); '
      f'max {delta.max() * 100:.1f} cm, mean {delta[poke].mean() * 100 if poke.any() else 0:.1f} cm')
