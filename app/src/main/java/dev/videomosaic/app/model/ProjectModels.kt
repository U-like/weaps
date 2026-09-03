package dev.videomosaic.app.model

data class AudioAnalysis(
    val sampleRate: Int,
    val channelCount: Int,
    val durationMs: Long,
    val rms: Double,
    val peak: Double,
    val onsetTimesMs: List<Long>
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
    val schemaVersion: Int = 1,
    val targetAudio: MediaAsset? = null,
    val samples: List<MediaAsset> = emptyList(),
    val updatedAtEpochMs: Long = System.currentTimeMillis()
)
