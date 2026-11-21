package ai.echo.app.capture

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.Location
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.util.Locale

data class Fix(val lat: Double, val lng: Double, val accuracy: Double, val locality: String?)

/** Location only while capture runs (foreground service type=location; no background-location permission). */
class LocationTracker(private val context: Context) {
    private val client = LocationServices.getFusedLocationProviderClient(context)
    private var cached: Pair<Long, Fix>? = null

    fun permitted(): Boolean =
        context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    suspend fun current(maxAgeMs: Long = 120_000): Fix? {
        if (!permitted()) return null
        cached?.let { (t, f) -> if (System.currentTimeMillis() - t < maxAgeMs) return f }
        val loc: Location = withTimeoutOrNull(8_000) {
            client.getCurrentLocation(Priority.PRIORITY_BALANCED_POWER_ACCURACY, CancellationTokenSource().token).await()
        } ?: runCatching { client.lastLocation.await() }.getOrNull() ?: return cached?.second
        val fix = Fix(loc.latitude, loc.longitude, loc.accuracy.toDouble(), locality(loc))
        cached = System.currentTimeMillis() to fix
        return fix
    }

    @Suppress("DEPRECATION")
    private suspend fun locality(loc: Location): String? = withContext(Dispatchers.IO) {
        if (!Geocoder.isPresent()) return@withContext null
        runCatching {
            val a = Geocoder(context, Locale.ENGLISH).getFromLocation(loc.latitude, loc.longitude, 1)?.firstOrNull() ?: return@runCatching null
            listOfNotNull(a.subLocality ?: a.featureName, a.locality).distinct().joinToString(", ").ifBlank { null }
        }.getOrNull()
    }
}
