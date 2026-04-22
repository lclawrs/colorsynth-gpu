#!/usr/bin/env python3
"""
ColorSynth GPU - Generative Art Engine
Original algorithm by Michael Haas (ColorSynth) circa 2015
GPU-accelerated rewrite by LClAwRS + Qwen2.5-7B, 2026

Runs on AMD RX 580 via ROCm/CuPy or falls back to NumPy.
"""

import argparse
import time
import sys
import os
import math
import numpy as np
from PIL import Image

# GPU backend: try CuPy (ROCm or CUDA), fall back to NumPy
try:
    import cupy as cp
    # Verify GPU is actually usable
    _ = cp.array([1.0])
    GPU = True
    print("✓ GPU backend: CuPy", file=sys.stderr)
except Exception as e:
    cp = np
    GPU = False
    print(f"⚠ GPU unavailable ({e}), falling back to NumPy CPU", file=sys.stderr)

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    print("⚠ cv2 not found — video mode unavailable", file=sys.stderr)

# ---------------------------------------------------------------------------
# COORDINATE GRID BUILDER
# ---------------------------------------------------------------------------

def make_grid(xRes, yRes, t=0.0):
    """Build zLIN and zSIN grids for given resolution and time offset."""
    x = 2 * (2 * cp.pi * (cp.arange(xRes, dtype=cp.float32) / xRes - 0.5))
    y = 2 * (2 * cp.pi * (cp.arange(yRes, dtype=cp.float32) / yRes - 0.5))
    X, Y = cp.meshgrid(x, y)  # shape: (yRes, xRes)

    # Apply time-based rotation to the complex plane
    if t != 0.0:
        rot = math.cos(t) + 1j * math.sin(t)
        zLIN = (X + 1j * Y).astype(cp.complex64) * rot
    else:
        zLIN = (X + 1j * Y).astype(cp.complex64)

    zSIN = (cp.sin(X) + 1j * cp.sin(Y)).astype(cp.complex64)
    return zLIN, zSIN

# ---------------------------------------------------------------------------
# FORMULA VARIATIONS
# (All return complex64 arrays — color mapper handles R/G/B extraction)
# ---------------------------------------------------------------------------

def var_original(zLIN, zSIN, t=0.0):
    """Original ColorSynth: z = (zLIN * zSIN)^2"""
    return cp.power(zLIN * zSIN, 2)

def var_conjugate(zLIN, zSIN, t=0.0):
    """Conjugate twist: z = (zLIN * conj(zSIN))^3"""
    return cp.power(zLIN * cp.conj(zSIN), 3)

def var_exponential(zLIN, zSIN, t=0.0):
    """Exponential warp: z = exp(zLIN) * zSIN"""
    return cp.exp(zLIN * 0.3) * zSIN  # scale to avoid overflow

def var_mandelbrot(zLIN, zSIN, t=0.0):
    """Mandelbrot-inspired (3 iterations): z = z^2 + zSIN"""
    z = zLIN.copy()
    for _ in range(3):
        z = z * z + zSIN
    return z

def var_hyperbolic(zLIN, zSIN, t=0.0):
    """Hyperbolic: z = (zLIN * tanh(zSIN))^2"""
    return cp.power(zLIN * cp.tanh(zSIN), 2)

def var_fourier(zLIN, zSIN, t=0.0):
    """Fourier blend: z = (sin(zLIN^2) + cos(zSIN^2)) * zLIN"""
    return (cp.sin(cp.power(zLIN, 2)) + cp.cos(cp.power(zSIN, 2))) * zLIN

def var_julia(zLIN, zSIN, t=0.0):
    """Julia-inspired (2 iterations): z = zSIN^2 + zLIN*0.7"""
    z = zSIN.copy()
    c = zLIN * 0.7
    for _ in range(2):
        z = z * z + c
    return z

def var_spiral(zLIN, zSIN, t=0.0):
    """Spiral: z = zLIN * exp(i * |zSIN|)"""
    return zLIN * cp.exp(1j * cp.abs(zSIN))

