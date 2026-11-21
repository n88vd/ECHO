package ai.echo.app.ui.screens

import ai.echo.app.ui.theme.EchoIcons
import ai.echo.app.EchoApp
import ai.echo.app.data.AskResponse
import ai.echo.app.ui.Player
import ai.echo.app.ui.VoiceRecorder
import ai.echo.app.ui.components.ParticleSphere
import ai.echo.app.ui.components.SphereMode
import ai.echo.app.ui.components.GlassCard
import ai.echo.app.ui.components.Pill
import ai.echo.app.ui.components.memoryIcon
import ai.echo.app.ui.components.memoryLabel
import ai.echo.app.ui.fullOf
import ai.echo.app.ui.renderCitations
import ai.echo.app.ui.theme.EchoColors
import android.Manifest
import android.os.SystemClock
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.clickable
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.produceState
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.delay
import android.content.pm.PackageManager
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import java.io.File

private data class Turn(val question: String, val answer: AskResponse? = null, val error: String? = null)

private val turns = mutableStateListOf<Turn>()

private const val MAX_VOICE_MS = 20_000L

/** Shown above the input while ECHO reads an answer aloud. */
@Composable
private fun SpeakingBar(level: Float, onStop: () -> Unit) {
    Row(
        Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp).fillMaxWidth().clip(RoundedCornerShape(24.dp))
            .background(Color.White.copy(alpha = 0.85f)).border(1.dp, EchoColors.Stroke, RoundedCornerShape(24.dp))
            .padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ParticleSphere(56.dp, level = level, mode = SphereMode.Speaking)
        Spacer(Modifier.width(6.dp))
        Text("ECHO is speaking…", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
        IconButton(onClick = onStop) { Icon(EchoIcons.Stop, "Stop speaking", tint = EchoColors.Violet) }
    }
}

/** Centred recording sheet: live orb, elapsed/limit timer, cancel and done. */
@Composable
private fun VoicePopup(level: Float, onDone: () -> Unit, onCancel: () -> Unit) {
    val started = remember { SystemClock.uptimeMillis() }
    val elapsed by produceState(0L) { while (true) { value = SystemClock.uptimeMillis() - started; delay(200) } }
    val progress by animateFloatAsState((elapsed / MAX_VOICE_MS.toFloat()).coerceIn(0f, 1f), tween(200), label = "progress")
    Dialog(onDismissRequest = onCancel, properties = DialogProperties(usePlatformDefaultWidth = false, dismissOnClickOutside = false)) {
        Column(
            Modifier.padding(horizontal = 28.dp).fillMaxWidth().clip(RoundedCornerShape(32.dp)).background(Color.White)
                .border(1.dp, EchoColors.Stroke, RoundedCornerShape(32.dp)).padding(horizontal = 24.dp, vertical = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("Listening…", style = MaterialTheme.typography.titleLarge)
            Text("Ask in any language", color = EchoColors.Muted, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(20.dp))
            Box(contentAlignment = Alignment.Center) {
                CircularProgressIndicator(
                    progress = { progress }, modifier = Modifier.size(212.dp), color = EchoColors.Violet,
                    trackColor = EchoColors.Lavender.copy(alpha = 0.18f), strokeWidth = 3.dp, strokeCap = StrokeCap.Round,
                )
                ParticleSphere(190.dp, level = level, mode = SphereMode.Listening)
            }
            Spacer(Modifier.height(16.dp))
            Text(
                "%d:%02d / 0:%02d".format(elapsed / 60_000, (elapsed / 1000) % 60, MAX_VOICE_MS / 1000),
                color = EchoColors.Muted, style = MaterialTheme.typography.labelLarge,
            )
            Spacer(Modifier.height(24.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly, verticalAlignment = Alignment.CenterVertically) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Box(Modifier.size(56.dp).clip(CircleShape).border(1.dp, EchoColors.Stroke, CircleShape).clickable(onClick = onCancel), contentAlignment = Alignment.Center) {
                        Icon(EchoIcons.Close, "Cancel", tint = EchoColors.Muted)
                    }
                    Spacer(Modifier.height(6.dp)); Text("Cancel", style = MaterialTheme.typography.labelMedium, color = EchoColors.Muted)
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Box(Modifier.size(72.dp).clip(CircleShape).background(EchoColors.Violet).clickable(onClick = onDone), contentAlignment = Alignment.Center) {
                        Icon(EchoIcons.Stop, "Done", tint = Color.White, modifier = Modifier.size(28.dp))
                    }
                    Spacer(Modifier.height(6.dp)); Text("Done", style = MaterialTheme.typography.labelMedium)
                }
            }
        }
    }
}

