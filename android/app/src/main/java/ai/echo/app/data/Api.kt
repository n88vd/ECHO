package ai.echo.app.data

import ai.echo.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.serializer
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiException(val code: Int, message: String) : IOException(message)

class Api(private val session: Session) {
    val json = Json { ignoreUnknownKeys = true; explicitNulls = false; encodeDefaults = true }
    private val base = BuildConfig.API_BASE_URL.trimEnd('/')
    private val jsonType = "application/json".toMediaType()

    private val authInterceptor = Interceptor { chain ->
        val req = chain.request()
        if (req.url.encodedPath.startsWith("/v1/auth/")) return@Interceptor chain.proceed(req)
        ensureFresh()
        val token = session.accessToken
        val res = chain.proceed(req.newBuilder().apply { if (token != null) header("Authorization", "Bearer $token") }.build())
        if (res.code == 401 && session.refreshToken != null) {
            res.close()
            if (refresh()) {
                return@Interceptor chain.proceed(req.newBuilder().header("Authorization", "Bearer ${session.accessToken}").build())
            }
            session.clear()
            return@Interceptor chain.proceed(req)
        }
        res
    }

    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(90, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .addInterceptor(authInterceptor)
        .build()

    private val plain = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).build()

    private fun ensureFresh() {
        val now = System.currentTimeMillis() / 1000
        if (session.refreshToken != null && session.expiresAt - now < 120) refresh()
    }

    @Synchronized
    private fun refresh(): Boolean {
        val rt = session.refreshToken ?: return false
        if (session.expiresAt - System.currentTimeMillis() / 1000 > 120 && session.accessToken != null) return true
        val body = buildJsonObject { put("refresh_token", rt) }.toString().toRequestBody(jsonType)
        return runCatching {
            plain.newCall(Request.Builder().url("$base/v1/auth/refresh").post(body).build()).execute().use { r ->
                if (!r.isSuccessful) return false
                session.save(json.decodeFromString(AuthSession.serializer(), r.body.string()))
                true
            }
        }.getOrDefault(false)
    }

    private fun <T> parse(res: Response, ser: KSerializer<T>): T = res.use {
        val text = it.body.string()
        if (!it.isSuccessful) {
            val detail = runCatching { json.parseToJsonElement(text).let { e -> (e as JsonObject)["detail"].toString().trim('"') } }.getOrNull()
            throw ApiException(it.code, detail ?: "HTTP ${it.code}")
        }
        json.decodeFromString(ser, text)
    }

    suspend fun <T> get(path: String, ser: KSerializer<T>): T = withContext(Dispatchers.IO) {
        parse(http.newCall(Request.Builder().url(base + path).get().build()).execute(), ser)
    }

    suspend fun <T> send(method: String, path: String, body: RequestBody?, ser: KSerializer<T>): T = withContext(Dispatchers.IO) {
        parse(http.newCall(Request.Builder().url(base + path).method(method, body).build()).execute(), ser)
    }

    private inline fun <reified B> jsonBody(b: B): RequestBody = json.encodeToString(serializer<B>(), b).toRequestBody(jsonType)
    private fun raw(s: String): RequestBody = s.toRequestBody(jsonType)
    private val anyJson = JsonObject.serializer()

    suspend fun signInGoogle(idToken: String): AuthSession = withContext(Dispatchers.IO) {
        val body = buildJsonObject { put("id_token", idToken) }.toString().toRequestBody(jsonType)
        parse(plain.newCall(Request.Builder().url("$base/v1/auth/google").post(body).build()).execute(), AuthSession.serializer())
            .also(session::save)
    }

    suspend fun signInPassword(email: String, password: String): AuthSession = withContext(Dispatchers.IO) {
        val body = buildJsonObject { put("email", email); put("password", password) }.toString().toRequestBody(jsonType)
        parse(plain.newCall(Request.Builder().url("$base/v1/auth/password").post(body).build()).execute(), AuthSession.serializer())
            .also(session::save)
    }

    suspend fun registerDevice(deviceId: String?, model: String, os: String, app: String): String {
        val body = buildJsonObject {
            if (deviceId != null) put("device_id", deviceId)
            put("model", model); put("os_version", os); put("app_version", app)
        }
        val res = send("POST", "/v1/devices", raw(body.toString()), anyJson)
        return res["device_id"].toString().trim('"')
    }