def var_tidal(zLIN, zSIN, t=0.0):
    """Tidal (LClAwRS original): z = sin(zLIN^2) * zSIN + zLIN * cos(zSIN)"""
    return cp.sin(zLIN * zLIN) * zSIN + zLIN * cp.cos(zSIN)

def var_vortex(zLIN, zSIN, t=0.0):
    """Vortex (LClAwRS original): recursive rotation through sin/cos space"""
    z = (zLIN + zSIN) * 0.5
    return z * z * cp.exp(1j * cp.abs(zLIN - zSIN))

def var_quantum_decay(zLIN, zSIN, t=0.0):
    decay_rate = 0.05 * (1 + cp.cos(t))
    z = zLIN * cp.exp(-decay_rate * t) + zSIN * cp.exp(1j * t)
    return z

def var_twilight_tide(zLIN, zSIN, t=0.0):
    freq = 0.1 + cp.sin(t * 0.1) * 0.4
    zSIN = zSIN * cp.exp(-0.01 * cp.abs(zLIN))
    zLIN = zLIN * cp.exp(1j * freq * t)
    return zLIN + zSIN

def var_nebula_cloud(zLIN, zSIN, t=0.0):
    z = zLIN + cp.exp(cp.sin(zSIN * 4 + t * 2) * cp.pi * 1j)
    return z

def var_phase_shifting(zLIN, zSIN, t=0.0):
    # use t for animation!
    return zLIN * cp.exp(1j * (cp.angle(zLIN) + t / 4)) + zSIN * cp.exp(1j * (cp.angle(zSIN) + t / 2))

def var_phase_shifting_3353(zLIN, zSIN, t=0.0):
    # use t for animation!
    phase_shift = cp.sin(t) * 0.5 + 0.5
    zSIN_shifted = zSIN * phase_shift
    return zSIN_shifted

def varphasor_morph(zLIN, zSIN, t=0.0):
    # use t for animation!
    angle = cp.angle(zLIN) + t
    radius = cp.abs(zLIN) * cp.tanh(t)
    return radius * cp.exp(1j * angle)

def var_phase_shifting_attractors(zLIN, zSIN, t=0.0):
    # use t for animation!
    z = zSIN * cp.exp(1j * cp.sin(cp.angle(zLIN) + t / 4))
    return z

def var_phase_shifting_3353(zLIN, zSIN, t=0.0):
    # use t for animation!
    phase = cp.sin(t) * 0.5 + 0.5
    return zLIN * phase

def var_phase_shifting_4355(zLIN, zSIN, t=0.0):
    # use t for animation!
    phase = cp.sin(t) * zSIN + cp.cos(t) * zLIN
    return phase * cp.exp(1j * t)

def var_phase_shifting_5355(zLIN, zSIN, t=0.0):
    # use t for animation!
    phase = cp.sin(t)
    z = zSIN * cp.exp(1j * phase)
    return z

def var_phase_shifting_attractors_1353(zLIN, zSIN, t=0.0):
    # use t for animation!
    phase_shift = cp.sin(t) * 0.5 + 0.5
    z = zLIN * cp.exp(1j * (cp.angle(zLIN) + phase_shift))
    return z

def var_phase_shifting_2355(zLIN, zSIN, t=0.0):
    # use t for animation!
    phase = cp.sin(t)
    z = zLIN * cp.exp(1j * phase)
    return z

def varphasor_morph(zLIN, zSIN, t=0.0):
    # use t for animation!
    angle = cp.angle(zLIN) + t
    radius = cp.abs(zLIN) * cp.tanh(t)
    return radius * cp.exp(1j * angle)

def var_phase_shifting_attractors_3353(zLIN, zSIN, t=0.0):
    # use t for animation!
    return (zLIN * cp.exp(cp.complex(0, cp.sin(t) * cp.abs(zLIN) / 10)) + zSIN * cp.exp(cp.complex(0, cp.cos(t) * cp.abs(zSIN) / 10))) / 2

