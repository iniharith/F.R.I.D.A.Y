package com.friday.assistant.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CutCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.Save
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.friday.assistant.ui.theme.*
import com.friday.assistant.viewmodel.FridayUiState
import kotlin.math.roundToInt

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    ui: FridayUiState,
    onBack: () -> Unit,
    onSave: (String, String, String) -> Unit,
    onSetMode: (String) -> Unit,
    onSetTuning: (Double, Double, Int, Int) -> Unit,
    onScanQr: () -> Unit,
) {
    var host by remember { mutableStateOf(ui.host) }
    var port by remember { mutableStateOf(ui.port) }
    var token by remember { mutableStateOf(ui.token) }
    var saved by remember { mutableStateOf(false) }
    var temperature by remember { mutableFloatStateOf(ui.temperature.toFloat()) }
    var topP by remember { mutableFloatStateOf(ui.topP.toFloat()) }
    var maxTokens by remember { mutableFloatStateOf(ui.maxNewTokens.toFloat()) }
    var contextTurns by remember { mutableFloatStateOf(ui.contextTurns.toFloat()) }

    LaunchedEffect(ui.host, ui.port, ui.token) {
        host = ui.host
        port = ui.port
        token = ui.token
    }
    LaunchedEffect(ui.temperature, ui.topP, ui.maxNewTokens, ui.contextTurns) {
        temperature = ui.temperature.toFloat()
        topP = ui.topP.toFloat()
        maxTokens = ui.maxNewTokens.toFloat()
        contextTurns = ui.contextTurns.toFloat()
    }

    val validPort = port.toIntOrNull() in 1..65535
    val canSave = host.isNotBlank() && host.trim() != "0.0.0.0" && validPort && token.isNotBlank()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("SETTINGS", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold) },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = White) } },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Bg),
            )
        },
        containerColor = Bg,
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).imePadding().padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text("CONNECTION", color = Cyan, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            Surface(
                color = Surface,
                border = BorderStroke(1.dp, Line),
                shape = CutCornerShape(topEnd = 14.dp, bottomStart = 8.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                    Text("Pair the app to your laptop", color = White, fontWeight = FontWeight.Bold)
                    Text("Tap to open the in-app scanner, or use your phone's camera on the URI. Like WhatsApp, no typing is needed.", color = Dim, fontSize = 12.sp)
                    Button(
                        onClick = onScanQr,
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = Cyan, contentColor = Bg),
                        shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
                    ) {
                        Icon(Icons.Filled.CameraAlt, null)
                        Spacer(Modifier.width(8.dp))
                        Text("SCAN QR CODE", fontWeight = FontWeight.Bold)
                    }
                    StatusRow(ui.connected)
                    Text("Paired host: ${ui.host}:${ui.port}", color = Cyan, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                    ui.pairingStatus?.let { Text(it, color = if (it.startsWith("Invalid")) Danger else Success, fontSize = 12.sp) }
                }
            }

            Text("MANUAL SETUP FALLBACK", color = Amber, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            ConnectionField("HOST / LAPTOP IP", host, { host = it; saved = false }, "192.168.1.100")
            ConnectionField(
                "PORT", port, { port = it.filter(Char::isDigit); saved = false }, "8000",
                keyboardType = KeyboardType.Number,
                isError = port.isNotBlank() && !validPort,
            )
            Text("PAIRING TOKEN", color = Dim, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            OutlinedTextField(
                value = token,
                onValueChange = { token = it.trim(); saved = false },
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text("Token from Windows CONFIG", color = Dim) },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                colors = fridayFieldColors(),
                shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
            )
            Button(
                onClick = { onSave(host.trim(), port.trim(), token.trim()); saved = true },
                modifier = Modifier.fillMaxWidth(),
                enabled = canSave,
                colors = ButtonDefaults.buttonColors(containerColor = Cyan, contentColor = Bg),
                shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
            ) {
                Icon(Icons.Filled.Save, null)
                Spacer(Modifier.width(8.dp))
                Text("SAVE & CONNECT", fontWeight = FontWeight.Bold)
            }
            if (saved) Text("Saved. Reconnecting...", color = Cyan, fontSize = 12.sp)

            HorizontalDivider(color = Line, modifier = Modifier.padding(vertical = 6.dp))
            Text("MODEL & REASONING", color = Cyan, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            Text("Selected: ${ui.selectedMode.uppercase()}  //  Effective: ${ui.effectiveMode.uppercase()}", color = White, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ModeSelector("LOCAL", "local", ui, onSetMode, Modifier.weight(1f))
                ModeSelector("OPENROUTER", "openrouter", ui, onSetMode, Modifier.weight(1f))
            }
            Text("Local: ${ui.localModel.ifBlank { "Not reported" }}", color = Dim, fontSize = 12.sp)
            Text("Cloud: ${ui.cloudModel.ifBlank { "Not reported" }}", color = Dim, fontSize = 12.sp)

            TuningSlider("TEMPERATURE", temperature, 0f..2f, 19, ui.connected, { "%.1f".format(it) }) { temperature = it }
            TuningSlider("TOP-P", topP, 0.1f..1f, 17, ui.connected, { "%.2f".format(it) }) { topP = it }
            TuningSlider("MAX TOKENS", maxTokens, 64f..2048f, 0, ui.connected, { it.roundToInt().toString() }) { maxTokens = it }
            TuningSlider("CONTEXT TURNS", contextTurns, 1f..30f, 28, ui.connected, { it.roundToInt().toString() }) { contextTurns = it }
            Button(
                onClick = {
                    onSetTuning(
                        temperature.toDouble(), topP.toDouble(),
                        maxTokens.roundToInt().coerceIn(64, 2048),
                        contextTurns.roundToInt().coerceIn(1, 30),
                    )
                },
                enabled = ui.connected,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = Cyan, contentColor = Bg),
                shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
            ) { Text("APPLY RUNTIME TUNING", fontWeight = FontWeight.Bold) }
            if (!ui.connected) Text("Connect to the laptop to change backend controls.", color = Amber, fontSize = 11.sp)
        }
    }
}

