package com.friday.assistant.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.foundation.background
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CutCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.friday.assistant.ui.theme.*
import com.friday.assistant.R
import com.friday.assistant.viewmodel.ChatBubble
import com.friday.assistant.viewmodel.FridayUiState
import java.text.SimpleDateFormat
import java.util.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    ui: FridayUiState,
    onSend: (String) -> Unit,
    onSetMicActive: (Boolean) -> Unit,
    onStop: () -> Unit,
    onToggleRecord: () -> Unit,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
    onDismissError: () -> Unit,
    onDismissGuardian: () -> Unit,
    onFeedback: (String, Int) -> Unit,
    onOpenSettings: () -> Unit,
    onOpenDashboard: () -> Unit,
) {
    var inputText by remember { mutableStateOf("") }
    val listState = rememberLazyListState()
    val focusManager = LocalFocusManager.current
    val timeFmt = remember { SimpleDateFormat("HH:mm", Locale.getDefault()) }
    val context = LocalContext.current

    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) onToggleRecord()
    }

    LaunchedEffect(ui.chatLog.size, ui.partialText) {
        if (ui.chatLog.isNotEmpty() || ui.partialText.isNotEmpty()) {
            listState.animateScrollToItem(listState.layoutInfo.totalItemsCount)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Image(
                            painter = painterResource(R.drawable.friday_logo),
                            contentDescription = "FRIDAY",
                            modifier = Modifier.size(34.dp).clip(CutCornerShape(topEnd = 10.dp)),
                        )
                        Spacer(Modifier.width(10.dp))
                        Box(
                            Modifier
                                .size(8.dp)
                                .clip(CircleShape)
                                .background(if (ui.connected) Success else Danger)
                        )
                        Spacer(Modifier.width(8.dp))
                        Column {
                            Text("F.R.I.D.A.Y.", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
                            Text("MOBILE COMMAND LINK", color = Dim, fontSize = 9.sp, fontFamily = FontFamily.Monospace)
                        }
                    }
                },
                actions = {
                    Text(
                        ui.state.uppercase(),
                        color = Dim,
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                        modifier = Modifier.padding(end = 8.dp)
                    )
                    TextButton(onClick = onOpenDashboard) {
                        Text("HUD", color = Cyan, fontSize = 11.sp)
                    }
                    IconButton(onClick = onOpenSettings) {
                        Icon(Icons.Outlined.Settings, "Settings", tint = Dim)
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
        ) {
            LazyRow(
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                item {
                    Button(
                        onClick = { onSetMicActive(!ui.micActive) },
                        enabled = ui.connected,
                        shape = CutCornerShape(topEnd = 10.dp, bottomStart = 6.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (ui.micActive) Danger else Success,
                            contentColor = Bg,
                        ),
                    ) { Text(if (ui.micActive) "MUTE LAPTOP MIC" else "UNMUTE LAPTOP MIC", fontSize = 11.sp, fontWeight = FontWeight.Bold) }
                }
                item { StatusTile("MEMORY", "${ui.memoryCount} FACTS", Cyan) }
                item { StatusTile("GUARDIAN", if (ui.guardianMessage == null) "NOMINAL" else "ALERT", if (ui.guardianMessage == null) Success else Amber) }
                item { StatusTile("VISION", if (ui.visionActive) "ACTIVE" else "OFFLINE", if (ui.visionActive) Danger else Dim) }
            }

            // Chat log
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                contentPadding = PaddingValues(vertical = 12.dp),
            ) {
                items(ui.chatLog) { bubble ->
                    ChatBubbleView(bubble, timeFmt, onFeedback)
                }
                if (ui.partialText.isNotEmpty()) {
                    item {
                        ChatBubbleView(
                            com.friday.assistant.viewmodel.ChatBubble(false, ui.partialText),
                            timeFmt,
                            onFeedback,
                            streaming = true,
                        )
                    }
                }
            }

            // Guardian alert
            AnimatedVisibility(visible = ui.guardianMessage != null) {
                GuardianBanner(ui.guardianMessage ?: "", onDismissGuardian)
            }

            // Confirmation panel
            AnimatedVisibility(visible = ui.confirmation != null) {
                ConfirmationBanner(ui.confirmation!!, onApprove, onDeny)
            }

            // Error toast
            AnimatedVisibility(visible = ui.errorMessage != null) {
                ErrorBanner(ui.errorMessage ?: "", onDismissError)
            }

            // Input bar
            Row(
                Modifier
                    .fillMaxWidth()
                    .background(Surface)
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // Phone record button
                IconButton(onClick = {
                    val hasPerm = ContextCompat.checkSelfPermission(
                        context, Manifest.permission.RECORD_AUDIO
                    ) == PackageManager.PERMISSION_GRANTED
                    if (hasPerm) {
                        onToggleRecord()
                    } else {
                        permLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }
                }) {
                    Icon(
                        if (ui.isRecording) Icons.Filled.FiberManualRecord else Icons.Outlined.RecordVoiceOver,
                        contentDescription = "Phone mic",
                        tint = if (ui.isRecording) Danger else Dim,
                    )
                }

                OutlinedTextField(
                    value = inputText,
                    onValueChange = { inputText = it },
                    modifier = Modifier
                        .weight(1f)
                        .heightIn(min = 48.dp, max = 112.dp),
                    placeholder = { Text("Type to F.R.I.D.A.Y.", color = Dim, fontSize = 14.sp) },
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = White,
                        unfocusedTextColor = White,
                        cursorColor = Cyan,
                        focusedBorderColor = Line,
                        unfocusedBorderColor = Line,
                    ),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(onSend = {
                        onSend(inputText.trim())
                        inputText = ""
                        focusManager.clearFocus()
                    }),
                    enabled = ui.connected,
                    maxLines = 4,
                    shape = CutCornerShape(topEnd = 12.dp, bottomStart = 12.dp),
                )

                Spacer(Modifier.width(8.dp))

                // Send / Stop
                IconButton(
                    onClick = {
                        if (ui.state == "speaking" || ui.state == "thinking") {
                            onStop()
                        } else {
                            onSend(inputText.trim())
                            inputText = ""
                            focusManager.clearFocus()
                        }
                    },
                    modifier = Modifier
                        .size(48.dp)
                        .clip(CutCornerShape(topEnd = 14.dp, bottomStart = 14.dp))
                        .background(if (ui.state in listOf("speaking", "thinking")) Danger else Cyan),
                    enabled = ui.connected,
                ) {
                    Icon(
                        if (ui.state in listOf("speaking", "thinking")) Icons.Filled.Stop else Icons.AutoMirrored.Filled.Send,
                        contentDescription = if (ui.state in listOf("speaking", "thinking")) "Stop" else "Send",
                        tint = Bg,
                    )
                }
            }
        }
    }
}

