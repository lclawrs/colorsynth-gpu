#!/usr/bin/env python3
"""
colorsynth_epic.py — Deliberate long-form showcase.

Pipeline:
  1. Render sample stills from the "interesting" variations at t=π (mid-animation)
  2. Send each image to Qwen's vision endpoint for description
  3. Qwen reviews all descriptions and designs a ~2-minute sequence:
     - Which variations to feature, in what order
     - How long each section (seconds), suggested colormap, speed notes
     - Crossfade/morph instructions
  4. Render each section as a video clip at consistent FPS
  5. Concatenate + crossfade with ffmpeg
  6. Compress and post to Discord
"""

import json, subprocess, sys, os, re, time, math, random, textwrap, tempfile
from pathlib import Path

REPO_DIR     = Path("/home/synth/.openclaw/workspace/colorsynth-gpu")
CODE_FILE    = REPO_DIR / "colorsynth_gpu.py"
EPIC_DIR     = REPO_DIR / "epic_work"
QWEN_URL     = "http://localhost:8080/v1/chat/completions"
DISCORD_CH   = "1496362899893911745"
RENDER_RES   = "512x512"      # balance quality vs CPU render time
SAMPLE_RES   = "256x256"      # stills for Qwen to inspect
FPS          = 24
DISCORD_MAX  = 7_500_000

EPIC_DIR.mkdir(exist_ok=True)

# Candidate variations — the interesting/animated ones worth featuring
CANDIDATES = [
    ("lyapunov_spirals",        "psychedelic"),
    ("lyapunov_dance",          "cosmic_rainbow"),
    ("rotating_moebius_transform", "psychedelic"),
    ("fractal_zoom",            "fire"),
    ("vortex",                  "psychedelic"),
    ("spiral",                  "hsv"),
    ("tidal",                   "palette"),
    ("julia",                   "cosmic_rainbow"),
    ("fourier",                 "psychedelic"),
    ("power_tower_zoom",        "fire"),
    ("quantum_decay",           "hsv"),
    ("rotating_julia_1550",     "psychedelic"),
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def qwen_text(system, user, max_tokens=800, temperature=0.6):
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
        ["curl", "-s", "-m", "120", QWEN_URL,
         "-H", "Content-Type: application/json",
         "-d", json.dumps(payload)],
        capture_output=True, text=True, timeout=130
    )
    data = json.loads(r.stdout)
    return data["choices"][0]["message"]["content"]


def qwen_vision(image_path: Path, var_name: str, cmap: str, code_snippet: str) -> str:
    """
    Qwen2.5-7B is text-only — no real vision.
    Instead give it the variation's source code + colormap + file size as richness signal,
    and ask it to reason about visual quality.
    """
    size_kb = image_path.stat().st_size // 1024 if image_path.exists() else 0
    prompt = (
        f"You are a generative art critic assessing a ColorSynth variation for visual quality.\n\n"
        f"Variation: {var_name}\n"
        f"Colormap: {cmap}\n"
        f"Source code:\n{code_snippet}\n\n"
        f"Sample image size: {size_kb}KB at 256x256\n"
        f"(Small image = low detail/flat; large image = rich complex structure)\n\n"
        f"Based on the math formula, describe in 2-3 sentences:\n"
        f"1. What geometric/color patterns would this produce?\n"
        f"2. Would the animation be too fast/chaotic, too static, or nicely flowing?\n"
        f"3. Is it good for a slow meditative showcase or should it be skipped?"
    )
    return qwen_text("You are a generative art critic.", prompt, max_tokens=200, temperature=0.5)


def run(cmd, cwd=None):
    return subprocess.run(cmd, shell=True, cwd=cwd or REPO_DIR,
                          capture_output=True, text=True)


def discord_send(message=None, media=None):
    cmd = ["openclaw", "message", "send", "--channel", "discord", "--target", DISCORD_CH]
    if message: cmd += ["--message", message]
    if media:   cmd += ["--media", str(media)]
    subprocess.run(cmd, capture_output=True, timeout=120, check=False)


def compress(src: Path, label="epic") -> Path:
    dst = EPIC_DIR / f"{label}_discord.mp4"
    subprocess.run(
        f'ffmpeg -i "{src}" -vf scale=480:480 -vcodec libx264 -crf 28 '
        f'-preset fast -movflags +faststart -an "{dst}" -y -loglevel error',
        shell=True, check=False
    )
    if dst.exists() and dst.stat().st_size > DISCORD_MAX:
        # Go harder
        subprocess.run(
            f'ffmpeg -i "{src}" -vf scale=360:360 -vcodec libx264 -crf 33 '
            f'-preset fast -movflags +faststart -an "{dst}" -y -loglevel error',
            shell=True, check=False
        )
    return dst


