#!/usr/bin/env python3
"""
colorsynth_iterate.py — Qwen-driven autonomous art iteration agent
Runs locally: reads current code, asks Qwen for improvements, applies them,
generates sample images, commits, pushes, reports to Discord.

Called by cron every 15 minutes. No cloud AI — Qwen only.
"""

import json
import subprocess
import sys
import os
import time
import re
import math
import random
import textwrap
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
REPO_DIR   = Path("/home/synth/.openclaw/workspace/colorsynth-gpu")
CODE_FILE  = REPO_DIR / "colorsynth_gpu.py"
LOG_FILE   = REPO_DIR / "iteration_log.md"
QWEN_URL   = "http://localhost:8080/v1/chat/completions"
DISCORD_CH = "1495098314121679171"
GIT_REMOTE = "https://github.com/lclawrs/colorsynth-gpu.git"
SAMPLE_RES = "768x768"

# ── Helpers ──────────────────────────────────────────────────────────────────

def qwen(system, user, max_tokens=3000, temperature=0.5):
    """Call local Qwen. Returns content string."""
    payload = {
        "model": "qwen",
        "messages": [
            {"role": "system",  "content": system},
            {"role": "user",    "content": user},
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


def clean_code(text):
    """Strip markdown fences if Qwen added them."""
    text = re.sub(r"^```python\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```\s*$",         "", text, flags=re.MULTILINE)
    return text.strip()


def run(cmd, cwd=None, check=True):
    return subprocess.run(cmd, shell=True, cwd=cwd or REPO_DIR,
                          capture_output=True, text=True, check=check)


def git_pull():
    run("git pull --rebase origin master", check=False)


def git_push(msg):
    run("git add -A")
    run(f'git commit -m "{msg}"', check=False)
    run("git push origin master", check=False)


def discord_send(message=None, image=None):
    """Send text or image to Discord channel via openclaw message tool."""
    # Use the openclaw CLI if available, otherwise use curl to the local API
    if image:
        subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "discord",
             "--target",  DISCORD_CH,
             "--media",   str(image),
             "--message", message or ""],
            capture_output=True, timeout=30, check=False
        )
    else:
        subprocess.run(
            ["openclaw", "message", "send",
             "--channel", "discord",
             "--target",  DISCORD_CH,
             "--message", message],
            capture_output=True, timeout=30, check=False
        )


def generate_samples(labels):
    """Generate sample images for each (variation, colormap) label pair.
       labels = list of (var_idx_or_name, colormap_name, output_path)"""
    images = []
    for var, cmap, outpath in labels:
        r = run(
            f"python3 colorsynth_gpu.py --mode image "
            f"--variation {var} --colormap {cmap} "
            f"--resolution {SAMPLE_RES} --output {outpath}",
            check=False
        )
        if Path(outpath).exists():
            images.append(outpath)
    return images


def read_current_code():
    return CODE_FILE.read_text()


def append_log(entry):
    ts = time.strftime("%Y-%m-%d %H:%M CDT")
    with open(LOG_FILE, "a") as f:
        f.write(f"\n\n---\n## {ts}\n{entry}\n")


# ── Main iteration ────────────────────────────────────────────────────────────

