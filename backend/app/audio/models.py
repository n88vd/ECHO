import threading
from functools import lru_cache

import numpy as np
import sherpa_onnx

from app.audio.decode import TARGET_SR
from app.core.config import get_settings

_lock = threading.Lock()


@lru_cache
def _speaker_extractor() -> sherpa_onnx.SpeakerEmbeddingExtractor:
    s = get_settings()
    return sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=s.speaker_model_path, num_threads=1)
    )


def vad_segments(
    samples: np.ndarray, threshold: float = 0.5, min_silence_s: float = 0.4, min_speech_s: float = 0.25
) -> list[tuple[int, int]]:
    """Speech regions as (start_sample, end_sample) using Silero VAD."""
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = get_settings().vad_model_path
    cfg.silero_vad.threshold = threshold
    cfg.silero_vad.min_silence_duration = min_silence_s
    cfg.silero_vad.min_speech_duration = min_speech_s
    cfg.silero_vad.max_speech_duration = 30
    cfg.sample_rate = TARGET_SR
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=max(30, len(samples) / TARGET_SR + 5))
    win = cfg.silero_vad.window_size
    out: list[tuple[int, int]] = []
    for i in range(0, len(samples), win):
        vad.accept_waveform(samples[i : i + win])
        while not vad.empty():
            seg = vad.front
            out.append((seg.start, seg.start + len(seg.samples)))
            vad.pop()
    vad.flush()
    while not vad.empty():
        seg = vad.front
        out.append((seg.start, seg.start + len(seg.samples)))
        vad.pop()
    return out


def speaker_embedding(samples: np.ndarray) -> list[float] | None:
    if len(samples) < int(0.8 * TARGET_SR):
        return None
    ext = _speaker_extractor()
    with _lock:
        st = ext.create_stream()
        st.accept_waveform(TARGET_SR, samples)
        st.input_finished()
        if not ext.is_ready(st):
            return None
        emb = np.asarray(ext.compute(st), dtype=np.float32)
    n = np.linalg.norm(emb)
    return (emb / n).tolist() if n else None
