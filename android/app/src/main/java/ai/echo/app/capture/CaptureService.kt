package ai.echo.app.capture

import ai.echo.app.EchoApp
import ai.echo.app.MainActivity
import ai.echo.app.R
import ai.echo.app.data.SegmentMeta
import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.File
import java.time.Instant
import java.time.LocalTime
import java.util.UUID
import kotlin.math.sqrt

enum class CaptureStatus { Stopped, Listening, Speech, Private, QuietHours, InCall, NoPermission }

data class CaptureState(
    val status: CaptureStatus = CaptureStatus.Stopped,
    val level: Float = 0f,
    val source: String = "phone",
    val lastSegmentAt: Long = 0,
    val segmentsToday: Int = 0,
)

class CaptureService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var loop: Job? = null
    private lateinit var app: EchoApp
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        app = application as EchoApp
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            app.prefs.captureEnabledValue = false
            stopSelf()
            return START_NOT_STICKY
        }
        if (!startInForeground()) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (loop?.isActive != true) loop = scope.launch { run() }
        return START_STICKY
    }

    private fun hasMic() = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun startInForeground(): Boolean {
        if (!hasMic()) return false
        var type = ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        if (app.prefs.locationEnabled && app.location.permitted()) type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        return runCatching {
            ServiceCompat.startForeground(this, NOTIF_ID, notification(CaptureStatus.Listening), type)
            true
        }.getOrElse {
            runCatching {
                ServiceCompat.startForeground(this, NOTIF_ID, notification(CaptureStatus.Listening), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
                true
            }.getOrDefault(false)
        }
    }

    private fun pauseReason(router: AudioRouter): CaptureStatus? = when {
        !hasMic() -> CaptureStatus.NoPermission
        app.prefs.privateModeValue -> CaptureStatus.Private
        app.prefs.quietHours?.contains(LocalTime.now()) == true -> CaptureStatus.QuietHours
        router.inCall() -> CaptureStatus.InCall
        else -> null
    }

    @SuppressLint("MissingPermission")
    private fun openRecorder(router: AudioRouter): AudioRecord? {
        val min = AudioRecord.getMinBufferSize(SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = runCatching {
            AudioRecord.Builder()
                .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
                .setAudioFormat(AudioFormat.Builder().setSampleRate(SR).setChannelMask(AudioFormat.CHANNEL_IN_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setBufferSizeInBytes(maxOf(min, SileroVad.WINDOW * 2 * 16))
                .build()
        }.getOrNull() ?: return null
        if (rec.state != AudioRecord.STATE_INITIALIZED) { rec.release(); return null }
        router.select()?.let { rec.setPreferredDevice(it) }
        rec.startRecording()
        return rec
    }

    private suspend fun run() {
        val router = AudioRouter(this) { app.prefs.earbudPolicy }
        val vad = SileroVad(this)
        val frame = ShortArray(SileroVad.WINDOW)
        val f32 = FloatArray(SileroVad.WINDOW)
        val preRoll = ArrayDeque<ShortArray>()
        val seg = ArrayList<ShortArray>()
        var inSpeech = false
        var speechRun = 0
        var silenceRun = 0
        var speechFrames = 0
        var segStart = 0L
        var lastSegEnd = 0L
        var session = UUID.randomUUID().toString()
        var rec: AudioRecord? = null
        var lastCheck = 0L
        var lastRoute = 0L
        var lastNotified: CaptureStatus? = null

        fun setStatus(s: CaptureStatus, level: Float = 0f) {
            state.value = state.value.copy(status = s, level = level, source = router.current)
            if (s != lastNotified && s != CaptureStatus.Speech) {
                lastNotified = s
                app.notifications.notify(NOTIF_ID, notification(s))
            }
        }

        try {
            while (scope.isActive) {
                val now = System.currentTimeMillis()
                if (now - lastCheck > 1000) {
                    lastCheck = now
                    val reason = pauseReason(router)
                    if (reason != null) {
                        rec?.let { it.stop(); it.release() }
                        rec = null
                        router.stopSco()
                        releaseWake()
                        inSpeech = false; seg.clear(); preRoll.clear(); vad.reset()
                        setStatus(reason)
                        delay(1000)
                        continue
                    }
                }
                if (rec == null) {
                    rec = openRecorder(router)
                    if (rec == null) { setStatus(CaptureStatus.NoPermission); delay(3000); continue }
                    acquireWake()
                    setStatus(CaptureStatus.Listening)
                    lastRoute = now
                }
                if (!inSpeech && now - lastRoute > 15_000) {
                    lastRoute = now
                    val before = router.current
                    val dev = router.select()
                    if (router.current != before) { rec.setPreferredDevice(dev) }
                }
                var read = 0
                while (read < frame.size) {
                    val n = rec.read(frame, read, frame.size - read)
                    if (n <= 0) break
                    read += n
                }
                if (read < frame.size) { rec.release(); rec = null; delay(200); continue }
                var sumSq = 0.0
                for (i in frame.indices) { val v = frame[i] / 32768f; f32[i] = v; sumSq += v * v }
                val level = sqrt(sumSq / frame.size).toFloat()
                val p = vad.probability(f32)
                val copy = frame.copyOf()

                if (!inSpeech) {
                    preRoll.addLast(copy)
                    if (preRoll.size > PRE_ROLL_FRAMES) preRoll.removeFirst()
                    speechRun = if (p > START_TH) speechRun + 1 else 0
                    if (speechRun >= START_FRAMES) {
                        inSpeech = true
                        seg.clear(); seg.addAll(preRoll); preRoll.clear()
                        speechFrames = speechRun
                        silenceRun = 0
                        segStart = System.currentTimeMillis() - seg.size * FRAME_MS
                        if (segStart - lastSegEnd > SESSION_GAP_MS) session = UUID.randomUUID().toString()
                    }
                    state.value = state.value.copy(status = CaptureStatus.Listening, level = level, source = router.current)
                } else {
                    seg.add(copy)
                    if (p > END_TH) { speechFrames++; silenceRun = 0 } else silenceRun++
                    state.value = state.value.copy(status = CaptureStatus.Speech, level = level, source = router.current)
                    val tooLong = seg.size >= MAX_FRAMES
                    if (silenceRun >= END_SILENCE_FRAMES || tooLong) {
                        val frames = ArrayList(seg)
                        val sf = speechFrames
                        val startMs = segStart
                        val src = router.current
                        val sess = session
                        seg.clear()
                        lastSegEnd = System.currentTimeMillis()
                        if (tooLong && silenceRun < END_SILENCE_FRAMES) {
                            segStart = lastSegEnd; speechFrames = 0; silenceRun = 0
                        } else {
                            inSpeech = false; speechRun = 0; vad.reset()
                        }
                        if (sf * FRAME_MS >= MIN_SPEECH_MS) scope.launch(Dispatchers.IO) { finalize(frames, sf, startMs, src, sess) }
                    }
                }
            }
        } finally {
            rec?.let { runCatching { it.stop() }; it.release() }
            router.stopSco()
            vad.close()
            releaseWake()
            state.value = CaptureState()
        }
    }

    private suspend fun finalize(frames: List<ShortArray>, speechFrames: Int, startMs: Long, source: String, session: String) {
        val pcm = ShortArray(frames.size * SileroVad.WINDOW)
        frames.forEachIndexed { i, f -> f.copyInto(pcm, i * SileroVad.WINDOW) }
        val id = UUID.randomUUID().toString()
        val encoded = AudioEncoder.encode(pcm, SR, File(app.outbox.dir, id))
        val fix = if (app.prefs.locationEnabled) runCatching { app.location.current() }.getOrNull() else null
        val pinned = System.currentTimeMillis() < app.prefs.pinUntil || startMs < app.prefs.pinUntil
        val meta = SegmentMeta(
            segment_id = id,
            sha256 = Outbox.sha256(encoded.file),
            duration_ms = (pcm.size * 1000L / SR).toInt().coerceIn(1, 60_000),
            started_at = Instant.ofEpochMilli(startMs).toString(),
            source = source,
            speech_ratio = speechFrames.toDouble() / frames.size,
            session_hint = session,
            pinned = pinned,
            device_id = app.prefs.serverDeviceId,
            lat = fix?.lat, lng = fix?.lng, accuracy_m = fix?.accuracy, locality = fix?.locality,
            content_type = encoded.contentType,
        )
        app.outbox.put(meta, encoded.file)
        state.value = state.value.copy(lastSegmentAt = System.currentTimeMillis(), segmentsToday = state.value.segmentsToday + 1)
        UploadWorker.enqueue(this)
    }

    private fun acquireWake() {
        if (wakeLock?.isHeld == true) return
        wakeLock = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "echo:capture").apply {
            setReferenceCounted(false); acquire()
        }
    }

    private fun releaseWake() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    private fun notification(s: CaptureStatus): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val text = when (s) {
            CaptureStatus.Listening, CaptureStatus.Speech -> "Listening — only speech is kept"
            CaptureStatus.Private -> "Private mode — nothing is recorded"
            CaptureStatus.QuietHours -> "Quiet hours — paused"
            CaptureStatus.InCall -> "Paused during a call"
            CaptureStatus.NoPermission -> "Microphone unavailable"
            CaptureStatus.Stopped -> "Stopped"
        }
        val private = app.prefs.privateModeValue
        return NotificationCompat.Builder(this, EchoApp.CHANNEL_CAPTURE)
            .setSmallIcon(R.drawable.ic_stat_echo)
            .setContentTitle("ECHO")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setContentIntent(open)
            .addAction(0, "Remember this", ActionReceiver.pending(this, ActionReceiver.ACTION_REMEMBER))
            .addAction(0, if (private) "Resume" else "Private", ActionReceiver.pending(this, ActionReceiver.ACTION_TOGGLE_PRIVATE))
            .addAction(0, "Stop", ActionReceiver.pending(this, ActionReceiver.ACTION_STOP))
            .build()
    }

    override fun onDestroy() {
        scope.cancel()
        state.value = CaptureState()
        super.onDestroy()
    }

    companion object {
        const val SR = 16000
        const val NOTIF_ID = 1001
        const val ACTION_STOP = "ai.echo.app.STOP"
        private const val FRAME_MS = 32L
        private const val PRE_ROLL_FRAMES = 10
        private const val START_TH = 0.6f
        private const val END_TH = 0.35f
        private const val START_FRAMES = 8
        private const val END_SILENCE_FRAMES = 25
        private const val MAX_FRAMES = (25_000 / FRAME_MS).toInt()
        private const val MIN_SPEECH_MS = 400L
        private const val SESSION_GAP_MS = 90_000L

        val state = MutableStateFlow(CaptureState())
        val stateFlow: StateFlow<CaptureState> get() = state

        fun start(context: Context) {
            (context.applicationContext as EchoApp).prefs.captureEnabledValue = true
            context.startForegroundService(Intent(context, CaptureService::class.java))
        }

        fun stop(context: Context) {
            (context.applicationContext as EchoApp).prefs.captureEnabledValue = false
            context.stopService(Intent(context, CaptureService::class.java))
        }

        fun refresh(context: Context) {
            if ((context.applicationContext as EchoApp).prefs.captureEnabledValue) {
                runCatching { context.startForegroundService(Intent(context, CaptureService::class.java)) }
            }
        }
    }
}