def main():
    t_start = time.perf_counter()
    ts = time.strftime("%Y%m%d_%H%M%S")
    print(f"[{ts}] ColorSynth iteration starting...")

    git_pull()
    current_code = read_current_code()
    code_lines   = current_code.count("\n")

    # ── Step 1: Ask Qwen what to work on ──────────────────────────────────
    SYSTEM_PLANNER = textwrap.dedent("""
        You are an autonomous generative art programmer and creative director.
        You are iterating on the ColorSynth project — a Python generative art engine
        based on complex math (zLIN/zSIN complex planes, sin-based RGB mapping).
        Your job: read the current code, pick ONE focused improvement, and describe it
        in 2-3 sentences. Be specific and creative. Think like an artist-coder.
        
        Ideas you can draw from (but invent your own too):
        - New formula variations (new ways to combine zLIN, zSIN, exp, tanh, log, etc.)
        - New color mapping modes (gradients, lut-based, hue-cycling, etc.)
        - Parameter animation (time-varying formulas, evolving constants)
        - Texture layering (combine two formula outputs)
        - Fractal iteration depth control
        - Symmetry modes (4-fold, 6-fold radial, mirror)
        - New CLI presets with evocative names
        - Output quality improvements (anti-aliasing, supersampling)
        
        Reply with ONLY a JSON object like:
        {"task": "one sentence task name", "description": "2-3 sentence description", "type": "variation|colormap|feature|preset"}
    """).strip()

    USER_PLANNER = f"Current colorsynth_gpu.py has {code_lines} lines. Here are the current variation names and colormaps:\n\n" + \
        run("python3 -c \"import sys; sys.path.insert(0,'.'); import colorsynth_gpu as c; " +
            "print('Variations:', [v[0] for v in c.VARIATIONS]); " +
            "print('Colormaps:', list(c.COLORMAPS.keys()))\"", check=False).stdout.strip() + \
        "\n\nPick something new and interesting to add."

    plan_raw, plan_usage = qwen(SYSTEM_PLANNER, USER_PLANNER, max_tokens=300, temperature=0.7)
    print(f"  Plan tokens: {plan_usage}")

    # Parse plan
    try:
        plan_json = re.search(r"\{.*\}", plan_raw, re.DOTALL).group()
        plan = json.loads(plan_json)
        task_name = plan.get("task", "art iteration")
        task_desc = plan.get("description", "")
        task_type = plan.get("type", "variation")
    except Exception:
        task_name = "creative iteration"
        task_desc = plan_raw[:200]
        task_type = "variation"

    print(f"  Task: {task_name}")
    print(f"  Desc: {task_desc}")

    # ── Step 2: Ask Qwen to implement it ──────────────────────────────────
    SYSTEM_CODER = textwrap.dedent("""
        You are an expert Python generative art programmer working on ColorSynth,
        a generative art engine using complex math (zLIN/zSIN complex planes).
        
        The codebase has:
        - VARIATIONS list: each entry is (name_str, function) where function(zLIN, zSIN, t) returns complex array
        - COLORMAPS dict: each value is function(z) returning (r, g, b) float arrays
        - cp = numpy (or CuPy if available)
        
        Output ONLY a JSON object with this exact shape:
        {
          "type": "variation" or "colormap",
          "name": "snake_case_name",
          "docstring": "one line description",
          "code": "def var_NAME(zLIN, zSIN, t=0.0):\\n    ...\\n    return z"
        }
        
        For a variation: code must be def var_NAME(zLIN, zSIN, t=0.0) returning a complex array using cp operations.
        For a colormap: code must be def cmap_NAME(z) returning (r, g, b) float arrays.
        No markdown. No backticks. Pure JSON.
    """).strip()

    USER_CODER = f"""Task: {task_name}

Description: {task_desc}

Existing variation names (don't duplicate): original, conjugate, exponential, mandelbrot, hyperbolic, fourier, julia, spiral, tidal, vortex

Write ONE new {"variation" if task_type in ("variation","feature") else "colormap"} function as a JSON object."""

    new_code_raw, code_usage = qwen(SYSTEM_CODER, USER_CODER, max_tokens=600, temperature=0.4)
    print(f"  Code tokens: {code_usage}")
    new_code = clean_code(new_code_raw)

    # ── Step 3: Parse and inject Qwen's new function ──────────────────────
    try:
        json_match = re.search(r"\{.*\}", new_code_raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON found in Qwen response")
        addition = json.loads(json_match.group())
        add_type  = addition["type"]    # "variation" or "colormap"
        add_name  = addition["name"]
        add_doc   = addition.get("docstring", "")
        add_code  = addition["code"]
    except Exception as e:
        print(f"  Parse error: {e}\n  Raw: {new_code_raw[:300]}")
        append_log(f"**Task:** {task_name}\n**Result:** Parse error — {e}")
        discord_send(f"🎨 **ColorSynth** — `{task_name}`\n⚠️ Qwen's response couldn't be parsed. Skipping cycle.")
        return

    # Validate the function code syntax
    syntax_check = subprocess.run(
        ["python3", "-c", add_code],
        capture_output=True, text=True
    )
    # syntax error shows in stderr with SyntaxError
    if "SyntaxError" in syntax_check.stderr:
        print(f"  SYNTAX ERROR: {syntax_check.stderr[:200]}")
        append_log(f"**Task:** {task_name}\n**Result:** Syntax error\n```\n{syntax_check.stderr[:200]}\n```")
        discord_send(f"🎨 **ColorSynth** — `{task_name}`\n⚠️ Syntax error in generated code. Skipping.")
        return

    # Inject into the codebase
    code = read_current_code()

    if add_type == "variation":
        prefix = f"var_{add_name}"
        if prefix in code:
            print(f"  Variation {add_name} already exists — skipping duplicate")
            add_name = add_name + "_v2"
            add_code = add_code.replace(f"def var_{addition['name']}", f"def var_{add_name}")

        # Insert function before VARIATIONS list
        insert_before = "\nVARIATIONS = ["
        entry = f'\n    ("{add_name}", var_{add_name}),'
        # Add function def
        code = code.replace(insert_before, f"\n{add_code}\n{insert_before}")
        # Add to VARIATIONS list (before closing bracket)
        code = code.replace("\n]\n\n# ---------------------------------------------------------------------------\n# COLOR MAPPERS", 
                           f"{entry}\n]\n\n# ---------------------------------------------------------------------------\n# COLOR MAPPERS")

    elif add_type == "colormap":
        prefix = f"cmap_{add_name}"
        if prefix in code:
            add_name = add_name + "_v2"
            add_code = add_code.replace(f"def cmap_{addition['name']}", f"def cmap_{add_name}")

        # Insert before COLORMAPS dict
        insert_before = "\nCOLORMAPS = {"
        entry = f'\n    "{add_name}":    cmap_{add_name},'
        code = code.replace(insert_before, f"\n{add_code}\n{insert_before}")
        code = code.replace('\n}\n\n# ---------------------------------------------------------------------------\n# IMAGE GENERATOR',
                           f"{entry}\n}}\n\n# ---------------------------------------------------------------------------\n# IMAGE GENERATOR")

    # Final syntax check on the whole file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as tf:
        tf.write(code)
        tf_name = tf.name
    full_syntax = subprocess.run(
        ["python3", "-m", "py_compile", tf_name],
        capture_output=True, text=True
    )
    os.unlink(tf_name)
    if full_syntax.returncode != 0:
        print(f"  Full file syntax error — reverting\n  {full_syntax.stderr[:300]}")
        append_log(f"**Task:** {task_name}\n**Result:** Injection caused syntax error — reverted")
        discord_send(f"🎨 **ColorSynth** — `{task_name}`\n⚠️ Injection caused syntax error. Reverted.")
        return

    # ── Step 4: Apply the new code ────────────────────────────────────────
    backup = CODE_FILE.with_suffix(".py.bak")
    backup.write_text(read_current_code())
    CODE_FILE.write_text(code)
    new_code = code
    print(f"  Injected {add_type} '{add_name}' ✓")

    # ── Step 5: Generate sample images ───────────────────────────────────
    # Use the newly added variation/colormap if possible
    if add_type == "variation":
        # Find its index in the updated file by reloading
        var_name_for_sample = add_name
        cmap_for_sample = random.choice(["psychedelic", "original", "hsv", "fire", "palette"])
        samples_spec = [
            (var_name_for_sample, cmap_for_sample, str(REPO_DIR / f"sample_{ts}_{add_name}_{cmap_for_sample}.png")),
            (var_name_for_sample, "psychedelic",   str(REPO_DIR / f"sample_{ts}_{add_name}_psychedelic.png")),
        ]
    else:
        # New colormap — render a few variations with it
        samples_spec = [
            (0, add_name, str(REPO_DIR / f"sample_{ts}_original_{add_name}.png")),
            (random.randint(1,9), add_name, str(REPO_DIR / f"sample_{ts}_vX_{add_name}.png")),
        ]
    images = generate_samples(samples_spec)
    print(f"  Generated {len(images)} sample(s)")

    # ── Step 6: Ask Qwen to describe the output artistically ─────────────
    SYSTEM_DESCRIBER = "You are a poetic art critic describing generative mathematical art. Be evocative and brief — 2 sentences max."
    USER_DESCRIBER = f"Describe the visual character of this ColorSynth variation: {task_desc} What does it look like?"
    art_desc, _ = qwen(SYSTEM_DESCRIBER, USER_DESCRIBER, max_tokens=120, temperature=0.8)
    art_desc = art_desc.strip()

    # ── Step 7: Commit and push ───────────────────────────────────────────
    new_lines = new_code.count("\n")
    delta = new_lines - code_lines
    commit_msg = f"art: {task_name} (+{delta} lines) [{ts}]"
    git_push(commit_msg)
    print(f"  Pushed: {commit_msg}")

    # ── Step 8: Log and report ────────────────────────────────────────────
    elapsed = time.perf_counter() - t_start
    log_entry = f"**Task:** {task_name}\n**Type:** {task_type}\n**Desc:** {task_desc}\n**Art:** {art_desc}\n**Tokens:** plan={plan_usage.get('total_tokens',0)} + code={code_usage.get('total_tokens',0)}\n**Time:** {elapsed:.0f}s"
    append_log(log_entry)

    # Send to Discord
    report = (f"🎨 **ColorSynth** — `{task_name}`\n"
              f"> {art_desc}\n"
              f"Lines: {code_lines}→{new_lines} | ⏱ {elapsed:.0f}s | "
              f"<https://github.com/lclawrs/colorsynth-gpu>")

    if images:
        discord_send(message=report, image=images[0])
        if len(images) > 1:
            discord_send(image=images[1])
    else:
        discord_send(message=report + "\n_(no image generated this cycle)_")

    print(f"  Done in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
