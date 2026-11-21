package ai.echo.app.ui.components

import ai.echo.app.ui.theme.EchoColors
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bookmark
import androidx.compose.material.icons.outlined.Event
import androidx.compose.material.icons.outlined.Gavel
import androidx.compose.material.icons.outlined.Handshake
import androidx.compose.material.icons.automirrored.outlined.HelpOutline
import androidx.compose.material.icons.outlined.Lightbulb
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Place
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.automirrored.outlined.Notes
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.withFrameMillis
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import android.os.SystemClock
import kotlin.math.cos
import kotlin.math.sin

private const val TWO_PI = (2 * Math.PI).toFloat()

/** Seamless, never-restarting orb: driven by a shared monotonic clock with whole-cycle periods. */
@Composable
fun EchoOrb(size: Dp, level: Float = 0f, active: Boolean = true, modifier: Modifier = Modifier) {
    val clock by produceState(SystemClock.uptimeMillis()) {
        while (true) withFrameMillis { value = SystemClock.uptimeMillis() }
    }
    val pulse by animateFloatAsState((level * 6f).coerceIn(0f, 0.18f), tween(120), label = "pulse")
    val activeAmt by animateFloatAsState(if (active) 1f else 0f, tween(600), label = "active")
    val phase = (clock % ORB_PERIOD_MS) / ORB_PERIOD_MS.toFloat() * TWO_PI
    val breathe = 0.995f + 0.035f * sin((clock % BREATHE_PERIOD_MS) / BREATHE_PERIOD_MS.toFloat() * TWO_PI)
    val scale = 0.94f + (breathe - 0.94f + pulse) * activeAmt
    val alpha = 0.45f + 0.55f * activeAmt
    Canvas(modifier.size(size)) {
        val r = this.size.minDimension / 2 * scale
        val c = center
        drawCircle(Brush.radialGradient(listOf(EchoColors.Lavender.copy(alpha = 0.35f * alpha), Color.Transparent), c, r * 1.35f), r * 1.35f, c)
        drawCircle(Brush.linearGradient(listOf(EchoColors.Sky, EchoColors.Lavender, EchoColors.Pink), Offset(c.x - r, c.y - r), Offset(c.x + r, c.y + r)), r, c, alpha = alpha)
        val blobs = listOf(Triple(EchoColors.Peach, 0f, 1), Triple(EchoColors.Violet, TWO_PI / 3, 2), Triple(Color.White, 2 * TWO_PI / 3, 1))
        for ((color, off, k) in blobs) {
            val bc = Offset(c.x + cos(phase + off) * r * 0.35f, c.y + sin(k * phase + off) * r * 0.3f)
            drawCircle(Brush.radialGradient(listOf(color.copy(alpha = 0.75f * alpha), Color.Transparent), bc, r * 0.75f), r * 0.75f, bc)
        }
        val hl = Offset(c.x - r * 0.35f, c.y - r * 0.4f)
        drawCircle(Brush.radialGradient(listOf(Color.White.copy(alpha = 0.55f), Color.Transparent), hl, r * 0.5f), r * 0.5f, hl)
    }
}

private const val ORB_PERIOD_MS = 9_000L
private const val BREATHE_PERIOD_MS = 2_600L

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
    "commitment" -> Icons.Outlined.Handshake to EchoColors.Violet
    "decision" -> Icons.Outlined.Gavel to Color(0xFF3D8BFD)
    "object_location" -> Icons.Outlined.Place to EchoColors.Coral
    "idea" -> Icons.Outlined.Lightbulb to Color(0xFFF2A93B)
    "learning" -> Icons.Outlined.School to EchoColors.Mint
    "event" -> Icons.Outlined.Event to Color(0xFF8E7CFF)
    "person_info" -> Icons.Outlined.Person to Color(0xFFE07BB3)
    "question" -> Icons.AutoMirrored.Outlined.HelpOutline to EchoColors.Muted
    "utterance" -> Icons.AutoMirrored.Outlined.Notes to EchoColors.Muted
    else -> Icons.Outlined.Bookmark to EchoColors.Lavender
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
