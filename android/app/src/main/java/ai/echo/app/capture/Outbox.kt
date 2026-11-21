package ai.echo.app.capture

import ai.echo.app.data.SegmentMeta
import android.content.Context
import kotlinx.serialization.json.Json
import java.io.File
import java.security.MessageDigest

/** Durable on-device queue: each segment = audio file + JSON metadata, deleted only after the server accepts it. */
class Outbox(context: Context) {
    val dir: File = File(context.filesDir, "outbox").apply { mkdirs() }
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    data class Item(val meta: SegmentMeta, val audio: File, val metaFile: File)

    fun put(meta: SegmentMeta, audio: File) {
        val metaFile = File(dir, "${meta.segment_id}.json")
        val tmp = File(dir, "${meta.segment_id}.json.tmp")
        tmp.writeText(json.encodeToString(SegmentMeta.serializer(), meta))
        tmp.renameTo(metaFile)
        enforceCap()
    }

    fun pending(): List<Item> = dir.listFiles { f -> f.name.endsWith(".json") }.orEmpty()
        .sortedBy { it.lastModified() }
        .mapNotNull { mf ->
            val meta = runCatching { json.decodeFromString(SegmentMeta.serializer(), mf.readText()) }.getOrNull()
            val audio = meta?.let { m -> listOf("ogg", "wav").map { File(dir, "${m.segment_id}.$it") }.firstOrNull { it.exists() } }
            if (meta == null || audio == null) { mf.delete(); null } else Item(meta, audio, mf)
        }

    fun remove(item: Item) {
        item.audio.delete()
        item.metaFile.delete()
    }

    fun count(): Int = dir.listFiles { f -> f.name.endsWith(".json") }?.size ?: 0

    fun bytes(): Long = dir.listFiles().orEmpty().sumOf { it.length() }

    private fun enforceCap() {
        var total = bytes()
        if (total <= MAX_BYTES) return
        for (item in pending()) {
            if (total <= MAX_BYTES * 0.9) break
            total -= item.audio.length() + item.metaFile.length()
            remove(item)
        }
    }

    companion object {
        const val MAX_BYTES = 500L * 1024 * 1024

        fun sha256(file: File): String {
            val md = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buf = ByteArray(16 * 1024)
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    md.update(buf, 0, n)
                }
            }
            return md.digest().joinToString("") { "%02x".format(it) }
        }
    }
}
