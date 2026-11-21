package ai.echo.app

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
import ai.echo.app.ui.screens.TimelineScreen
import ai.echo.app.ui.theme.EchoColors
import ai.echo.app.ui.theme.EchoTheme
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.ViewTimeline
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val app = application as EchoApp
        if (intent?.getBooleanExtra("resume_capture", false) == true && app.prefs.captureEnabledValue) CaptureService.refresh(this)
        setContent { EchoTheme { Root(app) } }
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
    Tab("home", "Home", Icons.Outlined.Home),
    Tab("ask", "Ask", Icons.Outlined.AutoAwesome),
    Tab("timeline", "Timeline", Icons.Outlined.ViewTimeline),
    Tab("settings", "Settings", Icons.Outlined.Settings),
)

@Composable
private fun Root(app: EchoApp) {
    val signedIn by app.session.signedIn.collectAsState()
    Box(Modifier.fillMaxSize().background(EchoColors.background)) {
        if (!signedIn) SignInScreen(app) else Main(app)
    }
}

@Composable
private fun Main(app: EchoApp) {
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val route = entry?.destination?.route
    LaunchedEffect(Unit) {
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { app.ensureDevice() }
        if (!app.prefs.onboarded) nav.navigate("onboarding")
    }
    Scaffold(
        containerColor = Color.Transparent,
        bottomBar = {
            if (tabs.any { it.route == route }) NavigationBar(containerColor = Color.White.copy(alpha = 0.92f)) {
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
        NavHost(nav, startDestination = "home", modifier = Modifier.padding(bottom = pad.calculateBottomPadding())) {
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
