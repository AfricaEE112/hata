package app.vidbox.data

import org.json.JSONArray
import org.json.JSONObject

// Манга: ті самі дані, що й на сайті (/api/manga…). Сторінки — картинки з ПК, прогрес — на ПК.

data class MangaCont(val cid: String, val label: String, val page: Int, val pages: Int)

data class MangaMeta(
    val src: String, val url: String, val alt: List<String>, val year: Int, val format: String, val status: String,
    val score: Int, val chapters: Int, val genres: List<String>, val desc: String,
    val artists: List<String>, val series: List<String>, val lang: String,
)

data class MangaChapter(val cid: String, val label: String, val sub: String, val pages: Int, val page: Int, val done: Boolean, val new: Boolean)

data class MangaTitle(
    val tid: String, val title: String, val n: Int, val pages: Int, val single: Boolean, val vols: Boolean,
    val read: Int, val lastAt: Double, val new: Int, val added: Double, val mode: String, val cover: String,
    val meta: MangaMeta?, val cont: MangaCont?, val chapters: List<MangaChapter> = emptyList(),
) {
    val done get() = n > 0 && read >= n
    /** Прогрес 0…1: для книжки — сторінки, для тайтлу з розділами — розділи. */
    val progress: Float
        get() = if (single) (cont?.let { it.page.toFloat() / it.pages } ?: if (read > 0) 1f else 0f)
        else ((read + (cont?.let { (it.page - 1f) / it.pages.coerceAtLeast(1) } ?: 0f)) / n.coerceAtLeast(1)).coerceAtMost(1f)
}

data class MangaList(val folder: String, val missing: Boolean, val scanning: Boolean, val chapters: Int, val titles: List<MangaTitle>)

data class MangaNear(val cid: String, val label: String, val pages: Int)

/** Розділ для читалки. */
data class MangaRead(
    val cid: String, val tid: String, val title: String, val label: String, val pages: Int, val page: Int,
    val done: Boolean, val mode: String, val index: Int, val count: Int, val prev: MangaNear?, val next: MangaNear?,
)

private fun JSONArray?.strings(): List<String> = if (this == null) emptyList() else (0 until length()).mapNotNull { optString(it).ifEmpty { null } }
private fun JSONObject.s(k: String) = if (isNull(k)) "" else optString(k)

private fun parseMangaMeta(o: JSONObject?, title: String): MangaMeta? {
    if (o == null) return null
    val alt = (listOf(o.s("english"), o.s("romaji"), o.s("native")) + o.optJSONArray("alt").strings())
        .filter { it.isNotEmpty() && it != title }.distinct().take(3)
    return MangaMeta(
        o.s("src"), o.s("url"), alt, o.optInt("year"), o.s("format"), o.s("status"), o.optInt("score"), o.optInt("chapters"),
        o.optJSONArray("genres").strings(), o.s("desc"), o.optJSONArray("artists").strings(), o.optJSONArray("series").strings(), o.s("lang"),
    )
}

fun parseMangaTitle(o: JSONObject): MangaTitle {
    val c = o.optJSONObject("cont")
    val chs = o.optJSONArray("chapters")
    val title = o.optString("title")
    return MangaTitle(
        tid = o.optString("tid"), title = title, n = o.optInt("n"), pages = o.optInt("pages"), single = o.optBoolean("single"),
        vols = o.optBoolean("vols"), read = o.optInt("read"), lastAt = o.optDouble("lastAt", 0.0), new = o.optInt("new"),
        added = o.optDouble("added", 0.0), mode = o.optString("mode", "rtl"), cover = o.optString("cover"),
        meta = parseMangaMeta(o.optJSONObject("meta"), title),
        cont = c?.let { MangaCont(it.optString("cid"), it.s("label"), it.optInt("page", 1), it.optInt("pages", 1)) },
        chapters = if (chs == null) emptyList() else (0 until chs.length()).map {
            val x = chs.getJSONObject(it)
            MangaChapter(x.optString("cid"), x.optString("label"), x.s("sub"), x.optInt("pages"), x.optInt("page"), x.optBoolean("done"), x.optBoolean("new"))
        },
    )
}

fun parseMangaList(o: JSONObject): MangaList {
    val a = o.optJSONArray("titles") ?: JSONArray()
    return MangaList(o.s("folder"), o.optBoolean("missing"), o.optBoolean("scanning"), o.optInt("chapters"),
        (0 until a.length()).map { parseMangaTitle(a.getJSONObject(it)) })
}

private fun parseNear(o: JSONObject?) = o?.let { MangaNear(it.optString("cid"), it.optString("label"), it.optInt("pages")) }

fun parseMangaRead(o: JSONObject) = MangaRead(
    o.optString("cid"), o.optString("tid"), o.optString("title"), o.optString("label"), o.optInt("pages"), o.optInt("page"),
    o.optBoolean("done"), o.optString("mode", "rtl"), o.optInt("index"), o.optInt("count"), parseNear(o.optJSONObject("prev")), parseNear(o.optJSONObject("next")),
)

fun mangaFormat(f: String) = mapOf("MANGA" to "манга", "ONE_SHOT" to "ваншот", "NOVEL" to "ранобе", "Manga" to "манга",
    "Manhwa" to "манхва", "Manhua" to "маньхуа", "Doujinshi" to "доджінші", "doujinshi" to "доджінші", "manga" to "манга")[f] ?: f

fun mangaStatus(s: String) = mapOf("FINISHED" to "завершена", "RELEASING" to "виходить", "NOT_YET_RELEASED" to "анонс",
    "CANCELLED" to "скасована", "HIATUS" to "на паузі")[s] ?: s

fun mangaSource(m: MangaMeta) = when (m.src) {
    "anilist" -> "AniList"; "mangaupdates" -> "MangaUpdates"; "hitomi" -> "Hitomi"
    else -> runCatching { java.net.URI(m.url).host?.removePrefix("www.") }.getOrNull() ?: "сайту"
}
