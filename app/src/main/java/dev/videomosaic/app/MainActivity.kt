package dev.videomosaic.app

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import dev.videomosaic.app.audio.AudioAnalyzer
import dev.videomosaic.app.media.MediaInspector
import dev.videomosaic.app.model.AudioAnalysis
import dev.videomosaic.app.model.MediaAsset
import dev.videomosaic.app.model.VideoMosaicProject
import dev.videomosaic.app.storage.ProjectStore
import java.util.Locale
import kotlin.concurrent.thread
import kotlin.math.log10
import kotlin.math.roundToInt

class MainActivity : Activity() {
    companion object {
        private const val REQUEST_TARGET_AUDIO = 1001
        private const val REQUEST_SAMPLE_VIDEOS = 1002
        private val NOTE_NAMES = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    }

    private lateinit var projectStore: ProjectStore
    private var project = VideoMosaicProject()

    private lateinit var targetDetails: TextView
    private lateinit var analysisDetails: TextView
    private lateinit var sampleSummary: TextView
    private lateinit var samplesContainer: LinearLayout
    private lateinit var statusText: TextView
    private lateinit var analyzeButton: Button
    private lateinit var analyzeSamplesButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        projectStore = ProjectStore(this)
        project = projectStore.load()
        setContentView(buildUi())
        renderProject()
    }

    private fun buildUi(): View {
        val density = resources.displayMetrics.density
        val pagePadding = (18 * density).toInt()

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pagePadding, pagePadding, pagePadding, pagePadding)
        }

        content.addView(TextView(this).apply {
            text = "VideoMosaic"
            textSize = 30f
            setTextColor(Color.rgb(25, 25, 28))
        })
        content.addView(TextView(this).apply {
            text = "Песня → ноты/атаки → видеосэмплы. Анализ выполняется локально."
            textSize = 15f
            setTextColor(Color.rgb(80, 80, 86))
            setPadding(0, dp(4), 0, dp(18))
        })

        content.addView(sectionTitle("Целевая музыка"))
        targetDetails = cardText()
        content.addView(targetDetails)
        content.addView(actionButton("Выбрать музыку") { pickTargetAudio() })

        analyzeButton = actionButton("Анализировать аудио") { analyzeTargetAudio() }
        content.addView(analyzeButton)
        analysisDetails = cardText()
        content.addView(analysisDetails)

        content.addView(sectionTitle("Библиотека видеосэмплов"))
        sampleSummary = TextView(this).apply {
            textSize = 14f
            setTextColor(Color.rgb(80, 80, 86))
            setPadding(0, dp(2), 0, dp(8))
        }
        content.addView(sampleSummary)
        content.addView(actionButton("Добавить видео") { pickSampleVideos() })
        analyzeSamplesButton = actionButton("Анализировать видео-библиотеку") { analyzeSampleLibrary() }
        content.addView(analyzeSamplesButton)
        samplesContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        content.addView(samplesContainer)

        content.addView(sectionTitle("Проект"))
        content.addView(actionButton("Очистить проект") { clearProject() })

        statusText = TextView(this).apply {
            textSize = 13f
            setTextColor(Color.rgb(90, 90, 96))
            setPadding(0, dp(14), 0, dp(24))
        }
        content.addView(statusText)

        return ScrollView(this).apply { addView(content) }
    }

    private fun sectionTitle(text: String) = TextView(this).apply {
        this.text = text
        textSize = 20f
        setTextColor(Color.rgb(30, 30, 34))
        setPadding(0, dp(12), 0, dp(8))
    }

    private fun cardText() = TextView(this).apply {
        textSize = 14f
        setTextColor(Color.rgb(45, 45, 50))
        setPadding(dp(14), dp(12), dp(14), dp(12))
        background = GradientDrawable().apply {
            setColor(Color.rgb(245, 245, 248))
            cornerRadius = dp(12).toFloat()
            setStroke(dp(1), Color.rgb(222, 222, 228))
        }
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(8) }
    }

    private fun actionButton(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(8) }
    }

    private fun pickTargetAudio() {
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "audio/*"
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }, REQUEST_TARGET_AUDIO)
    }

    private fun pickSampleVideos() {
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "video/*"
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }, REQUEST_SAMPLE_VIDEOS)
    }

    @Deprecated("Legacy Activity result API keeps this zero-dependency scaffold portable")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data == null) return

        when (requestCode) {
            REQUEST_TARGET_AUDIO -> data.data?.let { importTargetAudio(it) }
            REQUEST_SAMPLE_VIDEOS -> {
                val uris = buildList {
                    data.data?.let(::add)
                    val clipData = data.clipData
                    if (clipData != null) {
                        for (i in 0 until clipData.itemCount) add(clipData.getItemAt(i).uri)
                    }
                }.distinctBy(Uri::toString)
                if (uris.isNotEmpty()) importSampleVideos(uris)
            }
        }
    }

    private fun importTargetAudio(uri: Uri) {
        persistReadPermission(uri)
        setStatus("Читаю метаданные музыки…")
        thread(name = "target-import") {
            runCatching { MediaInspector.inspect(applicationContext, uri) }
                .onSuccess { asset ->
                    runOnUiThread {
                        project = project.copy(
                            targetAudio = asset,
                            updatedAtEpochMs = System.currentTimeMillis()
                        )
                        saveAndRender("Музыка добавлена")
                    }
                }
                .onFailure { showError("Не удалось открыть музыку", it) }
        }
    }

    private fun importSampleVideos(uris: List<Uri>) {
        uris.forEach(::persistReadPermission)
        setStatus("Импортирую видео: ${uris.size}…")
        thread(name = "sample-import") {
            val imported = uris.mapNotNull { uri ->
                runCatching { MediaInspector.inspect(applicationContext, uri) }.getOrNull()
            }
            runOnUiThread {
                val existingUris = project.samples.mapTo(HashSet()) { it.uri }
                val unique = imported.filter { existingUris.add(it.uri) }
                project = project.copy(
                    samples = project.samples + unique,
                    updatedAtEpochMs = System.currentTimeMillis()
                )
                saveAndRender("Добавлено видео: ${unique.size}")
            }
        }
    }

    private fun analyzeTargetAudio() {
        val target = project.targetAudio ?: return
        analyzeButton.isEnabled = false
        setStatus("Декодирую PCM, ищу атаки и высоту тона…")
        thread(name = "audio-analysis") {
            runCatching { AudioAnalyzer.analyze(applicationContext, Uri.parse(target.uri)) }
                .onSuccess { analysis ->
                    runOnUiThread {
                        val current = project.targetAudio
                        if (current?.id == target.id) {
                            project = project.copy(
                                targetAudio = current.copy(analysis = analysis),
                                updatedAtEpochMs = System.currentTimeMillis()
                            )
                            saveAndRender("Аудио проанализировано: ${analysis.onsetTimesMs.size} атак")
                        } else {
                            analyzeButton.isEnabled = project.targetAudio != null
                        }
                    }
                }
                .onFailure { error ->
                    runOnUiThread { analyzeButton.isEnabled = project.targetAudio != null }
                    showError("Ошибка анализа аудио", error)
                }
        }
    }

    private fun analyzeSampleLibrary() {
        val queue = project.samples.toList()
        if (queue.isEmpty()) return
        analyzeSamplesButton.isEnabled = false
        thread(name = "sample-audio-analysis") {
            var successCount = 0
            var failedCount = 0
            queue.forEachIndexed { index, asset ->
                runOnUiThread {
                    setStatus("Анализ видео ${index + 1}/${queue.size}: ${asset.displayName}")
                }
                runCatching { AudioAnalyzer.analyze(applicationContext, Uri.parse(asset.uri)) }
                    .onSuccess { analysis ->
                        successCount++
                        runOnUiThread {
                            project = project.copy(
                                samples = project.samples.map {
                                    if (it.id == asset.id) it.copy(analysis = analysis) else it
                                },
                                updatedAtEpochMs = System.currentTimeMillis()
                            )
                            projectStore.save(project)
                            renderProject()
                        }
                    }
                    .onFailure { failedCount++ }
            }
            runOnUiThread {
                analyzeSamplesButton.isEnabled = project.samples.isNotEmpty()
                setStatus("Видео проанализированы: $successCount, без аудио/ошибка: $failedCount")
            }
        }
    }

    private fun removeSample(asset: MediaAsset) {
        project = project.copy(
            samples = project.samples.filterNot { it.id == asset.id },
            updatedAtEpochMs = System.currentTimeMillis()
        )
        saveAndRender("Сэмпл удалён")
    }

    private fun clearProject() {
        val uris = buildList {
            project.targetAudio?.uri?.let { add(Uri.parse(it)) }
            project.samples.forEach { add(Uri.parse(it.uri)) }
        }
        uris.forEach { uri ->
            runCatching { contentResolver.releasePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
        }
        projectStore.clear()
        project = VideoMosaicProject()
        renderProject()
        setStatus("Проект очищен")
    }

    private fun saveAndRender(status: String) {
        projectStore.save(project)
        renderProject()
        setStatus(status)
    }

    private fun renderProject() {
        val target = project.targetAudio
        targetDetails.text = if (target == null) {
            "Музыка не выбрана"
        } else {
            buildString {
                append(target.displayName)
                target.durationMs?.let { append("\nДлительность: ${formatDuration(it)}") }
                target.sizeBytes?.let { append("\nРазмер: ${formatBytes(it)}") }
                target.mimeType?.let { append("\n$it") }
            }
        }

        analyzeButton.isEnabled = target != null
        analysisDetails.text = target?.analysis?.let { analysis ->
            val rmsDb = amplitudeDb(analysis.rms)
            val peakDb = amplitudeDb(analysis.peak)
            val preview = analysis.onsetTimesMs.take(12).joinToString { formatDuration(it) }
            buildString {
                append("PCM: ${analysis.sampleRate} Hz, ${analysis.channelCount} ch")
                append("\nRMS: ${formatDb(rmsDb)} dBFS   Peak: ${formatDb(peakDb)} dBFS")
                append("\nНайдено атак: ${analysis.onsetTimesMs.size}")
                pitchSummary(analysis)?.let { append("\nДоминирующий тон: $it") }
                if (preview.isNotBlank()) append("\nПервые атаки: $preview")
            }
        } ?: "Анализ ещё не запускался"

        val analyzedCount = project.samples.count { it.analysis != null }
        val pitchedCount = project.samples.count { it.analysis?.pitchHz != null }
        sampleSummary.text = "Видео: ${project.samples.size} · анализ: $analyzedCount · тон найден: $pitchedCount"
        analyzeSamplesButton.isEnabled = project.samples.isNotEmpty()
        samplesContainer.removeAllViews()
        project.samples.forEachIndexed { index, asset ->
            samplesContainer.addView(sampleRow(index, asset))
        }
    }

    private fun sampleRow(index: Int, asset: MediaAsset): View {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(10), dp(14), dp(10))
            background = GradientDrawable().apply {
                setColor(Color.rgb(248, 248, 250))
                cornerRadius = dp(10).toFloat()
                setStroke(dp(1), Color.rgb(228, 228, 232))
            }
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(8) }
        }

        row.addView(TextView(this).apply {
            textSize = 15f
            setTextColor(Color.rgb(35, 35, 40))
            text = "${index + 1}. ${asset.displayName}"
        })
        row.addView(TextView(this).apply {
            textSize = 13f
            setTextColor(Color.rgb(90, 90, 96))
            text = buildString {
                asset.durationMs?.let { append(formatDuration(it)) }
                if (asset.width != null && asset.height != null) {
                    if (isNotEmpty()) append(" · ")
                    append("${asset.width}×${asset.height}")
                }
                asset.sizeBytes?.let {
                    if (isNotEmpty()) append(" · ")
                    append(formatBytes(it))
                }
                asset.analysis?.let { analysis ->
                    append("\nАудио: ${analysis.sampleRate} Hz · ${analysis.onsetTimesMs.size} атак")
                    append(" · RMS ${formatDb(amplitudeDb(analysis.rms))} dBFS")
                    pitchSummary(analysis)?.let { append("\nТон: $it") }
                }
            }.ifBlank { asset.mimeType ?: "video" }
        })
        row.addView(Button(this).apply {
            text = "Удалить"
            isAllCaps = false
            gravity = Gravity.CENTER
            setOnClickListener { removeSample(asset) }
        })
        return row
    }

    private fun pitchSummary(analysis: AudioAnalysis): String? {
        val hz = analysis.pitchHz ?: return null
        val midi = analysis.midiNote ?: return null
        val roundedMidi = midi.roundToInt()
        val pitchClass = ((roundedMidi % 12) + 12) % 12
        val octave = roundedMidi / 12 - 1
        val confidence = ((analysis.pitchConfidence ?: 0.0) * 100.0).roundToInt()
        return String.format(
            Locale.US,
            "%s%d · %.1f Hz · confidence %d%%",
            NOTE_NAMES[pitchClass],
            octave,
            hz,
            confidence
        )
    }

    private fun persistReadPermission(uri: Uri) {
        runCatching {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }

    private fun setStatus(message: String) {
        statusText.text = message
    }

    private fun showError(prefix: String, error: Throwable) {
        runOnUiThread {
            val message = "$prefix: ${error.message ?: error.javaClass.simpleName}"
            setStatus(message)
            Toast.makeText(this, message, Toast.LENGTH_LONG).show()
        }
    }

    private fun formatDuration(ms: Long): String {
        val totalSeconds = ms / 1000.0
        return if (totalSeconds < 60.0) {
            String.format(Locale.US, "%.2f с", totalSeconds)
        } else {
            val minutes = (totalSeconds / 60).toInt()
            val seconds = totalSeconds - minutes * 60
            String.format(Locale.US, "%d:%05.2f", minutes, seconds)
        }
    }

    private fun formatBytes(bytes: Long): String = when {
        bytes >= 1024L * 1024L * 1024L -> String.format(Locale.US, "%.2f ГБ", bytes / (1024.0 * 1024.0 * 1024.0))
        bytes >= 1024L * 1024L -> String.format(Locale.US, "%.1f МБ", bytes / (1024.0 * 1024.0))
        bytes >= 1024L -> String.format(Locale.US, "%.1f КБ", bytes / 1024.0)
        else -> "$bytes Б"
    }

    private fun amplitudeDb(amplitude: Double): Double = 20.0 * log10(amplitude.coerceAtLeast(1e-9))
    private fun formatDb(value: Double): String = String.format(Locale.US, "%.1f", value)
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
