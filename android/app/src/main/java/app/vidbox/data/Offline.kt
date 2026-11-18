package app.vidbox.data

import android.content.Context
import androidx.compose.runtime.mutableStateMapOf
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream

/** Завантажене відео: лежить у приватній папці апки (не в галереї), видаляється разом з апкою. */
data class Dl(val v: Video, val bytes: Long, val total: Long, val done: Boolean, val error: String? = null,
              val note: String? = null, val h: Int = 0) {
    val progress: Float get() = if (total > 0) (bytes.toFloat() / total).coerceIn(0f, 1f) else 0f
}

fun Video.json(): JSONObject = JSONObject().put("id", id).put("title", title).put("folder", folder).put("ext", ext)
    .put("size", size).put("added", added).put("dur", dur).put("w", w).put("h", h).put("thumb", thumb)
    .put("prep", false).put("ready", false).put("vote", vote).put("pos", pos).put("posAt", posAt).put("score", score)
    .put("views", views).put("cmp", cmp).put("pop", pop).put("last", last).put("sprite", 0).put("file", file)
    .put("vc", vc).put("ac", ac)

class Offline(private val ctx: Context, private val client: OkHttpClient) {
    /** Власна область корутин: завантаження не прив'язані до екрана й ViewModel. */
    private val own = CoroutineScope(kotlinx.coroutines.SupervisorJob() + Dispatchers.Main)
    private val dir = File(ctx.getExternalFilesDir(null) ?: ctx.filesDir, "offline").apply { mkdirs() }
    private val index = File(dir, "index.json")
    private val jobs = HashMap<String, Job>()
    val items = mutableStateMapOf<String, Dl>()

    init {
        runCatching {
            val a = JSONArray(index.readText())
            for (i in 0 until a.length()) {
                val o = a.getJSONObject(i)
                val v = parseVideo(o.getJSONObject("v"))
                val f = if (o.optBoolean("done")) file(v.id) else part(v.id)
                items[v.id] = Dl(v, f.length(), o.optLong("total"), o.optBoolean("done") && f.exists(),
                    if (o.optBoolean("done")) null else "Перервано", h = o.optInt("h"))
            }
        }
    }

    fun file(id: String) = File(dir, "$id.media")
    private fun part(id: String) = File(dir, "$id.part")
    fun thumb(id: String) = File(dir, "$id.jpg")
    fun ready(id: String): File? = items[id]?.takeIf { it.done }?.let { file(id).takeIf { f -> f.exists() } }
    val usedBytes: Long get() = items.values.sumOf { it.bytes }
    fun running(id: String) = jobs[id]?.isActive == true

    private fun save() = runCatching {
        val a = JSONArray()
        items.values.forEach { a.put(JSONObject().put("v", it.v.json()).put("total", it.total).put("done", it.done).put("h", it.h)) }
        index.writeText(a.toString())
    }

    /** prep — спершу дочекатися, поки ПК підготує копію потрібної якості (оновлює підпис note). */
    fun start(scope: CoroutineScope, v: Video, url: String, thumbUrl: String?, h: Int = 0, sizeHint: Long = v.size,
              prep: (suspend ((String) -> Unit) -> Unit)? = null) {
        if (running(v.id) || ready(v.id) != null) return
        if ((items[v.id]?.h ?: h) != h) part(v.id).delete()   // інша якість — качаємо заново
        items[v.id] = Dl(v, part(v.id).length(), sizeHint, false, h = h)
        save()
        jobs[v.id] = own.launch {
            val err = withContext(Dispatchers.IO) {
                runCatching {
                    prep?.invoke { n -> items[v.id] = items[v.id]!!.copy(note = n) }
                    items[v.id] = items[v.id]!!.copy(note = null)
                    if (thumbUrl != null && !thumb(v.id).exists()) runCatching {
                        client.newCall(Request.Builder().url(thumbUrl).build()).execute().use { r ->
                            if (r.isSuccessful) thumb(v.id).writeBytes(r.body!!.bytes())
                        }
                    }
                    val p = part(v.id)
                    var have = p.length()
                    val req = Request.Builder().url(url).apply { if (have > 0) header("Range", "bytes=$have-") }.build()
                    client.newCall(req).execute().use { r ->
                        if (!r.isSuccessful) throw Exception("ПК відповів ${r.code}")
                        if (r.code != 206) have = 0L            // сервер почав з нуля — і ми теж
                        val body = r.body!!
                        val total = if (body.contentLength() > 0) have + body.contentLength() else sizeHint
                        FileOutputStream(p, have > 0).use { os ->
                            body.byteStream().use { inp ->
                                val buf = ByteArray(128 * 1024)
                                var got = have
                                var shown = 0L
                                while (isActive) {
                                    val n = inp.read(buf)
                                    if (n < 0) break
                                    os.write(buf, 0, n)
                                    got += n
                                    if (got - shown > 1_000_000) { shown = got; items[v.id] = Dl(v, got, total, false, h = h) }
                                }
                                if (!isActive) throw Exception("Зупинено")
                                if (body.contentLength() > 0 && got < total) throw Exception("Зв'язок обірвався")
                                items[v.id] = Dl(v, got, total, false, h = h)
                            }
                        }
                    }
                    if (!p.renameTo(file(v.id))) throw Exception("Не вдалося зберегти файл")
                }.exceptionOrNull()
            }
            val cur = items[v.id] ?: return@launch
            items[v.id] = if (err == null) cur.copy(bytes = file(v.id).length(), total = file(v.id).length(), done = true, error = null)
                          else cur.copy(error = err.message ?: "Помилка")
            save()
        }
        DownloadService.start(ctx)
    }

    fun stop(id: String) { jobs.remove(id)?.cancel() }

    fun remove(id: String) {
        stop(id)
        items.remove(id)
        listOf(file(id), part(id), thumb(id)).forEach { it.delete() }
        save()
    }

    /** Позиція перегляду, щоб «продовжити» працювало й без зв'язку з ПК. */
    fun setPos(id: String, pos: Double) {
        val d = items[id] ?: return
        items[id] = d.copy(v = d.v.copy(pos = pos, posAt = System.currentTimeMillis() / 1000.0))
        save()
    }
}
