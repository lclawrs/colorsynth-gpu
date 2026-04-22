#!/usr/bin/env python3
"""
colorsynth_showcase.py — Qwen-directed showcase: 3 longer, richer animations
Each is 10 seconds at 30fps (300 frames), 768x768, using the best existing variations.
Qwen picks interesting combos and optionally writes a new showcase variation for each.
"""

import json, subprocess, sys, os, re, time, math, random, textwrap, tempfile
from pathlib import Path

REPO_DIR     = Path("/home/synth/.openclaw/workspace/colorsynth-gpu")
CODE_FILE    = REPO_DIR / "colorsynth_gpu.py"
QWEN_URL     = "http://localhost:8080/v1/chat/completions"
DISCORD_CH   = "1496362899893911745"
SHOWCASE_RES = "768x768"
FRAMES       = 300   # 10s @ 30fps
FPS          = 30

def qwen(system, user, max_tokens=800, temperature=0.6):
    payload = {
        "model": "qwen",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = subprocess.run(
        ["curl", "-s", QWEN_URL, "-H", "Content-Type: application/json",
         "-d", json.dumps(payload)],
        capture_output=True, text=True, timeout=120
    )
    data = json.loads(r.stdout)
    return data["choices"][0]["message"]["content"]

def run(cmd, cwd=None, check=False):
    return subprocess.run(cmd, shell=True, cwd=cwd or REPO_DIR,
                          capture_output=True, text=True, check=check)

def discord_send(message=None, media=None):
    cmd = ["openclaw", "message", "send", "--channel", "discord", "--target", DISCORD_CH]
    if message: cmd += ["--message", message]
    if media:   cmd += ["--media", str(media)]
    subprocess.run(cmd, capture_output=True, timeout=90, check=False)

def syntax_check(code_str):
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tf:
        tf.write(code_str); tf_name = tf.name
    r = subprocess.run(["python3", "-m", "py_compile", tf_name], capture_output=True, text=True)
    os.unlink(tf_name)
    return r.returncode == 0, r.stderr

def runtime_check(code_str, var_name=None, cmap_name=None):
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, dir=REPO_DIR) as tf:
        tf.write(code_str); tf_name = tf.name
    out = str(REPO_DIR / "_rt_test.png")
    var_arg  = f"--variation {var_name}"   if var_name  else ""
    cmap_arg = f"--colormap {cmap_name}"   if cmap_name else ""
    r = subprocess.run(
        f"python3 {tf_name} --mode image --resolution 32x32 {var_arg} {cmap_arg} --output {out}",
        shell=True, cwd=REPO_DIR, capture_output=True, text=True, timeout=30
    )
    os.unlink(tf_name)
    if Path(out).exists(): Path(out).unlink()
    return r.returncode == 0, r.stderr[-400:] if r.stderr else ""

# ── Prompt constants ──────────────────────────────────────────────────────────

PLAN_SYSTEM = textwrap.dedent("""
    You are directing a generative art showcase for ColorSynth, a complex-plane renderer
    that maps pixel coordinates through zLIN/zSIN math to animated RGB color.
    
    You must plan 3 distinct showcase animations. Each should be visually DIFFERENT —
    vary the mood, color palette, and motion style. Think: one calm/organic, one chaotic/fractal,
    one bold/geometric.
    
    For each piece you have two options:
    A) Use an existing variation + colormap combo (just pick from the list)
    B) Write a NEW variation function (more interesting — do this for at least 2 of the 3)
    
    Reply ONLY as a JSON array of 3 objects:
    [
      {
        "title": "Showcase piece title",
        "description": "2-3 evocative sentences about what it will look like",
        "mood": "calm|chaotic|geometric|organic|etc",
        "option": "existing" or "new",
        "variation": "name_if_existing or new_function_name",
        "colormap": "one of: original, psychedelic, hsv, fire, palette, cosmic_rainbow",
        "new_code": "only if option=new: the full def var_NAME(zLIN, zSIN, t=0.0) function"
      },
      ...
    ]
""").strip()

