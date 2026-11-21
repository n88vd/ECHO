import numpy as np
import pytest

from app.audio.decode import TARGET_SR, decode
from app.audio.qa import analyze, decide
from app.audio.speakers import agglomerative, cosine
from app.pipeline.common import compact_speech, map_ms


@pytest.mark.parametrize("name,keep", [
    ("en_promise.ogg", True), ("hi_passport.ogg", True), ("ta_doctor.ogg", True), ("hinglish_remember.ogg", True),
    ("silence.ogg", False), ("hiss.ogg", False), ("hum.ogg", False),
])
def test_blank_detection(fixture_bytes, name, keep):
    f = analyze(decode(fixture_bytes(name)))
    assert decide(f, 400, 0.15, -55).keep is keep


def test_decode_resamples_to_16k():
    import io

    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, np.zeros(48000, dtype=np.float32), 48000, format="WAV")
    assert len(decode(buf.getvalue())) == TARGET_SR


def test_compact_speech_mapping(fixture_bytes):
    samples = decode(fixture_bytes("hi_passport.ogg"))
    f = analyze(samples)
    wav, mapping = compact_speech(samples, f.speech_regions)
    compact = decode(wav)
    assert len(compact) < len(samples)
    assert mapping[0][0] == 0
    assert map_ms(0, mapping) == mapping[0][1]
    assert map_ms(mapping[0][2] + 10, mapping) >= mapping[0][1]


def test_speaker_embedding_same_voice_closer(fixture_bytes):
    from app.audio.models import speaker_embedding
    a = decode(fixture_bytes("en_promise.ogg"))
    b = decode(fixture_bytes("hinglish_remember.ogg"))
    ea1, ea2 = speaker_embedding(a[: len(a) // 2]), speaker_embedding(a[len(a) // 2 :])
    eb = speaker_embedding(b)
    assert cosine(ea1, ea2) > cosine(ea1, eb)


def test_agglomerative_clusters():
    rng = np.random.default_rng(0)
    base1, base2 = rng.standard_normal(64), rng.standard_normal(64)
    embs = [(base1 + 0.1 * rng.standard_normal(64)).tolist() for _ in range(4)] + [
        (base2 + 0.1 * rng.standard_normal(64)).tolist() for _ in range(3)]
    labels, conf = agglomerative(embs, 0.5)
    assert len(set(labels[:4])) == 1 and len(set(labels[4:])) == 1 and labels[0] != labels[4]
    assert conf > 0


def test_android_mediamuxer_ogg_decodes(fixture_bytes):
    samples = decode(fixture_bytes("android_mediamuxer.ogg"))
    assert 5.0 < len(samples) / TARGET_SR < 6.0
