package ai.echo.app.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.time.LocalTime
import java.util.UUID

data class QuietHours(val start: LocalTime, val end: LocalTime) {
    fun contains(t: LocalTime): Boolean = if (start <= end) t >= start && t < end else t >= start || t < end
    fun encode() = "$start-$end"

    companion object {
        fun decode(s: String): QuietHours? = runCatching {
            val (a, b) = s.split("-")
            QuietHours(LocalTime.parse(a), LocalTime.parse(b))
        }.getOrNull()
    }
}

class Prefs(context: Context) {
    private val p = context.getSharedPreferences("echo_prefs", Context.MODE_PRIVATE)

    private val _captureEnabled = MutableStateFlow(p.getBoolean("capture_enabled", false))
    val captureEnabled: StateFlow<Boolean> = _captureEnabled
    private val _privateMode = MutableStateFlow(p.getBoolean("private_mode", false))
    val privateMode: StateFlow<Boolean> = _privateMode

    var captureEnabledValue: Boolean
        get() = _captureEnabled.value
        set(v) { p.edit().putBoolean("capture_enabled", v).apply(); _captureEnabled.value = v }

    var privateModeValue: Boolean
        get() = _privateMode.value
        set(v) { p.edit().putBoolean("private_mode", v).apply(); _privateMode.value = v }

    var earbudPolicy: String
        get() = p.getString("earbud_policy", "when_no_media")!!
        set(v) = p.edit().putString("earbud_policy", v).apply()

    var locationEnabled: Boolean
        get() = p.getBoolean("location_enabled", true)
        set(v) = p.edit().putBoolean("location_enabled", v).apply()

    var quietHours: QuietHours?
        get() = p.getString("quiet_hours", null)?.let(QuietHours::decode)
        set(v) = p.edit().putString("quiet_hours", v?.encode()).apply()

    var onboarded: Boolean
        get() = p.getBoolean("onboarded", false)
        set(v) = p.edit().putBoolean("onboarded", v).apply()

    var syncCursor: String?
        get() = p.getString("sync_cursor", null)
        set(v) = p.edit().putString("sync_cursor", v).apply()

    var pinUntil: Long
        get() = p.getLong("pin_until", 0)
        set(v) = p.edit().putLong("pin_until", v).apply()

    var serverDeviceId: String?
        get() = p.getString("server_device_id", null)
        set(v) = p.edit().putString("server_device_id", v).apply()

    val installId: String
        get() = p.getString("install_id", null) ?: UUID.randomUUID().toString().also { p.edit().putString("install_id", it).apply() }
}
