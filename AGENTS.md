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

## Required Git and GitHub workflow

- Never implement or commit features directly on `main`.
- Create a GitHub Issue before coding each feature or milestone. Include its goal, scope, and clear Acceptance Criteria.
- Create the feature branch from `main` using `feat/<issue-number>-<short-name>`.
- Preserve existing local changes when moving work from `main` to a feature branch.
- Run all relevant tests and checks before committing.
- Commit messages must be written in Vietnamese with diacritics. An English Conventional Commit prefix is allowed.
- Reference the Issue in the commit message, for example `Refs #12`.
- After tests pass, stage, commit, and push the feature branch to `origin`.
- Open a Pull Request into `main`; link the Issue and document changes and tests run.
- Do not merge while CI is failing or while blockers remain.
- When CI passes and no blockers remain, squash-merge the PR and confirm the linked Issue is closed.
- Never force-push, commit directly to `main`, or weaken/delete tests to make CI pass.
- Continue routine Git/GitHub steps automatically. Request approval only when permissions require it.