def var_phase_shifting_attractors_4353(zLIN, zSIN, t=0.0):
    # use t for animation!
    phase_shift = cp.sin(t) * 0.5 + 0.5
    z = zLIN * cp.exp(1j * cp.angle(zSIN) * phase_shift)
    return z

def var_time_warped_julia(zLIN, zSIN, t=0.0):
    # use t for animation!
    c = (cp.cos(t) + 1j * cp.sin(t)) * 0.8 + 0.2 * cp.exp(1j * cp.pi * cp.abs(zLIN))
    return zLIN + zSIN * cp.tanh(c * zLIN)

def var_time_warp_1415(zLIN, zSIN, t=0.0):
    # use t for animation!
    return cp.sin(zLIN + cp.tanh(cp.abs(zSIN) * t)) * cp.exp(-cp.abs(zLIN) / 10 + cp.sin(t) / 10)

def varphasor_morph(zLIN, zSIN, t=0.0):
    # use t for animation!
    angle = cp.angle(zLIN) + t
    radius = cp.abs(zLIN) * cp.tanh(t)
    return radius * cp.exp(1j * angle)

def var_phase_shifting_3352(zLIN, zSIN, t=0.0):
    # use t for animation!
    return zLIN * cp.exp(1j * (cp.sin(t) * cp.angle(zLIN) + cp.cos(t)))

def varphasor_morph(zLIN, zSIN, t=0.0):
    # use t for animation!
    phase = cp.angle(zLIN) + t
    return cp.exp(1j * phase)

def var_rotating_vortex(zLIN, zSIN, t=0.0):
    # use t for animation!
    angle = t * 2 * cp.pi
    vortex = cp.exp(1j * angle) * zLIN
    return vortex

def var_PHASE_SHIFTING_COLORS(zLIN, zSIN, t=0.0):
    # use t for animation!
    phase = cp.sin(t)
    z = zLIN * cp.exp(1j * phase)
    return z

def var_phase_shifting_attractors_3414(zLIN, zSIN, t=0.0):
    # use t for animation!
    return (zLIN * cp.exp(cp.complex(0, t / 4)) + zSIN * cp.exp(cp.complex(0, t / 6))) / 2

def var_phase_shifting_attractors_4352(zLIN, zSIN, t=0.0):
    # use t for animation!
    return (zLIN * cp.exp(cp.complex(0, t / 10)) + zSIN * cp.exp(cp.complex(0, t / 15))) / 2

VARIATIONS = [
    ("original",     var_original),
    ("conjugate",    var_conjugate),
    ("exponential",  var_exponential),
    ("mandelbrot",   var_mandelbrot),
    ("hyperbolic",   var_hyperbolic),
    ("fourier",      var_fourier),
    ("julia",        var_julia),
    ("spiral",       var_spiral),
    ("tidal",        var_tidal),
    ("vortex",       var_vortex),
    ("quantum_decay", var_quantum_decay),
    ("twilight_tide", var_twilight_tide),
    ("nebula_cloud", var_nebula_cloud),
    ("phase_shifting", var_phase_shifting),
    ("phase_shifting_3353", var_phase_shifting_3353),
    ("phasor_morph", var_phasor_morph),
    ("phase_shifting_attractors", var_phase_shifting_attractors),
    ("phase_shifting_3353", var_phase_shifting_3353),
    ("phase_shifting_4355", var_phase_shifting_4355),
    ("phase_shifting_5355", var_phase_shifting_5355),
    ("phase_shifting_attractors_1353", var_phase_shifting_attractors_1353),
    ("phase_shifting_2355", var_phase_shifting_2355),
    ("phasor_morph", var_phasor_morph),
    ("phase_shifting_attractors_3353", var_phase_shifting_attractors_3353),
    ("phase_shifting_attractors_4353", var_phase_shifting_attractors_4353),
    ("time_warped_julia", var_time_warped_julia),
    ("time_warp_1415", var_time_warp_1415),
    ("phasor_morph", var_phasor_morph),
    ("phase_shifting_3352", var_phase_shifting_3352),
    ("phasor_morph", var_phasor_morph),
    ("rotating_vortex", var_rotating_vortex),
    ("phase_shifting_colors", var_phase_shifting_colors),
    ("phase_shifting_attractors_3414", var_phase_shifting_attractors_3414),
    ("phase_shifting_attractors_4352", var_phase_shifting_attractors_4352),
]

