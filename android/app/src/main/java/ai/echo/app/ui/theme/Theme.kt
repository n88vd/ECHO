package ai.echo.app.ui.theme

import ai.echo.app.R
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

object EchoColors {
    val Bg = Color(0xFFF7F7FB)
    val Ink = Color(0xFF14142B)
    val Muted = Color(0xFF6E6E87)
    val Faint = Color(0xFFA9A9BF)
    val Violet = Color(0xFF6C63FF)
    val Lavender = Color(0xFFB9A8FF)
    val Sky = Color(0xFF9BD2FF)
    val Pink = Color(0xFFFFB3CC)
    val Peach = Color(0xFFFFD6A5)
    val Mint = Color(0xFF7ED6B4)
    val Coral = Color(0xFFFF6B6B)
    val Glass = Color(0xD9FFFFFF)
    val Stroke = Color(0x1A14142B)
    val background = Brush.verticalGradient(listOf(Color(0xFFF1EEFF), Color(0xFFF7F7FB), Color(0xFFFFF1F6)))
    val accent = Brush.horizontalGradient(listOf(Color(0xFFE6DEFF), Color(0xFFFFDDE9)))
}

private val scheme = lightColorScheme(
    primary = EchoColors.Violet,
    onPrimary = Color.White,
    secondary = EchoColors.Lavender,
    background = EchoColors.Bg,
    surface = Color.White,
    onSurface = EchoColors.Ink,
    onBackground = EchoColors.Ink,
    error = EchoColors.Coral,
)

/** Overused Grotesk by RandomMaerks (SIL OFL 1.1). Latin/Greek/Cyrillic; Indic scripts fall back to system fonts. */
val Grotesk = FontFamily(
    Font(R.font.overused_grotesk_regular, FontWeight.Normal),
    Font(R.font.overused_grotesk_medium, FontWeight.Medium),
    Font(R.font.overused_grotesk_semibold, FontWeight.SemiBold),
    Font(R.font.overused_grotesk_bold, FontWeight.Bold),
)

private val base = Typography()

private fun TextStyle.grotesk() = copy(fontFamily = Grotesk)

private val type = Typography(
    displayLarge = base.displayLarge.grotesk(),
    displayMedium = base.displayMedium.grotesk(),
    displaySmall = TextStyle(fontFamily = Grotesk, fontSize = 32.sp, lineHeight = 38.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.8).sp, color = EchoColors.Ink),
    headlineLarge = base.headlineLarge.grotesk(),
    headlineMedium = base.headlineMedium.grotesk(),
    headlineSmall = TextStyle(fontFamily = Grotesk, fontSize = 24.sp, lineHeight = 30.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.4).sp, color = EchoColors.Ink),
    titleLarge = base.titleLarge.grotesk(),
    titleMedium = TextStyle(fontFamily = Grotesk, fontSize = 17.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.2).sp, color = EchoColors.Ink),
    titleSmall = base.titleSmall.grotesk(),
    bodyLarge = TextStyle(fontFamily = Grotesk, fontSize = 16.sp, lineHeight = 23.sp, color = EchoColors.Ink),
    bodyMedium = TextStyle(fontFamily = Grotesk, fontSize = 14.sp, lineHeight = 20.sp, color = EchoColors.Ink),
    bodySmall = base.bodySmall.grotesk(),
    labelLarge = base.labelLarge.grotesk(),
    labelMedium = TextStyle(fontFamily = Grotesk, fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium, color = EchoColors.Muted),
    labelSmall = base.labelSmall.grotesk(),
)

@Composable
fun EchoTheme(content: @Composable () -> Unit) = MaterialTheme(colorScheme = scheme, typography = type, content = content)
