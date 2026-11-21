package ai.echo.app.ui.screens

import ai.echo.app.EchoApp
import ai.echo.app.data.ConversationDetail
import ai.echo.app.data.MemoryDetail
import ai.echo.app.ui.Player
import ai.echo.app.ui.components.GlassCard
import ai.echo.app.ui.components.MemoryRow
import ai.echo.app.ui.components.Pill
import ai.echo.app.ui.components.SectionTitle
import ai.echo.app.ui.components.memoryIcon
import ai.echo.app.ui.components.memoryLabel
import ai.echo.app.ui.fullOf
import ai.echo.app.ui.timeOf
import ai.echo.app.ui.theme.EchoColors
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.PushPin
import androidx.compose.material.icons.outlined.Stop
import androidx.compose.material.icons.outlined.Translate
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

@Composable
private fun TopBar(title: String, onBack: () -> Unit, actions: @Composable () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 8.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back") }
        Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
        actions()
    }
}

@Composable
fun MemoryDetailScreen(app: EchoApp, id: String, onBack: () -> Unit, onConversation: (String) -> Unit, onMemory: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var m by remember { mutableStateOf<MemoryDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var confirmDelete by remember { mutableStateOf(false) }
    var labeling by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    val playing by Player.playing.collectAsState()

    LaunchedEffect(id, reload) { runCatching { app.api.memory(id) }.onSuccess { m = it }.onFailure { error = it.message } }

    Column(Modifier.fillMaxSize()) {
        TopBar("Memory", onBack) {
            m?.let { mem ->
                IconButton(onClick = { scope.launch { runCatching { app.api.pinMemory(id, !mem.pinned) }; reload++ } }) {
                    Icon(Icons.Outlined.PushPin, "Pin", tint = if (mem.pinned) EchoColors.Violet else EchoColors.Faint)
                }
                IconButton(onClick = { confirmDelete = true }) { Icon(Icons.Outlined.Delete, "Delete", tint = EchoColors.Muted) }
            }
        }
        val mem = m
        if (mem == null) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { if (error != null) Text(error!!, color = EchoColors.Coral) else CircularProgressIndicator() }
            return@Column
        }
        Column(Modifier.verticalScroll(rememberScrollState()).padding(20.dp)) {
            val (icon, color) = memoryIcon(mem.type)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(36.dp).clip(CircleShape).background(color.copy(alpha = 0.15f)), contentAlignment = Alignment.Center) { Icon(icon, null, tint = color) }
                Spacer(Modifier.width(10.dp))
                Text(memoryLabel(mem.type), style = MaterialTheme.typography.labelMedium)
                if (mem.superseded_by != null) Text("  · outdated", style = MaterialTheme.typography.labelMedium, color = EchoColors.Coral)
            }
            Spacer(Modifier.height(12.dp))
            Text(mem.content, style = MaterialTheme.typography.headlineSmall)
            if (!mem.content_native.isNullOrBlank() && mem.content_native != mem.content) {
                Spacer(Modifier.height(8.dp))
                Text(mem.content_native, style = MaterialTheme.typography.bodyLarge, color = EchoColors.Muted)
            }
            Spacer(Modifier.height(12.dp))
            Text(listOfNotNull(fullOf(mem.captured_at), mem.place).joinToString(" · "), style = MaterialTheme.typography.labelMedium)
            mem.commitment?.let { c ->
                Spacer(Modifier.height(16.dp))
                GlassCard(Modifier.fillMaxWidth()) {
                    Text(if (c.owner == "user") "You promised" else "Promised to you", style = MaterialTheme.typography.labelMedium)
                    Text(c.action, style = MaterialTheme.typography.bodyLarge)
                    c.due_at?.let { Text("Due ${fullOf(it)}", style = MaterialTheme.typography.labelMedium) }
                    Spacer(Modifier.height(8.dp))
                    if (c.status == "open") Pill("Mark as done", icon = Icons.Outlined.CheckCircle) {
                        scope.launch { runCatching { app.api.setCommitment(id, "done") }; reload++ }
                    } else Text("Status: ${c.status}", color = EchoColors.Mint)
                }
            }
            SectionTitle("Evidence")
            mem.evidence.forEach { e ->
                GlassCard(Modifier.fillMaxWidth().padding(bottom = 8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(e.speaker.label ?: "Unknown speaker", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        Text(timeOf(e.spoken_at), style = MaterialTheme.typography.labelMedium)
                        e.audio_url?.let { url ->
                            IconButton(onClick = { if (playing == e.utterance_id) Player.stop() else Player.play(url, e.utterance_id, e.start_ms ?: 0) }) {
                                Icon(if (playing == e.utterance_id) Icons.Outlined.Stop else Icons.Outlined.PlayArrow, "Play")
                            }
                        }
                    }
                    Text("“${e.quote_native}”", style = MaterialTheme.typography.bodyLarge)
                    if (!e.quote_en.isNullOrBlank() && e.quote_en != e.quote_native) Text(e.quote_en, style = MaterialTheme.typography.bodyMedium, color = EchoColors.Muted)
                    if (e.speaker.is_user != true && e.speaker.id != null) {
                        Text("Who is this?", color = EchoColors.Violet, style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier.padding(top = 6.dp).clip(CircleShape).background(EchoColors.accent)
                                .clickable { labeling = e.speaker.id }.padding(horizontal = 10.dp, vertical = 4.dp))
                    }
                }
            }
            if (mem.entities.isNotEmpty()) {
                SectionTitle("Connected")
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    mem.entities.forEach { Pill(it.name) }
                }
            }
            if (mem.links.isNotEmpty()) {
                SectionTitle("Related memories")
                mem.links.forEach { l ->
                    val tag = when (l.kind) { "supersedes" -> if (l.direction == "out") "Replaces" else "Replaced by"; "same_topic" -> "Similar"; else -> l.kind }
                    MemoryRow("fact", l.content, "$tag · ${fullOf(l.captured_at)}") { onMemory(l.memory_id) }
                }
            }
            mem.conversation.id?.let { cid ->
                Spacer(Modifier.height(16.dp))
                Pill("Open conversation: ${mem.conversation.title ?: ""}") { onConversation(cid) }
            }
            Spacer(Modifier.height(40.dp))
        }
    }

    if (confirmDelete) AlertDialog(
        onDismissRequest = { confirmDelete = false },
        title = { Text("Delete this memory?") },
        text = { Text("ECHO will forget it permanently.") },
        confirmButton = { TextButton(onClick = { scope.launch { runCatching { app.api.deleteMemory(id) }; confirmDelete = false; onBack() } }) { Text("Delete", color = EchoColors.Coral) } },
        dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancel") } },
    )
    labeling?.let { sid -> LabelDialog(app, sid, onDone = { labeling = null; reload++ }) }
}