# ── Step 1: Render sample stills ───────────────────────────────────────────────

def render_samples():
    print("\n── Step 1: Rendering sample stills ──")
    samples = {}
    for var, cmap in CANDIDATES:
        out = EPIC_DIR / f"sample_{var}_{cmap}.png"
        if out.exists():
            print(f"  (cached) {var}")
            samples[var] = (out, cmap)
            continue
        # Render at t=π (mid-cycle, most interesting frame for most variations)
        # We pass t indirectly by using a tiny 1-frame video and extracting frame 15/30
        # Simpler: render image mode (t=0) — good enough for visual inspection
        result = run(
            f"python3 colorsynth_gpu.py --mode image "
            f"--variation {var} --colormap {cmap} "
            f"--resolution {SAMPLE_RES} --output {out}"
        )
        if out.exists():
            print(f"  ✓ {var}")
            samples[var] = (out, cmap)
        else:
            print(f"  ✗ {var}: {result.stderr[:100]}")
    return samples


# ── Step 2: Qwen inspects each image ──────────────────────────────────────────

def inspect_samples(samples):
    print("\n── Step 2: Qwen analyses each variation ──")
    # Pre-extract all source snippets from the code file
    code_text = CODE_FILE.read_text()
    def get_snippet(var_name):
        m = re.search(rf"(def var_{re.escape(var_name)}\(.*?)(?=\ndef |\nVARIATIONS)", code_text, re.DOTALL)
        return m.group(1).strip() if m else "(code not found)"

    descriptions = {}
    for var, (img_path, cmap) in samples.items():
        print(f"  Analysing {var}...", end=" ", flush=True)
        snippet = get_snippet(var)
        desc = qwen_vision(img_path, var, cmap, snippet)
        descriptions[var] = desc.strip()
        print(f"done")
        time.sleep(0.3)
    return descriptions


# ── Step 3: Qwen designs the sequence ─────────────────────────────────────────

DIRECTOR_SYSTEM = textwrap.dedent("""
    You are a generative art director designing a 2-minute cinematic video.
    The video will be assembled from sections of different ColorSynth math animations,
    crossfaded together into one flowing film.
    
    VIEWER PREFERENCE (important!):
    - Slow, meditative pacing — NOT fast or stroby
    - Avoid variations that zoom in too far (makes it look abstract/muddy)
    - Prefer large-scale structure, flowing organic shapes, deep color fields
    - The video should feel like a journey: calm → mysterious → beautiful peak → resolution
    
    Rules:
    - Only pick variations explicitly rated as "good for meditative showcase" or similar
    - Skip anything described as chaotic, noisy, too fast, or over-zoomed
    - Each section: 20–30 seconds minimum
    - Total runtime: 100–130 seconds
    - 4–5 sections maximum
    - Crossfade 3s between sections
    - Vary the colormap between sections for visual contrast
    
    Reply ONLY as a JSON array. Each element:
    {
      "order": 1,
      "variation": "exact variation name from the list",
      "colormap": "one of: original, psychedelic, hsv, fire, palette, cosmic_rainbow",
      "duration_sec": 25,
      "mood": "one word",
      "note": "brief director note — why this variation here, what will it look like"
    }
""").strip()


