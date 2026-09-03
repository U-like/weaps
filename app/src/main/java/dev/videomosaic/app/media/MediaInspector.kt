package dev.videomosaic.app.media

import android.content.Context
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.OpenableColumns
import dev.videomosaic.app.model.MediaAsset
import java.util.UUID

object MediaInspector {
    fun inspect(context: Context, uri: Uri): MediaAsset {
        val resolver = context.contentResolver
        var displayName = uri.lastPathSegment ?: "media"
        var sizeBytes: Long? = null

        resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (nameIndex >= 0 && !cursor.isNull(nameIndex)) displayName = cursor.getString(nameIndex)
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) sizeBytes = cursor.getLong(sizeIndex)
            }
        }

        var durationMs: Long? = null
        var width: Int? = null
        var height: Int? = null
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(context, uri)
            durationMs = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull()
            width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull()
            height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull()
        } catch (_: Throwable) {
            // Metadata is optional. The persisted URI is still useful even when probing fails.
        } finally {
            retriever.release()
        }

        return MediaAsset(
            id = UUID.randomUUID().toString(),
            uri = uri.toString(),
            displayName = displayName,
            mimeType = resolver.getType(uri),
            sizeBytes = sizeBytes,
            durationMs = durationMs,
            width = width,
            height = height,
            addedAtEpochMs = System.currentTimeMillis()
        )
    }
}
