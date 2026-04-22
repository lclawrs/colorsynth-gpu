#!/usr/bin/env python3
"""
colorsynth_iterate.py — Qwen-driven autonomous art iteration agent
Primary goal: ANIMATIONS (MP4 video loops)
Secondary: still images when video fails

Runs locally every 10 min. Only external calls: GitHub push/pull + Discord post.
"""

import json
import subprocess
import sys
import os
import re
import time
import math
import random
import textwrap
import tempfile
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
REPO_DIR    = Path("/home/synth/.openclaw/workspace/colorsynth-gpu")
CODE_FILE   = REPO_DIR / "colorsynth_gpu.py"
LOG_FILE    = REPO_DIR / "iteration_log.md"
QWEN_URL    = "http://localhost:8080/v1/chat/completions"
DISCORD_CH  = "1496362899893911745"   # #colorsynth-art
VIDEO_RES   = "512x512"               # fast enough for smooth animation
IMAGE_RES   = "768x768"
VIDEO_FRAMES = 60                     # 2s @ 30fps — short, punchy loops
VIDEO_FPS    = 30

# ── Helpers ──────────────────────────────────────────────────────────────────

def qwen(system, user, max_tokens=600, temperature=0.5):
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
        capture_output=True, text=True, timeout=600
    )
    data = json.loads(r.stdout)
    content = data["choices"][0]["message"]["content"]
    usage   = data.get("usage", {})
    return content, usage


def run(cmd, cwd=None, check=True):
    return subprocess.run(cmd, shell=True, cwd=cwd or REPO_DIR,
                          capture_output=True, text=True, check=check)


def git_pull():
    run("git pull --rebase origin master", check=False)


def git_push(msg):
    run("git add -A")
    run(f'git commit -m "{msg}"', check=False)
    run("git push origin master", check=False)


def discord_send(message=None, media=None):
    cmd = ["openclaw", "message", "send",
           "--channel", "discord",
           "--target",  DISCORD_CH]
    if message:
        cmd += ["--message", message]
    if media:
        cmd += ["--media", str(media)]
    subprocess.run(cmd, capture_output=True, timeout=60, check=False)


def append_log(entry):
    ts = time.strftime("%Y-%m-%d %H:%M CDT")
    with open(LOG_FILE, "a") as f:
        f.write(f"\n\n---\n## {ts}\n{entry}\n")


def syntax_check_file(code_str):
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tf:
        tf.write(code_str)
        tf_name = tf.name
    r = subprocess.run(["python3", "-m", "py_compile", tf_name],
                       capture_output=True, text=True)
    os.unlink(tf_name)
    return r.returncode == 0, r.stderr


def read_current_code():
    return CODE_FILE.read_text()


def runtime_test(code_str, var_name=None, cmap_name=None):
    """Quick render test — generates 1 frame at tiny resolution to catch runtime errors."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, dir=REPO_DIR) as tf:
        tf.write(code_str)
        tf_name = tf.name
    out = str(REPO_DIR / "_runtime_test.png")
    var_arg = f"--variation {var_name}" if var_name else ""
    cmap_arg = f"--colormap {cmap_name}" if cmap_name else ""
    r = subprocess.run(
        f"python3 {tf_name} --mode image --resolution 32x32 {var_arg} {cmap_arg} --output {out}",
        shell=True, cwd=REPO_DIR, capture_output=True, text=True, timeout=30
    )
    os.unlink(tf_name)
    if Path(out).exists():
        Path(out).unlink()
    return r.returncode == 0, r.stderr[-300:] if r.stderr else ""


# ── Qwen planning ─────────────────────────────────────────────────────────────

PLAN_SYSTEM = textwrap.dedent("""
    You are an autonomous generative art programmer directing a ColorSynth animation project.
    ColorSynth maps pixel coordinates through complex math (zLIN/zSIN planes) to RGB color.
    The engine supports animated video loops where a time parameter `t` (0→2π) smoothly
    evolves the formula, creating seamless looping animations.
    
    Your job: pick ONE creative addition that will look GREAT as an ANIMATION.
    Think about what changes beautifully over time — rotating fields, pulsing patterns,
    morphing attractors, phase-shifting colors, evolving symmetry.
    
    IMPORTANT: Be diverse! Avoid plain phase-angle tricks (they produce static/boring output).
    Great ideas: fractal zoom, Möbius transforms, Newton's method attractors, 
    burning ship, Lyapunov spirals, custom colormaps (fire/ice/neon), domain warping,
    power towers z^z^z, sinh/cosh distortions, rotating Julia params, etc.
    
    Reply ONLY as JSON:
    {"task": "short name", "description": "2-3 sentences", "type": "variation|colormap"}