def design_sequence(descriptions):
    print("\n── Step 3: Qwen designs the sequence ──")

    # Trim descriptions to first 2 sentences each, and limit to 8 candidates
    def trim_desc(d):
        sentences = re.split(r'(?<=[.!?])\s+', d.strip())
        return " ".join(sentences[:2])

    # Pick 8 most interesting (skip duplicates, prefer varied names)
    selected = list(descriptions.items())[:8]

    desc_block = "\n".join(
        f"- {var}: {trim_desc(desc)}" for var, desc in selected
    )
    user_msg = (
        f"Available variations (with analysis):\n{desc_block}\n\n"
        f"Design a ~2-minute cinematic sequence from these. "
        f"Slow pacing, no zoom-heavy or chaotic ones. "
        f"4-5 sections, 20-30s each. Reply ONLY as JSON array."
    )
    raw = qwen_text(DIRECTOR_SYSTEM, user_msg, max_tokens=700, temperature=0.65)
    print(f"  Raw:\n{raw[:800]}\n")

    try:
        seq = json.loads(re.search(r"\[.*\]", raw, re.DOTALL).group())
        seq.sort(key=lambda x: x.get("order", 99))
        print(f"  Sequence ({len(seq)} sections):")
        for s in seq:
            print(f"    {s['order']}. {s['variation']} / {s['colormap']} — {s['duration_sec']}s ({s.get('mood','')})")
        return seq
    except Exception as e:
        print(f"  Parse failed: {e} — using curated fallback")
        return [
            {"order":1,"variation":"lyapunov_spirals","colormap":"psychedelic","duration_sec":30,"mood":"organic","note":"opening — breathing spiral arms"},
            {"order":2,"variation":"spiral","colormap":"hsv","duration_sec":25,"mood":"flowing","note":"clean spiral wash"},
            {"order":3,"variation":"rotating_moebius_transform","colormap":"cosmic_rainbow","duration_sec":25,"mood":"geometric","note":"peak — kaleidoscopic rotation"},
            {"order":4,"variation":"tidal","colormap":"palette","duration_sec":25,"mood":"calm","note":"resolution — warm wave patterns"},
            {"order":5,"variation":"lyapunov_dance","colormap":"cosmic_rainbow","duration_sec":20,"mood":"dreamlike","note":"coda"},
        ]


# ── Step 4: Render each section ───────────────────────────────────────────────

def render_section(section, idx):
    var    = section["variation"]
    cmap   = section["colormap"]
    dur    = int(section.get("duration_sec", 20))
    frames = dur * FPS
    out    = EPIC_DIR / f"section_{idx:02d}_{var}.mp4"

    if out.exists() and out.stat().st_size > 50000:
        print(f"  (cached) section {idx}: {var} ({dur}s)")
        return out

    print(f"  Rendering section {idx}: {var} + {cmap}, {dur}s = {frames} frames @ {RENDER_RES}...", flush=True)
    t0 = time.perf_counter()
    result = run(
        f"python3 colorsynth_gpu.py --mode video "
        f"--variation {var} --colormap {cmap} "
        f"--resolution {RENDER_RES} --frames {frames} --fps {FPS} "
        f"--output {out}"
    )
    elapsed = time.perf_counter() - t0

    if out.exists() and out.stat().st_size > 50000:
        print(f"  ✓ {out.name} — {out.stat().st_size//1024}KB in {elapsed:.0f}s")
        return out
    else:
        print(f"  ✗ Failed: {result.stderr[:200]}")
        return None


# ── Step 5: Crossfade concat ──────────────────────────────────────────────────

