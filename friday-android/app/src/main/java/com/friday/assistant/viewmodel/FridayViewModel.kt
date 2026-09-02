package com.friday.assistant.viewmodel

import android.app.Application
import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.friday.assistant.audio.AudioPlayer
import com.friday.assistant.audio.MicRecorder
import com.friday.assistant.network.FridayMessage
import com.friday.assistant.network.FridayWebSocket
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

val Context.dataStore: DataStore<Preferences> by preferencesDataStore("friday_settings")

data class ChatBubble(
    val isUser: Boolean,
    val text: String,
    val timestamp: Long = System.currentTimeMillis(),
    val responseId: String = "",
    val feedback: Int? = null,
)

data class ConfirmationAction(
    val id: String,
    val title: String,
    val description: String,
)

data class FridayUiState(
    val connected: Boolean = false,
    val state: String = "idle",
    val micActive: Boolean = false,
    val isRecording: Boolean = false,
    val chatLog: List<ChatBubble> = emptyList(),
    val partialText: String = "",
    val confirmation: ConfirmationAction? = null,
    val guardianMessage: String? = null,
    val visionActive: Boolean = false,
    val memoryCount: Int = 0,
    val errorMessage: String? = null,
    val host: String = "192.168.1.1",
    val port: String = "8000",
    val token: String = "",
    val pairingStatus: String? = null,
    val assistantState: String = "idle",
    val modelState: String = "unknown",
    val selectedMode: String = "local",
    val effectiveMode: String = "local",
    val cloudAvailable: Boolean = false,
    val cloudModel: String = "",
    val localModel: String = "",
    val cpuPercent: Double = 0.0,
    val ramPercent: Double = 0.0,
    val diskPercent: Double = 0.0,
    val uptimeSeconds: Double = 0.0,
    val gpuAvailable: Boolean = false,
    val gpuUtilizationPercent: Double = 0.0,
    val gpuTemperatureC: Double = 0.0,
    val gpuMemoryUsedMb: Double = 0.0,
    val gpuMemoryTotalMb: Double = 0.0,
    val temperature: Double = 0.7,
    val topP: Double = 0.9,
    val maxNewTokens: Int = 512,
    val contextTurns: Int = 10,
)

class FridayViewModel(application: Application) : AndroidViewModel(application) {
    private val _ui = MutableStateFlow(FridayUiState())
    val ui: StateFlow<FridayUiState> = _ui.asStateFlow()

    private var ws: FridayWebSocket? = null
    private var mic: MicRecorder? = null
    private val player = AudioPlayer(application)
    private val timeFmt = SimpleDateFormat("HH:mm", Locale.getDefault())

    init {
        viewModelScope.launch {
            getSettings().collect { settings ->
                _ui.update { it.copy(host = settings.host, port = settings.port, token = settings.token) }
                reconnect(settings.host, settings.port, settings.token)
            }
        }
    }

    private data class LinkSettings(val host: String, val port: String, val token: String)

    private fun getSettings(): Flow<LinkSettings> {
        val ctx = getApplication<Application>()
        return ctx.dataStore.data.map { prefs ->
            val h = prefs[stringPreferencesKey("host")] ?: "192.168.1.1"
            val p = prefs[stringPreferencesKey("port")] ?: "8000"
            val token = prefs[stringPreferencesKey("token")] ?: ""
            LinkSettings(h, p, token)
        }
    }

    fun saveSettings(host: String, port: String, token: String) {
        viewModelScope.launch {
            val ctx = getApplication<Application>()
            ctx.dataStore.edit { prefs ->
                prefs[stringPreferencesKey("host")] = host
                prefs[stringPreferencesKey("port")] = port
                prefs[stringPreferencesKey("token")] = token
            }
        }
    }

