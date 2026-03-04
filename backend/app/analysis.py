from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import librosa
import numpy as np
import soundfile as sf
from scipy import signal

from .music_theory import (
    build_pitch_class_histogram,
    generate_chord_candidates_by_segment,
    midi_to_name,
    score_keys,
    build_progressions,
    NOTE_NAME_TO_PC,
)


def preprocess_audio(path: Path, sr: int = 22050) -> Tuple[np.ndarray, int]:
    y, _ = librosa.load(path, sr=sr, mono=True)
    y = librosa.util.normalize(y)
    b, a = signal.butter(2, 70 / (sr / 2), btype="highpass")
    y = signal.filtfilt(b, a, y)
    return y, sr


def estimate_bpm(y: np.ndarray, sr: int) -> Tuple[float, float]:
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, start_bpm=110, tightness=100)
    if hasattr(tempo, "item"):
        tempo = tempo.item()
    beat_conf = min(1.0, len(beats) / max(1, (len(y) / sr) * (tempo / 60)))
    return float(tempo or 110.0), float(max(0.05, beat_conf))


def extract_melody_notes(y: np.ndarray, sr: int) -> List[dict]:
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y,
        sr=sr,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C6"),
        frame_length=2048,
        hop_length=256,
    )
    times = librosa.times_like(f0, sr=sr, hop_length=256)
    notes = []
    active = None
    min_dur = 0.08

    for i, pitch in enumerate(f0):
        voiced = bool(voiced_flag[i]) and not np.isnan(pitch)
        midi = int(round(librosa.hz_to_midi(pitch))) if voiced else None
        conf = float(voiced_prob[i]) if voiced else 0.0

        if voiced:
            if active is None:
                active = {"midi": midi, "start": float(times[i]), "last_t": float(times[i]), "conf": [conf]}
            elif abs(midi - active["midi"]) <= 1:
                active["last_t"] = float(times[i])
                active["conf"].append(conf)
                active["midi"] = int(round((active["midi"] * (len(active["conf"]) - 1) + midi) / len(active["conf"])))
            else:
                dur = active["last_t"] - active["start"] + (256 / sr)
                if dur >= min_dur:
                    notes.append(
                        {
                            "start_s": round(active["start"], 4),
                            "dur_s": round(dur, 4),
                            "midi": active["midi"],
                            "name": midi_to_name(active["midi"]),
                            "confidence": round(float(np.mean(active["conf"])), 3),
                        }
                    )
                active = {"midi": midi, "start": float(times[i]), "last_t": float(times[i]), "conf": [conf]}
        elif active is not None:
            dur = active["last_t"] - active["start"] + (256 / sr)
            if dur >= min_dur:
                notes.append(
                    {
                        "start_s": round(active["start"], 4),
                        "dur_s": round(dur, 4),
                        "midi": active["midi"],
                        "name": midi_to_name(active["midi"]),
                        "confidence": round(float(np.mean(active["conf"])), 3),
                    }
                )
            active = None

    return notes


def beat_strength(note_start: float, bpm: float, ts_num: int) -> float:
    beat_dur = 60.0 / bpm
    beat_idx = int(round(note_start / beat_dur))
    if beat_idx % ts_num == 0:
        return 1.0
    if beat_idx % 2 == 0:
        return 0.6
    return 0.2


def quantize_notes(notes: List[dict], bpm: float, grid: str = "1/8") -> List[dict]:
    division = {"1/4": 1, "1/8": 2, "1/16": 4}.get(grid, 2)
    beat_dur = 60.0 / bpm
    unit = beat_dur / division
    out = []
    for n in notes:
        start_q = round(n["start_s"] / unit) * unit
        end_q = round((n["start_s"] + n["dur_s"]) / unit) * unit
        dur_q = max(unit, end_q - start_q)
        obj = dict(n)
        obj["start_s"] = round(float(start_q), 4)
        obj["dur_s"] = round(float(dur_q), 4)
        out.append(obj)
    return out


def build_segments(duration_s: float, bpm: float, ts_num: int = 4, subdivide: bool = True) -> List[dict]:
    bar_dur = (60.0 / bpm) * ts_num
    seg_dur = bar_dur / 2 if subdivide else bar_dur
    segs = []
    t = 0.0
    bar = 0
    while t < duration_s + 1e-9:
        segs.append({"bar_index": bar, "start_s": round(t, 4), "end_s": round(min(duration_s, t + seg_dur), 4)})
        t += seg_dur
        if (len(segs) % (2 if subdivide else 1)) == 0:
            bar += 1
    return segs


def analyze_audio_file(audio_path: Path, session_path: Path, log_cb=None) -> Dict:
    def log(msg: str):
        if log_cb:
            log_cb(msg)

    log("decoding audio")
    y, sr = preprocess_audio(audio_path)
    duration_s = len(y) / sr

    log("estimating tempo")
    bpm, bpm_conf = estimate_bpm(y, sr)

    log("extracting melody")
    notes = extract_melody_notes(y, sr)
    if not notes:
        raise RuntimeError("No clear monophonic melody detected. Try a cleaner vocal take.")

    ts = "4/4"
    ts_num = int(ts.split("/")[0])
    for n in notes:
        n["beat_strength"] = beat_strength(n["start_s"], bpm, ts_num)

    log("quantizing notes")
    notes_q = quantize_notes(notes, bpm, grid="1/8")

    log("estimating key")
    hist = build_pitch_class_histogram(notes_q)
    key_candidates = score_keys(hist)
    top_key = key_candidates[0]
    tonic_pc = NOTE_NAME_TO_PC[top_key["key"]]

    log("generating chord candidates")
    segments = build_segments(duration_s, bpm, ts_num=ts_num, subdivide=True)
    candidates = generate_chord_candidates_by_segment(segments, notes_q, tonic_pc, top_key["mode"], top_k=8)

    log("building progressions")
    progressions = build_progressions(candidates, tonic_pc, top_key["mode"], num_options=10)

    voiced_ratio = sum(n["dur_s"] for n in notes_q) / max(duration_s, 1e-6)
    confidence = {
        "tempo": round(bpm_conf, 3),
        "pitch_tracking": round(float(np.mean([n["confidence"] for n in notes_q])), 3),
        "monophonicity": round(min(1.0, voiced_ratio), 3),
    }

    results = {
        "bpm": round(bpm, 2),
        "bpm_confidence": round(bpm_conf, 3),
        "time_signature": ts,
        "key_candidates": key_candidates,
        "melody_notes": notes_q,
        "segments": segments,
        "chord_candidates_by_segment": {str(k): v for k, v in candidates.items()},
        "progressions": progressions,
        "confidence": confidence,
        "warnings": [] if confidence["monophonicity"] > 0.45 else ["Low voiced-note ratio detected; possible noise/polyphony."],
    }

    session_path.write_text(json.dumps(results, indent=2))
    return results


def load_audio_data(path: Path):
    y, sr = sf.read(path)
    if y.ndim > 1:
        y = np.mean(y, axis=1)
    return y, sr
