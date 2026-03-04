from app.music_theory import build_pitch_class_histogram, score_keys, generate_chord_candidates_by_segment, NOTE_NAME_TO_PC


def test_key_detection_c_major():
    notes = [
        {"midi": 60, "dur_s": 0.5, "beat_strength": 1.0},
        {"midi": 64, "dur_s": 0.5, "beat_strength": 0.8},
        {"midi": 67, "dur_s": 0.5, "beat_strength": 1.0},
        {"midi": 69, "dur_s": 0.5, "beat_strength": 0.5},
    ]
    hist = build_pitch_class_histogram(notes)
    top = score_keys(hist)[0]
    assert top["key"] == "C"
    assert top["mode"] == "major"


def test_chord_scoring_prefers_tonic():
    segs = [{"start_s": 0.0, "end_s": 2.0, "bar_index": 0}]
    notes = [
        {"start_s": 0.0, "dur_s": 0.6, "midi": 60, "beat_strength": 1.0},
        {"start_s": 0.6, "dur_s": 0.6, "midi": 64, "beat_strength": 0.6},
        {"start_s": 1.2, "dur_s": 0.6, "midi": 67, "beat_strength": 0.8},
    ]
    cand = generate_chord_candidates_by_segment(segs, notes, NOTE_NAME_TO_PC["C"], "major")
    assert cand[0][0]["chord_name"] in {"C", "Cmaj7"}
