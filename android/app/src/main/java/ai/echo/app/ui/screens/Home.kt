package ai.echo.app.ui.screens

import ai.echo.app.EchoApp
import ai.echo.app.capture.CaptureService
import ai.echo.app.capture.CaptureStatus
import ai.echo.app.capture.RememberAction
import ai.echo.app.data.Commitment
import ai.echo.app.data.Digest
import ai.echo.app.data.Person
import ai.echo.app.data.Status
import ai.echo.app.ui.components.EchoOrb
import ai.echo.app.ui.components.EmptyHint
import ai.echo.app.ui.components.GlassCard
import ai.echo.app.ui.components.MemoryRow
import ai.echo.app.ui.components.Pill
import ai.echo.app.ui.components.SectionTitle
import ai.echo.app.ui.greeting
import ai.echo.app.ui.relative
import ai.echo.app.ui.renderCitations
import ai.echo.app.ui.theme.EchoColors
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.BookmarkAdd
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Mic
import androidx.compose.material.icons.outlined.VisibilityOff
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun HomeScreen(app: EchoApp, onAsk: () -> Unit, onMemory: (String) -> Unit, onTimeline: () -> Unit, onOnboard: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val capture by CaptureService.stateFlow.collectAsState()
    val enabled by app.prefs.captureEnabled.collectAsState()
    val private by app.prefs.privateMode.collectAsState()
    var status by remember { mutableStateOf<Status?>(null) }
    var promises by remember { mutableStateOf<List<Commitment>>(emptyList()) }
    var digest by remember { mutableStateOf<Digest?>(null) }
    var people by remember { mutableStateOf<List<Person>>(emptyList()) }
    var refreshKey by remember { mutableStateOf(0) }

    LaunchedEffect(refreshKey) {
        while (true) {
            runCatching { status = app.api.status() }
            runCatching { promises = app.api.commitments().items }
            runCatching { digest = app.api.latestDigest().digest }
            runCatching { people = app.api.people().items.take(12) }
            delay(30_000)
        }
    }

    val label = when {
        !enabled -> "ECHO is off"
        private -> "Private mode"
        else -> when (capture.status) {
            CaptureStatus.Speech -> "Listening…"
            CaptureStatus.Listening -> "Ready — waiting for speech"
            CaptureStatus.QuietHours -> "Quiet hours"
            CaptureStatus.InCall -> "Paused during call"
            CaptureStatus.NoPermission -> "Microphone unavailable"
            CaptureStatus.Private -> "Private mode"
            CaptureStatus.Stopped -> "Starting…"
        }
    }

    Column(Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp)) {
        Spacer(Modifier.height(16.dp))
        Text(greeting() + (app.session.name?.split(" ")?.firstOrNull()?.let { ", $it" } ?: ""), style = MaterialTheme.typography.displaySmall)
        Text("What would you like to remember?", color = EchoColors.Muted)
        Spacer(Modifier.height(20.dp))

        GlassCard(Modifier.fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                EchoOrb(96.dp, level = capture.level, active = enabled && !private && capture.status in setOf(CaptureStatus.Listening, CaptureStatus.Speech))
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f)) {
                    Text(label, style = MaterialTheme.typography.titleMedium)
                    val src = when (capture.source) { "bt_sco", "bt_le" -> "Earbuds mic"; "wired" -> "Headset mic"; else -> "Phone mic" }
                    Text(if (enabled) "$src · ${status?.speech_minutes_today ?: 0.0} min today" else "Tap the switch to start", style = MaterialTheme.typography.labelMedium)
                    if ((status?.segments_pending ?: 0) > 0 || app.outbox.count() > 0) {
                        Text("Processing ${(status?.segments_pending ?: 0) + app.outbox.count()} clips…", style = MaterialTheme.typography.labelMedium, color = EchoColors.Violet)
                    }
                }
                Switch(checked = enabled, onCheckedChange = {
                    if (it) {
                        if (!app.prefs.onboarded) onOnboard() else CaptureService.start(context)
                    } else CaptureService.stop(context)
                })
            }
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Pill("Remember this", icon = Icons.Outlined.BookmarkAdd) {
                    RememberAction.trigger(context)
                    Toast.makeText(context, "ECHO will remember this moment", Toast.LENGTH_SHORT).show()
                }
                Pill(if (private) "Resume" else "Private", selected = private, icon = Icons.Outlined.VisibilityOff) {
                    app.prefs.privateModeValue = !private
                    CaptureService.refresh(context)
                }
            }
        }

        Spacer(Modifier.height(14.dp))
        Row(
            Modifier.fillMaxWidth().clip(CircleShape).background(EchoColors.Glass).border(1.dp, EchoColors.Stroke, CircleShape).clickable(onClick = onAsk).padding(start = 20.dp, end = 6.dp, top = 6.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Ask ECHO anything…", color = EchoColors.Faint, modifier = Modifier.weight(1f))
            Box(Modifier.size(44.dp).clip(CircleShape).background(EchoColors.accent), contentAlignment = Alignment.Center) {
                Icon(Icons.Outlined.Mic, null, tint = EchoColors.Ink)
            }
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("My promises", "Where are my keys?").forEach { Pill(it, onClick = onAsk) }
        }

        if (status != null && status?.voice_enrolled == false) {
            Spacer(Modifier.height(16.dp))
            GlassCard(Modifier.fillMaxWidth(), onClick = onOnboard) {
                Text("Teach ECHO your voice", style = MaterialTheme.typography.titleMedium)
                Text("So it knows which promises are yours and which are someone else's.", style = MaterialTheme.typography.labelMedium)
            }
        }

        SectionTitle("Open promises", "See all", onTimeline)
        GlassCard(Modifier.fillMaxWidth()) {
            if (promises.isEmpty()) EmptyHint("No open promises. ECHO will catch them as you talk.")
            promises.take(5).forEach { c ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.weight(1f)) {
                        MemoryRow("commitment", c.content, listOfNotNull(if (c.owner == "user") "You owe" else "Owed to you", c.counterparty, c.due_at?.let { "due " + relative(it).ifBlank { it } }).joinToString(" · ")) { onMemory(c.memory_id) }
                    }
                    IconButton(onClick = {
                        scope.launch { runCatching { app.api.setCommitment(c.memory_id, "done") }; refreshKey++ }
                    }) { Icon(Icons.Outlined.CheckCircle, "Mark done", tint = EchoColors.Mint) }
                }
            }
        }

        digest?.let { d ->
            SectionTitle("Your day")
            GlassCard(Modifier.fillMaxWidth()) {
                Text(d.day, style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.height(6.dp))
                Text(renderCitations(d.content).first, style = MaterialTheme.typography.bodyMedium)
            }
        }

        if (people.isNotEmpty()) {
            SectionTitle("People")
            LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                items(people) { p ->
                    GlassCard(Modifier.width(150.dp)) {
                        Box(Modifier.size(36.dp).clip(CircleShape).background(EchoColors.accent), contentAlignment = Alignment.Center) {
                            Text(p.name.take(1).uppercase(), fontWeight = FontWeight.SemiBold)
                        }
                        Spacer(Modifier.height(8.dp))
                        Text(p.name, style = MaterialTheme.typography.titleMedium, fontSize = 15.sp, maxLines = 1)
                        Text(listOfNotNull(p.last_interaction_at?.let(::relative), if (p.open_commitments > 0) "${p.open_commitments} promises" else null).joinToString(" · "),
                            style = MaterialTheme.typography.labelMedium, maxLines = 1)
                    }
                }
            }
        }
        Spacer(Modifier.height(32.dp))
    }
}