# ---------------------------------------------------------------------------
# COLOR MAPPERS
# (take complex array z, return (r,g,b) each float32 in [0,255])
# ---------------------------------------------------------------------------

def normalize(arr):
    a = arr - arr.min()
    mx = a.max()
    if mx < 1e-10:
        return a
    return a * (255.0 / mx)

def cmap_original(z):
    """Original ColorSynth: sin of real/imag/abs -> RGB"""
    r = normalize(cp.sin(cp.real(z)))
    g = normalize(cp.sin(cp.imag(z)))
    b = normalize(cp.sin(cp.abs(z)))
    return r, g, b

def cmap_psychedelic(z):
    """Triple-frequency with phase offsets"""
    r = normalize(cp.sin(cp.real(z) * 3.0))
    g = normalize(cp.sin(cp.imag(z) * 3.0 + 2.1))
    b = normalize(cp.sin(cp.abs(z)  * 3.0 + 4.2))
    return r, g, b

def cmap_hsv(z):
    """HSV rotation: abs->hue, normalized real->sat, normalized imag->val"""
    hue = (cp.abs(z) % (2 * cp.pi)) / (2 * cp.pi)  # 0-1
    sat = (cp.sin(cp.real(z)) + 1) * 0.5
    val = (cp.sin(cp.imag(z)) + 1) * 0.5
    # HSV to RGB vectorized
    h6 = hue * 6.0
    i = cp.floor(h6).astype(cp.int32) % 6
    f = h6 - cp.floor(h6)
    p = val * (1 - sat)
    q = val * (1 - f * sat)
    t_ = val * (1 - (1 - f) * sat)
    r = cp.where(i==0, val, cp.where(i==1, q, cp.where(i==2, p, cp.where(i==3, p, cp.where(i==4, t_, val)))))
    g = cp.where(i==0, t_, cp.where(i==1, val, cp.where(i==2, val, cp.where(i==3, q, cp.where(i==4, p, p)))))
    b = cp.where(i==0, p, cp.where(i==1, p, cp.where(i==2, t_, cp.where(i==3, val, cp.where(i==4, val, q)))))
    return r*255, g*255, b*255

def cmap_fire(z):
    """Fire colormap: maps abs(z) through black->red->yellow->white"""
    v = normalize(cp.sin(cp.abs(z)))  # 0-255
    v01 = v / 255.0
    r = normalize(cp.minimum(v01 * 3.0, 1.0))
    g = normalize(cp.maximum(cp.minimum(v01 * 3.0 - 1.0, 1.0), 0.0))
    b = normalize(cp.maximum(cp.minimum(v01 * 3.0 - 2.0, 1.0), 0.0))
    return r, g, b

def cmap_palette(z):
    """Custom 256-step palette with smooth interpolation through deep blues/purples/golds"""
    v = (cp.sin(cp.abs(z)) + 1) * 0.5  # 0-1
    # Palette: 0=deep blue, 0.33=purple, 0.66=gold, 1.0=white
    r = normalize(cp.sin(v * cp.pi))
    g = normalize(cp.sin(v * cp.pi * 0.7 + 0.5))
    b = normalize(cp.sin(v * cp.pi * 1.3 + 1.0))
    return r, g, b

def cmap_cosmic_rainbow(z):
    r = cp.where(cp.abs(z) < 1, cp.sin(cp.angle(z) * 4) * 0.5 + 0.5, 0.0)
    g = cp.where(cp.abs(z) < 1, cp.sin(cp.angle(z) * 2) * 0.5 + 0.5, 0.0)
    b = cp.where(cp.abs(z) < 1, cp.sin(cp.angle(z) * 6) * 0.5 + 0.5, 0.0)
    return r, g, b

