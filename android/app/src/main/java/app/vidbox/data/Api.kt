package app.vidbox.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Зв'язок з VidBox на комп'ютері. Токен входу йде в кукі «vb», як і на сайті. */
class Api(private val prefs: Prefs) {
    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .addInterceptor { chain ->
            val r = chain.request()
            val tok = prefs.token
            // токен іде лише на «свій» ПК, а не на всі адреси, які перебираємо під час пошуку
            val mine = prefs.server.toHttpUrlOrNull()?.let { it.host == r.url.host && it.port == r.url.port } == true
            chain.proceed(if (mine && tok.isNotEmpty() && r.header("Cookie") == null) r.newBuilder().header("Cookie", "vb=$tok").build() else r)
        }
        .build()

    private val quick: OkHttpClient = client.newBuilder()
        .connectTimeout(900, TimeUnit.MILLISECONDS)
        .readTimeout(1500, TimeUnit.MILLISECONDS)
        .build()

    private val jsonType = "application/json; charset=utf-8".toMediaType()

    val base: String get() = prefs.server.trimEnd('/')
    fun url(path: String) = base + path

    fun thumbUrl(v: Video) = url("/thumb/${v.id}?v=${v.thumb}")
    fun spriteUrl(v: Video) = url("/sprite/${v.id}?v=${v.sprite}")
    fun frameUrl(v: Video, i: Int) = url("/frame/${v.id}/$i?v=${v.sprite}")
    fun streamUrl(v: Video, raw: Boolean) = url("/stream/${v.id}" + if (raw) "?raw=1" else "")
    fun liveUrl(v: Video, h: Int, t: Double) = url("/live/${v.id}?h=$h&t=" + String.format(java.util.Locale.US, "%.2f", t))

    private fun call(c: OkHttpClient, req: Request): JSONObject = c.newCall(req).execute().use { r ->
        if (r.code == 401) {
            val body = r.body?.string().orEmpty()
            if (body.contains("auth")) throw AuthException()
            throw IOException(runCatching { JSONObject(body).optString("error") }.getOrNull() ?: "HTTP 401")
        }
        if (!r.isSuccessful) throw IOException("HTTP ${r.code}")
        JSONObject(r.body?.string().orEmpty().ifEmpty { "{}" })
    }

    suspend fun get(path: String): JSONObject = withContext(Dispatchers.IO) {
        call(client, Request.Builder().url(url(path)).build())
    }

    /** POST без даних іде з порожнім тілом (Content-Length: 0). */
    suspend fun post(path: String, body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        val rb = body?.toString()?.toRequestBody(jsonType) ?: ByteArray(0).toRequestBody(null)
        call(client, Request.Builder().url(url(path)).post(rb).build())
    }

    suspend fun library() = parseLibrary(get("/api/library"))
    suspend fun week() = parseWeek(get("/api/week"))
    suspend fun weekRefresh() = parseWeek(post("/api/week/refresh"))
    suspend fun settings() = get("/api/settings")
    suspend fun status() = get("/api/status")
    suspend fun saveSettings(o: JSONObject) = post("/api/settings", o)
    suspend fun vote(id: String, vote: Int) = post("/api/vote", JSONObject().put("id", id).put("vote", vote))
    suspend fun ping(o: JSONObject) = post("/api/ping", o)
    suspend fun rescan() = post("/api/rescan")
    suspend fun anime() = parseAnimeList(get("/api/anime"))
    suspend fun animeTitle(sid: String) = parseAnimeTitle(get("/api/anime/$sid"))
    suspend fun prepare(id: String, force: Boolean) = parsePrep(post("/api/prepare/$id" + if (force) "?mode=h264" else ""))
    suspend fun prepareStatus(id: String) = parsePrep(get("/api/prepare/$id"))
    suspend fun requestSprite(id: String): Long = post("/api/sprite/$id").optLong("sprite")

    /** Візитка сервера за адресою base (без пароля). null — там не VidBox або не відповідає. */
    suspend fun hello(base: String, fast: Boolean = true): Hello? = withContext(Dispatchers.IO) {
        try {
            val o = call(if (fast) quick else client, Request.Builder().url(base.trimEnd('/') + "/api/hello").build())
            parseHello(o).takeIf { it.app == "VidBox" }
        } catch (e: Exception) {
            null
        }
    }

    /** Вхід з паролем. Повертає токен (порожній, якщо пароль на ПК вимкнено). */
    suspend fun login(base: String, password: String): String = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(base.trimEnd('/') + "/api/login")
            .header("Cookie", "vb=")
            .post(JSONObject().put("password", password).toString().toRequestBody(jsonType)).build()
        val o = call(client, req)
        if (!o.optBoolean("ok")) throw IOException(o.optString("error", "Неправильний пароль"))
        o.optString("token")
    }
}
