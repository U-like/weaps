package dev.videomosaic.app

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.ExperimentalApi
import androidx.media3.common.util.UnstableApi
import androidx.media3.transformer.Composition
import androidx.media3.transformer.CompositionPlayer
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.Transformer
import androidx.media3.ui.PlayerView
import dev.videomosaic.app.audio.AudioAnalyzer
import dev.videomosaic.app.media.MediaInspector
import dev.videomosaic.app.model.AudioAnalysis
import dev.videomosaic.app.model.MediaAsset
import dev.videomosaic.app.model.VideoMosaicProject
import dev.videomosaic.app.mosaic.MosaicComposer
import dev.videomosaic.app.storage.ProjectStore
import java.io.File
import java.util.Locale
import kotlin.concurrent.thread
import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.roundToInt

@UnstableApi
@OptIn(ExperimentalApi::class)
class MainActivity : Activity() {
    companion object {
        private const val REQUEST_TARGET_AUDIO = 1001
        private const val REQUEST_SAMPLE_VIDEOS = 1002
        private val NOTE_NAMES = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    }

    private lateinit var projectStore: ProjectStore
    private var project = VideoMosaicProject()
    private var mosaicBuild: MosaicComposer.MosaicBuild? = null
    private var compositionPlayer: CompositionPlayer? = null
    private var transformer: Transformer? = null

