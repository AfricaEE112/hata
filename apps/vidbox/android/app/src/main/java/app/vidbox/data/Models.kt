package app.vidbox.data

import org.json.JSONArray
import org.json.JSONObject
import java.text.Collator
import java.util.Locale

data class Video(
    val id: String,
    val title: String,
    val folder: String,
    val ext: String,
    val size: Long,
    val added: Double,
    val dur: Double,
    val w: Int,
    val h: Int,
    val thumb: Long,
    val prep: Boolean,
    val ready: Boolean,
    val vote: Int,
    val pos: Double,
    val posAt: Double,
    val score: Double,
    val views: Int,
    val avg: Double?,
    val cmp: Double,
    val pop: Double,
    val last: Double,
    val sprite: Long,
    val file: String,
    val vc: String,
    val ac: String,
) {
    val hasSprite get() = sprite > 0 && dur > 0
    fun resumable(resume: Boolean) = resume && pos > 15 && dur > 0 && pos < dur * 0.95
    val resKey: Int get() = minOf(w, h).takeIf { it > 0 } ?: h
    val res: String
        get() {
            val x = resKey
            return when {
                x <= 0 -> ""
                x >= 2000 -> "4K"
                x >= 1400 -> "1440p"
                x >= 1000 -> "1080p"
                x >= 700 -> "720p"
                x >= 460 -> "480p"
                else -> "${x}p"
            }
        }
    val hue: Int get() = (id.take(4).toIntOrNull(16) ?: 0) % 360
    val initial: String get() = title.trim().firstOrNull()?.uppercase() ?: "?"
    val landscape: Boolean get() = w == 0 || h == 0 || w >= h

    /** Момент кадру i з нарізки (так само, як на сайті). */
    fun frameT(i: Int, n: Int) = dur * (0.03 + 0.94 * i / (n - 1))
}

data class Ui(val sort: String = "score", val dir: String = "desc", val group: String = "all") {
    fun json(): JSONObject = JSONObject().put("sort", sort).put("dir", dir).put("group", group)
}

data class Cfg(
    val autoplayNext: Boolean = true,
    val nextDelay: Int = 8,
    val resume: Boolean = true,
    val ui: Ui = Ui(),
    val theme: String = "arch",
    val hataTheme: String? = null,
)

data class Library(
    val videos: List<Video>,
    val folders: List<String>,
    val ffmpeg: Boolean,
    val pending: Int,
    val spritesPending: Int,
    val spriteN: Int,
    val weekSec: Double,
    val cfg: Cfg,
)

data class WeekSection(val key: String, val title: String, val sub: String, val ids: List<String>)
data class Week(val week: String, val start: String, val end: String, val hero: String?, val sections: List<WeekSection>)
data class Hello(val app: String, val version: String, val host: String, val port: Int, val auth: Boolean)
data class Prep(val state: String, val progress: Double, val error: String, val enc: String)
data class Queue(val pl: String, val name: String, val ids: List<String>, val shuffle: Boolean, val anime: String? = null)

/** Аніме: тайтл (підпапка) і серії. Серії — звичайні Video, плеєр грає їх так само. */
data class AnimeCont(val id: String, val ep: Int, val pos: Double, val dur: Double)
data class AnimeTitle(val sid: String, val title: String, val n: Int, val watched: Int, val cover: String,
                      val lastAt: Double, val cont: AnimeCont?, val eps: List<AnimeEp> = emptyList(), val meta: AnimeMeta? = null)

/** Метадані з AniList: назви, рік, формат, серії в сезоні, рейтинг 0–100, жанри, опис. */
data class AnimeMeta(val alt: List<String>, val year: Int, val format: String, val episodes: Int, val score: Int,
                     val genres: List<String>, val desc: String, val url: String)

private val ANIME_FMT = mapOf("TV" to "серіал", "TV_SHORT" to "короткий серіал", "MOVIE" to "фільм", "OVA" to "OVA",
    "ONA" to "ONA", "SPECIAL" to "спешл", "MUSIC" to "кліп")
fun animeFormat(f: String) = ANIME_FMT[f] ?: f

private fun parseAnimeMeta(o: JSONObject?, title: String): AnimeMeta? {
    if (o == null || o.optInt("id") == 0) return null
    val g = o.optJSONArray("genres")
    val alt = listOf("english", "romaji", "native").mapNotNull { k -> o.optString(k).takeIf { !o.isNull(k) && it.isNotBlank() && it != title } }.distinct().take(2)
    return AnimeMeta(alt, o.optInt("year"), if (o.isNull("format")) "" else o.optString("format"), o.optInt("episodes"),
        o.optInt("score"), if (g == null) emptyList() else (0 until g.length()).map { g.getString(it) },
        if (o.isNull("desc")) "" else o.optString("desc"), if (o.isNull("url")) "" else o.optString("url"))
}
data class AnimeEp(val v: Video, val ep: Int, val name: String, val done: Boolean)
data class AnimeList(val folder: String, val titles: List<AnimeTitle>)

