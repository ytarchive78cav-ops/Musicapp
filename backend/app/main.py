from __future__ import annotations

import io
import json
import uuid
from pathlib import Path
from threading import Thread
from typing import Dict, List

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from mido import Message, MidiFile, MidiTrack, MetaMessage
from pydantic import BaseModel

from .analysis import analyze_audio_file

BASE = Path(__file__).resolve().parents[1]
UPLOAD_DIR = BASE / "uploads"
SESSION_DIR = BASE / "sessions"
EXPORT_DIR = BASE / "exports"
for d in [UPLOAD_DIR, SESSION_DIR, EXPORT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Melody Launchpad API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: Dict[str, Dict] = {}


def _run_job(job_id: str, audio_path: Path, session_path: Path):
    try:
        JOBS[job_id]["status"] = "processing"
        logs: List[str] = []

        def logger(msg: str):
            logs.append(msg)
            JOBS[job_id]["progress"] = min(95, len(logs) * 14)
            JOBS[job_id]["logs"] = logs[:]

        result = analyze_audio_file(audio_path, session_path, log_cb=logger)
        JOBS[job_id].update({"status": "done", "progress": 100, "logs": logs, "result": result})
    except Exception as exc:
        JOBS[job_id].update({"status": "error", "error": str(exc)})


@app.post("/api/analyze")
async def analyze(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    suffix = Path(file.filename).suffix or ".wav"
    audio_path = UPLOAD_DIR / f"{job_id}{suffix}"
    content = await file.read()
    audio_path.write_bytes(content)
    session_path = SESSION_DIR / f"{job_id}.json"
    JOBS[job_id] = {"status": "queued", "progress": 2, "logs": ["job queued"]}
    background_tasks.add_task(_run_job, job_id, audio_path, session_path)
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


class ExportRequest(BaseModel):
    bpm: float
    time_signature: str
    melody_notes: List[dict]
    progression: List[dict]


def _write_melody_midi(path: Path, notes: List[dict], bpm: float):
    midi = MidiFile(ticks_per_beat=480)
    track = MidiTrack()
    midi.tracks.append(track)
    tempo = int(60_000_000 / max(1, bpm))
    track.append(MetaMessage("set_tempo", tempo=tempo, time=0))
    last_tick = 0
    for n in sorted(notes, key=lambda x: x["start_s"]):
        start = int(n["start_s"] * bpm / 60 * 480)
        dur = max(60, int(n["dur_s"] * bpm / 60 * 480))
        delta = max(0, start - last_tick)
        track.append(Message("note_on", note=int(n["midi"]), velocity=90, time=delta))
        track.append(Message("note_off", note=int(n["midi"]), velocity=0, time=dur))
        last_tick = start + dur
    midi.save(path)


def _chord_to_midis(name: str):
    root_map = {"C": 60, "C#": 61, "D": 62, "D#": 63, "E": 64, "F": 65, "F#": 66, "G": 67, "G#": 68, "A": 69, "A#": 70, "B": 71}
    root = name[0]
    rem = name[1:]
    if rem.startswith("#"):
        root += "#"
        rem = rem[1:]
    base = root_map[root]
    if rem.startswith("m") and not rem.startswith("maj"):
        triad = [base, base + 3, base + 7]
    elif rem.startswith("dim"):
        triad = [base, base + 3, base + 6]
    else:
        triad = [base, base + 4, base + 7]
    if "7" in rem:
        triad.append(base + (11 if "maj7" in rem else 10))
    return triad


def _write_chords_midi(path: Path, progression: List[dict], bpm: float):
    midi = MidiFile(ticks_per_beat=480)
    track = MidiTrack()
    midi.tracks.append(track)
    tempo = int(60_000_000 / max(1, bpm))
    track.append(MetaMessage("set_tempo", tempo=tempo, time=0))
    beat_ticks = 480
    seg_ticks = beat_ticks * 2
    for idx, c in enumerate(progression):
        notes = _chord_to_midis(c["chord_name"])
        delta = 0 if idx == 0 else 0
        for n in notes:
            track.append(Message("note_on", note=n, velocity=70, time=delta))
            delta = 0
        off_time = seg_ticks
        for i, n in enumerate(notes):
            track.append(Message("note_off", note=n, velocity=0, time=off_time if i == 0 else 0))
            off_time = 0
    midi.save(path)


@app.post("/api/export/midi")
def export_midi(payload: ExportRequest):
    export_id = str(uuid.uuid4())
    melody_path = EXPORT_DIR / f"{export_id}_melody.mid"
    chords_path = EXPORT_DIR / f"{export_id}_chords.mid"
    chart_path = EXPORT_DIR / f"{export_id}_chart.txt"

    _write_melody_midi(melody_path, payload.melody_notes, payload.bpm)
    _write_chords_midi(chords_path, payload.progression, payload.bpm)

    lines = []
    for i, c in enumerate(payload.progression):
        lines.append(f"Seg {i+1}: {c.get('roman', '?')} ({c['chord_name']})")
    chart_path.write_text("\n".join(lines))

    return {
        "melody_midi": f"/api/download/{melody_path.name}",
        "chords_midi": f"/api/download/{chords_path.name}",
        "chart_txt": f"/api/download/{chart_path.name}",
    }


@app.get("/api/download/{filename}")
def download(filename: str):
    target = EXPORT_DIR / filename
    if not target.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(target)


@app.get("/api/session/{job_id}")
def get_session(job_id: str):
    p = SESSION_DIR / f"{job_id}.json"
    if not p.exists():
        raise HTTPException(404, "session missing")
    return JSONResponse(content=json.loads(p.read_text()))


@app.post("/api/session/open")
async def open_session(file: UploadFile = File(...)):
    try:
        data = json.loads((await file.read()).decode("utf-8"))
        return data
    except Exception as exc:
        raise HTTPException(400, f"invalid session: {exc}")


@app.get("/api/health")
def health():
    return {"ok": True}