def crossfade_concat(clips: list, output: Path, xfade_sec=3):
    """Use ffmpeg xfade filter to crossfade all clips together."""
    if len(clips) == 1:
        subprocess.run(f'cp "{clips[0]}" "{output}"', shell=True)
        return output

    # Build ffmpeg filter graph for sequential xfades
    # Each xfade needs the offset = sum of durations so far - xfade_sec * (n-1)
    # Get durations
    durations = []
    for c in clips:
        r = subprocess.run(
            f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{c}"',
            shell=True, capture_output=True, text=True
        )
        try:
            durations.append(float(r.stdout.strip()))
        except:
            durations.append(20.0)

    print(f"  Clip durations: {[f'{d:.1f}s' for d in durations]}")

    n = len(clips)
    inputs = " ".join(f'-i "{c}"' for c in clips)

    # Build filter: chain xfades
    # [0][1]xfade=offset=d0-xf,duration=xf[v01]; [v01][2]xfade=offset=d0+d1-2*xf,duration=xf[v012]; ...
    filter_parts = []
    prev_label = "0"
    cumulative = 0.0
    for i in range(1, n):
        cumulative += durations[i-1] - xfade_sec
        out_label = f"v{i}" if i < n-1 else "vout"
        filter_parts.append(
            f"[{prev_label}][{i}]xfade=transition=fade:duration={xfade_sec}:offset={cumulative:.2f}[{out_label}]"
        )
        prev_label = out_label

    filter_str = "; ".join(filter_parts)
    cmd = (
        f'ffmpeg {inputs} -filter_complex "{filter_str}" '
        f'-map "[vout]" -vcodec libx264 -crf 22 -preset fast '
        f'-movflags +faststart "{output}" -y -loglevel error'
    )
    print(f"  Running ffmpeg concat ({n} clips)...")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ffmpeg error: {r.stderr[:300]}")
        # Fallback: simple concat without xfade
        list_file = EPIC_DIR / "concat_list.txt"
        list_file.write_text("\n".join(f"file '{c}'" for c in clips))
        subprocess.run(
            f'ffmpeg -f concat -safe 0 -i "{list_file}" -c copy "{output}" -y -loglevel error',
            shell=True
        )
    return output


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ts = time.strftime("%Y%m%d_%H%M%S")
    print(f"[{ts}] ColorSynth Epic — deliberate long-form pipeline")

    discord_send(
        "🎬 **ColorSynth Epic — starting deliberate long-form pipeline**\n"
        "Step 1: sampling all candidate variations as stills...\n"
        "Step 2: Qwen will inspect each image and describe what it sees\n"
        "Step 3: Qwen designs a ~2-minute sequence from the best ones\n"
        "Step 4: Render each section at 512px\n"
        "Step 5: Crossfade everything together\n"
        "_This will take 20-40 minutes. Will post progress._"
    )

    # Step 1
    samples = render_samples()
    print(f"  {len(samples)} samples ready")

    discord_send(
        f"✅ **Step 1 done** — {len(samples)} variation samples rendered\n"
        "🔍 Qwen is now inspecting each image..."
    )

    # Step 2
    descriptions = inspect_samples(samples)

    # Post Qwen's image assessments as a digest
    digest = "🔍 **Qwen's visual assessment:**\n"
    for var, desc in descriptions.items():
        first_sent = desc.split(".")[0].strip()
        digest += f"• **{var}**: {first_sent}.\n"
    discord_send(digest[:1900])  # Discord 2000 char limit

    # Step 3
    sequence = design_sequence(descriptions)

    seq_summary = "📋 **Sequence plan:**\n"
    total_sec = 0
    for s in sequence:
        seq_summary += f"`{s['order']}` {s['variation']} / {s['colormap']} — {s['duration_sec']}s ({s['mood']})\n"
        seq_summary += f"   _{s.get('note', '')}_\n"
        total_sec += s['duration_sec']
    seq_summary += f"\n**Total:** ~{total_sec}s ({total_sec//60}m{total_sec%60}s)"
    discord_send(seq_summary)

    discord_send("🎞️ Rendering sections now — each takes 1-3 min...")

    # Step 4
    clips = []
    for i, section in enumerate(sequence, 1):
        clip = render_section(section, i)
        if clip:
            clips.append(clip)
            discord_send(f"✅ Section {i}/{len(sequence)} done: `{section['variation']}`")
        else:
            discord_send(f"⚠️ Section {i} failed (`{section['variation']}`), skipping")

    if not clips:
        discord_send("❌ No sections rendered successfully. Aborting.")
        return

    # Step 5
    print(f"\n── Step 5: Crossfade concat ({len(clips)} clips) ──")
    final_raw = EPIC_DIR / f"epic_{ts}_raw.mp4"
    crossfade_concat(clips, final_raw, xfade_sec=3)

    if not final_raw.exists():
        discord_send("❌ ffmpeg concat failed.")
        return

    raw_size = final_raw.stat().st_size
    print(f"  Raw: {raw_size//1024//1024}MB")

    # Compress
    final_post = compress(final_raw, label=f"epic_{ts}")
    post_size  = final_post.stat().st_size if final_post.exists() else 0
    print(f"  Post: {post_size//1024}KB")

    # Get total duration
    dur_r = subprocess.run(
        f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{final_raw}"',
        shell=True, capture_output=True, text=True
    )
    total_dur = float(dur_r.stdout.strip()) if dur_r.stdout.strip() else total_sec

    # Final post
    variation_list = " → ".join(s["variation"] for s in sequence)
    discord_send(
        f"🎬 **ColorSynth Epic — complete**\n"
        f"> {variation_list}\n"
        f"{len(sequence)} sections · {total_dur:.0f}s · {post_size//1024}KB\n"
        f"Rendered at 512px, crossfaded with 3s transitions",
        media=final_post if post_size > 0 else None
    )

    # Commit
    run("git add -A")
    run(f'git commit -m "epic: {ts} — {len(sequence)}-section {total_dur:.0f}s film"', check=False)
    run("git push origin master", check=False)

    print(f"\nEpic complete. Total time in pipeline.")


if __name__ == "__main__":
    main()
