package com.friday.assistant.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.util.Base64
import kotlinx.coroutines.*
import java.io.File

class AudioPlayer(private val context: Context) {
    private var player: MediaPlayer? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    fun playBase64Wav(base64: String, onDone: (() -> Unit)? = null) {
        scope.launch {
            try {
                val bytes = Base64.decode(base64, Base64.NO_WRAP)
                val tmp = File(context.cacheDir, "friday_tts_${System.currentTimeMillis()}.wav")
                tmp.writeBytes(bytes)

                withContext(Dispatchers.Main) {
                    stop()
                    player = MediaPlayer().apply {
                        setAudioAttributes(
                            AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_MEDIA)
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                                .build()
                        )
                        setDataSource(tmp.absolutePath)
                        setOnPreparedListener { start() }
                        setOnCompletionListener {
                            onDone?.invoke()
                            tmp.delete()
                        }
                        setOnErrorListener { _, _, _ ->
                            tmp.delete()
                            false
                        }
                        prepareAsync()
                    }
                }
            } catch (_: Exception) {}
        }
    }

    fun playBase64Mp3(base64: String, onDone: (() -> Unit)? = null) {
        scope.launch {
            try {
                val bytes = Base64.decode(base64, Base64.NO_WRAP)
                val tmp = File(context.cacheDir, "friday_tts_${System.currentTimeMillis()}.mp3")
                tmp.writeBytes(bytes)

                withContext(Dispatchers.Main) {
                    stop()
                    player = MediaPlayer().apply {
                        setAudioAttributes(
                            AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_MEDIA)
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                                .build()
                        )
                        setDataSource(tmp.absolutePath)
                        setOnPreparedListener { start() }
                        setOnCompletionListener {
                            onDone?.invoke()
                            tmp.delete()
                        }
                        prepareAsync()
                    }
                }
            } catch (_: Exception) {}
        }
    }

    fun stop() {
        try {
            player?.stop()
        } catch (_: Exception) {}
        player?.release()
        player = null
    }

    fun destroy() {
        stop()
        scope.cancel()
    }
}
