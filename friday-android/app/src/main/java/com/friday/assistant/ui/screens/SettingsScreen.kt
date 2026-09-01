package com.friday.assistant.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CutCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.friday.assistant.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    currentHost: String,
    currentPort: String,
    currentToken: String,
    connected: Boolean,
    onBack: () -> Unit,
    onSave: (String, String, String) -> Unit,
) {
    var host by remember { mutableStateOf(currentHost) }
    var port by remember { mutableStateOf(currentPort) }
    var token by remember { mutableStateOf(currentToken) }
    var saved by remember { mutableStateOf(false) }
    val validPort = port.toIntOrNull() in 1..65535
    val canSave = host.isNotBlank() && validPort && token.isNotBlank()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("SETTINGS", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = White)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Bg),
            )
        },
        containerColor = Bg,
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .imePadding()
                .padding(24.dp),
        ) {
            // Connection status
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(10.dp)
                        .background(if (connected) Success else Danger, CutCornerShape(2.dp))
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    if (connected) "Connected" else "Disconnected",
                    color = if (connected) Success else Danger,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                )
            }

            Spacer(Modifier.height(24.dp))

            Text("SERVER IP", color = Dim, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(
                value = host,
                onValueChange = { host = it; saved = false },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("192.168.1.100", color = Dim) },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = White,
                    unfocusedTextColor = White,
                    cursorColor = Cyan,
                    focusedBorderColor = Cyan,
                    unfocusedBorderColor = Line,
                ),
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
            )

            Spacer(Modifier.height(16.dp))

            Text("PORT", color = Dim, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(
                value = port,
                onValueChange = { port = it; saved = false },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("8000", color = Dim) },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = White,
                    unfocusedTextColor = White,
                    cursorColor = Cyan,
                    focusedBorderColor = Cyan,
                    unfocusedBorderColor = Line,
                ),
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                isError = port.isNotBlank() && !validPort,
                supportingText = if (port.isNotBlank() && !validPort) ({ Text("Use a port from 1 to 65535") }) else null,
                shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
            )

            Spacer(Modifier.height(16.dp))

            Text("PAIRING TOKEN", color = Dim, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(
                value = token,
                onValueChange = { token = it.trim(); saved = false },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("Copy from Windows CONFIG", color = Dim) },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = White,
                    unfocusedTextColor = White,
                    cursorColor = Cyan,
                    focusedBorderColor = Cyan,
                    unfocusedBorderColor = Line,
                ),
                singleLine = true,
                shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
            )

            Spacer(Modifier.height(24.dp))

            Button(
                onClick = {
                    onSave(host.trim(), port.trim(), token.trim())
                    saved = true
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = canSave,
                colors = ButtonDefaults.buttonColors(containerColor = Cyan, contentColor = Bg),
                shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
            ) {
                Icon(Icons.Filled.Save, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("SAVE & CONNECT", fontWeight = FontWeight.Bold)
            }

            if (saved) {
                Spacer(Modifier.height(8.dp))
                Text("Saved! Reconnecting...", color = Cyan, fontSize = 12.sp)
            }

            Spacer(Modifier.height(32.dp))

            // Help
            Surface(
                color = Surface,
                shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text("HOW TO CONNECT", color = Cyan, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("1. Make sure phone & laptop are on same Wi-Fi", color = Dim, fontSize = 12.sp)
                    Text("2. Find your laptop IP (check F.R.I.D.A.Y. console)", color = Dim, fontSize = 12.sp)
                    Text("3. Enter the laptop IP, port, and pairing token", color = Dim, fontSize = 12.sp)
                    Text("4. Tap SAVE & CONNECT", color = Dim, fontSize = 12.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("VOICE:", color = White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                    Text("Tap the red record button to speak through your phone mic. Tap again to stop. F.R.I.D.A.Y. will transcribe and respond.", color = Dim, fontSize = 11.sp)
                }
            }
        }
    }
}
