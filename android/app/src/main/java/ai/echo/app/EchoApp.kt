package ai.echo.app

import ai.echo.app.capture.LocationTracker
import ai.echo.app.capture.Outbox
import ai.echo.app.capture.SyncWorker
import ai.echo.app.data.Api
import ai.echo.app.data.Prefs
import ai.echo.app.data.Session
import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build

class EchoApp : Application() {
    lateinit var session: Session
    lateinit var prefs: Prefs
    lateinit var api: Api
    lateinit var outbox: Outbox
    lateinit var location: LocationTracker
    lateinit var notifications: NotificationManager

    override fun onCreate() {
        super.onCreate()
        session = Session(this)
        prefs = Prefs(this)
        api = Api(session)
        outbox = Outbox(this)
        location = LocationTracker(this)
        notifications = getSystemService(NotificationManager::class.java)
        notifications.createNotificationChannel(
            NotificationChannel(CHANNEL_CAPTURE, "Listening status", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Shows when ECHO is listening"
                setShowBadge(false)
            },
        )
        notifications.createNotificationChannel(
            NotificationChannel(CHANNEL_REMINDERS, "Reminders & digests", NotificationManager.IMPORTANCE_DEFAULT),
        )
        SyncWorker.schedulePeriodic(this)
    }

    @Synchronized
    fun ensureDevice() {
        if (prefs.serverDeviceId != null || !session.signedIn.value) return
        runCatching {
            kotlinx.coroutines.runBlocking {
                prefs.serverDeviceId = api.registerDevice(
                    null, "${Build.MANUFACTURER} ${Build.MODEL}", "Android ${Build.VERSION.RELEASE} (${Build.VERSION.SDK_INT})", BuildConfig.VERSION_NAME,
                )
            }
        }
    }

    companion object {
        const val CHANNEL_CAPTURE = "capture"
        const val CHANNEL_REMINDERS = "reminders"
    }
}
