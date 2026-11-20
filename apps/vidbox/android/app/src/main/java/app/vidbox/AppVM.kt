package app.vidbox

import android.app.Application
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.vidbox.data.AuthException
import app.vidbox.data.Fmt
import app.vidbox.data.LEN_GROUPS
import app.vidbox.data.AnimeList
import app.vidbox.data.AnimeTitle
import app.vidbox.data.Library
import app.vidbox.data.Offline
import app.vidbox.data.Update
import app.vidbox.data.Updater
import app.vidbox.data.Queue
import app.vidbox.data.Ui
import app.vidbox.data.Video
import app.vidbox.data.Week
import app.vidbox.data.byName
import app.vidbox.data.inOrder
import app.vidbox.data.lenGroup
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import kotlin.random.Random

// ── маршрути: як хеш-адреси на сайті ──
sealed interface Route {
    val key: String
}

data object Home : Route { override val key = "home" }
data object Lib : Route { override val key = "lib" }
data object Playlists : Route { override val key = "pl" }
data object Top : Route { override val key = "top" }
data object Settings : Route { override val key = "settings" }
data object Connect : Route { override val key = "connect" }
data class Playlist(val id: String) : Route { override val key = "pl/$id" }
data class Info(val id: String, val random: Boolean = false) : Route { override val key = "i/$id" }
data class Player(val id: String, val startAt: Double? = null) : Route { override val key = "v/$id" }
data object Anime : Route { override val key = "anime" }
data object Downloads : Route { override val key = "downloads" }
data class AnimeShow(val sid: String) : Route { override val key = "anime/$sid" }
data object Manga : Route { override val key = "manga" }
data class MangaShow(val tid: String) : Route { override val key = "manga/$tid" }
/** Читалка на весь екран; page = з якої сторінки (null — де зупинився). */
data class Reader(val cid: String, val page: Int? = null) : Route { override val key = "r/$cid" }

val TABS = listOf(Home, Lib, Anime, Manga, Playlists, Top, Settings)

class Nav {
    val stack = mutableStateListOf<Route>(Home)
    val top: Route get() = stack.last()
    private val lists = HashMap<String, LazyListState>()
    private val grids = HashMap<String, LazyGridState>()

    fun list(key: String) = lists.getOrPut(key) { LazyListState() }
    fun grid(key: String) = grids.getOrPut(key) { LazyGridState() }

    fun go(r: Route) {
        if (r in TABS || r == Connect) {
            stack.clear()
            if (r != Home && r != Connect) stack.add(Home)
            stack.add(r)
        } else {
            if (top == r) return
            stack.add(r)
        }
    }

    fun replace(r: Route) {
        if (stack.size > 0) stack.removeAt(stack.lastIndex)
        stack.add(r)
    }

    fun back(): Boolean {
        if (stack.size <= 1) return false
        stack.removeAt(stack.lastIndex)
        return true
    }

    /** Таб, до якого належить поточний екран (для підсвітки в доку). */
    val tab: Route get() = stack.lastOrNull { it in TABS } ?: Home
}

data class Toast(val text: String, val action: String? = null, val onAction: (() -> Unit)? = null, val id: Long = System.nanoTime())

class AppVM(app: Application) : AndroidViewModel(app) {
    private val vb = app as VidBoxApp
    val api = vb.api
    val prefs = vb.prefs
    val nav = Nav()
    /** Завантажене на телефон: грається без ПК. */
    val dl = vb.dl

    var lib by mutableStateOf<Library?>(null)
        private set
    var week by mutableStateOf<Week?>(null)
        private set
    var offline by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var ui by mutableStateOf(Ui())
        private set
    var themeId by mutableStateOf(prefs.theme)
        private set
    /** Схема в панелі Хати; null — VidBox працює не під Хатою. */
    var hataTheme by mutableStateOf(prefs.hataTheme.ifEmpty { null })
        private set
    var queue by mutableStateOf<Queue?>(null)
    /** Кнопки (контролер Quest, пульт, клавіатура) для плеєра. */
    val keys = kotlinx.coroutines.flow.MutableSharedFlow<Int>(extraBufferCapacity = 8)
    var toast by mutableStateOf<Toast?>(null)
    var foreground = true
    var pip by mutableStateOf(false)