    private fun reconnect(host: String, port: String, token: String) {
        ws?.disconnect()
        if (host.isBlank() || host == "0.0.0.0" || token.isBlank()) {
            ws = null
            _ui.update {
                it.copy(
                    connected = false,
                    errorMessage = null,
                    pairingStatus = "Scan the QR code in Windows CONFIG -> NETWORK to connect.",
                )
            }
            return
        }
        ws = FridayWebSocket(
            host = host,
            port = port.toIntOrNull() ?: 8000,
            token = token,
            onMessage = ::handleMessage,
            onConnected = {
                _ui.update {
                    it.copy(
                        connected = true,
                        pairingStatus = "Connected to $host:$port",
                        errorMessage = null,
                    )
                }
                ws?.sendSystemSnapshotGet()
                ws?.sendTuningGet()
            },
            onDisconnected = {
                _ui.update { it.copy(connected = false) }
            },
            onError = { message ->
                _ui.update { it.copy(errorMessage = message) }
            },
        )
        ws?.connect()
    }

    private fun handleMessage(msg: FridayMessage) {
        when (msg.type) {
            "state" -> _ui.update { it.copy(state = msg.value ?: "idle", assistantState = msg.value ?: "idle") }
            "mic" -> _ui.update { it.copy(micActive = msg.active == true) }
            "system_snapshot" -> _ui.update {
                it.copy(
                    state = msg.assistant_state ?: it.state,
                    assistantState = msg.assistant_state ?: it.assistantState,
                    modelState = msg.model_state ?: it.modelState,
                    selectedMode = msg.selected_mode ?: it.selectedMode,
                    effectiveMode = msg.effective_mode ?: it.effectiveMode,
                    cloudAvailable = msg.cloud_available ?: it.cloudAvailable,
                    cloudModel = msg.cloud_model.orEmpty(),
                    localModel = msg.local_model.orEmpty(),
                    micActive = msg.mic_active ?: it.micActive,
                    cpuPercent = msg.cpu_percent ?: it.cpuPercent,
                    ramPercent = msg.ram_percent ?: it.ramPercent,
                    diskPercent = msg.disk_percent ?: it.diskPercent,
                    uptimeSeconds = msg.uptime_seconds ?: it.uptimeSeconds,
                    gpuAvailable = msg.gpu_available ?: it.gpuAvailable,
                    gpuUtilizationPercent = msg.gpu_utilization_percent ?: it.gpuUtilizationPercent,
                    gpuTemperatureC = msg.gpu_temperature_c ?: it.gpuTemperatureC,
                    gpuMemoryUsedMb = msg.gpu_memory_used_mb ?: it.gpuMemoryUsedMb,
                    gpuMemoryTotalMb = msg.gpu_memory_total_mb ?: it.gpuMemoryTotalMb,
                )
            }
            "mode" -> _ui.update {
                it.copy(
                    selectedMode = msg.selected_mode ?: it.selectedMode,
                    effectiveMode = msg.effective_mode ?: it.effectiveMode,
                    cloudAvailable = msg.cloud_available ?: it.cloudAvailable,
                    cloudModel = msg.cloud_model.orEmpty(),
                )
            }
            "tuning" -> _ui.update {
                it.copy(
                    temperature = msg.temperature ?: it.temperature,
                    topP = msg.top_p ?: it.topP,
                    maxNewTokens = msg.max_new_tokens ?: it.maxNewTokens,
                    contextTurns = msg.context_turns ?: it.contextTurns,
                )
            }
            "tuning_error", "mode_error" -> _ui.update {
                it.copy(errorMessage = msg.text ?: "Backend rejected the setting")
            }
            "assistant" -> {
                val text = msg.text.orEmpty()
                if (text.isBlank()) return
                _ui.update {
                    it.copy(
                        chatLog = it.chatLog + ChatBubble(
                            false,
                            text,
                            ((msg.timestamp ?: (System.currentTimeMillis() / 1000.0)) * 1000).toLong(),
                            msg.response_id.orEmpty(),
                        ),
                        partialText = "",
                    )
                }
            }
            "delta" -> _ui.update {
                it.copy(partialText = it.partialText + (msg.text ?: ""))
            }
            "response_complete" -> _ui.update {
                val completed = it.partialText
                if (completed.isBlank()) it.copy(partialText = "") else it.copy(
                    chatLog = it.chatLog + ChatBubble(
                        false,
                        completed,
                        ((msg.timestamp ?: (System.currentTimeMillis() / 1000.0)) * 1000).toLong(),
                        msg.response_id.orEmpty(),
                    ),
                    partialText = "",
                )
            }
            "user" -> {
                if (msg.text?.isNotBlank() == true) {
                    _ui.update {
                        it.copy(chatLog = it.chatLog + ChatBubble(true, msg.text))
                    }
                }
            }
            "confirmation" -> {
                val action = msg.action
                if (action != null) {
                    _ui.update {
                        it.copy(
                            confirmation = ConfirmationAction(
                                id = action.get("id")?.asString ?: "",
                                title = action.get("title")?.asString ?: "",
                                description = action.get("description")?.asString ?: "",
                            )
                        )
                    }
                }
            }
            "confirmation_resolved" -> _ui.update { it.copy(confirmation = null) }
            "guardian" -> _ui.update {
                it.copy(guardianMessage = if (msg.active == true) msg.message else null)
            }
            "vision" -> _ui.update { it.copy(visionActive = msg.active == true) }
            "memory_stats" -> _ui.update {
                it.copy(memoryCount = msg.facts?.takeIf { value -> value.isJsonPrimitive }?.asInt ?: 0)
            }
            "error" -> _ui.update {
                it.copy(errorMessage = msg.text)
            }
            "interrupted" -> _ui.update { it.copy(partialText = "") }
            "feedback_saved" -> if (msg.saved != true) {
                _ui.update { it.copy(errorMessage = "Feedback could not be saved") }
            }
        }
    }

