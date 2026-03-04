import math
import struct
import wave
from pathlib import Path


def generate_sample_audio(out_path: Path) -> Path:
    sr = 22050
    notes_hz = [261.63, 293.66, 329.63, 392.0, 440.0, 392.0, 329.63, 293.66]
    dur = 0.5
    sil = 0.05
    samples = []
    for hz in notes_hz:
        total = int(sr * dur)
        for i in range(total):
            t = i / sr
            env = min(1.0, t * 8) * min(1.0, (dur - t) * 8)
            v = 0.35 * math.sin(2 * math.pi * hz * t) * env
            samples.append(int(max(-1, min(1, v)) * 32767))
        samples.extend([0] * int(sr * sil))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b''.join(struct.pack('<h', s) for s in samples))
    return out_path


if __name__ == '__main__':
    out = generate_sample_audio(Path('backend/data/sample_melody.wav'))
    print(out)