""").strip()

CODE_SYSTEM = textwrap.dedent("""
    You are a Python generative art programmer working on ColorSynth.
    The codebase uses:
    - cp = numpy (vectorized array math, no loops)
    - VARIATIONS: list of (name, fn) where fn(zLIN, zSIN, t) returns complex64 array
    - COLORMAPS: dict of name→fn(z) returning (r, g, b) float arrays
    - t parameter (0→2π) drives animation — USE IT for time-varying behavior
    
    Output ONLY a JSON object:
    {
      "type": "variation" or "colormap",
      "name": "snake_case_name",
      "code": "def var_NAME(zLIN, zSIN, t=0.0):\\n    # use t for animation!\\n    return z"
    }
    
    For variation: fn(zLIN, zSIN, t=0.0) → complex array. Use t to animate!
    For colormap: fn(z) → (r, g, b). Can also take t if needed.
    Use cp.sin, cp.cos, cp.exp, cp.abs, cp.real, cp.imag, cp.power, cp.tanh.
    
    CRITICAL: cp.complex() does NOT exist! Use Python complex literals or arithmetic:
    - WRONG: cp.complex(real, imag)
    - RIGHT: real_val + 1j * imag_val  (e.g., cp.cos(t) + 1j * cp.sin(t))
    
    No markdown. Pure JSON only.
