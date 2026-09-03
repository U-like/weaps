package dev.videomosaic.app.model

data class ToneEvent(
    val startMs: Long,
    val durationMs: Long,
    val pitchHz: Double? = null,
    val midiNote: Double? = null,
    val confidence: Double = 0.0
)

data class AudioAnalysis(
    val sampleRate: Int,
    val channelCount: Int,
    val durationMs: Long,
    val rms: Double,
    val peak: Double,
    val onsetTimesMs: List<Long>,
    val pitchHz: Double? = null,
    val midiNote: Double? = null,
    val pitchConfidence: Double? = null,
    val toneEvents: List<ToneEvent> = emptyList()
)

data class MediaAsset(
    val id: String,
    val uri: String,
    val displayName: String,
    val mimeType: String?,
    val sizeBytes: Long?,
    val durationMs: Long?,
    val width: Int?,
    val height: Int?,
    val addedAtEpochMs: Long,
    val analysis: AudioAnalysis? = null
)

data class VideoMosaicProject(
    val schemaVersion: Int = 2,
    val targetAudio: MediaAsset? = null,
    val samples: List<MediaAsset> = emptyList(),
    val updatedAtEpochMs: Long = System.currentTimeMillis()
)
