package ai.echo.app.capture

import ai.echo.app.EchoApp
import ai.echo.app.MainActivity
import ai.echo.app.R
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.service.quicksettings.TileService
import android.widget.Toast
import androidx.core.app.NotificationCompat
import kotlin.concurrent.thread

object RememberAction {
    fun trigger(context: Context) {
        val app = context.applicationContext as EchoApp
        app.prefs.pinUntil = System.currentTimeMillis() + 60_000
        thread { app.api.rememberBlocking() }
    }
}

class ActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext as EchoApp
        when (intent.action) {
            ACTION_REMEMBER -> {
                RememberAction.trigger(context)
                Toast.makeText(context, "ECHO will remember this moment", Toast.LENGTH_SHORT).show()
            }
            ACTION_TOGGLE_PRIVATE -> {
                app.prefs.privateModeValue = !app.prefs.privateModeValue
                CaptureService.refresh(context)
            }
            ACTION_STOP -> CaptureService.stop(context)
        }
    }

    companion object {
        const val ACTION_REMEMBER = "ai.echo.app.REMEMBER"
        const val ACTION_TOGGLE_PRIVATE = "ai.echo.app.TOGGLE_PRIVATE"
        const val ACTION_STOP = "ai.echo.app.ACTION_STOP"

        fun pending(context: Context, action: String): PendingIntent = PendingIntent.getBroadcast(
            context, action.hashCode(), Intent(context, ActionReceiver::class.java).setAction(action),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext as EchoApp
        SyncWorker.schedulePeriodic(context)
        SyncWorker.runNow(context)
        if (app.outbox.count() > 0) UploadWorker.enqueue(context)
        if (app.prefs.captureEnabledValue) {
            val open = PendingIntent.getActivity(context, 7, Intent(context, MainActivity::class.java).putExtra("resume_capture", true), PendingIntent.FLAG_IMMUTABLE)
            val n = NotificationCompat.Builder(context, EchoApp.CHANNEL_REMINDERS)
                .setSmallIcon(R.drawable.ic_stat_echo)
                .setContentTitle("ECHO is paused")
                .setContentText("Tap to resume listening after restart")
                .setContentIntent(open)
                .setAutoCancel(true)
                .build()
            runCatching { app.notifications.notify(2001, n) }
        }
    }
}

class RememberTileService : TileService() {
    override fun onClick() {
        super.onClick()
        RememberAction.trigger(this)
        Toast.makeText(this, "ECHO will remember this moment", Toast.LENGTH_SHORT).show()
    }
}