    /** Пошук і фільтр папки в бібліотеці. */
    var query by mutableStateOf("")
    var folder by mutableStateOf<String?>(null)
    var focusSearch by mutableStateOf(false)
    val collapsed = mutableStateMapOf<String, Boolean>()

    private var rnd = HashMap<String, Double>()
    var rndGen by mutableIntStateOf(0)
        private set
    private var uiFromServer = false
    private var themeSetAt = 0L
    private var poller: Job? = null

    /** Серії аніме: окремо від бібліотеки, але плеєр шукає відео в byId. */
    val animeEps = mutableStateMapOf<String, Video>()
    var animeList by mutableStateOf<AnimeList?>(null)
    val animeShows = mutableStateMapOf<String, AnimeTitle>()
    val byId: Map<String, Video> by derivedStateOf {
        dl.items.mapValues { it.value.v } + (lib?.videos?.associateBy { it.id } ?: emptyMap()) + animeEps
    }

    /** h > 0 — ПК спершу перекодовує в цю висоту (звичайний MP4 з перемоткою), потім телефон качає копію. */
    fun download(v: Video, h: Int = dl.items[v.id]?.h ?: 0) {
        val th = if (v.thumb > 0) api.thumbUrl(v) else null
        when {
            dl.ready(v.id) != null -> say("Уже на телефоні")
            h > 0 -> dl.start(viewModelScope, v, api.dlFileUrl(v.id, h), th, h,
                ((mapOf(1080 to 6128, 720 to 3128, 480 to 1628)[h] ?: 3128) * 125L * v.dur).toLong()) { note ->
                var st = api.dlPrep(v.id, h, true)
                while (st.optString("state") == "working") {
                    note("ПК готує ${h}p: ${(st.optDouble("progress", 0.0) * 100).toInt()}%")
                    kotlinx.coroutines.delay(2000)
                    st = api.dlPrep(v.id, h, false)
                }
                if (st.optString("state") != "ready") throw Exception(st.optString("error").ifEmpty { "ПК не підготував копію" })
            }
            !v.prep -> dl.start(viewModelScope, v, api.streamUrl(v, raw = true), if (v.thumb > 0) api.thumbUrl(v) else null)
            v.ready -> dl.start(viewModelScope, v, api.streamUrl(v, raw = false), if (v.thumb > 0) api.thumbUrl(v) else null)
            else -> viewModelScope.launch {
                runCatching { api.prepare(v.id, false) }
                say("Телефон не грає цей формат — ПК робить MP4-копію. Натисни «Завантажити» ще раз, коли вона буде готова")
            }
        }
    }
    val videos: List<Video> get() = lib?.videos ?: emptyList()
    val connected get() = prefs.server.isNotEmpty()
    val host: String get() = prefs.host.ifEmpty { "pc" }
    val spriteN get() = lib?.spriteN ?: 20

    init {
        if (!connected) nav.go(Connect)
        startPolling()
    }

    // ── оновлення апки з GitHub ──
    var update by mutableStateOf<Update?>(null)
        private set
    var updateState by mutableStateOf("")      // "", "checking", "latest", "error: …", "downloading"
        private set
    var updateProgress by mutableStateOf(0f)
        private set

    init { checkUpdate(manual = false) }   // після оголошення стану оновлення, інакше він ще null

    fun checkUpdate(manual: Boolean = true) = viewModelScope.launch {
        if (updateState == "checking" || updateState == "downloading") return@launch
        updateState = "checking"
        runCatching { Updater.check() }
            .onSuccess { u ->
                update = u
                updateState = if (u == null) "latest" else ""
                if (u != null && !manual) say("Є нова версія апки ${u.name}", "Оновити") { installUpdate() }
                if (u == null && manual) say("Встановлено найновішу версію")
            }
            .onFailure { updateState = if (manual) "error: ${it.message}" else "" }
    }

