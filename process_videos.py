import subprocess
import re
import sys
from pathlib import Path
from tqdm import tqdm

# ------------------------------
# Run ffmpeg with progress bar
# ------------------------------
def run_ffmpeg_with_progress(cmd, total_duration=None, desc="Processing"):
    print("▶ Running:", " ".join(str(c) for c in cmd))

    process = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,                # enable text mode
        encoding="utf-8",         # force utf-8 decoding
        errors="replace",         # replace undecodable chars instead of crashing
        bufsize=1
    )

    pbar = None
    if total_duration:
        pbar = tqdm(total=total_duration, unit="s", desc=desc, file=sys.stdout, ncols=80)

    time_pattern = re.compile(r"time=(\d+):(\d+):(\d+).(\d+)")

    for line in process.stderr:
        if "time=" in line and total_duration and pbar:
            match = time_pattern.search(line)
            if match:
                h, m, s, ms = match.groups()
                seconds = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 100.0
                pbar.n = min(seconds, total_duration)
                pbar.refresh()

    process.wait()

    if pbar:
        pbar.n = pbar.total
        pbar.close()

    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd)

# ------------------------------
# Probe video duration
# ------------------------------
def get_duration(video_path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ],
        capture_output=True, text=True, check=True
    )
    return float(result.stdout.strip())

# ------------------------------
# Probe video stream info (width, height, fps)
# ------------------------------
def get_stream_info(video_path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ],
        capture_output=True, text=True, check=True
    )
    lines = result.stdout.strip().splitlines()
    width, height, fps_str = lines
    num, den = map(int, fps_str.split("/"))
    fps = num / den if den != 0 else 25
    return int(width), int(height), fps

# ------------------------------
# Build crossfade chain
# ------------------------------
def build_crossfade_filter(intro_img, main_video, outro_img, main_duration,
                           w, h, fps, intro_visible=4.0, crossfade_dur=1.0, outro_visible=4.0):

    offset1 = intro_visible
    offset2 = offset1 + main_duration - crossfade_dur
    intro_ms = int(intro_visible * 1000)

    return (
        f"[1:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[vmain];"
        f"[0:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[vintro];"
        f"[2:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[voutro];"
        f"[vintro][vmain]xfade=transition=fade:duration={crossfade_dur}:offset={offset1}[im];"
        f"[im][voutro]xfade=transition=fade:duration={crossfade_dur}:offset={offset2}[outv];"
        f"[1:a]afade=t=out:st={max(0, main_duration-crossfade_dur)}:d={crossfade_dur}[a1];"
        f"[a1]adelay={intro_ms}|{intro_ms},asetpts=PTS-STARTPTS[aout]"
    )

# ------------------------------
# Process one project
# ------------------------------
def process_project(proj_dir, codec):
    print(f"\n🚀 Processing project: {proj_dir.name}")
    work_dir = proj_dir / "02_Work"
    final_dir = proj_dir / "03_Final"
    work_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    # Find main video
    main_video = next(proj_dir.glob("*.mp4"), None)
    if main_video is None:
        print(f"⚠️ No main video found in {proj_dir}")
        return

    intro_img = proj_dir / "intro.png"
    outro_img = proj_dir / "outro.png"
    if not intro_img.exists() or not outro_img.exists():
        print(f"⚠️ Missing intro/outro in {proj_dir}")
        return

    normalized_video = work_dir / "normalized.mp4"
    final_video = final_dir / f"{proj_dir.name}_final.mp4"

    # Normalize audio
    run_ffmpeg_with_progress([
        "ffmpeg", "-y",
        "-i", str(main_video),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        str(normalized_video)
    ], total_duration=get_duration(main_video), desc="Normalizing")

    # Get main duration
    main_dur = get_duration(normalized_video)
    print(f"⏱ Main video duration: {main_dur:.2f} sec")

    # Probe fps/res
    w, h, fps = get_stream_info(normalized_video)

    filter_complex = build_crossfade_filter(intro_img, normalized_video, outro_img,
                                            main_dur, w, h, fps)

    # Codec selection
    if codec == "h265":  # CPU libx265 (archival)
        vcodec = [
            "-c:v", "libx265",
            "-pix_fmt", "yuv420p",
            "-x265-params", "crf=28"
        ]
    elif codec == "h264":  # GPU h264 (fallback / compatibility)
        vcodec = [
            "-c:v", "h264_nvenc",
            "-pix_fmt", "yuv420p"
        ]
    else:  # Default = h265_nvenc (HQ on modern RTX cards)
        vcodec = [
            "-c:v", "hevc_nvenc",
            "-preset", "p7",
            "-tune", "hq",
            "-pix_fmt", "yuv420p"
        ]

    total_proj_duration = main_dur + 8  # intro+outro approx
    run_ffmpeg_with_progress([
        "ffmpeg", "-y",
        "-loop", "1", "-t", "5", "-i", str(intro_img),
        "-i", str(normalized_video),
        "-loop", "1", "-t", "5", "-i", str(outro_img),
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[aout]",
        *vcodec,
        "-c:a", "aac", "-b:a", "192k",
        str(final_video)
    ], total_duration=total_proj_duration, desc="Rendering")

    print(f"✅ Finished project: {proj_dir.name}")
    print(f"🎬 Final video: {final_video}\n")

# ------------------------------
# Main entry
# ------------------------------
def main():
    ROOT = Path(__file__).parent
    VID_DIR = ROOT / "VID"

    if not VID_DIR.exists():
        print(f"❌ No 'VID' folder found at {VID_DIR}")
        sys.exit(1)

    codec = "h265_nvenc"  # default now is GPU HEVC with HQ settings
    if "--codec" in sys.argv:
        idx = sys.argv.index("--codec")
        if idx + 1 < len(sys.argv):
            codec = sys.argv[idx + 1].lower()
            
    proj_dirs = [d for d in VID_DIR.iterdir() if d.is_dir()]
    for proj_dir in proj_dirs:
        process_project(proj_dir, codec)

if __name__ == "__main__":
    main()