fun parseAnimeTitle(o: JSONObject): AnimeTitle {
    val c = o.optJSONObject("cont")
    val eps = o.optJSONArray("eps")
    return AnimeTitle(
        sid = o.optString("sid"), title = o.optString("title"), n = o.optInt("n"), watched = o.optInt("watched"),
        cover = o.optString("cover"), lastAt = o.optDouble("lastAt", 0.0),
        cont = c?.let { AnimeCont(it.optString("id"), it.optInt("ep"), it.optDouble("pos", 0.0), it.optDouble("dur", 0.0)) },
        meta = parseAnimeMeta(o.optJSONObject("meta"), o.optString("title")),
        eps = if (eps == null) emptyList() else (0 until eps.length()).map {
            val e = eps.getJSONObject(it)
            AnimeEp(parseVideo(e), e.optInt("ep"), e.optString("etitle"), e.optBoolean("done"))
        },
    )
}

fun parseAnimeList(o: JSONObject): AnimeList {
    val a = o.optJSONArray("titles") ?: JSONArray()
    return AnimeList(o.optString("folder"), (0 until a.length()).map { parseAnimeTitle(a.getJSONObject(it)) })
}

class AuthException : Exception("auth")

// ── розбір JSON ──
private fun JSONObject.d(k: String): Double = if (isNull(k)) 0.0 else optDouble(k, 0.0).let { if (it.isNaN()) 0.0 else it }
private fun JSONObject.s(k: String): String = if (isNull(k)) "" else optString(k, "")
private fun JSONArray.strings(): List<String> = (0 until length()).map { optString(it) }

fun parseVideo(o: JSONObject) = Video(
    id = o.s("id"), title = o.s("title"), folder = o.s("folder"), ext = o.s("ext"),
    size = o.optLong("size"), added = o.d("added"), dur = o.d("dur"),
    w = o.optInt("w"), h = o.optInt("h"), thumb = o.optLong("thumb"),
    prep = o.optBoolean("prep"), ready = o.optBoolean("ready"), vote = o.optInt("vote"),
    pos = o.d("pos"), posAt = o.d("posAt"), score = o.d("score"), views = o.optInt("views"),
    avg = if (!o.has("avg") || o.isNull("avg")) null else o.d("avg"),
    cmp = o.d("cmp"), pop = o.d("pop"), last = o.d("last"), sprite = o.optLong("sprite"),
    file = o.s("file"), vc = o.s("vc"), ac = o.s("ac"),
)

fun parseUi(o: JSONObject?) = if (o == null) Ui() else Ui(
    sort = o.optString("sort", "score"), dir = o.optString("dir", "desc"), group = o.optString("group", "all"),
)

fun parseLibrary(o: JSONObject): Library {
    val c = o.optJSONObject("cfg") ?: JSONObject()
    val arr = o.optJSONArray("videos") ?: JSONArray()
    return Library(
        videos = (0 until arr.length()).map { parseVideo(arr.getJSONObject(it)) },
        folders = (o.optJSONArray("folders") ?: JSONArray()).strings(),
        ffmpeg = o.optBoolean("ffmpeg"),
        pending = o.optInt("pending"),
        spritesPending = o.optInt("spritesPending"),
        spriteN = o.optInt("spriteN", 20).coerceAtLeast(2),
        weekSec = o.d("weekSec"),
        cfg = Cfg(
            autoplayNext = c.optBoolean("autoplay_next", true),
            nextDelay = c.optInt("next_delay", 8),
            resume = c.optBoolean("resume", true),
            ui = parseUi(c.optJSONObject("ui")),
            theme = c.optString("theme", "arch"),
            hataTheme = if (c.isNull("hataTheme")) null else c.optString("hataTheme").ifEmpty { null },
        ),
    )
}

fun parseWeek(o: JSONObject): Week {
    val arr = o.optJSONArray("sections") ?: JSONArray()
    return Week(
        week = o.s("week"), start = o.s("start"), end = o.s("end"),
        hero = o.s("hero").ifEmpty { null },
        sections = (0 until arr.length()).map {
            val s = arr.getJSONObject(it)
            WeekSection(s.s("key"), s.s("title"), s.s("sub"), (s.optJSONArray("ids") ?: JSONArray()).strings())
        },
    )
}

