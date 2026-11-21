package ai.echo.app.ui.screens

import ai.echo.app.BuildConfig
import ai.echo.app.EchoApp
import ai.echo.app.capture.CaptureService
import ai.echo.app.data.QuietHours
import ai.echo.app.data.ServerSettings
import ai.echo.app.ui.components.GlassCard
import ai.echo.app.ui.components.Pill
import ai.echo.app.ui.components.SectionTitle
import ai.echo.app.ui.theme.EchoColors
import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.File
import java.time.LocalTime

@Composable
fun SettingsScreen(app: EchoApp, onEnrollVoice: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var s by remember { mutableStateOf<ServerSettings?>(null) }
    var earbud by remember { mutableStateOf(app.prefs.earbudPolicy) }
    var location by remember { mutableStateOf(app.prefs.locationEnabled) }
    var quiet by remember { mutableStateOf(app.prefs.quietHours) }
    val private by app.prefs.privateMode.collectAsState()
    var confirm by remember { mutableStateOf<String?>(null) }
    var message by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) { runCatching { app.api.settings() }.onSuccess { s = it; earbud = it.earbud_policy; location = it.location_enabled } }

    fun patch(block: kotlinx.serialization.json.JsonObjectBuilder.() -> Unit) {
        scope.launch { runCatching { app.api.patchSettings(buildJsonObject(block)) }.onSuccess { s = it }.onFailure { message = it.message } }
    }

    Column(Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState()).padding(20.dp)) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall)
        Text(app.session.email ?: "", style = MaterialTheme.typography.labelMedium)

        SectionTitle("Capture")
        GlassCard(Modifier.fillMaxWidth()) {
            ToggleRow("Private mode", "Pause all recording instantly", private) { app.prefs.privateModeValue = it; CaptureService.refresh(context) }
            ToggleRow("Location context", "Remember where conversations happened (only while listening)", location) {
                location = it; app.prefs.locationEnabled = it; patch { put("location_enabled", it) }; CaptureService.refresh(context)
            }
            Text("Earbud microphone", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 10.dp))
            Text("Bluetooth mics switch earbuds to call mode, which pauses music on many phones.", style = MaterialTheme.typography.labelMedium)
            FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("never" to "Never", "when_no_media" to "When no music", "always" to "Always").forEach { (k, label) ->
                    Pill(label, selected = earbud == k) { earbud = k; app.prefs.earbudPolicy = k; patch { put("earbud_policy", k) } }
                }
            }
            Text("Quiet hours", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 14.dp))
            FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val options = listOf(null to "Off", QuietHours(LocalTime.of(23, 0), LocalTime.of(7, 0)) to "11pm–7am", QuietHours(LocalTime.of(22, 0), LocalTime.of(8, 0)) to "10pm–8am")
                options.forEach { (q, label) ->
                    Pill(label, selected = quiet == q) {
                        quiet = q; app.prefs.quietHours = q
                        patch { put("quiet_hours", kotlinx.serialization.json.JsonArray(listOfNotNull(q?.let { JsonPrimitive(it.encode()) }))) }
                        CaptureService.refresh(context)
                    }
                }
            }
        }

        SectionTitle("Memory")
        GlassCard(Modifier.fillMaxWidth()) {
            Text("Keep raw audio", style = MaterialTheme.typography.titleMedium)
            Text("Transcripts and memories are kept until you delete them.", style = MaterialTheme.typography.labelMedium)
            val current = s?.let { if (it.retention_forever) -1 else it.audio_retention_days } ?: -1
            FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(0 to "Delete after processing", 7 to "7 days", 30 to "30 days", 90 to "90 days", -1 to "Forever").forEach { (d, label) ->
                    Pill(label, selected = current == d) { patch { if (d < 0) put("retention_forever", true) else put("audio_retention_days", d) } }
                }
            }
            Text("Daily digest", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 14.dp))
            FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("20:00", "21:00", "22:00").forEach { t -> Pill(t, selected = s?.daily_digest_time == t) { patch { put("daily_digest_time", t) } } }
            }
            Spacer(Modifier.height(10.dp))
            Pill("Re-record my voice") { onEnrollVoice() }
        }

        SectionTitle("Your data")
        GlassCard(Modifier.fillMaxWidth()) {
            TextButton(onClick = {
                scope.launch {
                    runCatching {
                        val f = app.api.exportTo(File(context.cacheDir, "echo-export.json"))
                        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", f)
                        context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("application/json").putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), "Export memories"))
                    }.onFailure { message = it.message }
                }
            }) { Text("Export all my data") }
            TextButton(onClick = { confirm = "delete" }) { Text("Delete all my ECHO data", color = EchoColors.Coral) }
            TextButton(onClick = { confirm = "signout" }) { Text("Sign out") }
        }
        message?.let { Text(it, color = EchoColors.Coral, modifier = Modifier.padding(top = 8.dp)) }
        Spacer(Modifier.height(16.dp))
        Text("ECHO ${BuildConfig.VERSION_NAME} · Silence is dropped on your phone. Only speech is uploaded, encrypted in transit, and processed to build your private memory.",
            style = MaterialTheme.typography.labelMedium)
        Spacer(Modifier.height(40.dp))
    }

    confirm?.let { what ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(if (what == "delete") "Delete everything?" else "Sign out?") },
            text = { Text(if (what == "delete") "All recordings, transcripts and memories will be permanently deleted. This cannot be undone." else "Listening will stop on this phone.") },
            confirmButton = {
                TextButton(onClick = {
                    scope.launch {
                        if (what == "delete") runCatching { app.api.deleteAccount() }
                        CaptureService.stop(context)
                        app.outbox.pending().forEach(app.outbox::remove)
                        app.prefs.onboarded = false
                        app.prefs.serverDeviceId = null
                        app.session.clear()
                        confirm = null
                    }
                }) { Text(if (what == "delete") "Delete" else "Sign out", color = EchoColors.Coral) }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun ToggleRow(title: String, sub: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(sub, style = MaterialTheme.typography.labelMedium)
        }
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
