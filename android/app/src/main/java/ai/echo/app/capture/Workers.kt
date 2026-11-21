package ai.echo.app.capture

import ai.echo.app.EchoApp
import ai.echo.app.MainActivity
import ai.echo.app.R
import ai.echo.app.data.ApiException
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.Instant
import java.util.concurrent.TimeUnit

private val netConstraint = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

class UploadWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val app = applicationContext as EchoApp
        if (!app.session.signedIn.value) return@withContext Result.success()
        app.ensureDevice()
        var failures = 0
        for (item in app.outbox.pending()) {
            try {
                val meta = if (item.meta.device_id == null && app.prefs.serverDeviceId != null) item.meta.copy(device_id = app.prefs.serverDeviceId) else item.meta
                app.api.uploadSegmentBlocking(meta, item.audio)
                app.outbox.remove(item)
            } catch (e: ApiException) {
                if (e.code in 400..499 && e.code !in listOf(401, 408, 409, 429)) app.outbox.remove(item) else failures++
            } catch (e: Exception) {
                failures++
            }
            if (failures >= 3) break
        }
        if (failures > 0) return@withContext Result.retry()
        SyncWorker.runNow(applicationContext)
        Result.success()
    }

    companion object {
        fun enqueue(context: Context) {
            val req = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(netConstraint)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork("echo-upload", ExistingWorkPolicy.APPEND_OR_REPLACE, req)
        }
    }
}

class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val app = applicationContext as EchoApp
        if (!app.session.signedIn.value) return@withContext Result.success()
        runCatching {
            val res = app.api.syncBlocking(app.prefs.syncCursor, app.prefs.serverDeviceId)
            val wm = WorkManager.getInstance(applicationContext)
            for (r in res.reminders) {
                val name = "reminder-${r.id}"
                if (r.status != "scheduled") { wm.cancelUniqueWork(name); continue }
                val delayMs = Duration.between(Instant.now(), Instant.parse(r.fire_at)).toMillis().coerceAtLeast(0)
                val req = OneTimeWorkRequestBuilder<ReminderWorker>()
                    .setInitialDelay(delayMs, TimeUnit.MILLISECONDS)
                    .setInputData(workDataOf("id" to r.id, "title" to r.title, "body" to (r.body ?: ""), "kind" to r.kind))
                    .build()
                wm.enqueueUniqueWork(name, ExistingWorkPolicy.REPLACE, req)
            }
            app.prefs.syncCursor = res.cursor
        }.fold({ Result.success() }, { Result.retry() })
    }

    companion object {
        fun schedulePeriodic(context: Context) {
            val req = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES).setConstraints(netConstraint).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("echo-sync", ExistingPeriodicWorkPolicy.KEEP, req)
        }

        fun runNow(context: Context) {
            val req = OneTimeWorkRequestBuilder<SyncWorker>().setConstraints(netConstraint).build()
            WorkManager.getInstance(context).enqueueUniqueWork("echo-sync-now", ExistingWorkPolicy.REPLACE, req)
        }
    }
}

class ReminderWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as EchoApp
        val id = inputData.getString("id") ?: return Result.success()
        val open = PendingIntent.getActivity(
            applicationContext, id.hashCode(),
            Intent(applicationContext, MainActivity::class.java).putExtra("open", if (inputData.getString("kind") == "digest") "home" else "home"),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val n = NotificationCompat.Builder(applicationContext, EchoApp.CHANNEL_REMINDERS)
            .setSmallIcon(R.drawable.ic_stat_echo)
            .setContentTitle(inputData.getString("title") ?: "ECHO")
            .setContentText(inputData.getString("body"))
            .setStyle(NotificationCompat.BigTextStyle().bigText(inputData.getString("body")))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        runCatching { app.notifications.notify(id.hashCode(), n) }
        withContext(Dispatchers.IO) {
            runCatching {
                app.api.http.newCall(
                    okhttp3.Request.Builder().url(ai.echo.app.BuildConfig.API_BASE_URL.trimEnd('/') + "/v1/reminders/$id/delivered")
                        .post(okhttp3.RequestBody.EMPTY).build(),
                ).execute().close()
            }
        }
        return Result.success()
    }
}
