package com.friday.assistant

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
import com.friday.assistant.ui.screens.SettingsScreen
import com.friday.assistant.ui.theme.FridayTheme
import com.friday.assistant.viewmodel.FridayViewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            FridayTheme {
                val vm: FridayViewModel = viewModel()
                val ui by vm.ui.collectAsState()
                val nav = rememberNavController()

                NavHost(navController = nav, startDestination = "chat") {
                    composable("chat") {
                        ChatScreen(
                            ui = ui,
                            onSend = vm::sendChat,
                            onToggleMic = vm::toggleMic,
                            onStop = vm::stop,
                            onToggleRecord = vm::toggleRecord,
                            onApprove = vm::approve,
                            onDeny = vm::deny,
                            onDismissError = vm::dismissError,
                            onDismissGuardian = vm::dismissGuardian,
                            onFeedback = vm::sendFeedback,
                            onOpenSettings = { nav.navigate("settings") },
                        )
                    }
                    composable("settings") {
                        SettingsScreen(
                            currentHost = ui.host,
                            currentPort = ui.port,
                            currentToken = ui.token,
                            connected = ui.connected,
                            onBack = { nav.popBackStack() },
                            onSave = vm::saveSettings,
                        )
                    }
                }
            }
        }
    }
}
