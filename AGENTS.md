# YTB02 AutoEditor scope

- This project is a local automatic video assembler/editor.
- The user provides all video clips; this project never creates them.
- The JSON script is the source of truth for scene order and subtitle text.
- Audio is the master timeline. Always use measured WAV durations.
- Kokoro handles English and Vietnamese narration through its configured Python environment.
- FFmpeg/ffprobe handle media processing.
- Subtitle text comes only from the script. Do not use speech-to-text.
- No image generation and no AI video generation.
- No database, message queue, Docker, backend, frontend, or web stack.
- Keep the architecture lightweight, local, and Windows-first using Python 3.12.
- Do not modify, delete, or write into `H:\KokoroCPU`; invoke its Python only.
- Keep intermediate artifacts in `work/` and never delete user input clips.