@Composable
private fun StatusRow(connected: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(9.dp).background(if (connected) Success else Danger, CutCornerShape(2.dp)))
        Spacer(Modifier.width(8.dp))
        Text(if (connected) "CONNECTED" else "DISCONNECTED", color = if (connected) Success else Danger, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
    }
}

@Composable
private fun ConnectionField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    keyboardType: KeyboardType = KeyboardType.Text,
    isError: Boolean = false,
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, color = Dim, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text(placeholder, color = Dim) },
            colors = fridayFieldColors(),
            singleLine = true,
            isError = isError,
            supportingText = if (isError) ({ Text("Use a port from 1 to 65535") }) else null,
            keyboardOptions = KeyboardOptions(keyboardType = keyboardType, imeAction = ImeAction.Next),
            shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
        )
    }
}

@Composable
private fun ModeSelector(label: String, mode: String, ui: FridayUiState, onSetMode: (String) -> Unit, modifier: Modifier) {
    OutlinedButton(
        onClick = { onSetMode(mode) },
        enabled = ui.connected && (mode != "openrouter" || ui.cloudAvailable),
        modifier = modifier,
        border = BorderStroke(1.dp, if (ui.selectedMode == mode) Cyan else Line),
        shape = CutCornerShape(topEnd = 10.dp, bottomStart = 6.dp),
    ) { Text(label, color = if (ui.selectedMode == mode) Cyan else Dim, fontSize = 11.sp) }
}

@Composable
private fun TuningSlider(
    label: String,
    value: Float,
    range: ClosedFloatingPointRange<Float>,
    steps: Int,
    enabled: Boolean,
    format: (Float) -> String,
    onValueChange: (Float) -> Unit,
) {
    Column {
        Row(Modifier.fillMaxWidth()) {
            Text(label, color = Dim, fontSize = 10.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.weight(1f))
            Text(format(value), color = Cyan, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
        }
        Slider(
            value = value.coerceIn(range.start, range.endInclusive),
            onValueChange = onValueChange,
            valueRange = range,
            steps = steps,
            enabled = enabled,
        )
    }
}

@Composable
private fun fridayFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor = White,
    unfocusedTextColor = White,
    cursorColor = Cyan,
    focusedBorderColor = Cyan,
    unfocusedBorderColor = Line,
)
