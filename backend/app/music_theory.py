from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

PITCH_CLASS_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_NAME_TO_PC = {name: i for i, name in enumerate(PITCH_CLASS_NAMES)}

MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

ROMAN_MAJOR = {0: "I", 2: "ii", 4: "iii", 5: "IV", 7: "V", 9: "vi", 11: "vii°"}
ROMAN_MINOR = {0: "i", 2: "ii°", 3: "III", 5: "iv", 7: "v", 8: "VI", 10: "VII"}


@dataclass
class Chord:
    root_pc: int
    quality: str
    tones: Tuple[int, ...]

    @property
    def name(self) -> str:
        suffix = {
            "maj": "",
            "min": "m",
            "dim": "dim",
            "maj7": "maj7",
            "min7": "m7",
            "dom7": "7",
        }[self.quality]
        return f"{PITCH_CLASS_NAMES[self.root_pc]}{suffix}"


def midi_to_name(midi: int) -> str:
    pc = midi % 12
    octave = midi // 12 - 1
    return f"{PITCH_CLASS_NAMES[pc]}{octave}"


def build_pitch_class_histogram(notes: List[dict]) -> List[float]:
    hist = [0.0] * 12
    for n in notes:
        weight = n["dur_s"] * (1.0 + 0.25 * n.get("beat_strength", 0))
        hist[n["midi"] % 12] += max(weight, 0.001)
    total = sum(hist) or 1.0
    return [h / total for h in hist]


def score_keys(hist: List[float]) -> List[dict]:
    results = []
    for tonic in range(12):
        maj_score = sum(hist[i] * MAJOR_PROFILE[(i - tonic) % 12] for i in range(12))
        min_score = sum(hist[i] * MINOR_PROFILE[(i - tonic) % 12] for i in range(12))
        results.append({"key": PITCH_CLASS_NAMES[tonic], "mode": "major", "raw": maj_score})
        results.append({"key": PITCH_CLASS_NAMES[tonic], "mode": "minor", "raw": min_score})
    results.sort(key=lambda x: x["raw"], reverse=True)
    top = results[:6]
    mx = top[0]["raw"] if top else 1.0
    mn = top[-1]["raw"] if len(top) > 1 else 0.0
    den = (mx - mn) or 1.0
    for r in top:
        r["confidence"] = max(0.0, min(1.0, (r["raw"] - mn) / den))
    return [{"key": r["key"], "mode": r["mode"], "confidence": round(r["confidence"], 3)} for r in top[:3]]


def build_chord_library() -> List[Chord]:
    chords: List[Chord] = []
    for root in range(12):
        chords.extend(
            [
                Chord(root, "maj", (root, (root + 4) % 12, (root + 7) % 12)),
                Chord(root, "min", (root, (root + 3) % 12, (root + 7) % 12)),
                Chord(root, "dim", (root, (root + 3) % 12, (root + 6) % 12)),
                Chord(root, "maj7", (root, (root + 4) % 12, (root + 7) % 12, (root + 11) % 12)),
                Chord(root, "min7", (root, (root + 3) % 12, (root + 7) % 12, (root + 10) % 12)),
                Chord(root, "dom7", (root, (root + 4) % 12, (root + 7) % 12, (root + 10) % 12)),
            ]
        )
    return chords


CHORD_LIBRARY = build_chord_library()


def roman_numeral(chord: Chord, tonic_pc: int, mode: str) -> str:
    degree = (chord.root_pc - tonic_pc) % 12
    mapper = ROMAN_MAJOR if mode == "major" else ROMAN_MINOR
    base = mapper.get(degree, "?")
    if chord.quality in {"maj7", "min7", "dom7"}:
        return base + "7"
    return base