    fun uploadSegmentBlocking(meta: SegmentMeta, file: File): SegmentResult {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("meta", json.encodeToString(SegmentMeta.serializer(), meta))
            .addFormDataPart("file", file.name, file.asRequestBody(meta.content_type.toMediaType()))
            .build()
        return parse(http.newCall(Request.Builder().url("$base/v1/segments").post(body).build()).execute(), SegmentResult.serializer())
    }

    fun syncBlocking(since: String?, deviceId: String?): SyncResponse {
        val q = buildString {
            append("/v1/sync?")
            if (since != null) append("since=").append(java.net.URLEncoder.encode(since, "UTF-8")).append('&')
            if (deviceId != null) append("device_id=").append(deviceId)
        }
        return parse(http.newCall(Request.Builder().url(base + q).get().build()).execute(), SyncResponse.serializer())
    }

    fun rememberBlocking(): Boolean = runCatching {
        http.newCall(Request.Builder().url("$base/v1/remember").post("{}".toRequestBody(jsonType)).build()).execute().use { it.isSuccessful }
    }.getOrDefault(false)

    suspend fun status() = get("/v1/status", Status.serializer())
    suspend fun ask(q: String, speak: Boolean) = send("POST", "/v1/ask", jsonBody(AskRequest(q, null, speak)), AskResponse.serializer())

    suspend fun askVoice(file: File, speak: Boolean): AskResponse {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", file.name, file.asRequestBody("audio/wav".toMediaType()))
            .addFormDataPart("speak", speak.toString())
            .build()
        return send("POST", "/v1/ask/voice", body, AskResponse.serializer())
    }

    suspend fun feedback(askId: String, up: Boolean) =
        send("POST", "/v1/ask/$askId/feedback", raw("""{"feedback":"${if (up) "up" else "down"}"}"""), anyJson)

    suspend fun timeline(before: String? = null, q: String? = null): Timeline {
        val params = listOfNotNull(before?.let { "before=" + java.net.URLEncoder.encode(it, "UTF-8") }, q?.let { "q=" + java.net.URLEncoder.encode(it, "UTF-8") })
        return get("/v1/timeline" + if (params.isEmpty()) "" else "?" + params.joinToString("&"), Timeline.serializer())
    }

    suspend fun memory(id: String) = get("/v1/memories/$id", MemoryDetail.serializer())
    suspend fun deleteMemory(id: String) = send("DELETE", "/v1/memories/$id", null, anyJson)
    suspend fun pinMemory(id: String, pinned: Boolean) = send("PATCH", "/v1/memories/$id", raw("""{"pinned":$pinned}"""), anyJson)
    suspend fun conversation(id: String) = get("/v1/conversations/$id", ConversationDetail.serializer())
    suspend fun deleteConversation(id: String) = send("DELETE", "/v1/conversations/$id", null, anyJson)
    suspend fun labelSpeaker(id: String, name: String?, isMe: Boolean): JsonObject {
        val body = buildJsonObject { if (name != null) put("name", name); put("is_me", isMe) }
        return send("POST", "/v1/speakers/$id/label", raw(body.toString()), anyJson)
    }
    suspend fun commitments(status: String = "open") = get("/v1/commitments?status=$status", Commitments.serializer())
    suspend fun setCommitment(id: String, status: String) = send("PATCH", "/v1/commitments/$id", raw("""{"status":"$status"}"""), anyJson)
    suspend fun people() = get("/v1/people", People.serializer())
    suspend fun latestDigest() = get("/v1/digests/latest", DigestEnvelope.serializer())
    suspend fun settings() = get("/v1/settings", ServerSettings.serializer())
    suspend fun patchSettings(body: JsonObject) = send("PATCH", "/v1/settings", raw(body.toString()), ServerSettings.serializer())
    suspend fun enrollVoice(file: File) = send(
        "POST", "/v1/voiceprint",
        MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("file", file.name, file.asRequestBody("audio/wav".toMediaType())).build(),
        anyJson,
    )
    suspend fun deleteAccount() = send("DELETE", "/v1/account", null, anyJson)

    suspend fun exportTo(file: File) = withContext(Dispatchers.IO) {
        http.newCall(Request.Builder().url("$base/v1/export").get().build()).execute().use { r ->
            if (!r.isSuccessful) throw ApiException(r.code, "export failed")
            file.outputStream().use { out -> r.body.byteStream().copyTo(out) }
        }
        file
    }
}
