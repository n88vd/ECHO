package ai.echo.app.ui.screens

import ai.echo.app.ui.theme.EchoIcons
import ai.echo.app.BuildConfig
import ai.echo.app.EchoApp
import ai.echo.app.capture.CaptureService
import ai.echo.app.ui.VoiceRecorder
import ai.echo.app.ui.components.ParticleSphere
import ai.echo.app.ui.components.SphereMode
import ai.echo.app.ui.components.GlassCard
import ai.echo.app.ui.components.GradientButton
import ai.echo.app.ui.theme.EchoColors
import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlinx.coroutines.launch
import java.io.File

@Composable
fun SignInScreen(app: EchoApp) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var showEmail by remember { mutableStateOf(false) }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }

    Column(
        Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(28.dp).verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(48.dp))
        Text("ECHO", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.clickable { showEmail = !showEmail })
        Spacer(Modifier.height(36.dp))
        ParticleSphere(220.dp)
        Spacer(Modifier.height(36.dp))
        Text("Your external memory", style = MaterialTheme.typography.displaySmall, textAlign = TextAlign.Center)
        Spacer(Modifier.height(12.dp))
        Text(
            "Ask about anything you've talked about: promises, ideas, where you kept things. In any Indian language.",
            color = EchoColors.Muted, textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(40.dp))
        if (busy) CircularProgressIndicator() else GradientButton("Continue with Google", Modifier.fillMaxWidth()) {
            busy = true; error = null
            scope.launch {
                runCatching {
                    require(BuildConfig.GOOGLE_WEB_CLIENT_ID.isNotBlank()) { "Google sign-in is not configured in this build" }
                    val option = GetGoogleIdOption.Builder()
                        .setServerClientId(BuildConfig.GOOGLE_WEB_CLIENT_ID)
                        .setFilterByAuthorizedAccounts(false)
                        .setAutoSelectEnabled(true)
                        .build()
                    val result = CredentialManager.create(context).getCredential(context as Activity, GetCredentialRequest.Builder().addCredentialOption(option).build())
                    val cred = result.credential
                    check(cred is CustomCredential && cred.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) { "Unexpected credential" }
                    app.api.signInGoogle(GoogleIdTokenCredential.createFrom(cred.data).idToken)
                }.onFailure { error = it.message ?: "Sign-in failed" }
                busy = false
            }
        }
        if (showEmail) {
            Spacer(Modifier.height(20.dp))
            OutlinedTextField(email, { email = it }, label = { Text("Email") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email))
            OutlinedTextField(password, { password = it }, label = { Text("Password") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                visualTransformation = PasswordVisualTransformation())
            Spacer(Modifier.height(12.dp))
            GradientButton("Sign in with email", Modifier.fillMaxWidth(), enabled = !busy && email.isNotBlank() && password.isNotBlank()) {
                busy = true; error = null
                scope.launch {
                    runCatching { app.api.signInPassword(email.trim(), password) }.onFailure { error = it.message ?: "Sign-in failed" }
                    busy = false
                }
            }
        }
        error?.let { Text(it, color = EchoColors.Coral, modifier = Modifier.padding(top = 16.dp), textAlign = TextAlign.Center) }
        Spacer(Modifier.height(24.dp))
        Text(
            "ECHO records speech only while you allow it, and you can delete any memory or all of your data at any time.",
            color = EchoColors.Faint, fontSize = 12.sp, textAlign = TextAlign.Center,
        )
    }
}

private val ENROL_PROMPT = """
    "Hi ECHO, this is my voice. I'm reading this so you can recognise me in conversations.
    I talk about my day, my work, my friends and family, and the things I want to remember.
    Please keep my memories private and help me recall them when I ask."
""".trimIndent()

