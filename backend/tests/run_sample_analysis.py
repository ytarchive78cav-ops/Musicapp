from pathlib import Path

from app.analysis import analyze_audio_file
from scripts.generate_sample_audio import generate_sample_audio

sample = Path(__file__).resolve().parents[1] / 'data' / 'sample_melody.wav'
if not sample.exists():
    generate_sample_audio(sample)

session = Path(__file__).resolve().parents[1] / 'sessions' / 'sample_session.json'
session.parent.mkdir(parents=True, exist_ok=True)
result = analyze_audio_file(sample, session)
print('BPM', result['bpm'], 'conf', result['bpm_confidence'])
print('Top key', result['key_candidates'][0])
print('First chords', [c['chord_name'] for c in result['progressions'][0]['chords'][:8]])
