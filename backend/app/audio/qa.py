"""Server-side audio quality gate: decides whether a segment contains usable speech."""

from dataclasses import asdict, dataclass

import numpy as np

from app.audio.decode import TARGET_SR
from app.audio.models import vad_segments

FRAME = 480


@dataclass
class AudioFeatures:
    duration_ms: int
    rms_dbfs: float
    peak_dbfs: float
    clipping_ratio: float
    speech_ms: int
    speech_ratio: float
    snr_db: float | None
    media_suspect: bool
    speech_regions: list[tuple[int, int]]

    def dict(self) -> dict:
        d = asdict(self)
        d.pop("speech_regions")
        return d


@dataclass
class QADecision:
    keep: bool
    reason: str


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def frame_rms(samples: np.ndarray) -> np.ndarray:
    n = len(samples) // FRAME
    if n == 0:
        return np.array([float(np.sqrt(np.mean(samples**2))) if len(samples) else 0.0])
    frames = samples[: n * FRAME].reshape(n, FRAME)
    return np.sqrt(np.mean(frames**2, axis=1))


def analyze(samples: np.ndarray) -> AudioFeatures:
    duration_ms = int(len(samples) / TARGET_SR * 1000)
    if len(samples) == 0:
        return AudioFeatures(0, -120.0, -120.0, 0.0, 0, 0.0, None, False, [])
    rms = float(np.sqrt(np.mean(samples**2)))
    peak = float(np.max(np.abs(samples)))
    clipping = float(np.mean(np.abs(samples) >= 0.999))
    regions = vad_segments(samples)
    speech_samples = sum(e - s for s, e in regions)
    speech_ms = int(speech_samples / TARGET_SR * 1000)
    speech_ratio = speech_samples / len(samples)

    mask = np.zeros(len(samples), dtype=bool)
    for s, e in regions:
        mask[s:e] = True
    snr = None
    if regions and speech_ratio < 0.98:
        sp = float(np.sqrt(np.mean(samples[mask] ** 2)))
        nz = samples[~mask]
        noise = float(np.sqrt(np.mean(nz**2))) if len(nz) else 0.0
        snr = _db(sp) - _db(noise) if noise > 0 else 60.0
    elif regions:
        fr = frame_rms(samples)
        snr = _db(float(np.percentile(fr, 90))) - _db(float(np.percentile(fr, 10)) + 1e-9)

    fr = frame_rms(samples)
    dyn_range = _db(float(np.percentile(fr, 95))) - _db(float(np.percentile(fr, 5)) + 1e-9)
    media_suspect = bool(
        duration_ms >= 8000 and ((speech_ratio > 0.97 and dyn_range < 12) or (speech_ratio < 0.3 and _db(rms) > -30))
    )
    return AudioFeatures(
        duration_ms=duration_ms,
        rms_dbfs=round(_db(rms), 2),
        peak_dbfs=round(_db(peak), 2),
        clipping_ratio=round(clipping, 5),
        speech_ms=speech_ms,
        speech_ratio=round(speech_ratio, 4),
        snr_db=None if snr is None else round(snr, 2),
        media_suspect=media_suspect,
        speech_regions=regions,
    )


def decide(f: AudioFeatures, min_speech_ms: int, min_speech_ratio: float, min_rms_dbfs: float) -> QADecision:
    if f.duration_ms < 300:
        return QADecision(False, "too_short")
    if f.rms_dbfs < min_rms_dbfs:
        return QADecision(False, "silent")
    if f.speech_ms < min_speech_ms:
        return QADecision(False, "no_speech")
    if f.speech_ratio < min_speech_ratio:
        return QADecision(False, "low_speech_ratio")
    return QADecision(True, "ok")
