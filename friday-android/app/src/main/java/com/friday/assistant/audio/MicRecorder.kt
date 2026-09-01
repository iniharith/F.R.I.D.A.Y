package com.friday.assistant.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Base64
import kotlinx.coroutines.*
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

class MicRecorder(
    private val onAudioReady: (String) -> Unit
) {
    private var recorder: AudioRecord? = null
    private var job: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val recorded = ByteArrayOutputStream()
    @Volatile private var recording = false

    companion object {
        const val SAMPLE_RATE = 16000
        const val CHANNEL = AudioFormat.CHANNEL_IN_MONO
        const val ENCODING = AudioFormat.ENCODING_PCM_16BIT
    }

    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        val bufferSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL, ENCODING)
        if (bufferSize <= 0) return false
        recorder = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE, CHANNEL, ENCODING,
            bufferSize * 2
        )
        if (recorder?.state != AudioRecord.STATE_INITIALIZED) {
            recorder?.release()
            recorder = null
            return false
        }
        synchronized(recorded) { recorded.reset() }
        recording = true
        recorder?.startRecording()

        job = scope.launch {
            val chunk = ByteArray(bufferSize)
            while (isActive && recording) {
                val count = recorder?.read(chunk, 0, chunk.size) ?: -1
                if (count > 0) {
                    synchronized(recorded) { recorded.write(chunk, 0, count) }
                }
            }
        }
        return true
    }

    fun stop() {
        if (!recording) return
        recording = false
        try {
            recorder?.stop()
        } catch (_: Exception) {}
        runBlocking { job?.cancelAndJoin() }
        job = null
        recorder?.release()
        recorder = null
        val pcm = synchronized(recorded) { recorded.toByteArray() }
        if (pcm.isNotEmpty()) {
            val wav = wavBytes(pcm)
            onAudioReady(Base64.encodeToString(wav, Base64.NO_WRAP))
        }
    }

    private fun wavBytes(pcm: ByteArray): ByteArray {
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        val byteRate = SAMPLE_RATE * 2
        header.put("RIFF".toByteArray())
        header.putInt(36 + pcm.size)
        header.put("WAVEfmt ".toByteArray())
        header.putInt(16)
        header.putShort(1.toShort())
        header.putShort(1.toShort())
        header.putInt(SAMPLE_RATE)
        header.putInt(byteRate)
        header.putShort(2.toShort())
        header.putShort(16.toShort())
        header.put("data".toByteArray())
        header.putInt(pcm.size)
        return header.array() + pcm
    }

    fun destroy() {
        stop()
        scope.cancel()
    }
}