fun parseHello(o: JSONObject) = Hello(
    app = o.s("app"), version = o.s("version"), host = o.s("host"), port = o.optInt("port", 8800), auth = o.optBoolean("auth"),
)

fun parsePrep(o: JSONObject) = Prep(o.s("state").ifEmpty { "none" }, o.d("progress"), o.s("error"), o.s("enc"))

// ── порівняння назв «як людина»: Серія 2 < Серія 10, без різниці великих літер ──
object Natural : Comparator<String> {
    private val col: Collator = Collator.getInstance(Locale("uk")).apply { strength = Collator.SECONDARY }

    override fun compare(a: String, b: String): Int {
        var i = 0
        var j = 0
        while (i < a.length && j < b.length) {
            val da = a[i].isDigit()
            val db = b[j].isDigit()
            var ei = i
            while (ei < a.length && a[ei].isDigit() == da) ei++
            var ej = j
            while (ej < b.length && b[ej].isDigit() == db) ej++
            val c = if (da && db) {
                val na = a.substring(i, ei).trimStart('0')
                val nb = b.substring(j, ej).trimStart('0')
                if (na.length != nb.length) na.length - nb.length else na.compareTo(nb)
            } else {
                synchronized(col) { col.compare(a.substring(i, ei), b.substring(j, ej)) }
            }
            if (c != 0) return c
            i = ei
            j = ej
        }
        return (a.length - i) - (b.length - j)
    }
}

val byName = Comparator<Video> { a, b -> Natural.compare(a.title, b.title) }
val inOrder = Comparator<Video> { a, b -> Natural.compare(a.folder, b.folder).let { if (it != 0) it else byName.compare(a, b) } }

// ── сортування, як у бібліотеці на сайті ──
data class SortDef(val id: String, val label: String, val desc: String, val asc: String, val first: String = "desc")

val SORTS = listOf(
    SortDef("score", "Рейтинг", "Спершу найвищий", "Спершу найнижчий"),
    SortDef("added", "Дата додавання", "Спершу нові", "Спершу старі"),
    SortDef("name", "Назва", "Від Я до А", "Від А до Я", "asc"),
    SortDef("size", "Розмір файлу", "Від більшого", "Від меншого"),
    SortDef("dur", "Тривалість", "Спершу довші", "Спершу коротші"),
    SortDef("res", "Роздільність", "Спершу вища", "Спершу нижча"),
    SortDef("views", "Кількість переглядів", "Спершу найчастіші", "Спершу найрідші"),
    SortDef("last", "Останній перегляд", "Спершу нещодавні", "Спершу давно не бачені"),
    SortDef("folder", "Папка", "Від Я до А", "Від А до Я", "asc"),
    SortDef("random", "Випадково", "Випадково", "Випадково"),
)

fun sortDef(id: String) = SORTS.firstOrNull { it.id == id } ?: SORTS[0]

fun sorter(key: String, dir: String, rnd: Map<String, Double>): Comparator<Video> {
    val m = if (dir == "asc") 1 else -1
    val base: Comparator<Video> = when (key) {
        "added" -> compareBy<Video> { it.added }
        "name" -> byName
        "size" -> compareBy<Video> { it.size }
        "dur" -> compareBy<Video> { it.dur }
        "res" -> compareBy<Video> { it.resKey }
        "views" -> compareBy<Video> { it.views }
        "last" -> compareBy<Video> { it.last }
        "folder" -> inOrder
        "random" -> compareBy<Video> { rnd[it.id] ?: 0.0 }
        else -> compareBy<Video> { it.score }
    }
    val mm = if (key == "random") 1 else m
    return Comparator { a, b -> (mm * base.compare(a, b)).let { if (it != 0) it else byName.compare(a, b) } }
}

// ── плейлисти за тривалістю ──
data class LenGroup(val id: String, val name: String, val file: String, val hint: String, val test: (Video) -> Boolean)

val LEN_GROUPS = listOf(
    LenGroup("short", "До 20 хвилин", "короткі", "Коли є кілька вільних хвилин") { it.dur > 0 && it.dur < 1200 },
    LenGroup("mid", "До години", "середні", "Від 20 хвилин до години: серія чи документалка") { it.dur >= 1200 && it.dur < 3600 },
    LenGroup("long", "Понад годину", "довгі", "Фільми й довгі записи на вечір") { it.dur >= 3600 },
)
val UNKNOWN_LEN = LenGroup("unknown", "Тривалість ще невідома", "невідомі", "VidBox ще не прочитав ці файли") { it.dur <= 0 }

fun lenGroup(id: String) = LEN_GROUPS.firstOrNull { it.id == id }
