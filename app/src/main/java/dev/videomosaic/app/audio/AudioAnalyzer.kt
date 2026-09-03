package dev.videomosaic.app.audio

import android.content.Context
import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import dev.videomosaic.app.model.AudioAnalysis
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.sqrt

object AudioAnalyzer {
    private const val TIMEOUT_US = 10_000L

    fun analyze(context: Context, uri: Uri): AudioAnalysis {
        val extractor = MediaExtractor()
        var codec: MediaCodec? = null
        try {
            extractor.setDataSource(context, uri, null)
            val trackIndex = findAudioTrack(extractor)
            require(trackIndex >= 0) { "В файле нет аудиодорожки" }

            extractor.selectTrack(trackIndex)
            val inputFormat = extractor.getTrackFormat(trackIndex)
            val mime = inputFormat.getString(MediaFormat.KEY_MIME)
                ?: error("У аудиодорожки нет MIME-типа")

            codec = MediaCodec.createDecoderByType(mime)
            codec.configure(inputFormat, null, null, 0)
            codec.start()

            var sampleRate = inputFormat.getIntegerOrDefault(MediaFormat.KEY_SAMPLE_RATE, 44_100)
            var channels = inputFormat.getIntegerOrDefault(MediaFormat.KEY_CHANNEL_COUNT, 1)
            var pcmEncoding = AudioFormat.ENCODING_PCM_16BIT
            var accumulator = PcmAccumulator(sampleRate, channels)

            val info = MediaCodec.BufferInfo()
            var inputDone = false
            var outputDone = false

            while (!outputDone) {
                if (!inputDone) {
                    val inputIndex = codec.dequeueInputBuffer(TIMEOUT_US)
                    if (inputIndex >= 0) {
                        val inputBuffer = codec.getInputBuffer(inputIndex)
                            ?: error("Decoder input buffer is null")
                        inputBuffer.clear()
                        val sampleSize = extractor.readSampleData(inputBuffer, 0)
                        if (sampleSize < 0) {
                            codec.queueInputBuffer(
                                inputIndex,
                                0,
                                0,
                                0L,
                                MediaCodec.BUFFER_FLAG_END_OF_STREAM
                            )
                            inputDone = true
                        } else {
                            codec.queueInputBuffer(
                                inputIndex,
                                0,
                                sampleSize,
                                extractor.sampleTime,
                                0
                            )
                            extractor.advance()
                        }
                    }
                }

                when (val outputIndex = codec.dequeueOutputBuffer(info, TIMEOUT_US)) {
                    MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        val outputFormat = codec.outputFormat
                        val newRate = outputFormat.getIntegerOrDefault(MediaFormat.KEY_SAMPLE_RATE, sampleRate)
                        val newChannels = outputFormat.getIntegerOrDefault(MediaFormat.KEY_CHANNEL_COUNT, channels)
                        pcmEncoding = outputFormat.getIntegerOrDefault(
                            MediaFormat.KEY_PCM_ENCODING,
                            AudioFormat.ENCODING_PCM_16BIT
                        )
                        if (newRate != sampleRate || newChannels != channels) {
                            sampleRate = newRate
                            channels = newChannels
                            accumulator = PcmAccumulator(sampleRate, channels)
                        }
                    }
                    else -> if (outputIndex >= 0) {
                        val outputBuffer = codec.getOutputBuffer(outputIndex)
                        if (outputBuffer != null && info.size > 0) {
                            val start = info.offset.coerceAtLeast(0)
                            val end = (info.offset + info.size).coerceAtMost(outputBuffer.capacity())
                            outputBuffer.position(start)
                            outputBuffer.limit(end)
                            accumulator.consume(outputBuffer.slice(), pcmEncoding)
                        }
                        outputDone = info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                        codec.releaseOutputBuffer(outputIndex, false)
                    }
                }
            }

            return accumulator.finish()
        } finally {
            runCatching { codec?.stop() }
            runCatching { codec?.release() }
            extractor.release()
        }
    }

    private fun findAudioTrack(extractor: MediaExtractor): Int {
        for (i in 0 until extractor.trackCount) {
            val format = extractor.getTrackFormat(i)
            if (format.getString(MediaFormat.KEY_MIME)?.startsWith("audio/") == true) return i
        }
        return -1
    }

    private fun MediaFormat.getIntegerOrDefault(key: String, fallback: Int): Int =
        if (containsKey(key)) getInteger(key) else fallback

    private class PcmAccumulator(
        private val sampleRate: Int,
        private val channels: Int
    ) {
        private val windowFrames = max(1, sampleRate / 50) // ~20 ms
        private val windowRms = ArrayList<Double>()
        private var totalSquares = 0.0
        private var totalFrames = 0L
        private var peak = 0.0
        private var currentWindowSquares = 0.0
        private var currentWindowFrames = 0

        fun consume(buffer: ByteBuffer, pcmEncoding: Int) {
            buffer.order(ByteOrder.LITTLE_ENDIAN)
            when (pcmEncoding) {
                AudioFormat.ENCODING_PCM_FLOAT -> consumeFloat(buffer)
                else -> consume16Bit(buffer)
            }
        }

        private fun consume16Bit(buffer: ByteBuffer) {
            val bytesPerFrame = channels * 2
            while (buffer.remaining() >= bytesPerFrame) {
                var mono = 0.0
                repeat(channels) {
                    mono += buffer.short.toDouble() / 32768.0
                }
                consumeFrame(mono / channels)
            }
        }

        private fun consumeFloat(buffer: ByteBuffer) {
            val bytesPerFrame = channels * 4
            while (buffer.remaining() >= bytesPerFrame) {
                var mono = 0.0
                repeat(channels) {
                    mono += buffer.float.toDouble().coerceIn(-1.0, 1.0)
                }
                consumeFrame(mono / channels)
            }
        }

        private fun consumeFrame(sample: Double) {
            val square = sample * sample
            totalSquares += square
            totalFrames++
            peak = max(peak, abs(sample))
            currentWindowSquares += square
            currentWindowFrames++
            if (currentWindowFrames >= windowFrames) flushWindow()
        }

        private fun flushWindow() {
            if (currentWindowFrames == 0) return
            windowRms += sqrt(currentWindowSquares / currentWindowFrames)
            currentWindowSquares = 0.0
            currentWindowFrames = 0
        }

        fun finish(): AudioAnalysis {
            flushWindow()
            val rms = if (totalFrames > 0) sqrt(totalSquares / totalFrames) else 0.0
            val durationMs = if (sampleRate > 0) totalFrames * 1000L / sampleRate else 0L
            return AudioAnalysis(
                sampleRate = sampleRate,
                channelCount = channels,
                durationMs = durationMs,
                rms = rms,
                peak = peak,
                onsetTimesMs = detectOnsets(windowRms)
            )
        }

        private fun detectOnsets(windows: List<Double>): List<Long> {
            if (windows.size < 5) return emptyList()
            val result = ArrayList<Long>()
            var lastOnset = -10

            for (i in 4 until windows.size) {
                val historyStart = max(0, i - 8)
                var historySum = 0.0
                for (j in historyStart until i) historySum += windows[j]
                val history = historySum / max(1, i - historyStart)
                val current = windows[i]

                val strongEnough = current >= 0.018
                val transient = current > history * 1.75 && current - history > 0.008
                val separated = i - lastOnset >= 4
                if (strongEnough && transient && separated) {
                    result += i * 20L
                    lastOnset = i
                }
            }
            return result
        }
    }
}