    fun sendChat(text: String) {
        if (text.isBlank()) return
        ws?.sendChat(text)
    }

    fun setMicActive(active: Boolean) {
        if (!ui.value.connected || ui.value.micActive == active) return
        ws?.sendMicSet(active)
    }

    fun setMode(mode: String) {
        if (!ui.value.connected || mode !in setOf("local", "openrouter") || ui.value.selectedMode == mode) return
        ws?.sendMode(mode)
    }

    fun setTuning(temperature: Double, topP: Double, maxNewTokens: Int, contextTurns: Int) {
        if (!ui.value.connected || temperature !in 0.0..2.0 || topP !in 0.1..1.0 ||
            maxNewTokens !in 64..2048 || contextTurns !in 1..30) return
        val current = ui.value
        if (current.temperature == temperature && current.topP == topP &&
            current.maxNewTokens == maxNewTokens && current.contextTurns == contextTurns) return
        ws?.sendTuning(temperature, topP, maxNewTokens, contextTurns)
    }

    fun setPairingStatus(status: String?) {
        _ui.update { it.copy(pairingStatus = status) }
    }

    fun stop() {
        ws?.sendStop()
        mic?.stop()
        _ui.update { it.copy(isRecording = false) }
    }

    fun toggleRecord() {
        val currently = _ui.value.isRecording
        if (currently) {
            mic?.stop()
            _ui.update { it.copy(isRecording = false) }
        } else {
            mic = MicRecorder { b64 ->
                ws?.sendPhoneAudio(b64)
            }
            val started = mic?.start() == true
            _ui.update { it.copy(isRecording = started, errorMessage = if (started) null else "Phone microphone unavailable") }
        }
    }

    fun approve() {
        val id = _ui.value.confirmation?.id ?: return
        ws?.sendApprove(id)
        _ui.update { it.copy(confirmation = null) }
    }

    fun deny() {
        val id = _ui.value.confirmation?.id ?: return
        ws?.sendDeny(id)
        _ui.update { it.copy(confirmation = null) }
    }

    fun dismissError() {
        _ui.update { it.copy(errorMessage = null) }
    }

    fun dismissGuardian() {
        _ui.update { it.copy(guardianMessage = null) }
    }

    fun sendFeedback(responseId: String, score: Int) {
        val target = _ui.value.chatLog.lastOrNull { it.responseId == responseId } ?: return
        if (responseId.isBlank()) return
        ws?.sendFeedback(responseId, target.timestamp / 1000.0, score)
        _ui.update { state ->
            state.copy(chatLog = state.chatLog.map {
                if (it.responseId == responseId) it.copy(feedback = score) else it
            })
        }
    }

    override fun onCleared() {
        super.onCleared()
        mic?.destroy()
        player.destroy()
        ws?.disconnect()
    }
}
