package app.vidbox.player

import android.content.Context
import android.media.MediaCodecList
import android.net.ConnectivityManager
import android.os.Build
import app.vidbox.data.Video

/** Що вміє цей телефон і яка зараз мережа — для якості «Авто». */
object Caps {
    private val cache = HashMap<String, Boolean>()

    private fun mime(vc: String) = when (vc.lowercase()) {
        "av1" -> "video/av01"
        "hevc", "h265" -> "video/hevc"
        "vp9" -> "video/x-vnd.on2.vp9"
        "vp8" -> "video/x-vnd.on2.vp8"
        "h264" -> "video/avc"
        "mpeg4" -> "video/mp4v-es"
        else -> ""
    }

    /** Чи є апаратний декодер для кодека відео (програмний 4K AV1 смикається). */
    fun hwDecode(v: Video): Boolean {
        val m = mime(v.vc)
        if (m.isEmpty()) return true
        return cache.getOrPut(m) {
            runCatching {
                MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos.any { c ->
                    !c.isEncoder && c.supportedTypes.any { it.equals(m, true) } &&
                        if (Build.VERSION.SDK_INT >= 29) c.isHardwareAccelerated
                        else !(c.name.startsWith("OMX.google.") || c.name.startsWith("c2.android."))
                }
            }.getOrDefault(true)
        }
    }

    /** Мобільний інтернет чи інша мережа з лімітом трафіку. */
    fun metered(ctx: Context): Boolean =
        runCatching { ctx.getSystemService(ConnectivityManager::class.java).isActiveNetworkMetered }.getOrDefault(false)
}
