import io

import numpy as np
import soundfile as sf
import soxr

TARGET_SR = 16000


class AudioDecodeError(Exception):
    pass


def _decode_av(data: bytes) -> np.ndarray:
    import av

    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=TARGET_SR)
        parts = [f.to_ndarray().reshape(-1) for frame in container.decode(stream) for f in resampler.resample(frame)]
        parts += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
    return np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, dtype=np.float32)


def decode(data: bytes) -> np.ndarray:
    """Decode WAV/OGG-Opus/FLAC/M4A bytes to mono float32 @16 kHz (libsndfile first, FFmpeg/PyAV fallback)."""
    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception as sf_err:
        try:
            return np.ascontiguousarray(_decode_av(data), dtype=np.float32)
        except Exception as av_err:
            raise AudioDecodeError(f"{sf_err}; {av_err}") from av_err
    mono = audio.mean(axis=1)
    if sr != TARGET_SR:
        mono = soxr.resample(mono, sr, TARGET_SR)
    return np.ascontiguousarray(mono, dtype=np.float32)


def to_wav(samples: np.ndarray, sr: int = TARGET_SR) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, samples, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()