@Composable
private fun LabelDialog(app: EchoApp, speakerId: String, onDone: () -> Unit) {
    val scope = rememberCoroutineScope()
    var name by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDone,
        title = { Text("Who is speaking?") },
        text = {
            Column {
                OutlinedTextField(name, { name = it }, label = { Text("Name") }, singleLine = true)
                TextButton(onClick = { scope.launch { runCatching { app.api.labelSpeaker(speakerId, null, true) }; onDone() } }) { Text("This is me") }
            }
        },
        confirmButton = { TextButton(enabled = name.isNotBlank(), onClick = { scope.launch { runCatching { app.api.labelSpeaker(speakerId, name.trim(), false) }; onDone() } }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDone) { Text("Cancel") } },
    )
}

@Composable
fun ConversationScreen(app: EchoApp, id: String, onBack: () -> Unit, onMemory: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var c by remember { mutableStateOf<ConversationDetail?>(null) }
    var english by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    var labeling by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    LaunchedEffect(id, reload) { runCatching { app.api.conversation(id) }.onSuccess { c = it } }

    Column(Modifier.fillMaxSize()) {
        TopBar(c?.title ?: "Conversation", onBack) {
            IconButton(onClick = { english = !english }) { Icon(Icons.Outlined.Translate, "Translate", tint = if (english) EchoColors.Violet else EchoColors.Muted) }
            IconButton(onClick = { confirmDelete = true }) { Icon(Icons.Outlined.Delete, "Delete", tint = EchoColors.Muted) }
        }
        val conv = c ?: run { Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }; return@Column }
        Column(Modifier.verticalScroll(rememberScrollState()).padding(20.dp)) {
            Text(listOfNotNull(fullOf(conv.started_at), conv.place).joinToString(" · "), style = MaterialTheme.typography.labelMedium)
            conv.summary?.let { Text(it, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(vertical = 10.dp)) }
            if (conv.speakers.isNotEmpty()) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    conv.speakers.forEach { s -> Pill(if (s.is_user) "You" else s.label, selected = s.is_user) { if (!s.is_user) labeling = s.id } }
                }
            }
            if (conv.memories.isNotEmpty()) {
                SectionTitle("Memories")
                GlassCard(Modifier.fillMaxWidth()) { conv.memories.forEach { m -> MemoryRow(m.type, m.content) { onMemory(m.id) } } }
            }
            SectionTitle("Transcript")
            conv.utterances.forEach { u ->
                val mine = u.speaker.is_user == true
                Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalAlignment = if (mine) Alignment.End else Alignment.Start) {
                    Text("${u.speaker.label ?: "Unknown"} · ${timeOf(u.spoken_at)}", style = MaterialTheme.typography.labelMedium)
                    Box(Modifier.widthIn(max = 300.dp).clip(RoundedCornerShape(18.dp)).background(if (mine) EchoColors.Lavender.copy(alpha = 0.35f) else Color.White).padding(12.dp)) {
                        Text(if (english) (u.text_en ?: u.text_native) else u.text_native)
                    }
                }
            }
            Spacer(Modifier.height(40.dp))
        }
    }
    if (confirmDelete) AlertDialog(
        onDismissRequest = { confirmDelete = false },
        title = { Text("Delete conversation?") },
        text = { Text("The audio, transcript and all memories from it will be deleted permanently.") },
        confirmButton = { TextButton(onClick = { scope.launch { runCatching { app.api.deleteConversation(id) }; confirmDelete = false; onBack() } }) { Text("Delete", color = EchoColors.Coral) } },
        dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancel") } },
    )
    labeling?.let { sid -> LabelDialog(app, sid, onDone = { labeling = null; reload++ }) }
}
