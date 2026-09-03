package dev.videomosaic.app.mosaic

import android.net.Uri
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.audio.SpeedProvider
import androidx.media3.common.util.UnstableApi
import androidx.media3.transformer.Composition
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.EditedMediaItemSequence
import dev.videomosaic.app.model.MediaAsset
import dev.videomosaic.app.model.ToneEvent
import dev.videomosaic.app.model.VideoMosaicProject
import kotlin.math.abs
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min

@UnstableApi
object MosaicComposer {
    data class MatchedClip(
        val targetIndex: Int,
        val targetStartMs: Long,
        val targetDurationMs: Long,
        val targetMidi: Double?,
        val sourceName: String,
        val sourceUri: String,
        val sourceStartMs: Long,
        val sourceDurationMs: Long,
        val sourceMidi: Double?,
        val pitchDistanceSemitones: Double?,
        val playbackSpeed: Float
    )

    data class MosaicBuild(
        val composition: Composition,
        val matches: List<MatchedClip>,
        val targetDurationMs: Long
    )

    private data class Candidate(val asset: MediaAsset, val event: ToneEvent)

    fun build(project: VideoMosaicProject): MosaicBuild {
        val target = project.targetAudio ?: error("Сначала выберите целевую музыку")
        val targetAnalysis = target.analysis ?: error("Сначала проанализируйте целевую музыку")
        val targetEvents = targetAnalysis.toneEvents.ifEmpty {
            listOf(
                ToneEvent(
                    startMs = 0L,
                    durationMs = targetAnalysis.durationMs,
                    pitchHz = targetAnalysis.pitchHz,
                    midiNote = targetAnalysis.midiNote,
                    confidence = targetAnalysis.pitchConfidence ?: 0.0
                )
            )
        }.filter { it.durationMs >= 35L }
        require(targetEvents.isNotEmpty()) { "В целевой музыке не найдено событий" }

        val candidates = project.samples.flatMap { asset ->
            val analysis = asset.analysis ?: return@flatMap emptyList()
            val events = analysis.toneEvents.ifEmpty {
                listOf(
                    ToneEvent(
                        startMs = 0L,
                        durationMs = analysis.durationMs,
                        pitchHz = analysis.pitchHz,
                        midiNote = analysis.midiNote,
                        confidence = analysis.pitchConfidence ?: 0.0
                    )
                )
            }
            events.filter { it.durationMs >= 35L }.map { Candidate(asset, it) }
        }
        require(candidates.isNotEmpty()) { "Сначала проанализируйте хотя бы одно видео с аудиодорожкой" }

        val reuseCount = HashMap<String, Int>()
        var previousAssetId: String? = null
        val matches = ArrayList<MatchedClip>(targetEvents.size)
        val editedItems = ArrayList<EditedMediaItem>(targetEvents.size)

        targetEvents.forEachIndexed { index, targetEvent ->
            val candidate = candidates.minBy { candidate ->
                score(targetEvent, candidate, reuseCount[candidate.asset.id] ?: 0, previousAssetId)
            }
            val sourceWindow = fitSourceWindow(candidate, targetEvent.durationMs)
            val speed = (sourceWindow.second.toDouble() / targetEvent.durationMs.coerceAtLeast(1L))
                .toFloat()
                .coerceIn(0.08f, 12f)

            val sourceDuration = candidate.asset.durationMs
                ?: candidate.asset.analysis?.durationMs
                ?: (sourceWindow.first + sourceWindow.second)
            val clipping = MediaItem.ClippingConfiguration.Builder()
                .setStartPositionMs(sourceWindow.first)
                .setEndPositionMs(sourceWindow.first + sourceWindow.second)
                .build()
            val mediaItem = MediaItem.Builder()
                .setUri(Uri.parse(candidate.asset.uri))
                .setClippingConfiguration(clipping)
                .build()
            val edited = EditedMediaItem.Builder(mediaItem)
                .setDurationUs(max(1L, sourceDuration) * 1000L)
                .setSpeed(ConstantSpeedProvider(speed))
                .build()
            editedItems += edited

            val distance = if (targetEvent.midiNote != null && candidate.event.midiNote != null) {
                abs(targetEvent.midiNote - candidate.event.midiNote)
            } else null
            matches += MatchedClip(
                targetIndex = index,
                targetStartMs = targetEvent.startMs,
                targetDurationMs = targetEvent.durationMs,
                targetMidi = targetEvent.midiNote,
                sourceName = candidate.asset.displayName,
                sourceUri = candidate.asset.uri,
                sourceStartMs = sourceWindow.first,
                sourceDurationMs = sourceWindow.second,
                sourceMidi = candidate.event.midiNote,
                pitchDistanceSemitones = distance,
                playbackSpeed = speed
            )
            reuseCount[candidate.asset.id] = (reuseCount[candidate.asset.id] ?: 0) + 1
            previousAssetId = candidate.asset.id
        }

        val sequence = EditedMediaItemSequence.withAudioAndVideoFrom(editedItems)
        val composition = Composition.Builder(sequence).build()
        return MosaicBuild(
            composition = composition,
            matches = matches,
            targetDurationMs = targetAnalysis.durationMs
        )
    }

    private fun score(
        target: ToneEvent,
        candidate: Candidate,
        reuse: Int,
        previousAssetId: String?
    ): Double {
        val pitchCost = when {
            target.midiNote != null && candidate.event.midiNote != null ->
                abs(target.midiNote - candidate.event.midiNote) * 8.0
            target.midiNote == null -> 3.0 - candidate.event.confidence.coerceIn(0.0, 1.0)
            else -> 60.0
        }
        val targetDuration = target.durationMs.coerceAtLeast(1L).toDouble()
        val sourceDuration = candidate.event.durationMs.coerceAtLeast(1L).toDouble()
        val durationCost = abs(ln(sourceDuration / targetDuration)) * 1.8
        val confidenceCost = (1.0 - candidate.event.confidence.coerceIn(0.0, 1.0)) * 2.0
        val reuseCost = reuse * 0.65
        val consecutiveCost = if (previousAssetId == candidate.asset.id) 0.45 else 0.0
        return pitchCost + durationCost + confidenceCost + reuseCost + consecutiveCost
    }

    private fun fitSourceWindow(candidate: Candidate, targetDurationMs: Long): Pair<Long, Long> {
        val assetDuration = candidate.asset.durationMs
            ?: candidate.asset.analysis?.durationMs
            ?: (candidate.event.startMs + candidate.event.durationMs)
        val target = targetDurationMs.coerceAtLeast(40L)
        val minUseful = max(40L, target / 2L)
        val maxUseful = max(minUseful, target * 2L)
        var desired = candidate.event.durationMs.coerceIn(minUseful, maxUseful)
        desired = min(desired, assetDuration.coerceAtLeast(40L))

        var start = candidate.event.startMs.coerceIn(0L, max(0L, assetDuration - 1L))
        if (start + desired > assetDuration) {
            start = max(0L, assetDuration - desired)
        }
        val available = max(1L, assetDuration - start)
        val duration = min(desired, available).coerceAtLeast(1L)
        return start to duration
    }

    private class ConstantSpeedProvider(private val speed: Float) : SpeedProvider {
        override fun getSpeed(timeUs: Long): Float = speed
        override fun getNextSpeedChangeTimeUs(timeUs: Long): Long = C.TIME_UNSET
    }
}
