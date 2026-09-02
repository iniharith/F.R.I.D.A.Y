package com.friday.assistant

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.*
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.friday.assistant.ui.screens.ChatScreen
import com.friday.assistant.ui.screens.DashboardScreen
import com.friday.assistant.ui.screens.QrScannerScreen
import com.friday.assistant.ui.screens.SettingsScreen
import com.friday.assistant.ui.theme.FridayTheme
import com.friday.assistant.viewmodel.FridayViewModel

class MainActivity : ComponentActivity() {
    private var incomingIntent by mutableStateOf<Intent?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        incomingIntent = intent
        setContent {
            FridayTheme {
                val vm: FridayViewModel = viewModel()
                val ui by vm.ui.collectAsState()
                val nav = rememberNavController()

                LaunchedEffect(incomingIntent) {
                    incomingIntent?.data?.let { uri ->
                        val pairing = validatePairing(uri)
                        if (pairing != null) {
                            vm.saveSettings(pairing.host, pairing.port.toString(), pairing.token)
                            vm.setPairingStatus("Paired with ${pairing.host}:${pairing.port}. Connecting...")
                            nav.navigate("dashboard") { launchSingleTop = true }
                        } else if (uri.scheme != null) {
                            vm.setPairingStatus("Invalid pairing link. Scan a new QR code or use Manual setup.")
                            nav.navigate("settings") { launchSingleTop = true }
                        }
                    }
                    incomingIntent = null
                }

                NavHost(navController = nav, startDestination = "dashboard") {
                    composable("dashboard") {
                        DashboardScreen(
                            ui = ui,
                            onSetMicActive = vm::setMicActive,
                            onSetMode = vm::setMode,
                            onOpenChat = { nav.navigate("chat") },
                            onOpenSettings = { nav.navigate("settings") },
                        )
                    }
                    composable("chat") {
                        ChatScreen(
                            ui = ui,
                            onSend = vm::sendChat,
                            onSetMicActive = vm::setMicActive,
                            onStop = vm::stop,
                            onToggleRecord = vm::toggleRecord,
                            onApprove = vm::approve,
                            onDeny = vm::deny,
                            onDismissError = vm::dismissError,
                            onDismissGuardian = vm::dismissGuardian,
                            onFeedback = vm::sendFeedback,
                            onOpenSettings = { nav.navigate("settings") },
                            onOpenDashboard = { nav.navigate("dashboard") { popUpTo("dashboard") } },
                        )
                    }
composable("settings") {
                        SettingsScreen(
                            ui = ui,
                            onBack = { nav.popBackStack() },
                            onSave = vm::saveSettings,
                            onSetMode = vm::setMode,
                            onSetTuning = vm::setTuning,
                            onScanQr = { nav.navigate("scan") },
                        )
                    }
                    composable("scan") {
                        QrScannerScreen(
                            onBack = { nav.popBackStack() },
                            onPaired = { host, port, token ->
                                vm.saveSettings(host, port, token)
                                vm.setPairingStatus("Paired with $host:$port. Connecting...")
                                nav.navigate("dashboard") { launchSingleTop = true; popUpTo("dashboard") }
                            },
                        )
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        incomingIntent = intent
    }

    private data class Pairing(val host: String, val port: Int, val token: String)

    private fun validatePairing(uri: Uri): Pairing? {
        if (uri.scheme != "friday" || uri.host != "pair") return null
        val host = uri.getQueryParameter("host")?.trim().orEmpty()
        val port = uri.getQueryParameter("port")?.toIntOrNull()
        val token = uri.getQueryParameter("token")?.trim().orEmpty()
        if (host.isBlank() || host == "0.0.0.0" || port !in 1..65535 || token.isBlank()) return null
        return Pairing(host, port!!, token)
    }
}