""").strip()

DESCRIBE_SYSTEM = "You are a poetic art critic. One evocative sentence describing this animation."


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    t_start = time.perf_counter()
    ts = time.strftime("%Y%m%d_%H%M%S")
    print(f"[{ts}] ColorSynth animation iteration...")

    git_pull()
    current_code = read_current_code()
    code_lines   = current_code.count("\n")

    # ── Build context from current codebase + recent log ──────────────────
    var_names  = re.findall(r'def var_(\w+)\(', current_code)
    cmap_names = re.findall(r'def cmap_(\w+)\(', current_code)

    # Recent log: last ~600 chars
    recent_log = ""
    if LOG_FILE.exists():
        log_text = LOG_FILE.read_text()
        recent_log = log_text[-600:].strip()

    # ── Step 1: Plan ──────────────────────────────────────────────────────
    plan_user = (
        f"CURRENT STATE of colorsynth_gpu.py:\n"
        f"  Variations ({len(var_names)}): {', '.join(var_names)}\n"
        f"  Colormaps ({len(cmap_names)}): {', '.join(cmap_names)}\n\n"
        f"RECENT ITERATION LOG (last entries):\n{recent_log}\n\n"
        f"Based on what's already there and what recently worked/failed, "
        f"decide what to do next: fix a broken idea, improve an existing one, "
        f"or add something entirely new. Be specific and creative. "
        f"Avoid repeating names already in the variation/colormap lists above."
    )
    plan_raw, plan_usage = qwen(PLAN_SYSTEM, plan_user, max_tokens=200, temperature=0.8)
    print(f"  Plan: {plan_usage.get('completion_tokens',0)} tokens")

    try:
        plan = json.loads(re.search(r"\{.*\}", plan_raw, re.DOTALL).group())
        task_name = plan.get("task", "animation iteration")
        task_desc = plan.get("description", "")
        task_type = plan.get("type", "variation")
    except Exception:
        task_name, task_desc, task_type = "animation", plan_raw[:100], "variation"

    print(f"  → {task_name}")

    # ── Step 2: Generate code ─────────────────────────────────────────────
    code_user = (
        f"Task: {task_name}\n"
        f"Description: {task_desc}\n"
        f"Type: {task_type}\n"
        f"Existing variations: {', '.join(var_names)}\n"
        f"Existing colormaps: {', '.join(cmap_names)}\n"
        f"IMPORTANT: use the `t` parameter (0→2π) to create beautiful animation. "
        f"The formula should evolve smoothly as t increases.\n"
        f"Write one {'variation function var_NAME(zLIN, zSIN, t=0.0)' if task_type=='variation' else 'colormap function cmap_NAME(z)'} as JSON."
    )
    code_raw, code_usage = qwen(CODE_SYSTEM, code_user, max_tokens=500, temperature=0.3)
    print(f"  Code: {code_usage.get('completion_tokens',0)} tokens")

    # ── Step 3: Parse ─────────────────────────────────────────────────────
    try:
        addition = json.loads(re.search(r"\{.*\}", code_raw, re.DOTALL).group())
        add_type = addition["type"]
        add_name = addition["name"].replace("-","_").replace(" ","_")
        add_code = addition["code"]
    except Exception as e:
        print(f"  Parse error: {e}")
        discord_send(f"🎨 **ColorSynth** — `{task_name}`\n⚠️ Parse error this cycle, skipping.")
        return

    # ── Step 4: Inject into codebase ──────────────────────────────────────
    code = read_current_code()

    if add_type == "variation":
        # Normalize: ensure function is named exactly def var_{add_name}(...)
        add_code = re.sub(r"def\s+var_?\s*" + re.escape(add_name) + r"\s*\(", f"def var_{add_name}(", add_code)
        # Also catch any stray def var<name> without underscore
        add_code = re.sub(r"def\s+var([A-Za-z])", r"def var_\1", add_code)
        fn_prefix = f"def var_{add_name}"
        if fn_prefix in code:
            add_name += f"_{ts[-4:]}"
            add_code = re.sub(r"def var_\w+", f"def var_{add_name}", add_code, count=1)
        # Inject function before VARIATIONS list
        insert_marker = "\nVARIATIONS = ["
        if insert_marker not in code:
            print(f"  ERROR: VARIATIONS marker not found in code file!")
            discord_send(f"🎨 **ColorSynth** — `{task_name}`\n⚠️ Code structure error, skipping.")
            return
        code = code.replace(insert_marker, f"\n{add_code}\n{insert_marker}")
        # Inject entry at end of VARIATIONS list
        end_marker = "\n]\n\n# ---------------------------------------------------------------------------\n# COLOR MAPPERS"
        if end_marker not in code:
            print(f"  ERROR: VARIATIONS end marker not found!")
            discord_send(f"🎨 **ColorSynth** — `{task_name}`\n⚠️ Code structure error, skipping.")
            return
        code = code.replace(
            end_marker,
            f'\n    ("{add_name}", var_{add_name}),{end_marker}'
        )
    else:
        # Normalize colormap function name
        add_code = re.sub(r"def\s+cmap_?\s*" + re.escape(add_name) + r"\s*\(", f"def cmap_{add_name}(", add_code)
        add_code = re.sub(r"def\s+cmap([A-Za-z])", r"def cmap_\1", add_code)
        fn_prefix = f"def cmap_{add_name}"
        if fn_prefix in code:
            add_name += f"_{ts[-4:]}"
            add_code = re.sub(r"def cmap_\w+", f"def cmap_{add_name}", add_code, count=1)
        insert_marker = "\nCOLORMAPS = {"
        if insert_marker not in code:
            print(f"  ERROR: COLORMAPS marker not found!")
            discord_send(f"🎨 **ColorSynth** — `{task_name}`\n⚠️ Code structure error, skipping.")
            return
        code = code.replace(insert_marker, f"\n{add_code}\n{insert_marker}")
        end_marker = '\n}\n\n# ---------------------------------------------------------------------------\n# IMAGE GENERATOR'
        if end_marker not in code:
            print(f"  ERROR: COLORMAPS end marker not found!")
            discord_send(f"🎨 **ColorSynth** — `{task_name}`\n⚠️ Code structure error, skipping.")
            return
        code = code.replace(
            end_marker,
            f'\n    "{add_name}":    cmap_{add_name},{end_marker}'
        )

    ok, err = syntax_check_file(code)
    if not ok:
        print(f"  Syntax error after injection: {err[:200]}")
        discord_send(f"🎨 **ColorSynth** — `{task_name}`\n⚠️ Syntax error, skipping this cycle.")
        return

    ok2, err2 = runtime_test(code, var_name=add_name if add_type == "variation" else None,
                              cmap_name=add_name if add_type == "colormap" else None)
    if not ok2:
        print(f"  Runtime error after injection: {err2[:200]}")
        discord_send(f"🎨 **ColorSynth** — `{task_name}`\n⚠️ Runtime error (`{err2[:120]}`), skipping this cycle.")
        return

    CODE_FILE.write_text(code)
    new_lines = code.count("\n")
    print(f"  Injected {add_type} '{add_name}' ({code_lines}→{new_lines} lines) ✓")

    # ── Step 5: Generate animation (primary goal) ──────────────────────────
    video_path = None
    image_paths = []

    if add_type == "variation":
        var_arg = add_name
        cmap_arg = random.choice(["psychedelic", "hsv", "fire", "palette", "original"])
    else:
        # New colormap — animate with a good base variation
        var_arg = random.choice(["spiral", "vortex", "tidal", "fourier", "julia"])
        cmap_arg = add_name  # colormap choices are dynamic from COLORMAPS.keys()

    video_out = str(REPO_DIR / f"anim_{ts}_{add_name}.mp4")
    print(f"  Rendering {VIDEO_FRAMES}f animation at {VIDEO_RES}...")
    t0 = time.perf_counter()
    vr = run(
        f"python3 colorsynth_gpu.py --mode video "
        f"--variation {var_arg} --colormap {cmap_arg} "
        f"--resolution {VIDEO_RES} --frames {VIDEO_FRAMES} --fps {VIDEO_FPS} "
        f"--output {video_out}",
        check=False
    )
    vid_time = time.perf_counter() - t0

    if Path(video_out).exists() and Path(video_out).stat().st_size > 50000:
        video_path = video_out
        print(f"  ✓ Video: {vid_time:.0f}s, {Path(video_out).stat().st_size//1024}KB")
    else:
        print(f"  Video failed ({vr.stderr[:100]}), falling back to images")
        # Fallback: still images
        for i, t_val in enumerate([0.0, 1.047, 2.094]):
            img_out = str(REPO_DIR / f"img_{ts}_{add_name}_{i}.png")
            run(
                f"python3 colorsynth_gpu.py --mode image "
                f"--variation {var_arg} --colormap {cmap_arg} "
                f"--resolution {IMAGE_RES} --output {img_out}",
                check=False
            )
            if Path(img_out).exists():
                image_paths.append(img_out)

    # ── Step 6: Artistic description ──────────────────────────────────────
    desc_user = f"Describe this generative animation: {task_name} — {task_desc}"
    art_desc, _ = qwen(DESCRIBE_SYSTEM, desc_user, max_tokens=80, temperature=0.9)
    art_desc = art_desc.strip().strip('"')

    # ── Step 7: Commit + push ─────────────────────────────────────────────
    commit_msg = f"art: {task_name} [{ts}]"
    git_push(commit_msg)

    # ── Step 8: Report to Discord ─────────────────────────────────────────
    elapsed = time.perf_counter() - t_start
    gh_url = f"https://github.com/lclawrs/colorsynth-gpu/commit/{run('git rev-parse --short HEAD', check=False).stdout.strip()}"

    report = (
        f"🎨 **{task_name}**\n"
        f"> {art_desc}\n"
        f"Type: `{add_type}` · Render: `{vid_time:.0f}s` · Total: `{elapsed:.0f}s`\n"
        f"{gh_url}"
    )

    if video_path:
        discord_send(message=report, media=video_path)
    elif image_paths:
        discord_send(message=report, media=image_paths[0])
        for p in image_paths[1:]:
            discord_send(media=p)
    else:
        discord_send(message=report + "\n_(render failed — code still committed)_")

    append_log(
        f"**Task:** {task_name} | **Type:** {add_type} | **Name:** {add_name}\n"
        f"**Desc:** {task_desc}\n"
        f"**Result:** {'✓ VIDEO rendered ({Path(video_out).stat().st_size//1024}KB)' if video_path else ('✓ images only (video too small/static)' if image_paths else '✗ render failed')}\n"
        f"**Time:** {elapsed:.0f}s"
    )
    print(f"  Done in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