@Composable
fun OnboardingScreen(app: EchoApp, onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    fun granted(p: String) = context.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED
    var mic by remember { mutableStateOf(granted(Manifest.permission.RECORD_AUDIO)) }
    var notif by remember { mutableStateOf(Build.VERSION.SDK_INT < 33 || granted(Manifest.permission.POST_NOTIFICATIONS)) }
    var loc by remember { mutableStateOf(granted(Manifest.permission.ACCESS_COARSE_LOCATION)) }
    var bt by remember { mutableStateOf(Build.VERSION.SDK_INT < 31 || granted(Manifest.permission.BLUETOOTH_CONNECT)) }
    var step by remember { mutableIntStateOf(0) }
    var enrolled by remember { mutableStateOf(false) }
    var recording by remember { mutableStateOf(false) }
    var enrolError by remember { mutableStateOf<String?>(null) }
    val recorder = remember { VoiceRecorder() }
    val level by recorder.level.collectAsState()

    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        mic = granted(Manifest.permission.RECORD_AUDIO)
        notif = Build.VERSION.SDK_INT < 33 || granted(Manifest.permission.POST_NOTIFICATIONS)
        loc = granted(Manifest.permission.ACCESS_COARSE_LOCATION)
        bt = Build.VERSION.SDK_INT < 31 || granted(Manifest.permission.BLUETOOTH_CONNECT)
    }

    Column(
        Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(24.dp).verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(24.dp))
        ParticleSphere(150.dp, level = level, mode = SphereMode.Listening)
        Spacer(Modifier.height(24.dp))
        if (step == 0) {
            Text("Activate ECHO", style = MaterialTheme.typography.displaySmall)
            Spacer(Modifier.height(8.dp))
            Text("ECHO listens for speech, drops silence on your phone, and turns conversations into memories you can ask about.",
                color = EchoColors.Muted, textAlign = TextAlign.Center)
            Spacer(Modifier.height(24.dp))
            GlassCard(Modifier.fillMaxWidth()) {
                PermRow("Microphone", "Required to capture speech", mic)
                PermRow("Notifications", "Listening status, promises and daily digest", notif)
                PermRow("Location (optional)", "Remember where conversations happened. Only while listening.", loc)
                PermRow("Nearby devices (optional)", "Use your Bluetooth earbuds' mic", bt)
            }
            Spacer(Modifier.height(24.dp))
            GradientButton(if (mic) "Continue" else "Allow access", Modifier.fillMaxWidth()) {
                if (!mic || !notif || !loc || !bt) {
                    val perms = buildList {
                        add(Manifest.permission.RECORD_AUDIO)
                        add(Manifest.permission.ACCESS_COARSE_LOCATION)
                        add(Manifest.permission.ACCESS_FINE_LOCATION)
                        if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
                        if (Build.VERSION.SDK_INT >= 31) add(Manifest.permission.BLUETOOTH_CONNECT)
                    }
                    if (!mic) launcher.launch(perms.toTypedArray()) else { launcher.launch(perms.toTypedArray()); step = 1 }
                } else step = 1
            }
        } else {
            Text("Teach ECHO your voice", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.height(8.dp))
            Text("So ECHO knows which promises are yours. Read this aloud (about 20 seconds):", color = EchoColors.Muted, textAlign = TextAlign.Center)
            Spacer(Modifier.height(16.dp))
            GlassCard(Modifier.fillMaxWidth()) { Text(ENROL_PROMPT, style = MaterialTheme.typography.bodyLarge) }
            Spacer(Modifier.height(20.dp))
            when {
                enrolled -> Text("Voice saved ✓", color = EchoColors.Mint, style = MaterialTheme.typography.titleMedium)
                recording -> GradientButton("Done reading", Modifier.fillMaxWidth()) { recorder.stopRequested = true }
                else -> GradientButton("Start recording", Modifier.fillMaxWidth()) {
                    recording = true; enrolError = null
                    scope.launch {
                        runCatching {
                            val f = recorder.record(File(context.cacheDir, "enrol.wav"), 30_000)
                            app.api.enrollVoice(f)
                            f.delete()
                        }.onSuccess { enrolled = true }.onFailure { enrolError = it.message }
                        recording = false
                    }
                }
            }
            enrolError?.let { Text(it, color = EchoColors.Coral, modifier = Modifier.padding(top = 12.dp), textAlign = TextAlign.Center) }
            Spacer(Modifier.height(28.dp))
            GradientButton(if (enrolled) "Start listening" else "Skip for now", Modifier.fillMaxWidth(), enabled = !recording) {
                app.prefs.onboarded = true
                if (mic) CaptureService.start(context)
                onDone()
            }
        }
    }
}

@Composable
private fun PermRow(title: String, sub: String, ok: Boolean) {
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Icon(if (ok) EchoIcons.CheckCircle else EchoIcons.Unchecked, null, tint = if (ok) EchoColors.Mint else EchoColors.Faint, modifier = Modifier.size(22.dp))
        Column {
            Text(title, style = MaterialTheme.typography.titleMedium, fontSize = 15.sp)
            Text(sub, style = MaterialTheme.typography.labelMedium)
        }
    }
}
