"""Розпізнавання мови для VidBox. Запускається окремим процесом Python з власного середовища (faster-whisper).

python whisper_worker.py <аудіо.wav> <модель> <тека моделей> <потоки>
Друкує рядки JSON: {"lang": "ja", "dur": 1440.0}, далі {"s": 1.2, "e": 3.4, "t": "…", "p": 0.01} на кожну фразу.
"""
import json
import sys


def main():
    audio, model_name, root, threads = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    import wave
    import numpy as np
    from faster_whisper import WhisperModel
    # Звук готує ffmpeg (16 кГц, моно, 16 біт) — читаємо самі й даємо масивом: так faster-whisper не відкриває
    # файл через PyAV (нові версії PyAV несумісні з його decode_audio: «unexpected keyword 'metadata_errors'»).
    with wave.open(audio, 'rb') as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    print(json.dumps({'stage': 'model'}), flush=True)
    model = WhisperModel(model_name, device='cpu', compute_type='int8', cpu_threads=threads, download_root=root)
    segments, info = model.transcribe(
        pcm, beam_size=5, vad_filter=True,               # тишу й музику без слів пропускаємо — менше «вигаданих» фраз
        vad_parameters={'min_silence_duration_ms': 500},
        condition_on_previous_text=False)                   # не зациклюється на одній фразі
    dur = float(info.duration or 0) or 1.0
    print(json.dumps({'lang': info.language, 'prob': round(float(info.language_probability or 0), 3), 'dur': dur}), flush=True)
    for s in segments:
        t = (s.text or '').strip()
        if t:
            print(json.dumps({'s': round(s.start, 3), 'e': round(s.end, 3), 't': t, 'p': round(min(1.0, s.end / dur), 4)},
                             ensure_ascii=False), flush=True)
    print(json.dumps({'done': True}), flush=True)


if __name__ == '__main__':
    main()