def var_PHASE_SHIFTING_COLORS(z):
    t = 0.0
    r = cp.sin(cp.abs(z) + t) * 0.5 + 0.5
    g = cp.sin(cp.abs(z) + t + cp.pi / 2) * 0.5 + 0.5
    b = cp.sin(cp.abs(z) + t + cp.pi) * 0.5 + 0.5
    return r, g, b

def var_PHASE_SHIFTING(z):
    t = 0.0
    r = cp.abs(cp.sin(z * cp.exp(1j * t)))
    g = cp.abs(cp.sin(z * cp.exp(1j * (t + cp.pi / 3))))
    b = cp.abs(cp.sin(z * cp.exp(1j * (t + cp.pi / 6))))
    return r, g, b

def var_NAME(z):
    t = 0.0
    # use t for animation!
    hue = cp.angle(z) + t
    hue = cp.remainder(hue, 2 * cp.pi)
    r = cp.sin(hue + cp.pi / 3)
    g = cp.sin(hue)
    b = cp.sin(hue - cp.pi / 3)
    return r, g, b

def var_NAME(z):
    t = 0.0
    phase = cp.angle(z)
    hue = (phase + t) % (2 * cp.pi) / (2 * cp.pi)
    return cp.array([hue, (hue + 1/3) % 1, (hue + 2/3) % 1]).T

def var_PHASE_SHIFT_COLORS(z):
    r = cp.abs(z) * cp.sin(cp.angle(z) + t)
    g = cp.abs(z) * cp.cos(cp.angle(z) + t)
    b = cp.abs(z) * cp.tanh(cp.angle(z) + t)
    return cp.stack([r, g, b], axis=-1)

def var_PHASE_SHIFTING(z):
    t = 0.0
    r = cp.abs(z) * cp.cos(cp.angle(z) + t)
    g = cp.abs(z) * cp.sin(cp.angle(z) + t)
    b = cp.abs(z) * cp.tanh(cp.angle(z) + t)
    return cp.stack([r, g, b], axis=-1)

def cmap_phase_shifting(z):
    # Use t for animation!
    t = 0.0
    r = cp.abs(z) * cp.cos(cp.angle(z) + t)
    g = cp.abs(z) * cp.sin(cp.angle(z) + t)
    b = cp.abs(z) * cp.tanh(cp.angle(z) + t)
    return r, g, b

def var_PHASE_SHIFTING(z):
    t = 0.0
    r = cp.abs(z) * cp.cos(cp.angle(z) + t)
    g = cp.abs(z) * cp.sin(cp.angle(z) + t)
    b = cp.abs(z) * cp.tanh(cp.angle(z) + t)
    return r, g, b

def var_PHASE_SHIFTING_COLORS(z):
    t = 0.0
    r = cp.abs(z) * cp.cos(cp.angle(z) + t)
    g = cp.abs(z) * cp.sin(cp.angle(z) + t)
    b = cp.abs(z) * cp.tanh(cp.angle(z) + t)
    return cp.stack([r, g, b], axis=-1)

def var_PHASE_SHIFTING(z):
    r = cp.abs(z) * cp.cos(cp.angle(z) + t)
    g = cp.abs(z) * cp.sin(cp.angle(z) + t)
    b = cp.abs(z) * cp.tanh(cp.angle(z) + t)
    return r, g, b

COLORMAPS = {
    "original":    cmap_original,
    "psychedelic": cmap_psychedelic,
    "hsv":         cmap_hsv,
    "fire":        cmap_fire,
    "palette":     cmap_palette,
    "cosmic_rainbow":    cmap_cosmic_rainbow,
    "phase_shifting_colors":    cmap_phase_shifting_colors,
    "phase_shifting":    cmap_phase_shifting,
    "phase_shifting":    cmap_phase_shifting,
    "phase_shifting_colors":    cmap_phase_shifting_colors,
    "phase_shift_colors":    cmap_phase_shift_colors,
    "phase_shifting":    cmap_phase_shifting,
    "phase_shifting":    cmap_phase_shifting,
    "phase_shifting_4352":    cmap_phase_shifting_4352,
    "phase_shifting_colors":    cmap_phase_shifting_colors,
    "phase_shifting_1352":    cmap_phase_shifting_1352,
}