    fun installUpdate() = viewModelScope.launch {
        val u = update ?: return@launch
        if (updateState == "downloading") return@launch
        updateState = "downloading"
        updateProgress = 0f
        val ctx = getApplication<Application>()
        runCatching { Updater.download(ctx, u) { p -> updateProgress = p } }
            .onSuccess { f ->
                updateState = ""
                if (!Updater.install(ctx, f)) say("Дозволь VidBox встановлювати апки й натисни «Оновити» ще раз")
            }
            .onFailure { updateState = "error: ${it.message}" }
    }

    fun say(text: String, action: String? = null, onAction: (() -> Unit)? = null) {
        toast = Toast(text, action, onAction)
    }

    // ── завантаження ──
    fun refresh(withWeek: Boolean = true) {
        viewModelScope.launch { load(withWeek) }
    }

    private suspend fun load(withWeek: Boolean) {
        if (!connected) return
        loading = true
        try {
            val l = api.library()
            // випадковий порядок не перемішуємо при кожному оновленні
            l.videos.forEach { if (it.id !in rnd) rnd[it.id] = Random.nextDouble() }
            lib = l
            if (!uiFromServer) {   // сортування беремо з ПК лише раз — далі воно наше, локальне
                ui = l.cfg.ui
                uiFromServer = true
            }
            if (l.cfg.hataTheme != hataTheme) {
                hataTheme = l.cfg.hataTheme
                prefs.hataTheme = l.cfg.hataTheme ?: ""
            }
            if (System.currentTimeMillis() - themeSetAt > 10_000 && l.cfg.theme != themeId) {
                themeId = l.cfg.theme
                prefs.theme = l.cfg.theme
            }
            if (withWeek || week == null) week = api.week()
            offline = null
        } catch (e: AuthException) {
            offline = null
            prefs.token = ""
            nav.go(Connect)
        } catch (e: Exception) {
            offline = e.message ?: "немає зв'язку"
        } finally {
            loading = false
        }
    }

    private fun startPolling() {
        poller?.cancel()
        poller = viewModelScope.launch {
            load(true)
            while (true) {
                val busy = (lib?.spritesPending ?: 0) > 0 || (lib?.pending ?: 0) > 0
                delay(if (busy) 6_000 else if (offline != null) 8_000 else 45_000)
                if (foreground && connected && nav.top !is Player) load(false)
            }
        }
    }

    fun onConnected(base: String, token: String, host: String) {
        prefs.server = base
        prefs.token = token
        prefs.host = host
        lib = null
        week = null
        uiFromServer = false
        queue = null
        folder = null
        query = ""
        nav.go(Home)
        startPolling()
    }

    fun disconnect() {
        prefs.server = ""
        prefs.token = ""
        lib = null
        week = null
        nav.go(Connect)
    }

    // ── сортування й групування (зберігаються на ПК, але локальний вибір не перетирається) ──
    fun changeUi(u: Ui) {
        if (u.sort == "random" && ui.sort == "random") reshuffle()
        ui = u
        viewModelScope.launch { runCatching { api.saveSettings(JSONObject().put("ui", u.json())) } }
    }

    fun reshuffle() {
        rnd = HashMap(videos.associate { it.id to Random.nextDouble() })
        rndGen++
    }

    fun rndMap(): Map<String, Double> = rnd

    fun setTheme(id: String) {
        themeId = id
        prefs.theme = id
        themeSetAt = System.currentTimeMillis()
        viewModelScope.launch { runCatching { api.saveSettings(JSONObject().put("theme", id)) } }
    }

    fun saveServer(o: JSONObject, then: () -> Unit = {}) {
        viewModelScope.launch {
            runCatching { api.saveSettings(o) }.onFailure { say("Не вдалося зберегти: ${it.message}") }
            load(false)
            then()
        }
    }