CODE_SYSTEM = textwrap.dedent("""
    You are writing a variation function for ColorSynth generative art.
    - cp = numpy (vectorized, NO loops)
    - fn(zLIN, zSIN, t=0.0) returns a complex64 array
    - t goes 0→2π over the animation loop
    - Use cp.sin, cp.cos, cp.exp, cp.abs, cp.real, cp.imag, cp.power, cp.tanh, cp.angle
    - NEVER use cp.complex() — it does not exist! Use: real + 1j * imag
    - Make it animate richly — t should drive significant visible change
    - Return a complex array; interesting values of abs(z) and angle(z) make good color
    
    Output ONLY the function body as a Python string (no JSON wrapper).
    Start with: def var_NAME(zLIN, zSIN, t=0.0):
""").strip()

DESCRIBE_SYSTEM = "You are a poetic art critic. Write one vivid, evocative sentence about this generative animation."

def main():
    current_code = CODE_FILE.read_text()
    var_names  = re.findall(r'def var_(\w+)\(', current_code)
    cmap_names = re.findall(r'def cmap_(\w+)\(', current_code)

    print(f"Current variations: {len(var_names)}, colormaps: {len(cmap_names)}")
    print("Asking Qwen to plan 3 showcase pieces...\n")

    plan_user = (
        f"Existing variations: {', '.join(var_names)}\n"
        f"Existing colormaps: {', '.join(cmap_names)}\n\n"
        f"Plan 3 showcase animations. For at least 2 of them, write a NEW variation function "
        f"(more interesting than reusing existing ones). Make each piece visually distinct."
    )

    plan_raw = qwen(PLAN_SYSTEM, plan_user, max_tokens=1200, temperature=0.75)
    print(f"Plan response:\n{plan_raw[:500]}\n")

    try:
        plan = json.loads(re.search(r"\[.*\]", plan_raw, re.DOTALL).group())
    except Exception as e:
        print(f"Failed to parse plan: {e}")
        discord_send("🎨 **ColorSynth Showcase** — failed to parse Qwen's plan. Aborting.")
        return

    discord_send(
        f"🎬 **ColorSynth Showcase — starting 3 longer animations** (10s × 768px each)\n"
        f"Qwen planned: {' · '.join(p.get('title','?') for p in plan)}\n"
        f"Rendering now, will post each as it finishes..."
    )

    for i, piece in enumerate(plan[:3], 1):
        t0 = time.perf_counter()
        title    = piece.get("title", f"Showcase {i}")
        desc     = piece.get("description", "")
        mood     = piece.get("mood", "")
        option   = piece.get("option", "existing")
        var_name = piece.get("variation", "original")
        cmap     = piece.get("colormap", "psychedelic")
        new_code = piece.get("new_code", "")

        print(f"\n{'='*60}")
        print(f"[{i}/3] {title} | {mood} | var={var_name} cmap={cmap} | option={option}")

        code = CODE_FILE.read_text()

        # ── If new variation needed ──────────────────────────────────────
        if option == "new" and new_code:
            # Normalize function name
            new_code = re.sub(r"def\s+var([A-Za-z])", r"def var_\1", new_code)
            # Extract actual fn name
            m = re.search(r"def (var_\w+)\(", new_code)
            if m:
                var_name = m.group(1).replace("var_", "")
            
            fn_def = f"def var_{var_name}"
            if fn_def in code:
                var_name += f"_s{i}"
                new_code = re.sub(r"def var_\w+\(", f"def var_{var_name}(", new_code, count=1)

            # Syntax check
            candidate = code.replace("\nVARIATIONS = [", f"\n{new_code}\n\nVARIATIONS = [")
            candidate = candidate.replace(
                "\n]\n\n# ---------------------------------------------------------------------------\n# COLOR MAPPERS",
                f'\n    ("{var_name}", var_{var_name}),\n]\n\n# ---------------------------------------------------------------------------\n# COLOR MAPPERS'
            )
            ok, err = syntax_check(candidate)
            if not ok:
                print(f"  Syntax error: {err[:200]}")
                print("  Asking Qwen to fix...")
                fix_raw = qwen(CODE_SYSTEM,
                    f"This function has a syntax error: {err[:200]}\n\nOriginal:\n{new_code}\n\nFix it.",
                    max_tokens=500, temperature=0.2)
                new_code = fix_raw.strip()
                new_code = re.sub(r"def\s+var([A-Za-z])", r"def var_\1", new_code)
                candidate = code.replace("\nVARIATIONS = [", f"\n{new_code}\n\nVARIATIONS = [")
                candidate = candidate.replace(
                    "\n]\n\n# ---------------------------------------------------------------------------\n# COLOR MAPPERS",
                    f'\n    ("{var_name}", var_{var_name}),\n]\n\n# ---------------------------------------------------------------------------\n# COLOR MAPPERS'
                )
                ok, err = syntax_check(candidate)
                if not ok:
                    print(f"  Still broken — falling back to existing var")
                    option = "existing"
                    var_name = random.choice(["lyapunov_spirals","power_tower_zoom","lyapunov_dance","rotating_moebius_transform","fractal_zoom"])

            if option == "new":
                # Runtime check
                ok2, err2 = runtime_check(candidate, var_name=var_name, cmap_name=cmap)
                if not ok2:
                    print(f"  Runtime error: {err2[:200]} — falling back")
                    option = "existing"
                    var_name = random.choice(["lyapunov_spirals","power_tower_zoom","lyapunov_dance"])
                else:
                    CODE_FILE.write_text(candidate)
                    code = candidate
                    print(f"  ✓ Injected new variation: var_{var_name}")
        else:
            # Existing — verify it's actually in the file
            if var_name not in var_names:
                print(f"  var_{var_name} not found — using fallback")
                var_name = random.choice(["lyapunov_spirals","power_tower_zoom","fractal_zoom"])

        # ── Render ──────────────────────────────────────────────────────────
        ts = time.strftime("%Y%m%d_%H%M%S")
        out = str(REPO_DIR / f"showcase_{i:02d}_{ts}_{var_name}.mp4")
        print(f"  Rendering {FRAMES}f @ {SHOWCASE_RES} ({FRAMES/FPS:.0f}s loop)...")
        t_render = time.perf_counter()
        result = run(
            f"python3 colorsynth_gpu.py --mode video "
            f"--variation {var_name} --colormap {cmap} "
            f"--resolution {SHOWCASE_RES} --frames {FRAMES} --fps {FPS} "
            f"--output {out}"
        )
        render_time = time.perf_counter() - t_render

        if Path(out).exists() and Path(out).stat().st_size > 50000:
            size_kb = Path(out).stat().st_size // 1024
            print(f"  ✓ {out} — {size_kb}KB in {render_time:.0f}s")

            # Artistic description
            art_desc = qwen(DESCRIBE_SYSTEM,
                f"Describe this animation: '{title}' — {desc} (mood: {mood})",
                max_tokens=80, temperature=0.9).strip().strip('"')

            total = time.perf_counter() - t0
            msg = (
                f"🎨 **{title}** *(showcase {i}/3)*\n"
                f"> {art_desc}\n"
                f"`{var_name}` + `{cmap}` · {FRAMES/FPS:.0f}s loop · {size_kb}KB · rendered in {render_time:.0f}s"
            )
            discord_send(message=msg, media=out)
        else:
            stderr_snip = result.stderr[:200] if result.stderr else "no output"
            print(f"  ✗ Render failed: {stderr_snip}")
            discord_send(
                f"🎨 **{title}** *(showcase {i}/3)*\n"
                f"⚠️ Render failed for `{var_name}` — skipping"
            )

    # Commit any new variations added
    run("git add -A")
    run('git commit -m "showcase: 3 longer animations via colorsynth_showcase.py"', check=False)
    run("git push origin master", check=False)
    print("\nShowcase complete.")

if __name__ == "__main__":
    main()
