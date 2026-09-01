package com.friday.assistant.network

import com.google.gson.Gson
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import kotlinx.coroutines.*
import okhttp3.*
import java.util.concurrent.TimeUnit

data class FridayMessage(
    val type: String,
    val text: String? = null,
    val value: String? = null,
    val active: Boolean? = null,
    val message: String? = null,
    val action: JsonObject? = null,
    val result: JsonObject? = null,
    val facts: JsonElement? = null,
    val episodes: Int? = null,
    val empty: Boolean? = null,
    val ok: Boolean? = null,
    val saved: Boolean? = null,
    val source: String? = null,
    val response_id: String? = null,
    val timestamp: Double? = null,
)

class FridayWebSocket(
    private val host: String,
    private val port: Int,
    private val token: String,
    private val onMessage: (FridayMessage) -> Unit,
    private val onConnected: () -> Unit,
    private val onDisconnected: () -> Unit,
    private val onError: (String) -> Unit,
) {
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private var ws: WebSocket? = null
    private val gson = Gson()
    private var scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    fun connect() {
        val url = try {
            HttpUrl.Builder()
                .scheme("http")
                .host(host)
                .port(port)
                .addPathSegment("ws")
                .apply { if (token.isNotBlank()) addQueryParameter("token", token) }
                .build()
        } catch (error: IllegalArgumentException) {
            onError("Invalid FRIDAY host or port")
            onDisconnected()
            return
        }
        val request = Request.Builder().url(url).build()
        ws = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                onConnected()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val msg = gson.fromJson(text, FridayMessage::class.java)
                    onMessage(msg)
                } catch (_: Exception) {
                    onError("FRIDAY sent an incompatible message")
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
                onDisconnected()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                onDisconnected()
                onError(response?.message ?: t.message ?: "Connection failed")
                scope.launch {
                    delay(3000)
                    connect()
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                onDisconnected()
            }
        })
    }

    fun send(type: String, payload: Map<String, Any> = emptyMap()) {
        val obj = JsonObject().apply {
            addProperty("type", type)
            payload.forEach { (k, v) ->
                when (v) {
                    is String -> addProperty(k, v)
                    is Number -> addProperty(k, v)
                    is Boolean -> addProperty(k, v)
                    else -> add(k, gson.toJsonTree(v))
                }
            }
        }
        ws?.send(gson.toJson(obj))
    }

    fun sendChat(text: String) = send("chat", mapOf("text" to text))
    fun sendMicToggle() = send("mic_toggle")
    fun sendStop() = send("stop")
    fun sendApprove(id: String) = send("tool_confirm", mapOf("id" to id))
    fun sendDeny(id: String) = send("tool_deny", mapOf("id" to id))
    fun sendMemoryList() = send("memory_list")
    fun sendMemoryForget(id: Int) = send("memory_forget", mapOf("id" to id))
    fun sendFeedback(responseId: String, timestamp: Double, score: Int) =
        send("feedback", mapOf("response_id" to responseId, "timestamp" to timestamp, "score" to score))
    fun sendPhoneAudio(base64Audio: String) =
        send("phone_audio", mapOf("audio" to base64Audio))

    fun disconnect() {
        scope.cancel()
        ws?.close(1000, "bye")
        ws = null
    }
}
