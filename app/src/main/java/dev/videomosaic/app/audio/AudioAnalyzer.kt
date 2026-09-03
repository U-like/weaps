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
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
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
            val expectedDurationUs = inputFormat.getLongOrDefault(MediaFormat.KEY_DURATION, 0L)

            codec = MediaCodec.createDecoderByType(mime)
            codec.configure(inputFormat, null, null, 0)
            codec.start()

            var sampleRate = inputFormat.getIntegerOrDefault(MediaFormat.KEY_SAMPLE_RATE, 44_100)
            var channels = inputFormat.getIntegerOrDefault(MediaFormat.KEY_CHANNEL_COUNT, 1)
            var pcmEncoding = AudioFormat.ENCODING_PCM_16BIT
            var accumulator = PcmAccumulator(sampleRate, channels, expectedDurationUs)

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
                            accumulator = PcmAccumulator(sampleRate, channels, expectedDurationUs)
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

    private fun MediaFormat.getLongOrDefault(key: String, fallback: Long): Long =
        if (containsKey(key)) getLong(key) else fallback

    private data class PitchEstimate(val hz: Double, val confidence: Double)

    private class PcmAccumulator(
        private val sampleRate: Int,
        private val channels: Int,
        expectedDurationUs: Long
    ) {
        private val windowFrames = max(1, sampleRate / 50) // ~20 ms
        private val windowRms = ArrayList<Double>()
        private var totalSquares = 0.0
        private var totalFrames = 0L
        private var peak = 0.0
        private var currentWindowSquares = 0.0
        private var currentWindowFrames = 0

        private val pitchWindowSize = 2048
        private val pitchBuffer = FloatArray(pitchWindowSize)
        private var pitchFill = 0
        private var nextPitchStartFrame = 0L
        private val pitchEstimates = ArrayList<PitchEstimate>()
        private val pitchHopFrames: Long

        init {
            val expectedFrames = if (expectedDurationUs > 0L) {
                expectedDurationUs * sampleRate / 1_000_000L
            } else {
                sampleRate * 30L
            }
            pitchHopFrames = max(sampleRate / 5L, expectedFrames / 120L).coerceAtLeast(1L)
        }

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
            val frameIndex = totalFrames
            if (frameIndex >= nextPitchStartFrame && pitchFill < pitchWindowSize) {
                pitchBuffer[pitchFill++] = sample.toFloat()
                if (pitchFill == pitchWindowSize) {
                    analyzePitchWindow()
                    pitchFill = 0
                    nextPitchStartFrame = frameIndex + pitchHopFrames
                }
            }

            val square = sample * sample
            totalSquares += square
            totalFrames++
            peak = max(peak, abs(sample))
            currentWindowSquares += square
            currentWindowFrames++
            if (currentWindowFrames >= windowFrames) flushWindow()
        }

        private fun analyzePitchWindow() {
            var squares = 0.0
            for (sample in pitchBuffer) squares += sample * sample
            val blockRms = sqrt(squares / pitchBuffer.size)
            if (blockRms < 0.015) return
            YinPitchDetector.estimate(pitchBuffer, sampleRate)?.let(pitchEstimates::add)
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
            val pitch = summarizePitch(pitchEstimates)
            return AudioAnalysis(
                sampleRate = sampleRate,
                channelCount = channels,
                durationMs = durationMs,
                rms = rms,
                peak = peak,
                onsetTimesMs = detectOnsets(windowRms),
                pitchHz = pitch?.hz,
                midiNote = pitch?.let { hzToMidi(it.hz) },
                pitchConfidence = pitch?.confidence
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

        private fun summarizePitch(estimates: List<PitchEstimate>): PitchEstimate? {
            if (estimates.isEmpty()) return null
            val midiSorted = estimates.map { hzToMidi(it.hz) }.sorted()
            val medianMidi = median(midiSorted)
            val inliers = estimates.filter { abs(hzToMidi(it.hz) - medianMidi) <= 1.0 }
            if (inliers.isEmpty()) return null

            val inlierMidis = inliers.map { hzToMidi(it.hz) }.sorted()
            val stableMidi = median(inlierMidis)
            val stableHz = 440.0 * 2.0.pow((stableMidi - 69.0) / 12.0)
            val meanConfidence = inliers.sumOf { it.confidence } / inliers.size
            val stability = inliers.size.toDouble() / estimates.size
            return PitchEstimate(stableHz, (meanConfidence * stability).coerceIn(0.0, 1.0))
        }

        private fun median(values: List<Double>): Double {
            val middle = values.size / 2
            return if (values.size % 2 == 0) {
                (values[middle - 1] + values[middle]) / 2.0
            } else {
                values[middle]
            }
        }

        private fun hzToMidi(hz: Double): Double = 69.0 + 12.0 * (ln(hz / 440.0) / ln(2.0))
    }

    private object YinPitchDetector {
        private const val MIN_FREQ_HZ = 55.0
        private const val MAX_FREQ_HZ = 1200.0
        private const val THRESHOLD = 0.15

        fun estimate(frame: FloatArray, sampleRate: Int): PitchEstimate? {
            val tauMin = max(2, (sampleRate / MAX_FREQ_HZ).toInt())
            val tauMax = min(frame.size / 2, (sampleRate / MIN_FREQ_HZ).toInt())
            if (tauMax <= tauMin) return null

            val difference = DoubleArray(tauMax + 1)
            val comparisonLength = frame.size - tauMax
            for (tau in 1..tauMax) {
                var sum = 0.0
                for (i in 0 until comparisonLength) {
                    val delta = frame[i] - frame[i + tau]
                    sum += delta * delta
                }
                difference[tau] = sum
            }

            val cmnd = DoubleArray(tauMax + 1)
            cmnd[0] = 1.0
            var cumulative = 0.0
            for (tau in 1..tauMax) {
                cumulative += difference[tau]
                cmnd[tau] = if (cumulative <= 1e-12) 1.0 else difference[tau] * tau / cumulative
            }

            var tau = tauMin
            var found = false
            while (tau <= tauMax) {
                if (cmnd[tau] < THRESHOLD) {
                    while (tau + 1 <= tauMax && cmnd[tau + 1] < cmnd[tau]) tau++
                    found = true
                    break
                }
                tau++
            }
            if (!found) return null

            val confidence = (1.0 - cmnd[tau]).coerceIn(0.0, 1.0)
            if (confidence < 0.65) return null

            val refinedTau = parabolicTau(cmnd, tau)
            if (refinedTau <= 0.0) return null
            val hz = sampleRate / refinedTau
            if (hz !in MIN_FREQ_HZ..MAX_FREQ_HZ) return null
            return PitchEstimate(hz, confidence)
        }

        private fun parabolicTau(values: DoubleArray, tau: Int): Double {
            if (tau <= 1 || tau >= values.lastIndex) return tau.toDouble()
            val y0 = values[tau - 1]
            val y1 = values[tau]
            val y2 = values[tau + 1]
            val denominator = y0 - 2.0 * y1 + y2
            if (abs(denominator) < 1e-12) return tau.toDouble()
            val offset = 0.5 * (y0 - y2) / denominator
            return tau + offset.coerceIn(-1.0, 1.0)
        }
    }
}