@Composable
fun ChatBubbleView(
    bubble: ChatBubble,
    timeFmt: SimpleDateFormat,
    onFeedback: (String, Int) -> Unit,
    streaming: Boolean = false,
) {
    val alignment = if (bubble.isUser) Alignment.End else Alignment.Start
    val bgColor = if (bubble.isUser) BubbleUser else BubbleBot
    val textColor = White
    val timeColor = Dim

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = alignment,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth(0.84f)
                .widthIn(max = 620.dp)
                .clip(CutCornerShape(topEnd = if (bubble.isUser) 0.dp else 14.dp, topStart = if (bubble.isUser) 14.dp else 0.dp, bottomStart = 8.dp, bottomEnd = 8.dp))
                .background(bgColor)
                .padding(horizontal = 14.dp, vertical = 10.dp)
        ) {
            Text(bubble.text, color = textColor, fontSize = 14.sp, lineHeight = 20.sp)
            if (streaming) {
                Text("PROCESSING //", color = Cyan, fontSize = 9.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.padding(top = 6.dp))
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                timeFmt.format(Date(bubble.timestamp)),
                color = timeColor,
                fontSize = 10.sp,
                modifier = Modifier.padding(top = 2.dp, start = 4.dp, end = 4.dp),
            )
            if (!bubble.isUser && bubble.responseId.isNotBlank()) {
                IconButton(onClick = { onFeedback(bubble.responseId, 1) }, modifier = Modifier.size(36.dp)) {
                    Icon(Icons.Outlined.ThumbUp, "Helpful", tint = if (bubble.feedback == 1) Success else Dim, modifier = Modifier.size(15.dp))
                }
                IconButton(onClick = { onFeedback(bubble.responseId, -1) }, modifier = Modifier.size(36.dp)) {
                    Icon(Icons.Outlined.ThumbDown, "Not helpful", tint = if (bubble.feedback == -1) Danger else Dim, modifier = Modifier.size(15.dp))
                }
            }
        }
    }
}

@Composable
private fun StatusTile(label: String, value: String, accent: Color, onClick: (() -> Unit)? = null) {
    Surface(
        color = Surface,
        shape = CutCornerShape(topEnd = 10.dp, bottomStart = 6.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, Line),
        modifier = Modifier.widthIn(min = 118.dp).then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
    ) {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 9.dp)) {
            Text(label, color = Dim, fontSize = 9.sp, fontFamily = FontFamily.Monospace, letterSpacing = 1.sp)
            Text(value, color = accent, fontSize = 12.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
        }
    }
}

@Composable
fun GuardianBanner(message: String, onDismiss: () -> Unit) {
    Surface(
        color = Amber.copy(alpha = 0.15f),
        shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Outlined.Security, contentDescription = null, tint = Amber)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text("SYSTEM GUARDIAN", color = Amber, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                Text(message, color = Dim, fontSize = 12.sp)
            }
            IconButton(onClick = onDismiss, modifier = Modifier.size(48.dp)) {
                Icon(Icons.Filled.Close, "Dismiss", tint = Dim, modifier = Modifier.size(16.dp))
            }
        }
    }
}

@Composable
fun ConfirmationBanner(
    confirmation: com.friday.assistant.viewmodel.ConfirmationAction,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
) {
    Surface(
        color = Surface,
        shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
        tonalElevation = 4.dp,
    ) {
        Column(Modifier.padding(16.dp)) {
            Text("CONFIRM ACTION", color = Cyan, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            Spacer(Modifier.height(4.dp))
            Text(confirmation.title, color = White, fontSize = 16.sp, fontWeight = FontWeight.Bold)
            Text(confirmation.description, color = Dim, fontSize = 12.sp)
            Spacer(Modifier.height(12.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(
                    onClick = onDeny,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Danger),
                ) { Text("DENY") }
                Button(
                    onClick = onApprove,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = Cyan, contentColor = Bg),
                ) { Text("APPROVE") }
            }
            Text("Or say \"Friday, confirm\" / \"Friday, cancel\"", color = Dim, fontSize = 10.sp, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

@Composable
fun ErrorBanner(message: String, onDismiss: () -> Unit) {
    Surface(
        color = Danger.copy(alpha = 0.15f),
        shape = CutCornerShape(topEnd = 12.dp, bottomStart = 8.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text("ERROR", color = Danger, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                Text(message, color = White, fontSize = 12.sp)
            }
            IconButton(onClick = onDismiss, modifier = Modifier.size(48.dp)) {
                Icon(Icons.Filled.Close, "Dismiss", tint = Dim, modifier = Modifier.size(16.dp))
            }
        }
    }
}
