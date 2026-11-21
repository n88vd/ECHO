package ai.echo.app.ui

import ai.echo.app.capture.AudioEncoder
import ai.echo.app.capture.CaptureService
import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.media.audiofx.Visualizer
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import java.io.File
import kotlin.coroutines.coroutineContext
import kotlin.math.abs
import kotlin.math.sin
import kotlin.math.sqrt

/** Short foreground recordings (Ask by voice, voice enrolment) to 16 kHz WAV. */
class VoiceRecorder {
    val level = MutableStateFlow(0f)
    @Volatile var stopRequested = false

    @SuppressLint("MissingPermission")
    suspend fun record(out: File, maxMs: Long): File = withContext(Dispatchers.IO) {
        stopRequested = false
        val sr = CaptureService.SR
        val min = AudioRecord.getMinBufferSize(sr, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, sr, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(min, 8192))
        val buf = ShortArray(1024)
        val all = ArrayList<Short>(sr * 30)
        rec.startRecording()
        val start = System.currentTimeMillis()
        try {
            while (coroutineContext.isActive && !stopRequested && System.currentTimeMillis() - start < maxMs) {
                val n = rec.read(buf, 0, buf.size)
                if (n <= 0) continue
                var s = 0.0
                for (i in 0 until n) { all.add(buf[i]); val v = buf[i] / 32768.0; s += v * v }
                level.value = sqrt(s / n).toFloat()
            }
        } finally {
            rec.stop(); rec.release(); level.value = 0f
        }
        AudioEncoder.writeWav(all.toShortArray(), sr, out).file
    }
}

object Player {
    private var mp: MediaPlayer? = null
    private var viz: Visualizer? = null
    private val main = Handler(Looper.getMainLooper())
    val playing = MutableStateFlow<String?>(null)
    /** RMS amplitude of what is being played (same scale as [VoiceRecorder.level]). */
    val level = MutableStateFlow(0f)

    fun play(url: String, key: String = url, seekMs: Int = 0) {
        stop()
        mp = MediaPlayer().apply {
            setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            setDataSource(url)
            setOnPreparedListener { if (seekMs > 0) it.seekTo(seekMs); it.start(); playing.value = key; meter(it) }
            setOnCompletionListener { stop() }
            setOnErrorListener { _, _, _ -> stop(); true }
            prepareAsync()
        }
    }

    fun stop() {
        main.removeCallbacks(fakeMeter)
        viz?.runCatching { enabled = false; release() }
        viz = null
        mp?.runCatching { stop() }
        mp?.release()
        mp = null
        playing.value = null
        level.value = 0f
    }

    private fun meter(player: MediaPlayer) {
        viz = runCatching {
            Visualizer(player.audioSessionId).apply {
                captureSize = Visualizer.getCaptureSizeRange()[0].coerceAtLeast(256)
                setDataCaptureListener(object : Visualizer.OnDataCaptureListener {
                    override fun onWaveFormDataCapture(v: Visualizer, wave: ByteArray, rate: Int) {
                        var s = 0.0
                        for (b in wave) { val x = ((b.toInt() and 0xFF) - 128) / 128.0; s += x * x }
                        level.value = (sqrt(s / wave.size) * 0.6).toFloat()
                    }
                    override fun onFftDataCapture(v: Visualizer, fft: ByteArray, rate: Int) = Unit
                }, Visualizer.getMaxCaptureRate(), true, false)
                enabled = true
            }
        }.getOrNull()
        if (viz == null) main.post(fakeMeter)
    }

    // Fallback when Visualizer is unavailable: a syllable-like envelope while audio plays.
    private val fakeMeter = object : Runnable {
        override fun run() {
            if (mp?.isPlaying != true) return
            val t = SystemClock.uptimeMillis() / 1000.0
            level.value = (0.06 + 0.05 * abs(sin(t * 9.0)) * (0.6 + 0.4 * sin(t * 2.3))).toFloat()
            main.postDelayed(this, 50)
        }
    }
}
