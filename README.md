# 🎨 ColorSynth GPU

GPU-accelerated generative art engine based on the original **ColorSynth** algorithm by Michael Haas (2015).

Architected by **LClAwRS** + written by **Qwen2.5-7B** (local, RX 580) + polished by LClAwRS.

## The Algorithm

The original ColorSynth maps pixel coordinates to complex space using two representations:
- `zLIN` — the linear complex plane (-2π to +2π)
- `zSIN` — sin-warped periodic complex space

Then: `z = (zLIN × zSIN)²` → RGB via `sin(real)`, `sin(imag)`, `sin(abs)`

## Usage

```bash
# Single image
python3 colorsynth_gpu.py --mode image --variation 0 --colormap psychedelic --resolution 2048x2048

# All 10 variations
python3 colorsynth_gpu.py --mode image --variation all --colormap hsv

# Batch (all variations × all colormaps = 50 images)
python3 colorsynth_gpu.py --mode batch

# Animated video (4s loop)
python3 colorsynth_gpu.py --mode video --variation spiral --colormap fire --frames 120 --fps 30

# Morph through all variations in one video
python3 colorsynth_gpu.py --mode video --animate-variation --colormap psychedelic
```

## Variations
| # | Name | Formula |
|---|------|---------|
| 0 | original | `(zLIN × zSIN)²` |
| 1 | conjugate | `(zLIN × conj(zSIN))³` |
| 2 | exponential | `exp(zLIN×0.3) × zSIN` |
| 3 | mandelbrot | iterated `z² + zSIN` (3x) |
| 4 | hyperbolic | `(zLIN × tanh(zSIN))²` |
| 5 | fourier | `(sin(zLIN²) + cos(zSIN²)) × zLIN` |
| 6 | julia | iterated `z² + zLIN×0.7` (2x) |
| 7 | spiral | `zLIN × exp(i×|zSIN|)` |
| 8 | tidal | `sin(zLIN²)×zSIN + zLIN×cos(zSIN)` |
| 9 | vortex | `((zLIN+zSIN)/2)² × exp(i×|zLIN-zSIN|)` |

## Colormaps
- `original` — ColorSynth classic: sin(real/imag/abs)
- `psychedelic` — triple-frequency with phase offsets
- `hsv` — abs→hue, vectorized HSV→RGB
- `fire` — black→red→yellow→white
- `palette` — deep blues/purples/golds

## GPU Notes
Requires CuPy with matching ROCm/CUDA version. Falls back to NumPy (still fast — vectorized, no pixel loops).
