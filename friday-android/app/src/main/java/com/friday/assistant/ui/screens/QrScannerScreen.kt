package com.friday.assistant.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import android.net.Uri
import android.util.Log
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CutCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.friday.assistant.ui.theme.Bg
import com.friday.assistant.ui.theme.Cyan
import com.friday.assistant.ui.theme.Danger
import com.friday.assistant.ui.theme.Dim
import com.friday.assistant.ui.theme.Line
import com.friday.assistant.ui.theme.Surface
import com.friday.assistant.ui.theme.White
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

private const val TAG = "QrScanner"

private data class Pairing(val host: String, val port: Int, val token: String)

private fun validatePairing(uri: Uri): Pairing? {
    if (uri.scheme != "friday" || uri.host != "pair") return null
    val host = uri.getQueryParameter("host")?.trim().orEmpty()
    val port = uri.getQueryParameter("port")?.toIntOrNull()
    val token = uri.getQueryParameter("token")?.trim().orEmpty()
    if (host.isBlank() || host == "0.0.0.0" || port !in 1..65535 || token.isBlank()) return null
    return Pairing(host, port!!, token)
}

@OptIn(ExperimentalGetImage::class, ExperimentalMaterial3Api::class)
@Composable
fun QrScannerScreen(
    onBack: () -> Unit,
    onPaired: (host: String, port: String, token: String) -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val cameraExecutor: ExecutorService = remember { Executors.newSingleThreadExecutor() }
    val scanner = remember { BarcodeScanning.getClient() }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var paired by remember { mutableStateOf(false) }
    var restartKey by remember { mutableIntStateOf(0) }
    val previewViewRef = remember { mutableStateOf<PreviewView?>(null) }

    val cameraProvider by produceState<ProcessCameraProvider?>(initialValue = null) {
        value = ProcessCameraProvider.getInstance(context).get()
    }

    DisposableEffect(restartKey, cameraProvider, previewViewRef.value) {
        val provider = cameraProvider ?: return@DisposableEffect onDispose {}
        val previewView = previewViewRef.value ?: return@DisposableEffect onDispose {}

        val preview = Preview.Builder().build().also {
            it.surfaceProvider = previewView.surfaceProvider
        }
        val analysis = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .build()
        analysis.setAnalyzer(cameraExecutor) { imageProxy ->
            val mediaImage = imageProxy.image
            if (mediaImage != null) {
                val inputImage = InputImage.fromMediaImage(mediaImage, imageProxy.imageInfo.rotationDegrees)
                scanner.process(inputImage)
                    .addOnSuccessListener { barcodes ->
                        val barcode = barcodes.firstOrNull()
                        val raw = barcode?.rawValue ?: barcode?.displayValue
                        if (raw != null && !paired) {
                            val properUri =
                                if (raw.startsWith("http")) {
                                    raw.replace("http://pair", "friday://pair")
                                        .replace("https://pair", "friday://pair")
                                } else raw
                            try {
                                val uri = Uri.parse(properUri)
                                val pairing = validatePairing(uri)
                                if (pairing != null) {
                                    paired = true
                                    onPaired(pairing.host, pairing.port.toString(), pairing.token)
                                } else {
                                    errorMessage = "Invalid pairing link. Use the QR from Windows CONFIG -> NETWORK."
                                }
                            } catch (_: Exception) {
                                errorMessage = "Malformed QR. Please try again."
                            }
                        }
                    }
                    .addOnCompleteListener { imageProxy.close() }
            } else {
                imageProxy.close()
            }
        }

        try {
            provider.unbindAll()
            provider.bindToLifecycle(
                lifecycleOwner,
                CameraSelector.DEFAULT_BACK_CAMERA,
                preview,
                analysis,
            )
        } catch (e: Exception) {
            Log.e(TAG, "Camera bind failed", e)
            errorMessage = "Could not start camera: ${e.message}"
        }
        onDispose {
            try { provider.unbindAll() } catch (_: Exception) {}
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            cameraExecutor.shutdown()
            try { scanner.close() } catch (_: Exception) {}
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) errorMessage = "Camera permission is required to scan the QR code."
    }

    LaunchedEffect(Unit) {
        permissionLauncher.launch(android.Manifest.permission.CAMERA)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("SCAN QR CODE", fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold) },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = White) } },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Bg),
            )
        },
        containerColor = Bg,
    ) { padding ->
        Box(
            Modifier.fillMaxSize().padding(padding),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                Modifier.fillMaxSize().padding(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text(
                    "Point the camera at the QR code shown in Windows CONFIG -> NETWORK",
                    color = White,
                    fontSize = 14.sp,
                    textAlign = TextAlign.Center,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "It pairs automatically like WhatsApp - no typing needed.",
                    color = Dim,
                    fontSize = 12.sp,
                    textAlign = TextAlign.Center,
                )

                Box(
                    Modifier
                        .fillMaxWidth()
                        .aspectRatio(1f)
                        .border(2.dp, Cyan, CutCornerShape(10.dp))
                        .background(Surface),
                    contentAlignment = Alignment.Center,
                ) {
                    AndroidView(
                        factory = { ctx ->
                            PreviewView(ctx).also { previewViewRef.value = it }
                        },
                        modifier = Modifier.fillMaxSize(),
                    )
                }

                errorMessage?.let {
                    Text(it, color = Danger, fontSize = 12.sp, textAlign = TextAlign.Center)
                }

                if (paired) {
                    Text("PAIRED SUCCESSFULLY", color = Cyan, fontWeight = FontWeight.Bold, fontSize = 14.sp, fontFamily = FontFamily.Monospace)
                } else {
                    OutlinedButton(
                        onClick = { restartKey++ },
                        border = BorderStroke(1.dp, Line),
                        shape = CutCornerShape(topEnd = 10.dp, bottomStart = 6.dp),
                    ) {
                        Icon(Icons.Filled.Refresh, null, tint = Cyan)
                        Spacer(Modifier.width(6.dp))
                        Text("RESTART SCANNER", color = White, fontSize = 12.sp)
                    }
                    Text(
                        "If nothing happens, tap the Refresh icon to restart the scanner.",
                        color = Dim,
                        fontSize = 11.sp,
                        textAlign = TextAlign.Center,
                    )
                }
            }
        }
    }
}