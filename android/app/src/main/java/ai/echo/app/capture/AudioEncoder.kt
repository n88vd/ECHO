package ai.echo.app.capture

import android.media.MediaCodec
import android.media.MediaFormat
import android.media.MediaMuxer
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

object AudioEncoder {
    data class Encoded(val file: File, val contentType: String)

    /** Encodes 16 kHz mono PCM16 to OGG/Opus (Android 10+). Falls back to WAV if the encoder is unavailable. */
    fun encode(pcm: ShortArray, sampleRate: Int, outBase: File): Encoded =
        runCatching { encodeOpus(pcm, sampleRate, File(outBase.path + ".ogg")) }
            .getOrElse {
                File(outBase.path + ".ogg").delete()
                writeWav(pcm, sampleRate, File(outBase.path + ".wav"))
            }

    private fun encodeOpus(pcm: ShortArray, sampleRate: Int, out: File): Encoded {
        val format = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_OPUS, sampleRate, 1).apply {
            setInteger(MediaFormat.KEY_BIT_RATE, 24_000)
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 16_384)
            setInteger(MediaFormat.KEY_COMPLEXITY, 5)
        }
        val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_OPUS)
        val muxer = MediaMuxer(out.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_OGG)
        try {
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            codec.start()
            val bytes = ByteBuffer.allocate(pcm.size * 2).order(ByteOrder.LITTLE_ENDIAN)
            bytes.asShortBuffer().put(pcm)
            val data = bytes.array()
            var offset = 0
            var inputDone = false
            var track = -1
            var muxing = false
            val info = MediaCodec.BufferInfo()
            var ptsUs = 0L
            while (true) {
                if (!inputDone) {
                    val idx = codec.dequeueInputBuffer(10_000)
                    if (idx >= 0) {
                        val buf = codec.getInputBuffer(idx)!!
                        buf.clear()
                        val n = minOf(buf.remaining(), data.size - offset, 3840)
                        if (n <= 0) {
                            codec.queueInputBuffer(idx, 0, 0, ptsUs, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                            inputDone = true
                        } else {
                            buf.put(data, offset, n)
                            codec.queueInputBuffer(idx, 0, n, ptsUs, 0)
                            offset += n
                            ptsUs += (n / 2) * 1_000_000L / sampleRate
                        }
                    }
                }
                val outIdx = codec.dequeueOutputBuffer(info, 10_000)
                when {
                    outIdx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        track = muxer.addTrack(codec.outputFormat)
                        muxer.start()
                        muxing = true
                    }
                    outIdx >= 0 -> {
                        val buf = codec.getOutputBuffer(outIdx)!!
                        if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) info.size = 0
                        if (info.size > 0 && muxing) {
                            buf.position(info.offset)
                            buf.limit(info.offset + info.size)
                            muxer.writeSampleData(track, buf, info)
                        }
                        codec.releaseOutputBuffer(outIdx, false)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                    }
                }
            }
            check(muxing) { "opus muxer never started" }
        } finally {
            runCatching { codec.stop() }
            codec.release()
            runCatching { muxer.stop() }
            runCatching { muxer.release() }
        }
        check(out.length() > 100) { "empty opus output" }
        return Encoded(out, "audio/ogg")
    }

    fun writeWav(pcm: ShortArray, sampleRate: Int, out: File): Encoded {
        RandomAccessFile(out, "rw").use { f ->
            f.setLength(0)
            val dataLen = pcm.size * 2
            val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
                put("RIFF".toByteArray()); putInt(36 + dataLen); put("WAVE".toByteArray())
                put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(1); putInt(sampleRate); putInt(sampleRate * 2)
                putShort(2); putShort(16); put("data".toByteArray()); putInt(dataLen)
            }
            f.write(header.array())
            val body = ByteBuffer.allocate(dataLen).order(ByteOrder.LITTLE_ENDIAN)
            body.asShortBuffer().put(pcm)
            f.write(body.array())
        }
        return Encoded(out, "audio/wav")
    }
}
