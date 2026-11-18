package app.vidbox.data

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import app.vidbox.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

/** Нова версія апки в релізах GitHub (теги android-v0.6.N, де N — versionCode). */
data class Update(val build: Int, val name: String, val url: String, val size: Long, val notes: String)

object Updater {
    private const val LATEST = "https://api.github.com/repos/AfricaEE112/vidbox/releases/latest"
    private val http = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()

    /** null — апка вже найновіша. */
    suspend fun check(): Update? = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(LATEST).header("Accept", "application/vnd.github+json").build()
        val o = http.newCall(req).execute().use { r ->
            if (!r.isSuccessful) throw Exception("GitHub відповів ${r.code}")
            JSONObject(r.body!!.string())
        }
        val tag = o.optString("tag_name")
        val build = tag.substringAfterLast('.').toIntOrNull() ?: throw Exception("Незрозумілий тег $tag")
        val assets = o.optJSONArray("assets")
        val apk = (0 until (assets?.length() ?: 0)).map { assets!!.getJSONObject(it) }
            .firstOrNull { it.optString("name").endsWith(".apk") } ?: throw Exception("У релізі немає APK")
        if (build <= BuildConfig.VERSION_CODE) null
        else Update(build, tag.removePrefix("android-v"), apk.optString("browser_download_url"), apk.optLong("size"), o.optString("body"))
    }

    suspend fun download(ctx: Context, u: Update, progress: (Float) -> Unit): File = withContext(Dispatchers.IO) {
        val dir = File(ctx.cacheDir, "updates").apply { mkdirs() }
        dir.listFiles()?.forEach { it.delete() }
        val out = File(dir, "VidBox-${u.name}.apk")
        http.newCall(Request.Builder().url(u.url).build()).execute().use { r ->
            if (!r.isSuccessful) throw Exception("Завантаження: HTTP ${r.code}")
            val body = r.body!!
            val total = body.contentLength().takeIf { it > 0 } ?: u.size
            body.byteStream().use { inp ->
                out.outputStream().use { os ->
                    val buf = ByteArray(64 * 1024)
                    var done = 0L
                    var last = 0L
                    while (true) {
                        val n = inp.read(buf)
                        if (n < 0) break
                        os.write(buf, 0, n)
                        done += n
                        if (total > 0 && done - last > 256 * 1024) { last = done; progress(done.toFloat() / total) }
                    }
                }
            }
        }
        progress(1f)
        out
    }

    /** false — спершу треба дозволити встановлення з цієї апки (відкриваємо системне налаштування). */
    fun install(ctx: Context, f: File): Boolean {
        if (Build.VERSION.SDK_INT >= 26 && !ctx.packageManager.canRequestPackageInstalls()) {
            ctx.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + ctx.packageName))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return false
        }
        val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f)
        ctx.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
        return true
    }
}