    fun rescan() {
        viewModelScope.launch {
            try {
                val r = api.rescan()
                val n = r.optInt("new")
                say(if (n > 0) "Знайдено нових відео: $n" else "Нових відео немає, всього ${r.optInt("total")}")
                load(true)
            } catch (e: Exception) {
                say("Не вдалося пересканувати: ${e.message}")
            }
        }
    }

    fun refreshWeek() {
        viewModelScope.launch {
            try {
                week = api.weekRefresh()
                say("Зібрав нову підбірку")
            } catch (e: Exception) {
                say("Немає зв'язку з комп'ютером")
            }
        }
    }

    // ── відео ──
    fun update(id: String, f: (Video) -> Video) {
        val l = lib ?: return
        lib = l.copy(videos = l.videos.map { if (it.id == id) f(it) else it })
    }

    fun vote(v: Video, value: Int) {
        val nv = if (v.vote == value) 0 else value
        update(v.id) { it.copy(vote = nv) }
        viewModelScope.launch {
            try {
                val r = api.vote(v.id, nv)
                if (r.optBoolean("ok")) update(v.id) {
                    it.copy(
                        score = r.optDouble("score", it.score), views = r.optInt("views", it.views),
                        avg = if (r.isNull("avg")) null else r.optDouble("avg"), pop = r.optDouble("pop", it.pop),
                        cmp = r.optDouble("cmp", it.cmp), last = r.optDouble("last", it.last),
                    )
                }
            } catch (e: Exception) {
                say("Оцінка не збереглась: немає зв'язку")
            }
        }
    }

    fun ensureSprite(v: Video) {
        if (lib?.ffmpeg != true || v.sprite != 0L || v.dur <= 0) return
        viewModelScope.launch {
            runCatching { api.requestSprite(v.id) }.onSuccess { s -> if (s != 0L) update(v.id) { it.copy(sprite = s) } }
        }
    }

    fun randomVideo(exclude: String? = null): Video? {
        val pool = videos.filter { it.vote >= 0 && it.id != exclude }
        if (pool.isEmpty()) return null
        val w = pool.map { (if (it.views > 0) 1.0 else 3.0) * (if (it.vote > 0) 1.5 else 1.0) }
        var r = Random.nextDouble() * w.sum()
        for (k in pool.indices) {
            r -= w[k]
            if (r <= 0) return pool[k]
        }
        return pool.last()
    }

    fun openRandom(replace: Boolean = false) {
        val v = randomVideo((nav.top as? Info)?.id)
        if (v == null) {
            say("Бібліотека порожня")
            return
        }
        if (replace) nav.replace(Info(v.id, true)) else nav.go(Info(v.id, true))
    }

    fun siblings(v: Video) = videos.filter { it.folder == v.folder }.sortedWith(byName)

    fun moreFromFolder(v: Video): List<Video> {
        val sib = siblings(v)
        val k = sib.indexOfFirst { it.id == v.id }
        return (sib.drop(k + 1) + sib.take(maxOf(k, 0))).filter { it.id != v.id }.take(14)
    }

    // ── плейлисти й черга ──
    fun plItems(id: String): List<Video> {
        val g = lenGroup(id) ?: return emptyList()
        return videos.filter(g.test).sortedWith(inOrder)
    }

    fun playQueue(id: String, startId: String? = null, shuffle: Boolean = false) {
        val g = lenGroup(id) ?: return
        var vs = plItems(id)
        if (vs.isEmpty()) {
            say("У цьому плейлисті поки немає відео")
            return
        }
        if (shuffle) vs = vs.shuffled()
        val ids = vs.map { it.id }
        queue = Queue(g.id, g.name, ids, shuffle)
        nav.go(Player(startId ?: ids[0]))
    }

    fun queueFor(v: Video) = queue?.takeIf { v.id in it.ids }

