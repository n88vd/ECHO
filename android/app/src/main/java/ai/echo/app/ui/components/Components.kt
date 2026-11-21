package ai.echo.app.ui.components

import ai.echo.app.ui.theme.EchoIcons
import ai.echo.app.ui.theme.EchoColors
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp


@Composable
fun GlassCard(modifier: Modifier = Modifier, onClick: (() -> Unit)? = null, padding: PaddingValues = PaddingValues(16.dp), content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier
            .clip(RoundedCornerShape(24.dp))
            .background(EchoColors.Glass)
            .border(1.dp, EchoColors.Stroke, RoundedCornerShape(24.dp))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(padding),
        content = content,
    )
}

@Composable
fun Pill(text: String, modifier: Modifier = Modifier, selected: Boolean = false, icon: ImageVector? = null, onClick: (() -> Unit)? = null) {
    Row(
        modifier
            .clip(CircleShape)
            .background(if (selected) EchoColors.Violet else Color.White)
            .border(1.dp, if (selected) Color.Transparent else EchoColors.Stroke, CircleShape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, null, Modifier.size(16.dp), tint = if (selected) Color.White else EchoColors.Violet)
            Spacer(Modifier.width(6.dp))
        }
        Text(text, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = if (selected) Color.White else EchoColors.Ink, maxLines = 1, softWrap = false)
    }
}

@Composable
fun GradientButton(text: String, modifier: Modifier = Modifier, enabled: Boolean = true, onClick: () -> Unit) {
    Box(
        modifier
            .clip(CircleShape)
            .background(if (enabled) EchoColors.accent else Brush.horizontalGradient(listOf(EchoColors.Stroke, EchoColors.Stroke)))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 28.dp, vertical = 15.dp),
        contentAlignment = Alignment.Center,
    ) { Text(text, fontWeight = FontWeight.SemiBold, color = EchoColors.Ink) }
}

@Composable
fun SectionTitle(text: String, action: String? = null, onAction: (() -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 10.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text(text, style = MaterialTheme.typography.titleMedium)
        if (action != null && onAction != null) Text(action, color = EchoColors.Muted, fontSize = 14.sp, modifier = Modifier.clickable(onClick = onAction))
    }
}

fun memoryIcon(type: String): Pair<ImageVector, Color> = when (type) {
    "commitment" -> EchoIcons.Commitment to EchoColors.Violet
    "decision" -> EchoIcons.Decision to Color(0xFF3D8BFD)
    "object_location" -> EchoIcons.Place to EchoColors.Coral
    "idea" -> EchoIcons.Idea to Color(0xFFF2A93B)
    "learning" -> EchoIcons.Learning to EchoColors.Mint
    "event" -> EchoIcons.Event to Color(0xFF8E7CFF)
    "person_info" -> EchoIcons.Person to Color(0xFFE07BB3)
    "question" -> EchoIcons.Question to EchoColors.Muted
    "utterance" -> EchoIcons.Notes to EchoColors.Muted
    else -> EchoIcons.Bookmark to EchoColors.Lavender
}

fun memoryLabel(type: String) = when (type) {
    "object_location" -> "Where it is"
    "person_info" -> "About someone"
    "commitment" -> "Promise"
    "utterance" -> "Just now"
    else -> type.replaceFirstChar { it.uppercase() }
}

@Composable
fun MemoryRow(type: String, content: String, sub: String? = null, onClick: (() -> Unit)? = null) {
    val (icon, color) = memoryIcon(type)
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier).padding(vertical = 8.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(Modifier.size(34.dp).clip(CircleShape).background(color.copy(alpha = 0.14f)), contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = color, modifier = Modifier.size(18.dp))
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(content, style = MaterialTheme.typography.bodyMedium)
            if (sub != null) Text(sub, style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(top = 2.dp))
        }
    }
}

@Composable
fun EmptyHint(text: String) {
    Text(text, color = EchoColors.Muted, fontSize = 14.sp, modifier = Modifier.padding(vertical = 12.dp))
}