@Composable
fun AskScreen(app: EchoApp, onMemory: (String) -> Unit) {
    val context = LocalContext.current
    val focus = LocalFocusManager.current
    val scope = rememberCoroutineScope()
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var recording by remember { mutableStateOf(false) }
    var speak by remember { mutableStateOf(true) }
    val recorder = remember { VoiceRecorder() }
    val level by recorder.level.collectAsState()
    val speakingKey by Player.playing.collectAsState()
    val speakLevel by Player.level.collectAsState()
    val speakingNow = speakingKey != null
    val list = rememberLazyListState()

    LaunchedEffect(turns.size) { if (turns.isNotEmpty()) list.animateScrollToItem(turns.size - 1) }

    fun submit(q: String) {
        if (q.isBlank() || busy) return
        turns += Turn(q)
        val idx = turns.size - 1
        busy = true
        scope.launch {
            runCatching { app.api.ask(q, speak) }
                .onSuccess { r -> turns[idx] = turns[idx].copy(answer = r); r.tts_url?.let { Player.play(it, r.ask_id) } }
                .onFailure { turns[idx] = turns[idx].copy(error = it.message ?: "Something went wrong") }
            busy = false
        }
    }

    var cancelled by remember { mutableStateOf(false) }

    fun voice() {
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return
        if (recording) { recorder.stopRequested = true; return }
        Player.stop()
        focus.clearFocus()
        cancelled = false
        recording = true
        scope.launch {
            val file = runCatching { recorder.record(File(context.cacheDir, "ask.wav"), MAX_VOICE_MS) }.getOrNull()
            recording = false
            if (file == null) return@launch
            if (cancelled) { file.delete(); return@launch }
            turns += Turn("🎙️ …")
            val idx = turns.size - 1
            busy = true
            runCatching { app.api.askVoice(file, speak) }
                .onSuccess { r -> turns[idx] = Turn(r.transcript ?: "(voice)", r); r.tts_url?.let { Player.play(it, r.ask_id) } }
                .onFailure { turns[idx] = turns[idx].copy(error = it.message ?: "Could not understand") }
            busy = false
            file.delete()
        }
    }

    if (recording) VoicePopup(level, onDone = { recorder.stopRequested = true }, onCancel = { cancelled = true; recorder.stopRequested = true })

    Column(Modifier.fillMaxSize().statusBarsPadding().imePadding()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Ask ECHO", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            Pill(if (speak) "Voice on" else "Voice off", selected = speak, icon = EchoIcons.Volume) { speak = !speak; if (!speak) Player.stop() }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = list, contentPadding = androidx.compose.foundation.layout.PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            if (turns.isEmpty()) item {
                Column(Modifier.fillMaxWidth().padding(top = 40.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    ParticleSphere(190.dp, level = if (speakingNow) speakLevel else 0f, mode = if (speakingNow) SphereMode.Speaking else SphereMode.Idle)
                    Spacer(Modifier.height(20.dp))
                    Text("Ask about anything you've talked about", style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
                    Text("In English, Hindi, Tamil or any Indian language", color = EchoColors.Muted, textAlign = TextAlign.Center)
                    Spacer(Modifier.height(20.dp))
                    listOf("What did I promise this week?", "Where did I keep my passport?", "What did I learn about robotics?", "Why did I reject that offer?")
                        .forEach { Pill(it, Modifier.padding(4.dp)) { submit(it) } }
                }
            }
            items(turns) { t -> TurnView(app, t, onMemory) }
        }
        if (speakingNow && turns.isNotEmpty()) SpeakingBar(speakLevel) { Player.stop() }
        Row(
            Modifier.padding(16.dp).fillMaxWidth().clip(RoundedCornerShape(28.dp)).background(Color.White).border(1.dp, EchoColors.Stroke, RoundedCornerShape(28.dp)).padding(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextField(
                input, { input = it }, Modifier.weight(1f), placeholder = { Text("Ask me anything…") },
                colors = TextFieldDefaults.colors(focusedContainerColor = Color.Transparent, unfocusedContainerColor = Color.Transparent, focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent),
                maxLines = 4,
            )
            if (input.isNotBlank()) IconButton(onClick = { submit(input.trim()); input = "" }, enabled = !busy) { Icon(EchoIcons.Send, "Send", tint = EchoColors.Violet) }
            Box(Modifier.size(48.dp).clip(CircleShape).background(EchoColors.accent, CircleShape), contentAlignment = Alignment.Center) {
                IconButton(onClick = { voice() }, enabled = !busy) { Icon(EchoIcons.Mic, "Speak", tint = EchoColors.Ink) }
            }
        }
    }
}

@Composable
private fun TurnView(app: EchoApp, t: Turn, onMemory: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var rated by remember(t.answer?.ask_id) { mutableStateOf<Boolean?>(null) }
    Column(Modifier.fillMaxWidth()) {
        Box(Modifier.align(Alignment.End).widthIn(max = 300.dp).clip(RoundedCornerShape(20.dp, 20.dp, 4.dp, 20.dp)).background(EchoColors.accent).padding(14.dp)) {
            Text(t.question)
        }
        Spacer(Modifier.height(10.dp))
        when {
            t.error != null -> Text(t.error, color = EchoColors.Coral)
            t.answer == null -> Row(verticalAlignment = Alignment.CenterVertically) {
                ParticleSphere(36.dp, mode = SphereMode.Listening); Spacer(Modifier.width(8.dp)); Text("Searching your memories…", color = EchoColors.Muted)
            }
            else -> {
                val (text, ids) = renderCitations(t.answer.answer)
                Text(text, style = MaterialTheme.typography.bodyLarge)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    t.answer.tts_url?.let { url -> IconButton(onClick = { Player.play(url, t.answer.ask_id) }) { Icon(EchoIcons.Volume, "Play", tint = EchoColors.Muted) } }
                    IconButton(onClick = { rated = true; scope.launch { runCatching { app.api.feedback(t.answer.ask_id, true) } } }) {
                        Icon(EchoIcons.ThumbUp, "Good", tint = if (rated == true) EchoColors.Violet else EchoColors.Faint)
                    }
                    IconButton(onClick = { rated = false; scope.launch { runCatching { app.api.feedback(t.answer.ask_id, false) } } }) {
                        Icon(EchoIcons.ThumbDown, "Bad", tint = if (rated == false) EchoColors.Coral else EchoColors.Faint)
                    }
                }
                val cites = ids.mapNotNull { id -> t.answer.citations.firstOrNull { it.id == id } }.ifEmpty { t.answer.citations }
                if (cites.isNotEmpty()) {
                    Text("Sources", style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(bottom = 6.dp))
                    cites.forEachIndexed { i, c ->
                        val (icon, color) = memoryIcon(c.type)
                        GlassCard(Modifier.fillMaxWidth().padding(bottom = 8.dp), onClick = if (c.kind == "memory") ({ onMemory(c.id) }) else null) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text("${i + 1}", color = EchoColors.Violet, fontSize = 13.sp)
                                Spacer(Modifier.width(8.dp))
                                Icon(icon, null, tint = color, modifier = Modifier.size(16.dp))
                                Spacer(Modifier.width(6.dp))
                                Text("${memoryLabel(c.type)} · ${fullOf(c.captured_at)}", style = MaterialTheme.typography.labelMedium)
                            }
                            c.evidence.firstOrNull()?.let { e ->
                                Text("“${e.quote_native ?: e.quote_en}”", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp))
                                e.speaker?.let { Text("— $it", style = MaterialTheme.typography.labelMedium) }
                            } ?: Text(c.content, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp))
                        }
                    }
                }
            }
        }
    }
}
