package ai.echo.app

import ai.echo.app.ui.theme.EchoIcons
import ai.echo.app.capture.CaptureService
import ai.echo.app.capture.SyncWorker
import ai.echo.app.capture.UploadWorker
import ai.echo.app.ui.screens.AskScreen
import ai.echo.app.ui.screens.ConversationScreen
import ai.echo.app.ui.screens.HomeScreen
import ai.echo.app.ui.screens.MemoryDetailScreen
import ai.echo.app.ui.screens.OnboardingScreen
import ai.echo.app.ui.screens.SettingsScreen
import ai.echo.app.ui.screens.SignInScreen
import ai.echo.app.ui.screens.SplashScreen
import ai.echo.app.ui.screens.TimelineScreen
import ai.echo.app.ui.theme.EchoColors
import ai.echo.app.ui.theme.EchoTheme
import android.os.Build
import android.os.Bundle
import android.view.Choreographer
import androidx.annotation.RequiresApi
import androidx.compose.animation.scaleOut
import androidx.compose.ui.unit.IntRect
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeOut
import kotlinx.coroutines.delay
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController

class MainActivity : ComponentActivity() {
    /** Screen bounds of the Android 12+ system splash icon, so the animated splash can sit exactly on it. */
    private val splashIcon = mutableStateOf<IntRect?>(null)
    /** True once the system splash is gone (always true below Android 12, which has none). */
    private val splashRevealed = mutableStateOf(Build.VERSION.SDK_INT < 31)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (Build.VERSION.SDK_INT >= 31) handOffSystemSplash()
        val app = application as EchoApp
        if (intent?.getBooleanExtra("resume_capture", false) == true && app.prefs.captureEnabledValue) CaptureService.refresh(this)
        setContent { EchoTheme { Root(app, splashIcon.value, splashRevealed.value, fromStatic = Build.VERSION.SDK_INT >= 31) } }
    }

    /**
     * Keep the static system splash up until Compose has drawn the identical first frame of the animated
     * splash underneath it, then drop it with no exit animation, so the user never sees a switch.
     */
    @RequiresApi(31)
    private fun handOffSystemSplash() {
        splashScreen.setOnExitAnimationListener { view ->
            view.iconView?.takeIf { it.width > 0 }?.let { icon ->
                val loc = IntArray(2).also { icon.getLocationOnScreen(it) }
                splashIcon.value = IntRect(loc[0], loc[1], loc[0] + icon.width, loc[1] + icon.height)
            }
            // Two frames: one to recompose at the icon's exact bounds, one to be sure it is on screen.
            val choreographer = Choreographer.getInstance()
            choreographer.postFrameCallback { choreographer.postFrameCallback { view.remove(); splashRevealed.value = true } }
        }
    }

    override fun onResume() {
        super.onResume()
        val app = application as EchoApp
        if (app.session.signedIn.value) {
            CaptureService.refresh(this)
            if (app.outbox.count() > 0) UploadWorker.enqueue(this)
            SyncWorker.runNow(this)
        }
    }
}

private data class Tab(val route: String, val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector)

private val tabs = listOf(
    Tab("home", "Home", EchoIcons.Home),
    Tab("ask", "Ask", EchoIcons.Ask),
    Tab("timeline", "Timeline", EchoIcons.Timeline),
    Tab("settings", "Settings", EchoIcons.Settings),
)

private const val SPLASH_MS = 1_800L
private const val SPLASH_HANDOFF_TIMEOUT_MS = 2_500L

@Composable
private fun Root(app: EchoApp, splashIcon: IntRect?, revealed: Boolean, fromStatic: Boolean) {
    val signedIn by app.session.signedIn.collectAsState()
    var splash by rememberSaveable { mutableStateOf(true) }
    // Safety net in case the system never hands over (e.g. a launch path without a system splash).
    var timedOut by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { delay(SPLASH_HANDOFF_TIMEOUT_MS); timedOut = true }
    val running = revealed || timedOut
    // The animation and its timer only start once the user can actually see them.
    LaunchedEffect(running) { if (running) { delay(SPLASH_MS); splash = false } }
    Box(Modifier.fillMaxSize().background(EchoColors.background)) {
        if (!signedIn) SignInScreen(app) else Main(app)
        AnimatedVisibility(splash, enter = EnterTransition.None, exit = fadeOut(tween(500)) + scaleOut(tween(500), targetScale = 1.08f)) {
            SplashScreen(splashIcon, fromStatic, running)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Main(app: EchoApp) {
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val route = entry?.destination?.route
    LaunchedEffect(Unit) {
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { app.ensureDevice() }
        if (!app.prefs.onboarded) nav.navigate("onboarding")
    }
    // Hide the tab bar while typing so the input sits directly on the keyboard.
    val imeOpen = WindowInsets.isImeVisible
    Scaffold(
        containerColor = Color.Transparent,
        bottomBar = {
            if (!imeOpen && tabs.any { it.route == route }) NavigationBar(containerColor = Color.White.copy(alpha = 0.92f)) {
                tabs.forEach { t ->
                    NavigationBarItem(
                        selected = route == t.route,
                        onClick = { nav.navigate(t.route) { popUpTo("home") { saveState = true }; launchSingleTop = true; restoreState = true } },
                        icon = { Icon(t.icon, t.label) },
                        label = { Text(t.label) },
                        colors = NavigationBarItemDefaults.colors(selectedIconColor = EchoColors.Violet, indicatorColor = EchoColors.Lavender.copy(alpha = 0.3f)),
                    )
                }
            }
        },
    ) { pad ->
        NavHost(nav, startDestination = "home", modifier = Modifier.padding(bottom = pad.calculateBottomPadding()).consumeWindowInsets(PaddingValues(bottom = pad.calculateBottomPadding()))) {
            composable("home") { HomeScreen(app, onAsk = { nav.go("ask") }, onMemory = { nav.navigate("memory/$it") }, onTimeline = { nav.go("timeline") }, onOnboard = { nav.navigate("onboarding") }) }
            composable("ask") { AskScreen(app) { nav.navigate("memory/$it") } }
            composable("timeline") { TimelineScreen(app, onConversation = { nav.navigate("conversation/$it") }, onMemory = { nav.navigate("memory/$it") }) }
            composable("settings") { SettingsScreen(app) { nav.navigate("onboarding") } }
            composable("onboarding") { OnboardingScreen(app) { nav.popBackStack("home", inclusive = false) } }
            composable("memory/{id}") { b ->
                MemoryDetailScreen(app, b.arguments?.getString("id")!!, onBack = { nav.popBackStack() },
                    onConversation = { nav.navigate("conversation/$it") }, onMemory = { nav.navigate("memory/$it") })
            }
            composable("conversation/{id}") { b ->
                ConversationScreen(app, b.arguments?.getString("id")!!, onBack = { nav.popBackStack() }, onMemory = { nav.navigate("memory/$it") })
            }
        }
    }
}

private fun NavHostController.go(route: String) = navigate(route) { popUpTo("home") { saveState = true }; launchSingleTop = true; restoreState = true }
