package com.friday.assistant.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.CutCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.friday.assistant.ui.theme.*
import com.friday.assistant.viewmodel.FridayUiState
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    ui: FridayUiState,
    onSetMicActive: (Boolean) -> Unit,
    onSetMode: (String) -> Unit,
    onOpenChat: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("F.R.I.D.A.Y. // HUD", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                        Text("LAPTOP TELEMETRY", color = Dim, fontSize = 9.sp, fontFamily = FontFamily.Monospace)
                    }
                },
                actions = {
                    TextButton(onClick = onOpenChat) { Text("CHAT") }
                    TextButton(onClick = onOpenSettings) { Text("SETTINGS") }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Bg),
            )
        },
        containerColor = Bg,
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            HudPanel("SYSTEM LINK") {
                StatusLine("CONNECTION", if (ui.connected) "ONLINE" else "OFFLINE", if (ui.connected) Success else Danger)
                StatusLine("ASSISTANT", ui.assistantState.uppercase(), Cyan)
                StatusLine("MODEL", ui.modelState.uppercase(), if (ui.modelState == "unknown") Dim else Success)
                StatusLine("UPTIME", formatUptime(ui.uptimeSeconds), White)
            }

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Metric("CPU", ui.cpuPercent, Modifier.weight(1f))
                Metric("RAM", ui.ramPercent, Modifier.weight(1f))
                Metric("DISK", ui.diskPercent, Modifier.weight(1f))
            }

            if (ui.gpuAvailable) {
                HudPanel("GPU") {
                    StatusLine("UTILIZATION", "${ui.gpuUtilizationPercent.oneDecimal()}%", Cyan)
                    StatusLine("TEMPERATURE", "${ui.gpuTemperatureC.oneDecimal()} C", Amber)
                    StatusLine("MEMORY", "${ui.gpuMemoryUsedMb.oneDecimal()} / ${ui.gpuMemoryTotalMb.oneDecimal()} MB", White)
                }
            }

            HudPanel("MODEL & REASONING") {
                StatusLine("SELECTED", ui.selectedMode.uppercase(), Cyan)
                StatusLine("EFFECTIVE", ui.effectiveMode.uppercase(), if (ui.effectiveMode == ui.selectedMode) Success else Amber)
                StatusLine("LOCAL MODEL", ui.localModel.ifBlank { "Not reported" }, White)
                StatusLine("CLOUD MODEL", ui.cloudModel.ifBlank { "Not reported" }, White)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ModeButton("LOCAL", "local", ui, onSetMode, Modifier.weight(1f))
                    ModeButton("OPENROUTER", "openrouter", ui, onSetMode, Modifier.weight(1f))
                }
                if (!ui.cloudAvailable) Text("Cloud reasoning unavailable", color = Amber, fontSize = 11.sp)
            }

            Button(
                onClick = { onSetMicActive(!ui.micActive) },
                enabled = ui.connected,
                modifier = Modifier.fillMaxWidth().height(54.dp),
                shape = CutCornerShape(topEnd = 14.dp, bottomStart = 10.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (ui.micActive) Danger else Success,
                    contentColor = Bg,
                ),
            ) {
                Text(if (ui.micActive) "MUTE LAPTOP MIC" else "UNMUTE LAPTOP MIC", fontWeight = FontWeight.Bold)
            }
            Text("Memory: ${ui.memoryCount} facts", color = Dim, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
        }
    }
}

@Composable
private fun HudPanel(title: String, content: @Composable ColumnScope.() -> Unit) {
    Surface(
        color = Surface,
        shape = CutCornerShape(topEnd = 16.dp, bottomStart = 10.dp),
        border = BorderStroke(1.dp, Line),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, color = Cyan, fontSize = 10.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace, letterSpacing = 1.sp)
            content()
        }
    }
}

@Composable
private fun StatusLine(label: String, value: String, color: Color) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(7.dp).clip(CircleShape).background(color))
        Spacer(Modifier.width(8.dp))
        Text(label, color = Dim, fontSize = 11.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.weight(1f))
        Text(value, color = color, fontSize = 11.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun Metric(label: String, value: Double, modifier: Modifier = Modifier) {
    Surface(color = SurfaceHigh, shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp), modifier = modifier) {
        Column(Modifier.padding(12.dp)) {
            Text(label, color = Dim, fontSize = 9.sp, fontFamily = FontFamily.Monospace)
            Text("${value.oneDecimal()}%", color = Cyan, fontSize = 19.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
            LinearProgressIndicator(
                progress = { (value.coerceIn(0.0, 100.0) / 100.0).toFloat() },
                modifier = Modifier.fillMaxWidth().padding(top = 7.dp),
                color = if (value >= 90) Danger else Cyan,
                trackColor = Line,
            )
        }
    }
}

@Composable
private fun ModeButton(label: String, mode: String, ui: FridayUiState, onSetMode: (String) -> Unit, modifier: Modifier) {
    OutlinedButton(
        onClick = { onSetMode(mode) },
        enabled = ui.connected && (mode != "openrouter" || ui.cloudAvailable),
        modifier = modifier,
        shape = CutCornerShape(topEnd = 10.dp, bottomStart = 6.dp),
        border = BorderStroke(1.dp, if (ui.selectedMode == mode) Cyan else Line),
    ) { Text(label, color = if (ui.selectedMode == mode) Cyan else Dim, fontSize = 11.sp) }
}

private fun Double.oneDecimal() = String.format(Locale.US, "%.1f", this)

private fun formatUptime(seconds: Double): String {
    val total = seconds.coerceAtLeast(0.0).toLong()
    val days = total / 86400
    val hours = (total % 86400) / 3600
    val minutes = (total % 3600) / 60
    return if (days > 0) "${days}d ${hours}h ${minutes}m" else "${hours}h ${minutes}m"
}
