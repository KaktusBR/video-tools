# 🎬 Video Tools

A collection of Python + FFmpeg utilities for automating video processing.

## 📂 Current Tool: `process_videos.py`

This script automates the process of:

- Normalizing audio loudness (`-16 LUFS`)
- Adding an **intro image** (slate) and an **outro image**
- Crossfading between intro → main video → outro
- Encoding the final result using NVIDIA NVENC (H.265 by default)

---

## 🚀 Usage

1. Place your projects inside the `VID/` folder with the following structure:

```bash
VID/
├── Project1/
│ ├── video.mp4
│ ├── intro.png
│ └── outro.png
├── Project2/
│ ├── video.mp4
│ ├── intro.png
│ └── outro.png
```

2. Run the script:

Default: hevc_nvenc -preset p7 -tune hq (fast + high quality)

```bash
python process_videos.py
```

bx265 -crf 28

```bash
python process_videos.py --codec h265
```

h264_nvenc

```bash
python process_videos.py --codec h264
```

---

## 📌 Requirements

- Python 3.9+
- FFmpeg installed and available in PATH
- NVIDIA GPU with NVENC support (for GPU modes)
