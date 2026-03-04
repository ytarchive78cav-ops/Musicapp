# Melody Launchpad (Replit)

Web app for songwriters to record/upload a vocal melody, estimate BPM/key, derive quantized melody notes, suggest chord progressions, audition arrangements, and export MIDI for DAW use.

## Stack
- Frontend: React + TypeScript + Vite (`/frontend`)
- Backend: FastAPI + librosa + mido (`/backend`)

## Run in Replit
1. Click **Run** (uses `./run.sh`).
2. Frontend opens at port 5173 and proxies `/api` to backend port 8000.

## Features
- Record (mic) or upload audio (`wav`, `mp3`, `m4a`, browser `webm` recording)
- Analysis job pipeline with step logs
- Melody extraction to note events: `start_s`, `dur_s`, `midi`, `name`, confidence
- BPM + confidence, key candidates + confidence, editable overrides
- Quantized melody timeline and chord timeline
- Ranked per-segment chord candidates + top 10 full progression options
- Chord swapping and progression reordering
- Playback of vocal audio and synthesized chord backing
- Export: `melody.mid`, `chords.mid`, chord chart text, and session JSON
- Open session JSON reload
- Confidence panel + warnings for low monophonicity
- Report issue workflow: download result/session JSON and logs from UI export buttons (raw audio not included)

## Audio analysis details
- Audio is converted to mono, normalized, high-pass filtered.
- Tempo via onset strength + beat tracking (`librosa.beat.beat_track`).
- Pitch extraction via `librosa.pyin` (monophonic-friendly), eventized with smoothing and min-note duration.
- Quantization maps notes to selected grid.
- Key estimation uses duration/metrical weighted pitch-class histogram + Krumhansl-like profiles.
- Chord scoring allows non-chord tones with penalties and adds transition smoothness.
- Progressions are generated via beam search over segment candidates.

## Dependency fallback behavior
- Preferred dependency is `librosa` with `pyin`; if `pyin` is unavailable the app currently errors with a clear message.
- Replit fallback recommendation: install `aubio` and wire aubio pitch tracking in `backend/app/analysis.py` (documented here if libc build constraints affect librosa backends).

## Recording tips
- Sing one melody line only (no harmony doubles)
- Use headphones during metronome recording to avoid bleed
- Keep room noise low; avoid reverb-heavy spaces

## Mic troubleshooting
- Ensure browser mic permissions are granted.
- In Replit preview, open in a new tab if permission prompts are blocked.
- If recording is silent, test upload flow with sample file first.

## Testing
```bash
# backend unit tests
source .venv/bin/activate && pytest backend/tests -q

# sample end-to-end analysis printout
PYTHONPATH=backend python backend/tests/run_sample_analysis.py
```

Sample file for quick testing is generated locally (not committed as binary): `python scripts/generate_sample_audio.py` then use `backend/data/sample_melody.wav`.

## GitHub push / PR troubleshooting
- If you see a 400 while creating a PR in mobile UI, it is usually a GitHub auth/session issue, not a repository code issue.
- Reconnect the GitHub account in Replit/Codex, refresh the session, and retry the push/PR action.
- Confirm the target repo/branch exists and you have write permission.
- If it still fails, copy the error request ID and retry from desktop browser where auth popups are less likely to be blocked.

- If Codex/GitHub UI shows `Binary files are not supported`, remove binary files from the commit (for this repo: generate sample audio locally instead of committing `.wav`).
