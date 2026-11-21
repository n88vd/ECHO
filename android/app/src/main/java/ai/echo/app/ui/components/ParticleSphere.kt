package ai.echo.app.ui.components

import ai.echo.app.ui.theme.EchoColors
import android.os.SystemClock
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.withFrameMillis
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

enum class SphereMode { Idle, Listening, Speaking }

private val SPHERE_PALETTE = listOf(EchoColors.Sky, EchoColors.Lavender, EchoColors.Pink)

/**
 * A rotating 3D sphere of dots that swells and ripples with voice.
 * [level] is a raw RMS amplitude (0..~0.3 for speech); it is normalised and smoothed here.
 */
@Composable
fun ParticleSphere(size: Dp, level: Float = 0f, mode: SphereMode = SphereMode.Idle, modifier: Modifier = Modifier) {
    val count = when {
        size < 64.dp -> 270
        size < 120.dp -> 540
        else -> 960
    }
    val points = remember(count) { fibonacciSphere(count) }
    val latestLevel by rememberUpdatedState(level)
    var clock by remember { mutableLongStateOf(SystemClock.uptimeMillis()) }
    var energy by remember { mutableFloatStateOf(0f) }

    LaunchedEffect(Unit) {
        while (true) withFrameMillis {
            clock = SystemClock.uptimeMillis()
            val target = (latestLevel * 7f).coerceIn(0f, 1f)
            // Fast attack, slow release, so syllables pop and pauses settle.
            energy += (target - energy) * if (target > energy) 0.35f else 0.07f
        }
    }

    // One palette everywhere (sky -> lavender -> pink); mode only changes motion.
    val palette = SPHERE_PALETTE
    val spin = if (mode == SphereMode.Idle) 0.22f else 0.4f

    Canvas(modifier.size(size)) {
        val t = (clock % 600_000L) / 1000f
        val e = energy
        val c = center
        val breathe = 1f + 0.025f * sin(t * 2.4f)
        val radius = this.size.minDimension / 2f * 0.72f * breathe * (1f + 0.2f * e)
        val dotBase = this.size.minDimension / if (count > 600) 92f else 62f

        // Soft halo that brightens with voice.
        drawCircle(
            Brush.radialGradient(listOf(palette[1].copy(alpha = 0.10f + 0.22f * e), Color.Transparent), c, radius * 1.45f),
            radius * 1.45f, c,
        )

        val yaw = t * spin
        val tilt = 0.42f + 0.08f * sin(t * 0.5f)
        val cy = cos(yaw); val sy = sin(yaw); val ct = cos(tilt); val st = sin(tilt)
        val projected = ArrayList<FloatArray>(points.size)
        for (p in points) {
            // Ripple: travelling waves over the surface, amplified by voice energy.
            val wave = sin(p[1] * 5f + t * 5f) * cos(p[0] * 4f - t * 3.5f) + 0.5f * sin(p[2] * 6f + t * 7f)
            val r = radius * (1f + (0.03f + 0.22f * e) * wave)
            // Rotate around Y (yaw) then X (tilt).
            val x1 = p[0] * cy + p[2] * sy
            val z1 = -p[0] * sy + p[2] * cy
            val y2 = p[1] * ct - z1 * st
            val z2 = p[1] * st + z1 * ct
            projected += floatArrayOf(c.x + x1 * r, c.y + y2 * r, z2, p[1])
        }
        projected.sortBy { it[2] }
        for (q in projected) {
            val depth = (q[2] + 1f) / 2f // 0 = back, 1 = front
            val colorT = (q[3] + 1f) / 2f
            val color = if (colorT < 0.5f) lerp(palette[0], palette[1], colorT * 2f) else lerp(palette[1], palette[2], (colorT - 0.5f) * 2f)
            drawCircle(
                color = color,
                radius = dotBase * (0.45f + 0.75f * depth) * (1f + 0.35f * e),
                center = Offset(q[0], q[1]),
                alpha = (0.18f + 0.82f * depth).coerceIn(0f, 1f),
            )
        }
    }
}

/** Evenly spread unit vectors on a sphere (golden-angle spiral). */
private fun fibonacciSphere(n: Int): List<FloatArray> {
    val golden = (PI * (3.0 - sqrt(5.0))).toFloat()
    return List(n) { i ->
        val y = 1f - 2f * (i + 0.5f) / n
        val r = sqrt(1f - y * y)
        val th = golden * i
        floatArrayOf(cos(th) * r, y, sin(th) * r)
    }
}
