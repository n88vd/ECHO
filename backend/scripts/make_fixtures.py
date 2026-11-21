"""Generate multilingual speech fixtures with Sarvam TTS (live; costs a few credits). Run once."""

import asyncio
import base64
import io
import json
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from app.core.config import get_settings

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CLIPS = {
    "en_promise": ("en-IN", "shubh", "Rahul, I promise I will send you the project report by Friday evening."),
    "hi_passport": ("hi-IN", "priya", "मैंने अपना पासपोर्ट बेडरूम की अलमारी में नीले बैग में रखा है।"),
    "ta_doctor": ("ta-IN", "kavya", "நாளை காலை பத்து மணிக்கு நான் டாக்டரை பார்க்க வேண்டும்."),
    "hinglish_remember": ("hi-IN", "rohan", "Echo, yaad rakhna, maine Priya ko bola hai ki main Sunday ko uski party mein zaroor aaunga."),
}


async def main() -> None:
    s = get_settings()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    async with httpx.AsyncClient(base_url=s.sarvam_base_url, headers={"api-subscription-key": s.sarvam_api_key}, timeout=60) as c:
        for name, (lang, speaker, text) in CLIPS.items():
            r = await c.post("/text-to-speech", json={
                "text": text, "language_code": lang, "speaker": speaker, "model": "bulbul:v3",
                "speech_sample_rate": 16000, "output_audio_codec": "wav",
            })
            r.raise_for_status()
            audio, sr = sf.read(io.BytesIO(base64.b64decode("".join(r.json()["audios"]))), dtype="float32")
            pad = np.zeros(int(0.8 * sr), dtype=np.float32)
            audio = np.concatenate([pad, audio, pad])
            sf.write(OUT / f"{name}.ogg", audio, sr, format="OGG", subtype="OPUS")
            manifest[name] = {"language": lang, "text": text, "seconds": round(len(audio) / sr, 2)}
            print(name, manifest[name]["seconds"], "s")
    sr = 16000
    rng = np.random.default_rng(7)
    sf.write(OUT / "silence.ogg", np.zeros(sr * 5, dtype=np.float32), sr, format="OGG", subtype="OPUS")
    sf.write(OUT / "hiss.ogg", (rng.standard_normal(sr * 5) * 0.003).astype(np.float32), sr, format="OGG", subtype="OPUS")
    t = np.arange(sr * 5) / sr
    sf.write(OUT / "hum.ogg", (0.2 * np.sin(2 * np.pi * 50 * t)).astype(np.float32), sr, format="OGG", subtype="OPUS")
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
