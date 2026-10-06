# Third-party software in the Windows build

Breakfast itself is MIT licensed (see LICENSE). The Windows build also contains:

- **Python** and the packages listed in `requirements.txt` (FastAPI, uvicorn, paho-mqtt, requests, edge-tts, ...),
  each under its own open-source license.
- **FFmpeg** (`ffmpeg.exe`, the LGPL build from https://github.com/BtbN/FFmpeg-Builds), used only to trim
  silence from generated voice-pack files. It runs as a separate program. Its source code and license are
  available from https://ffmpeg.org/ and from the build's own repository.
