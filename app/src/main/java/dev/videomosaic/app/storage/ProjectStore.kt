package dev.videomosaic.app.storage

import android.content.Context
import dev.videomosaic.app.model.AudioAnalysis
import dev.videomosaic.app.model.MediaAsset
import dev.videomosaic.app.model.VideoMosaicProject
import org.json.JSONArray
import org.json.JSONObject

class ProjectStore(context: Context) {
    private val file = context.filesDir.resolve("videomosaic-project.json")

    fun load(): VideoMosaicProject {
        if (!file.exists()) return VideoMosaicProject()
        return runCatching { projectFromJson(JSONObject(file.readText())) }
            .getOrElse { VideoMosaicProject() }
    }

    fun save(project: VideoMosaicProject) {
        file.writeText(projectToJson(project).toString(2))
    }

    fun clear() {
        if (file.exists()) file.delete()
    }

    private fun projectToJson(project: VideoMosaicProject): JSONObject = JSONObject().apply {
        put("schemaVersion", project.schemaVersion)
        put("updatedAtEpochMs", project.updatedAtEpochMs)
        put("targetAudio", project.targetAudio?.let(::assetToJson) ?: JSONObject.NULL)
        put("samples", JSONArray().apply { project.samples.forEach { put(assetToJson(it)) } })
    }

    private fun assetToJson(asset: MediaAsset): JSONObject = JSONObject().apply {
        put("id", asset.id)
        put("uri", asset.uri)
        put("displayName", asset.displayName)
        put("mimeType", asset.mimeType ?: JSONObject.NULL)
        put("sizeBytes", asset.sizeBytes ?: JSONObject.NULL)
        put("durationMs", asset.durationMs ?: JSONObject.NULL)
        put("width", asset.width ?: JSONObject.NULL)
        put("height", asset.height ?: JSONObject.NULL)
        put("addedAtEpochMs", asset.addedAtEpochMs)
        put("analysis", asset.analysis?.let(::analysisToJson) ?: JSONObject.NULL)
    }

    private fun analysisToJson(analysis: AudioAnalysis): JSONObject = JSONObject().apply {
        put("sampleRate", analysis.sampleRate)
        put("channelCount", analysis.channelCount)
        put("durationMs", analysis.durationMs)
        put("rms", analysis.rms)
        put("peak", analysis.peak)
        put("onsetTimesMs", JSONArray().apply { analysis.onsetTimesMs.forEach { put(it) } })
    }

    private fun projectFromJson(json: JSONObject): VideoMosaicProject {
        val samplesJson = json.optJSONArray("samples") ?: JSONArray()
        val samples = buildList {
            for (i in 0 until samplesJson.length()) {
                samplesJson.optJSONObject(i)?.let { add(assetFromJson(it)) }
            }
        }
        return VideoMosaicProject(
            schemaVersion = json.optInt("schemaVersion", 1),
            targetAudio = json.optJSONObject("targetAudio")?.let(::assetFromJson),
            samples = samples,
            updatedAtEpochMs = json.optLong("updatedAtEpochMs", System.currentTimeMillis())
        )
    }

    private fun assetFromJson(json: JSONObject): MediaAsset = MediaAsset(
        id = json.getString("id"),
        uri = json.getString("uri"),
        displayName = json.optString("displayName", "media"),
        mimeType = json.nullableString("mimeType"),
        sizeBytes = json.nullableLong("sizeBytes"),
        durationMs = json.nullableLong("durationMs"),
        width = json.nullableInt("width"),
        height = json.nullableInt("height"),
        addedAtEpochMs = json.optLong("addedAtEpochMs", System.currentTimeMillis()),
        analysis = json.optJSONObject("analysis")?.let(::analysisFromJson)
    )

    private fun analysisFromJson(json: JSONObject): AudioAnalysis {
        val onsetsJson = json.optJSONArray("onsetTimesMs") ?: JSONArray()
        val onsets = buildList {
            for (i in 0 until onsetsJson.length()) add(onsetsJson.optLong(i))
        }
        return AudioAnalysis(
            sampleRate = json.optInt("sampleRate"),
            channelCount = json.optInt("channelCount"),
            durationMs = json.optLong("durationMs"),
            rms = json.optDouble("rms"),
            peak = json.optDouble("peak"),
            onsetTimesMs = onsets
        )
    }

    private fun JSONObject.nullableString(key: String): String? =
        if (!has(key) || isNull(key)) null else optString(key, null)

    private fun JSONObject.nullableLong(key: String): Long? =
        if (!has(key) || isNull(key)) null else optLong(key)

    private fun JSONObject.nullableInt(key: String): Int? =
        if (!has(key) || isNull(key)) null else optInt(key)
}
