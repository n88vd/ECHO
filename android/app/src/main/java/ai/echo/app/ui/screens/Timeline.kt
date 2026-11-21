package ai.echo.app.ui.screens

import ai.echo.app.ui.theme.EchoIcons
import ai.echo.app.EchoApp
import ai.echo.app.data.TimelineItem
import ai.echo.app.ui.components.EmptyHint
import ai.echo.app.ui.components.GlassCard
import ai.echo.app.ui.components.MemoryRow
import ai.echo.app.ui.components.Pill
import ai.echo.app.ui.dayLabel
import ai.echo.app.ui.timeOf
import ai.echo.app.ui.theme.EchoColors
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun TimelineScreen(app: EchoApp, onConversation: (String) -> Unit, onMemory: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<TimelineItem>>(emptyList()) }
    var next by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var query by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(query) {
        delay(if (query.isEmpty()) 0 else 400)
        loading = true
        runCatching { app.api.timeline(q = query.ifBlank { null }) }
            .onSuccess { items = it.items; next = it.next_before; error = null }
            .onFailure { error = it.message }
        loading = false
    }

    LazyColumn(Modifier.fillMaxSize().statusBarsPadding(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text("Timeline", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.height(12.dp))
            TextField(
                query, { query = it }, Modifier.fillMaxWidth().clip(CircleShape).border(1.dp, EchoColors.Stroke, CircleShape),
                placeholder = { Text("Search conversations") }, leadingIcon = { Icon(EchoIcons.Search, null) }, singleLine = true,
                colors = TextFieldDefaults.colors(focusedContainerColor = Color.White, unfocusedContainerColor = Color.White, focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent),
            )
        }
        if (loading && items.isEmpty()) item {
            // Centre in the space left under the header rather than hugging the left edge.
            Box(Modifier.fillParentMaxWidth().fillParentMaxHeight(0.7f), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = EchoColors.Violet)
            }
        }
        error?.let { item { Text(it, color = EchoColors.Coral) } }
        if (!loading && items.isEmpty() && error == null) item { EmptyHint("Nothing yet. Conversations appear here a few minutes after they end.") }
        var lastDay = ""
        items.forEach { it ->
            val day = dayLabel(it.started_at)
            if (day != lastDay) {
                lastDay = day
                item(key = "day-$day-${it.id}") { Text(day, style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(top = 8.dp)) }
            }
            item(key = it.id) { ConversationCard(it, { onConversation(it.id) }, onMemory) }
        }
        if (next != null) item {
            Pill("Load more", Modifier.padding(8.dp)) {
                scope.launch {
                    runCatching { app.api.timeline(before = next, q = query.ifBlank { null }) }.onSuccess { items = items + it.items; next = it.next_before }
                }
            }
        }
    }
}

@Composable
private fun ConversationCard(c: TimelineItem, onOpen: () -> Unit, onMemory: (String) -> Unit) {
    GlassCard(Modifier.fillMaxWidth(), onClick = onOpen) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(timeOf(c.started_at), style = MaterialTheme.typography.labelMedium)
            if (c.place != null || c.in_transit) {
                Spacer(Modifier.width(10.dp))
                Icon(if (c.in_transit) EchoIcons.Car else EchoIcons.Place, null, Modifier.size(14.dp), tint = EchoColors.Muted)
                Text(if (c.in_transit) "On the move" else c.place!!, style = MaterialTheme.typography.labelMedium, maxLines = 1)
            }
            Spacer(Modifier.weight(1f))
            if (c.pinned) Icon(EchoIcons.Pin, "Pinned", Modifier.size(16.dp), tint = EchoColors.Violet)
            if (c.languages.isNotEmpty()) Text(c.languages.joinToString(" ") { it.substringBefore('-').uppercase() }, style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(start = 6.dp))
        }
        Spacer(Modifier.height(6.dp))
        Text(c.title, style = MaterialTheme.typography.titleMedium)
        c.summary?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = EchoColors.Muted, maxLines = 3) }
        if (c.people.isNotEmpty()) {
            Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                c.people.take(4).forEach { p -> Text(p.name, style = MaterialTheme.typography.labelMedium, modifier = Modifier.clip(CircleShape).background(EchoColors.accent).padding(horizontal = 10.dp, vertical = 4.dp)) }
            }
        }
        c.memories.take(3).forEach { m -> MemoryRow(m.type, m.content) { onMemory(m.id) } }
    }
}
