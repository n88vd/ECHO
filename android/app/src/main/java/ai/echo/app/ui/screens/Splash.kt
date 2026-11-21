package ai.echo.app.ui.screens

import ai.echo.app.ui.theme.EchoColors
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/*
 * Geometry of the launcher/splash logo. MUST stay identical to android/icons/gen_logo.py so the first
 * Compose frame is pixel-identical to the static system splash icon (all values are in the 108-unit
 * adaptive-icon viewport, expressed as fractions of the icon canvas).
 */
private const val LOGO_DOTS = 220
private const val LOGO_YAW = 0.55f
private const val LOGO_TILT = 0.45f
private const val LOGO_RADIUS = 25f / 108f
private const val LOGO_DOT_MIN = 0.7f / 108f
private const val LOGO_DOT_MAX = 2.1f / 108f
private const val LOGO_HALO = 36f / 108f

/** The system splash paints this solid colour (@color/echo_bg); we start from it and blend to the gradient. */
private val SplashBg = Color(0xFFF7F7FB)

/**
 * Animated splash. On Android 12+ [icon] is the on-screen bounds of the system splash icon, so the
 * sphere is drawn exactly over it; its first frame matches the static logo and motion eases in from
 * there, so the hand-off is invisible. Time only advances once [running] (the system splash is gone). [fromStatic] is false where there is no system logo (Android
 * 10/11), in which case the sphere fades in instead.
 */
@Composable
fun SplashScreen(icon: IntRect?, fromStatic: Boolean, running: Boolean) {
    val isRunning by rememberUpdatedState(running)
    val points = remember { logoSphere(LOGO_DOTS) }
    var elapsed by remember { mutableFloatStateOf(0f) } // seconds since first frame
    var yaw by remember { mutableFloatStateOf(LOGO_YAW) }

    LaunchedEffect(Unit) {
        var last = -1L
        while (true) withFrameNanos { now ->
            // Frozen on the logo frame while the system splash still covers us.
            if (last >= 0 && isRunning) {
                val dt = (now - last) / 1e9f
                elapsed += dt
                yaw += SPIN * ease(elapsed, HOLD, RAMP) * dt
            }
            last = now
        }
    }

    val motion = ease(elapsed, HOLD, RAMP)           // 0 = frozen logo, 1 = fully alive
    val sphereAlpha = if (fromStatic) 1f else ease(elapsed, 0f, 0.35f)
    val wordAlpha = ease(elapsed, 0.35f, 0.5f)

    val view = LocalView.current
    val density = LocalDensity.current
    val root = remember(view) { IntArray(2).also { view.getLocationOnScreen(it) } }
    // iconView is the 192dp mask circle; the logo itself is drawn on the 288dp canvas centred on it.
    val canvasPx = icon?.let { it.width * ICON_CANVAS_OVER_MASK } ?: with(density) { FALLBACK_ICON.toPx() }

    Box(Modifier.fillMaxSize().background(SplashBg)) {
        // Brand gradient fades in once the sphere is moving, so frame 0 is the plain splash colour.
        Box(Modifier.fillMaxSize().alpha(motion).background(EchoColors.background))

        val sphereModifier = if (icon != null) {
            Modifier.offset { IntOffset((icon.center.x - root[0] - canvasPx / 2).toInt(), (icon.center.y - root[1] - canvasPx / 2).toInt()) }
        } else {
            Modifier.align(Alignment.Center)
        }
        Canvas(sphereModifier.size(with(density) { canvasPx.toDp() }).alpha(sphereAlpha)) {
            val s = size.minDimension
            val c = center
            val t = elapsed
            val breathe = 1f + 0.02f * motion * sin(t * 2.6f)
            val radius = s * LOGO_RADIUS * breathe
            val halo = s * LOGO_HALO
            drawCircle(Brush.radialGradient(listOf(Color(0x40B9A8FF), Color(0x00B9A8FF)), c, halo), halo, c)

            val cy = cos(yaw); val sy = sin(yaw); val ct = cos(LOGO_TILT); val st = sin(LOGO_TILT)
            val drawn = ArrayList<FloatArray>(points.size)
            for (p in points) {
                val wave = sin(p[1] * 5f + t * 4f) * cos(p[0] * 4f - t * 3f)
                val r = radius * (1f + 0.045f * motion * wave)
                val x1 = p[0] * cy + p[2] * sy
                val z1 = -p[0] * sy + p[2] * cy
                val y2 = p[1] * ct - z1 * st
                val z2 = p[1] * st + z1 * ct
                drawn += floatArrayOf(c.x + x1 * r, c.y + y2 * r, z2, p[1])
            }
            drawn.sortBy { it[2] }
            for (q in drawn) {
                val depth = (q[2] + 1f) / 2f
                val ct2 = (q[3] + 1f) / 2f
                val color = if (ct2 < 0.5f) lerp(EchoColors.Sky, EchoColors.Lavender, ct2 * 2f) else lerp(EchoColors.Lavender, EchoColors.Pink, (ct2 - 0.5f) * 2f)
                drawCircle(color, s * (LOGO_DOT_MIN + (LOGO_DOT_MAX - LOGO_DOT_MIN) * depth), Offset(q[0], q[1]), alpha = 0.22f + 0.78f * depth)
            }
        }

        // Wordmark sits under the sphere and rises in after the logo starts moving.
        val below = with(density) { (if (icon != null) icon.center.y - root[1] else null)?.toDp() }
        Text(
            "ECHO", style = MaterialTheme.typography.headlineMedium, letterSpacing = 6.sp,
            modifier = (if (below != null) Modifier.align(Alignment.TopCenter).offset(y = below + 92.dp) else Modifier.align(Alignment.Center).offset(y = 92.dp))
                .graphicsLayer { alpha = wordAlpha; translationY = (1f - wordAlpha) * 10.dp.toPx() },
        )
    }
}

private const val HOLD = 0.12f      // seconds the frozen logo is held before moving
private const val RAMP = 0.9f       // seconds to ease up to full motion
private const val SPIN = 0.55f      // rad/s once fully alive
private val FALLBACK_ICON = 288.dp  // Android 12 splash icon canvas (no icon background)
private const val ICON_CANVAS_OVER_MASK = 288f / 192f

/** Smoothstep from 0 to 1 over [start, start + span] seconds. */
private fun ease(t: Float, start: Float, span: Float): Float {
    val x = ((t - start) / span).coerceIn(0f, 1f)
    return x * x * (3f - 2f * x)
}

/** Unrotated Fibonacci sphere; rotation is applied per frame (same spiral as gen_logo.py). */
private fun logoSphere(n: Int): List<FloatArray> {
    val golden = (PI * (3.0 - sqrt(5.0))).toFloat()
    return List(n) { i ->
        val y = 1f - 2f * (i + 0.5f) / n
        val r = sqrt(1f - y * y)
        floatArrayOf(cos(golden * i) * r, y, sin(golden * i) * r)
    }
}