    fun loadAnime() = viewModelScope.launch {
        runCatching { api.anime() }.onSuccess { animeList = it }.onFailure { if (it is AuthException) nav.go(Connect) }
    }

    fun loadAnimeShow(sid: String) = viewModelScope.launch {
        runCatching { api.animeTitle(sid) }.onSuccess { t ->
            t.eps.forEach { animeEps[it.v.id] = it.v }
            animeShows[sid] = t
        }
    }

    // ── манга ──
    var mangaList by mutableStateOf<app.vidbox.data.MangaList?>(null)
    val mangaShows = mutableStateMapOf<String, app.vidbox.data.MangaTitle>()
    var mangaFilter by mutableStateOf(prefs.mangaFilter)
    var mangaNewest by mutableStateOf(false)

    fun loadManga() = viewModelScope.launch {
        runCatching { api.manga() }.onSuccess { mangaList = it }.onFailure { if (it is AuthException) nav.go(Connect) }
    }

    fun loadMangaShow(tid: String) = viewModelScope.launch {
        runCatching { api.mangaTitle(tid) }.onSuccess { mangaShows[tid] = it }
    }

    private var mangaSave: Job? = null

    /** Де зупинився в читалці → на ПК. Гортання підряд зберігається раз, після паузи. */
    fun mangaRead(cid: String, page: Int, done: Boolean, now: Boolean = false) {
        mangaSave?.cancel()
        mangaSave = viewModelScope.launch {
            if (!now) delay(800)
            runCatching { api.mangaProgress(cid, page, done) }
        }
    }

    fun pickMangaFilter(f: String) {
        mangaFilter = f
        prefs.mangaFilter = f
    }

    fun setMangaMode(tid: String, mode: String) {
        mangaShows[tid]?.let { mangaShows[tid] = it.copy(mode = mode) }
        viewModelScope.launch { runCatching { api.mangaMode(tid, mode) } }
    }

    /** Скинути опис і обкладинку з інтернету: обкладинкою стає перша сторінка. */
    fun resetManga(tid: String) = viewModelScope.launch {
        runCatching { api.mangaReset(tid) }.onSuccess { say("Дані скинуто") }.onFailure { say("Не вдалося: ${it.message}") }
        loadMangaShow(tid)
        loadManga()
    }

    fun markManga(tid: String, cids: List<String>, read: Boolean) = viewModelScope.launch {
        runCatching { api.mangaMark(cids, read) }
        loadMangaShow(tid)
    }

    fun playAnime(t: AnimeTitle, id: String) {
        queue = Queue("anime", t.title, t.eps.map { it.v.id }, false, anime = t.sid)
        nav.go(Player(id))
    }

    fun nextOf(v: Video): Video? {
        queueFor(v)?.let { q ->
            val i = q.ids.indexOf(v.id)
            return q.ids.getOrNull(i + 1)?.let { byId[it] }
        }
        val sib = siblings(v)
        val i = sib.indexOfFirst { it.id == v.id }
        if (i >= 0 && i < sib.size - 1) return sib[i + 1]
        return videos.filter { it.id != v.id && it.views == 0 && it.vote >= 0 }.minByOrNull { rnd[it.id] ?: 0.0 }
    }

    /** Після перегляду оновлюємо місце зупинки локально, не чекаючи сервера. */
    fun localPos(id: String, pos: Double) {
        dl.setPos(id, pos)
        update(id) { it.copy(pos = pos, posAt = System.currentTimeMillis() / 1000.0) }
    }

    // ── підписи ──
    fun libCmd(): String {
        val u = ui
        return "ls --sort=" + u.sort + (if (u.dir == "asc" && u.sort != "random") " --reverse" else "") +
            when (u.group) { "folders" -> " --group=folder"; "duration" -> " --group=length"; else -> "" } +
            (folder?.let { " ./" + Fmt.shortFolder(it).replace(" / ", "/") } ?: "") +
            (if (query.isNotBlank()) " | grep -i '${query.trim()}'" else "")
    }

    val playlists get() = LEN_GROUPS
}