    private lateinit var playerView: PlayerView
    private lateinit var targetDetails: TextView
    private lateinit var analysisDetails: TextView
    private lateinit var sampleSummary: TextView
    private lateinit var samplesContainer: LinearLayout
    private lateinit var planDetails: TextView
    private lateinit var statusText: TextView
    private lateinit var analyzeButton: Button
    private lateinit var analyzeSamplesButton: Button
    private lateinit var buildButton: Button
    private lateinit var exportButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        projectStore = ProjectStore(this)
        project = projectStore.load()
        setContentView(buildUi())
        renderProject()
    }

    override fun onDestroy() {
        playerView.player = null
        compositionPlayer?.release()
        compositionPlayer = null
        transformer?.cancel()
        transformer = null
        super.onDestroy()
    }

    private fun buildUi(): View {
        val pagePadding = dp(18)
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pagePadding, pagePadding, pagePadding, pagePadding)
        }

        content.addView(TextView(this).apply {
            text = "VideoMosaic 0.5.0"
            textSize = 30f
            setTextColor(Color.rgb(25, 25, 28))
        })
        content.addView(TextView(this).apply {
            text = "Ноты целевой музыки → подобранные видеофрагменты → единый ролик."
            textSize = 15f
            setTextColor(Color.rgb(80, 80, 86))
            setPadding(0, dp(4), 0, dp(14))
        })

        content.addView(sectionTitle("Предпросмотр результата"))
        playerView = PlayerView(this).apply {
            useController = true
            setBackgroundColor(Color.BLACK)
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(240)
            ).apply { bottomMargin = dp(10) }
        }
        content.addView(playerView)

        content.addView(sectionTitle("Целевая музыка"))
        targetDetails = cardText()
        content.addView(targetDetails)
        content.addView(actionButton("Выбрать музыку") { pickTargetAudio() })
        analyzeButton = actionButton("1. Анализировать музыку по нотам/атакам") { analyzeTargetAudio() }
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
        analyzeSamplesButton = actionButton("2. Нарезать и проанализировать видео") { analyzeSampleLibrary() }
        content.addView(analyzeSamplesButton)
        samplesContainer = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        content.addView(samplesContainer)

        content.addView(sectionTitle("Автоматическая сборка"))
        buildButton = actionButton("3. Подобрать ноты и запустить предпросмотр") { buildAndPreviewMosaic() }
        content.addView(buildButton)
        planDetails = cardText()
        content.addView(planDetails)
        exportButton = actionButton("4. Экспортировать MP4") { exportMosaic() }
        exportButton.isEnabled = false
        content.addView(exportButton)

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

    @Deprecated("Legacy Activity result API keeps the scaffold dependency-light")
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
                        invalidateMosaic()
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
                invalidateMosaic()
                saveAndRender("Добавлено видео: ${unique.size}")
            }
        }
    }

    private fun analyzeTargetAudio() {
        val target = project.targetAudio ?: return
        analyzeButton.isEnabled = false
        setStatus("Декодирую музыку, ищу атаки и тон каждого фрагмента…")
        thread(name = "target-audio-analysis") {
            runCatching { AudioAnalyzer.analyze(applicationContext, Uri.parse(target.uri)) }
                .onSuccess { analysis ->
                    runOnUiThread {
                        val current = project.targetAudio
                        if (current?.id == target.id) {
                            project = project.copy(
                                targetAudio = current.copy(analysis = analysis),
                                updatedAtEpochMs = System.currentTimeMillis()
                            )
                            invalidateMosaic()
                            saveAndRender("Музыка: ${analysis.toneEvents.size} событий, ${analysis.toneEvents.count { it.midiNote != null }} с тоном")
                        }
                    }
                }
                .onFailure { error ->
                    runOnUiThread { analyzeButton.isEnabled = project.targetAudio != null }
                    showError("Ошибка анализа музыки", error)
                }
        }
    }

    private fun analyzeSampleLibrary() {
        val queue = project.samples.toList()
        if (queue.isEmpty()) return
        analyzeSamplesButton.isEnabled = false
        setStatus("Начинаю анализ ${queue.size} видео…")
        thread(name = "sample-audio-analysis") {
            var successCount = 0
            var failedCount = 0
            queue.forEachIndexed { index, asset ->
                runOnUiThread { setStatus("Видео ${index + 1}/${queue.size}: ${asset.displayName}") }
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
                invalidateMosaic()
                analyzeSamplesButton.isEnabled = project.samples.isNotEmpty()
                setStatus("Видео проанализированы: $successCount, без аудио/ошибка: $failedCount")
            }
        }
    }

    private fun buildAndPreviewMosaic() {
        runCatching { MosaicComposer.build(project) }
            .onSuccess { build ->
                mosaicBuild = build
                startCompositionPreview(build.composition)
                renderPlan(build)
                exportButton.isEnabled = true
                setStatus("Предпросмотр собран. Оригинальная музыка не используется: звучит аудио выбранных видеофрагментов.")
            }
            .onFailure { showError("Не удалось собрать мозаику", it) }
    }

    private fun startCompositionPreview(composition: Composition) {
        playerView.player = null
        compositionPlayer?.release()
        val player = CompositionPlayer.Builder(this).build()
        player.addListener(object : Player.Listener {
            override fun onPlayerError(error: PlaybackException) {
                setStatus("Ошибка проигрывателя: ${error.message ?: error.errorCodeName}")
            }
        })
        compositionPlayer = player
        playerView.player = player
        player.setComposition(composition)
        player.prepare()
        player.play()
    }

    private fun exportMosaic() {
        val build = mosaicBuild ?: return
        if (transformer != null) return

        val directory = getExternalFilesDir(Environment.DIRECTORY_MOVIES) ?: filesDir.resolve("exports")
        directory.mkdirs()
        val output = File(directory, "VideoMosaic-${System.currentTimeMillis()}.mp4")
        if (output.exists()) output.delete()

        exportButton.isEnabled = false
        setStatus("Экспортирую MP4…")
        val exportTransformer = Transformer.Builder(this)
            .addListener(object : Transformer.Listener {
                override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                    transformer = null
                    exportButton.isEnabled = mosaicBuild != null
                    setStatus("MP4 готов: ${output.absolutePath}\nРазмер: ${formatBytes(output.length())}")
                    Toast.makeText(this@MainActivity, "Видео экспортировано", Toast.LENGTH_LONG).show()
                }

                override fun onError(
                    composition: Composition,
                    exportResult: ExportResult,
                    exportException: ExportException
                ) {
                    transformer = null
                    exportButton.isEnabled = mosaicBuild != null
                    showError("Ошибка экспорта", exportException)
                }
            })
            .build()
        transformer = exportTransformer
        exportTransformer.start(build.composition, output.absolutePath)
    }

    private fun renderPlan(build: MosaicComposer.MosaicBuild) {
        val withPitch = build.matches.filter { it.pitchDistanceSemitones != null }
        val meanError = if (withPitch.isEmpty()) null else withPitch.mapNotNull { it.pitchDistanceSemitones }.average()
        val preview = build.matches.take(12).joinToString("\n") { match ->
            val target = match.targetMidi?.let(::midiName) ?: "?"
            val source = match.sourceMidi?.let(::midiName) ?: "?"
            val speed = String.format(Locale.US, "%.2fx", match.playbackSpeed)
            "${match.targetIndex + 1}. $target ← $source · ${formatDuration(match.targetDurationMs)} · $speed · ${match.sourceName}"
        }
        planDetails.text = buildString {
            append("Фрагментов: ${build.matches.size}")
            append("\nДлительность цели: ${formatDuration(build.targetDurationMs)}")
            meanError?.let { append(String.format(Locale.US, "\nСредняя ошибка подбора: %.2f полутона", it)) }
            if (preview.isNotBlank()) append("\n\n$preview")
            if (build.matches.size > 12) append("\n…")
        }
    }

    private fun removeSample(asset: MediaAsset) {
        project = project.copy(
            samples = project.samples.filterNot { it.id == asset.id },
            updatedAtEpochMs = System.currentTimeMillis()
        )
        invalidateMosaic()
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
        invalidateMosaic()
        renderProject()
        setStatus("Проект очищен")
    }

    private fun invalidateMosaic() {
        mosaicBuild = null
        exportButton.takeIf { ::exportButton.isInitialized }?.isEnabled = false
        if (::planDetails.isInitialized) planDetails.text = "Мозаика ещё не собрана"
        if (::playerView.isInitialized) playerView.player = null
        compositionPlayer?.release()
        compositionPlayer = null
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
            val pitchedEvents = analysis.toneEvents.count { it.midiNote != null }
            val firstEvents = analysis.toneEvents.take(10).joinToString { event ->
                event.midiNote?.let(::midiName) ?: "?"
            }
            buildString {
                append("PCM: ${analysis.sampleRate} Hz, ${analysis.channelCount} ch")
                append("\nRMS: ${formatDb(rmsDb)} dBFS · Peak: ${formatDb(peakDb)} dBFS")
                append("\nСобытий: ${analysis.toneEvents.size} · с определённым тоном: $pitchedEvents")
                pitchSummary(analysis)?.let { append("\nОбщий тон: $it") }
                if (firstEvents.isNotBlank()) append("\nПервые ноты: $firstEvents")
            }
        } ?: "Анализ ещё не запускался"

        val analyzedCount = project.samples.count { it.analysis != null }
        val toneCount = project.samples.sumOf { it.analysis?.toneEvents?.size ?: 0 }
        val pitchedCount = project.samples.sumOf { asset -> asset.analysis?.toneEvents?.count { it.midiNote != null } ?: 0 }
        sampleSummary.text = "Видео: ${project.samples.size} · анализ: $analyzedCount · фрагментов: $toneCount · с тоном: $pitchedCount"
        analyzeSamplesButton.isEnabled = project.samples.isNotEmpty()
        buildButton.isEnabled = target?.analysis != null && project.samples.any { it.analysis != null }
        samplesContainer.removeAllViews()
        project.samples.forEachIndexed { index, asset -> samplesContainer.addView(sampleRow(index, asset)) }
        if (mosaicBuild == null) {
            planDetails.text = "После анализа музыки и видео нажмите «Подобрать ноты»"
            exportButton.isEnabled = false
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
                asset.analysis?.let { analysis ->
                    append("\nФрагментов: ${analysis.toneEvents.size} · с тоном: ${analysis.toneEvents.count { it.midiNote != null }}")
                    val notes = analysis.toneEvents.mapNotNull { it.midiNote }.take(8).joinToString { midiName(it) }
                    if (notes.isNotBlank()) append("\nНоты: $notes")
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
        val confidence = ((analysis.pitchConfidence ?: 0.0) * 100.0).roundToInt()
        return String.format(Locale.US, "%s · %.1f Hz · %d%%", midiName(midi), hz, confidence)
    }

    private fun midiName(midi: Double): String {
        val rounded = midi.roundToInt()
        val pitchClass = ((rounded % 12) + 12) % 12
        val octave = rounded / 12 - 1
        return "${NOTE_NAMES[pitchClass]}$octave"
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
