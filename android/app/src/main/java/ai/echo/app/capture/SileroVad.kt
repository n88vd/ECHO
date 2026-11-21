package ai.echo.app.capture

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import java.nio.FloatBuffer

/** Silero VAD (16 kHz, 512-sample windows) via ONNX Runtime. Not thread-safe. */
class SileroVad(context: Context) : AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private val session: OrtSession = env.createSession(
        context.assets.open("silero_vad.onnx").use { it.readBytes() },
        OrtSession.SessionOptions().apply { setIntraOpNumThreads(1); setInterOpNumThreads(1) },
    )
    private var h = FloatArray(2 * 64)
    private var c = FloatArray(2 * 64)
    private val stateShape = longArrayOf(2, 1, 64)

    fun reset() {
        h = FloatArray(2 * 64)
        c = FloatArray(2 * 64)
    }

    fun probability(frame: FloatArray): Float {
        require(frame.size == WINDOW)
        OnnxTensor.createTensor(env, FloatBuffer.wrap(frame), longArrayOf(1, WINDOW.toLong())).use { x ->
            OnnxTensor.createTensor(env, FloatBuffer.wrap(h), stateShape).use { ht ->
                OnnxTensor.createTensor(env, FloatBuffer.wrap(c), stateShape).use { ct ->
                    session.run(mapOf("x" to x, "h" to ht, "c" to ct)).use { out ->
                        val prob = (out[0].value as Array<FloatArray>)[0][0]
                        h = flatten(out[1].value)
                        c = flatten(out[2].value)
                        return prob
                    }
                }
            }
        }
    }

    @Suppress("UNCHECKED_CAST")
    private fun flatten(v: Any): FloatArray {
        val arr = v as Array<Array<FloatArray>>
        return FloatArray(2 * 64) { i -> arr[i / 64][0][i % 64] }
    }

    override fun close() {
        session.close()
    }

    companion object {
        const val WINDOW = 512
        const val SAMPLE_RATE = 16000
    }
}