# ---------------------------------------------------------------------------
# IMAGE GENERATOR
# ---------------------------------------------------------------------------

def generate_image(var_idx, colormap_name, resolution=(2048, 2048), t=0.0):
    xRes, yRes = resolution
    t0 = time.perf_counter()

    zLIN, zSIN = make_grid(xRes, yRes, t)
    z = VARIATIONS[var_idx][1](zLIN, zSIN, t)
    z = cp.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)

    r, g, b = COLORMAPS[colormap_name](z)

    # Stack to (H, W, 3) uint8
    img_gpu = cp.stack([
        cp.nan_to_num(r).clip(0, 255).astype(cp.uint8),
        cp.nan_to_num(g).clip(0, 255).astype(cp.uint8),
        cp.nan_to_num(b).clip(0, 255).astype(cp.uint8),
    ], axis=-1)

    elapsed = time.perf_counter() - t0
    mp_s = (xRes * yRes) / elapsed / 1e6
    return img_gpu, elapsed, mp_s

# ---------------------------------------------------------------------------
# VIDEO GENERATOR
# ---------------------------------------------------------------------------

def generate_video(var_idx, colormap_name, resolution=(1024, 1024),
                   frames=120, fps=30, animate_variation=False, output=None):
    if not HAS_CV2:
        print("ERROR: cv2 required for video mode", file=sys.stderr)
        return

    xRes, yRes = resolution
    if output is None:
        var_name = VARIATIONS[var_idx][0]
        output = f"colorsynth_VAR{var_idx}_{var_name}_{colormap_name}_{int(time.time())}.mp4"

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output, fourcc, fps, (xRes, yRes))

    print(f"  Generating {frames} frames at {xRes}x{yRes}...")
    t_start = time.perf_counter()

    for frame_i in range(frames):
        t = (2 * math.pi * frame_i) / frames  # 0 → 2pi, loops perfectly

        if animate_variation:
            # Blend between variations based on time
            v1_idx = (frame_i * len(VARIATIONS)) // frames
            v2_idx = (v1_idx + 1) % len(VARIATIONS)
            alpha = (frame_i % (frames // len(VARIATIONS))) / (frames // len(VARIATIONS))

            zLIN, zSIN = make_grid(xRes, yRes, t)
            z1 = VARIATIONS[v1_idx][1](zLIN, zSIN, t)
            z2 = VARIATIONS[v2_idx][1](zLIN, zSIN, t)
            z = z1 * (1 - alpha) + z2 * alpha
        else:
            zLIN, zSIN = make_grid(xRes, yRes, t)
            z = VARIATIONS[var_idx][1](zLIN, zSIN, t)

        z = cp.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)
        r, g, b = COLORMAPS[colormap_name](z)

        frame_gpu = cp.stack([
            cp.nan_to_num(b).clip(0, 255).astype(cp.uint8),  # cv2 is BGR
            cp.nan_to_num(g).clip(0, 255).astype(cp.uint8),
            cp.nan_to_num(r).clip(0, 255).astype(cp.uint8),
        ], axis=-1)

        if GPU:
            frame_cpu = cp.asnumpy(frame_gpu)
        else:
            frame_cpu = frame_gpu

        writer.write(frame_cpu)

        # Progress
        elapsed = time.perf_counter() - t_start
        fps_actual = (frame_i + 1) / elapsed
        eta = (frames - frame_i - 1) / fps_actual if fps_actual > 0 else 0
        print(f"\r  Frame {frame_i+1}/{frames} | {fps_actual:.1f} fps | ETA {eta:.1f}s    ",
              end="", flush=True)

    writer.release()
    total = time.perf_counter() - t_start
    print(f"\n  ✓ Video saved: {output} ({total:.1f}s)")
    return output

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_resolution(s):
    try:
        w, h = s.lower().split('x')
        return int(w), int(h)
    except Exception:
        raise argparse.ArgumentTypeError(f"Resolution must be WxH, got: {s}")

def main():
    parser = argparse.ArgumentParser(
        description="ColorSynth GPU — generative art engine (GPU-accelerated)"
    )
    parser.add_argument("--mode", choices=["image", "video", "batch"], default="image")
    parser.add_argument("--variation", default="0",
                        help="Variation index 0-9, name, or 'all' for batch")
    parser.add_argument("--colormap", choices=list(COLORMAPS.keys()), default="original")
    parser.add_argument("--resolution", type=parse_resolution, default=(2048, 2048),
                        metavar="WxH")
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--animate-variation", action="store_true",
                        help="Video: morph through all variations over time")
    args = parser.parse_args()

    # Resolve variation
    if args.variation.lower() == "all":
        var_indices = list(range(len(VARIATIONS)))
    else:
        try:
            vi = int(args.variation)
        except ValueError:
            # Try by name
            names = [v[0] for v in VARIATIONS]
            if args.variation in names:
                vi = names.index(args.variation)
            else:
                print(f"Unknown variation: {args.variation}", file=sys.stderr)
                print(f"Available: {', '.join(names)}", file=sys.stderr)
                sys.exit(1)
        var_indices = [vi]

    print(f"\n🎨 ColorSynth GPU")
    print(f"   Mode:       {args.mode}")
    print(f"   Resolution: {args.resolution[0]}x{args.resolution[1]}")
    print(f"   Colormap:   {args.colormap}")
    print(f"   Backend:    {'GPU (CuPy)' if GPU else 'CPU (NumPy fallback)'}")

    total_start = time.perf_counter()

    if args.mode == "image":
        for vi in var_indices:
            var_name = VARIATIONS[vi][0]
            print(f"\n  Generating variation {vi} ({var_name})...")
            img_gpu, elapsed, mp_s = generate_image(vi, args.colormap, args.resolution)
            img_cpu = cp.asnumpy(img_gpu) if GPU else img_gpu
            img = Image.fromarray(img_cpu, 'RGB')
            fname = args.output or f"colorsynth_VAR{vi}_{var_name}_{args.colormap}_{int(time.time())}.png"
            img.save(fname)
            print(f"  ✓ {fname}")
            print(f"    GPU time: {elapsed*1000:.1f}ms | {mp_s:.2f} MP/s")

    elif args.mode == "video":
        vi = var_indices[0]
        var_name = VARIATIONS[vi][0]
        print(f"\n  Variation: {vi} ({var_name})")
        print(f"  Frames: {args.frames} @ {args.fps}fps = {args.frames/args.fps:.1f}s loop")
        generate_video(vi, args.colormap, args.resolution,
                      args.frames, args.fps, args.animate_variation, args.output)

    elif args.mode == "batch":
        print(f"\n  Batch: all {len(VARIATIONS)} variations × {len(COLORMAPS)} colormaps")
        for vi in range(len(VARIATIONS)):
            var_name = VARIATIONS[vi][0]
            for cmap in COLORMAPS:
                print(f"  → VAR{vi} {var_name} / {cmap}", end=" ", flush=True)
                img_gpu, elapsed, mp_s = generate_image(vi, cmap, args.resolution)
                img_cpu = cp.asnumpy(img_gpu) if GPU else img_gpu
                img = Image.fromarray(img_cpu, 'RGB')
                fname = f"colorsynth_VAR{vi}_{var_name}_{cmap}_{int(time.time())}.png"
                img.save(fname)
                print(f"✓ {elapsed*1000:.0f}ms {mp_s:.1f}MP/s")

    total = time.perf_counter() - total_start
    print(f"\n⏱  Total time: {total:.2f}s")

if __name__ == "__main__":
    main()
