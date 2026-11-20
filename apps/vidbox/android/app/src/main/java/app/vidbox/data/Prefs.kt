package app.vidbox.data

import android.content.Context

/** Налаштування самої апки (сервер, вхід, тема й плеєр). Те, що спільне з сайтом, живе на ПК. */
class Prefs(ctx: Context) {
    private val p = ctx.getSharedPreferences("vidbox", Context.MODE_PRIVATE)

    private fun str(k: String, d: String = "") = p.getString(k, d) ?: d
    private fun put(k: String, v: String) = p.edit().putString(k, v).apply()

    var server: String
        get() = str("server")
        set(v) = put("server", v)
    var token: String
        get() = str("token")
        set(v) = put("token", v)
    var host: String
        get() = str("host")
        set(v) = put("host", v)
    var theme: String
        get() = str("theme", "arch")
        set(v) = put("theme", v)
    /** Схема, вибрана зараз у панелі Хати (для теми «Як у Хаті»). */
    var hataTheme: String
        get() = str("hata_theme")
        set(v) = put("hata_theme", v)

    /** Фільтр бібліотеки манги: all, reading, new, done, none. */
    var mangaFilter: String
        get() = str("manga_filter", "all")
        set(v) = put("manga_filter", v)

    /** Якість відео: auto, orig, 1080, 720, 480. */
    var quality: String
        get() = str("quality", "auto")
        set(v) = put("quality", v)

    var seekStep: Int
        get() = p.getInt("seek_step", 10)
        set(v) = p.edit().putInt("seek_step", v).apply()
    /** Субтитри вимкнені (запам'ятовується для всіх відео). */
    var subsOff: Boolean
        get() = p.getBoolean("subs_off", false)
        set(v) = p.edit().putBoolean("subs_off", v).apply()
    var bgAudio: Boolean
        get() = p.getBoolean("bg_audio", true)
        set(v) = p.edit().putBoolean("bg_audio", v).apply()
    var autoLandscape: Boolean
        get() = p.getBoolean("auto_landscape", true)
        set(v) = p.edit().putBoolean("auto_landscape", v).apply()
    var gestures: Boolean
        get() = p.getBoolean("gestures", !Device.isQuest)   // на Quest свайпи курсором контролера незручні
        set(v) = p.edit().putBoolean("gestures", v).apply()
}

/** Шолом Meta Quest: апка там — пласке вікно, керування курсором і кнопками контролера. */
object Device {
    val isQuest: Boolean = android.os.Build.MANUFACTURER.equals("Oculus", true) ||
        android.os.Build.MANUFACTURER.equals("Meta", true) && android.os.Build.MODEL.contains("Quest", true) ||
        android.os.Build.MODEL.contains("Quest", true)
}