def chord_fit_score(chord: Chord, segment_notes: List[dict], tonic_pc: int, mode: str, previous: Chord | None = None) -> float:
    if not segment_notes:
        return 0.0
    score = 0.0
    for n in segment_notes:
        pc = n["midi"] % 12
        weight = n["dur_s"] * (1 + n.get("beat_strength", 0.0))
        if pc in chord.tones:
            score += 1.8 * weight
        elif any((pc - t) % 12 in (1, 2, 10, 11) for t in chord.tones):
            score += 0.7 * weight
        else:
            score -= 1.0 * weight

    degree = (chord.root_pc - tonic_pc) % 12
    if mode == "major" and degree in (0, 5, 7, 9):
        score += 0.6
    if mode == "minor" and degree in (0, 5, 7, 8, 10):
        score += 0.6

    if previous:
        jump = min((chord.root_pc - previous.root_pc) % 12, (previous.root_pc - chord.root_pc) % 12)
        score -= 0.12 * jump
        functional_bonus = ((previous.root_pc - tonic_pc) % 12, degree)
        if functional_bonus in {(7, 0), (5, 7), (2, 7), (9, 2), (0, 5)}:
            score += 0.7
    return score


def generate_chord_candidates_by_segment(
    segments: List[dict], notes: List[dict], tonic_pc: int, mode: str, top_k: int = 8
) -> Dict[int, List[dict]]:
    result: Dict[int, List[dict]] = {}
    for idx, seg in enumerate(segments):
        seg_notes = [n for n in notes if n["start_s"] < seg["end_s"] and (n["start_s"] + n["dur_s"]) > seg["start_s"]]
        scored = []
        for chord in CHORD_LIBRARY:
            s = chord_fit_score(chord, seg_notes, tonic_pc, mode)
            scored.append((s, chord))
        scored.sort(key=lambda x: x[0], reverse=True)
        result[idx] = [
            {
                "chord_name": c.name,
                "roman": roman_numeral(c, tonic_pc, mode),
                "quality": c.quality,
                "score": round(float(score), 3),
            }
            for score, c in scored[:top_k]
        ]
    return result


def _parse_chord(chord_name: str) -> Chord:
    root = chord_name[0]
    remainder = chord_name[1:]
    if remainder.startswith("#"):
        root += "#"
        remainder = remainder[1:]
    root_pc = NOTE_NAME_TO_PC[root]
    quality = "maj"
    if remainder.startswith("m7"):
        quality = "min7"
    elif remainder.startswith("maj7"):
        quality = "maj7"
    elif remainder.startswith("m"):
        quality = "min"
    elif remainder.startswith("dim"):
        quality = "dim"
    elif remainder.startswith("7"):
        quality = "dom7"
    for c in CHORD_LIBRARY:
        if c.root_pc == root_pc and c.quality == quality:
            return c
    return Chord(root_pc, "maj", (root_pc, (root_pc + 4) % 12, (root_pc + 7) % 12))


def build_progressions(candidates: Dict[int, List[dict]], tonic_pc: int, mode: str, num_options: int = 10) -> List[dict]:
    if not candidates:
        return []
    beams = [([], 0.0, None)]
    for seg_idx in sorted(candidates.keys()):
        new_beams = []
        for seq, total, prev in beams:
            for cand in candidates[seg_idx][:6]:
                chord = _parse_chord(cand["chord_name"])
                transition_bonus = 0.0
                if prev is not None:
                    transition_bonus += chord_fit_score(chord, [], tonic_pc, mode, prev)
                new_beams.append((seq + [cand], total + cand["score"] + transition_bonus, chord))
        new_beams.sort(key=lambda x: x[1], reverse=True)
        beams = new_beams[: max(24, num_options * 2)]

    progressions = []
    seen = set()
    for i, (seq, score, _) in enumerate(sorted(beams, key=lambda x: x[1], reverse=True)):
        key = tuple(x["chord_name"] for x in seq)
        if key in seen:
            continue
        seen.add(key)
        progressions.append(
            {
                "id": f"prog_{i+1}",
                "chords": [{"segment": j, "chord_name": c["chord_name"], "roman": c["roman"]} for j, c in enumerate(seq)],
                "score": round(float(score), 3),
            }
        )
        if len(progressions) >= num_options:
            break
    return progressions
