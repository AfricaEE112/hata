package app.vidbox.ui.screens

import android.view.KeyEvent
import android.view.WindowManager
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChanged
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import app.vidbox.AppVM
import app.vidbox.MainActivity
import app.vidbox.Reader
import app.vidbox.data.Fmt
import app.vidbox.data.MangaRead
import app.vidbox.ui.*
import coil.compose.AsyncImage
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

// Читалка манги. Типово справа наліво, як у японській манзі: лівий край / свайп праворуч — далі.
// Режими: справа наліво, зліва направо, стрічка (вниз), розворот (дві сторінки на широкому екрані).

private val MODE_SHORT = mapOf("rtl" to "← стор.", "ltr" to "стор. →", "strip" to "стрічка", "spread" to "розворот")
private val MODE_HINT = mapOf("rtl" to "Справа наліво, як у японській манзі", "ltr" to "Зліва направо", "strip" to "Усі сторінки вниз",
    "spread" to "Розворот: дві сторінки на широкому екрані")

@Composable
fun ReaderScreen(vm: AppVM, route: Reader, activity: MainActivity) {
    var ch by remember(route.cid) { mutableStateOf<MangaRead?>(null) }
    var err by remember(route.cid) { mutableStateOf<String?>(null) }
    LaunchedEffect(route.cid) {
        runCatching { vm.api.mangaChapter(route.cid) }.onSuccess { ch = it }.onFailure { err = it.message ?: "Немає зв’язку з ПК" }
    }
    // на весь екран, екран не гасне
    DisposableEffect(Unit) {
        val w = activity.window
        val c = WindowCompat.getInsetsController(w, w.decorView)
        c.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        c.hide(WindowInsetsCompat.Type.systemBars())
        w.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose {
            c.show(WindowInsetsCompat.Type.systemBars())
            w.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }
    val p = LocalPal.current
    Box(Modifier.fillMaxSize().background(Color(0xFF08080C))) {
        val c = ch
        when {
            c != null -> key(c.cid) { ReaderBody(vm, c, route.page) }
            err != null -> Column(Modifier.align(Alignment.Center).padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Не вдалося відкрити розділ", style = display(24.sp), color = Color.White)
                Spacer(Modifier.height(8.dp))
                Text(err ?: "", style = body(14.sp), color = Color(0xFFAAAAAA), textAlign = TextAlign.Center)
                Spacer(Modifier.height(16.dp))
                Btn("Назад", { vm.nav.back() }, icon = Ic.left)
            }
            else -> Text("Відкриваю…", style = mono(13.sp), color = p.mute, modifier = Modifier.align(Alignment.Center))
        }
    }
}

@Composable
private fun ReaderBody(vm: AppVM, c: MangaRead, startAt: Int?) {
    val p = LocalPal.current
    val scope = rememberCoroutineScope()
    val cfg = LocalConfiguration.current
    val screenPx = with(LocalDensity.current) { cfg.screenHeightDp.dp.toPx() }
    val wide = cfg.screenWidthDp > cfg.screenHeightDp && cfg.screenWidthDp >= 560
    var mode by remember { mutableStateOf(c.mode) }
    val n = c.pages.coerceAtLeast(1)
    var page by remember { mutableIntStateOf((startAt ?: if (c.done) 1 else c.page).coerceIn(1, n)) }
    var ended by remember { mutableStateOf(false) }
    var ui by remember { mutableStateOf(true) }
    var zoomed by remember { mutableStateOf(false) }
    val rtl = mode == "rtl" || mode == "spread"
    val spread = mode == "spread" && wide

    // прогрес — на ПК (з невеликою паузою, щоб не смикати сервер на кожному гортанні)
    LaunchedEffect(page, ended) { vm.mangaRead(c.cid, page, ended) }
    DisposableEffect(Unit) { onDispose { vm.mangaRead(c.cid, page, ended, now = true) } }

    val next = { vm.nav.replace(Reader(c.next!!.cid, 1)) }
    Box(Modifier.fillMaxSize()) {
        if (mode == "strip") {
            val list = rememberLazyListState(initialFirstVisibleItemIndex = page - 1)
            LaunchedEffect(list) {
                snapshotFlow { list.firstVisibleItemIndex to list.layoutInfo.totalItemsCount }.collect { (i, total) ->
                    if (total > 0) {
                        ended = i >= n
                        if (i < n) page = i + 1
                    }
                }
            }
            LaunchedEffect(Unit) {
                vm.keys.collectLatest { k ->
                    when (k) {
                        KeyEvent.KEYCODE_VOLUME_DOWN, KeyEvent.KEYCODE_PAGE_DOWN, KeyEvent.KEYCODE_SPACE, KeyEvent.KEYCODE_DPAD_DOWN -> list.animateScrollBy(screenPx * 0.8f)
                        KeyEvent.KEYCODE_VOLUME_UP, KeyEvent.KEYCODE_PAGE_UP, KeyEvent.KEYCODE_DPAD_UP -> list.animateScrollBy(-screenPx * 0.8f)
                    }
                }
            }
            LazyColumn(
                state = list, modifier = Modifier.fillMaxSize().clickable(remember { MutableInteractionSource() }, null) { ui = !ui },
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                items(n, key = { it }) { i ->
                    AsyncImage(
                        model = vm.api.pageUrl(c.cid, i + 1), contentDescription = "Сторінка ${i + 1}", contentScale = ContentScale.FillWidth,
                        modifier = Modifier.widthIn(max = 900.dp).fillMaxWidth().heightIn(min = 120.dp),
                    )
                }
                item(key = "end") { EndCard(c, next, { vm.nav.back() }, Modifier.padding(vertical = 60.dp)) }
            }
        } else key(spread) {
            // одиниці гортання: сторінка, або розворот (1 окремо, далі 2–3, 4–5…)
            val units = remember(spread, n) { if (spread) listOf(listOf(1)) + (2..n step 2).map { listOf(it, it + 1).filter { x -> x <= n } } else (1..n).map { listOf(it) } }
            val start = units.indexOfFirst { page in it }.coerceAtLeast(0)
            val pager = rememberPagerState(initialPage = if (ended) units.size else start) { units.size + 1 }
            LaunchedEffect(pager, units) {
                snapshotFlow { pager.currentPage }.collect { i ->
                    ended = i >= units.size
                    if (i < units.size) page = units[i].first()
                    zoomed = false
                }
            }
            fun go(d: Int) = scope.launch {
                val t = pager.currentPage + d
                if (t < 0) { if (c.prev != null) vm.say("Це перша сторінка. Попередній: ${c.prev.label}"); return@launch }
                if (t > units.size) { if (c.next != null) next(); return@launch }
                if (ui) ui = false
                pager.animateScrollToPage(t)
            }
            LaunchedEffect(Unit) {
                vm.keys.collectLatest { k ->
                    when (k) {
                        KeyEvent.KEYCODE_VOLUME_DOWN, KeyEvent.KEYCODE_PAGE_DOWN, KeyEvent.KEYCODE_SPACE -> go(1)
                        KeyEvent.KEYCODE_VOLUME_UP, KeyEvent.KEYCODE_PAGE_UP -> go(-1)
                        KeyEvent.KEYCODE_DPAD_LEFT -> go(if (rtl) 1 else -1)
                        KeyEvent.KEYCODE_DPAD_RIGHT -> go(if (rtl) -1 else 1)
                    }
                }
            }
            HorizontalPager(
                state = pager, reverseLayout = rtl, beyondViewportPageCount = 2, userScrollEnabled = !zoomed,
                key = { if (it < units.size) "u" + units[it].first() else "end" }, modifier = Modifier.fillMaxSize(),
            ) { i ->
                if (i >= units.size) {
                    Box(Modifier.fillMaxSize().clickable(remember { MutableInteractionSource() }, null) { ui = !ui }, contentAlignment = Alignment.Center) {
                        EndCard(c, next, { vm.nav.back() })
                    }
                } else {
                    Zoomable(
                        onZoom = { if (pager.currentPage == i) zoomed = it },
                        onTap = { x ->
                            when {
                                x < .34f -> go(if (rtl) 1 else -1)
                                x > .66f -> go(if (rtl) -1 else 1)
                                else -> ui = !ui
                            }
                        },
                    ) {
                        // у розвороті справа наліво менша сторінка — праворуч
                        val pages = if (rtl) units[i].reversed() else units[i]
                        if (pages.size == 1) {
                            AsyncImage(model = vm.api.pageUrl(c.cid, pages[0]), contentDescription = "Сторінка ${pages[0]}",
                                contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize())
                        } else Row(Modifier.fillMaxSize(), verticalAlignment = Alignment.CenterVertically) {
                            pages.forEachIndexed { k, pg ->
                                AsyncImage(
                                    model = vm.api.pageUrl(c.cid, pg), contentDescription = "Сторінка $pg", contentScale = ContentScale.Fit,
                                    modifier = Modifier.fillMaxHeight().weight(1f),
                                    alignment = if (k == 0) Alignment.CenterEnd else Alignment.CenterStart,
                                )
                            }
                        }
                    }
                }
            }
            // повзунок: стрибок на сторінку
            SliderBar(ui && !ended, page, n, rtl, c, onJump = { target ->
                scope.launch { pager.scrollToPage(units.indexOfFirst { target in it }.coerceAtLeast(0)) }
            }, onChapter = { cid -> vm.nav.replace(Reader(cid, 1)) }, modifier = Modifier.align(Alignment.BottomCenter))
        }
        if (mode == "strip") {
            SliderBar(ui && !ended, page, n, false, c, onJump = {}, onChapter = { cid -> vm.nav.replace(Reader(cid, 1)) },
                modifier = Modifier.align(Alignment.BottomCenter), slider = false)
        }

        // верхня панель
        AnimatedVisibility(ui, enter = fadeIn() + slideInVertically { -it }, exit = fadeOut() + slideOutVertically { -it }, modifier = Modifier.align(Alignment.TopCenter)) {
            Row(
                Modifier.fillMaxWidth().background(p.bg2.copy(alpha = .94f)).statusBarsPadding().padding(horizontal = 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconBtn(Ic.left, { vm.nav.back() }, desc = "До тайтлу")
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(c.title, style = display(17.sp), color = p.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text((if (c.count > 1) c.label + " · " else "") + "стор. $page / $n", style = mono(11.5.sp), color = p.mute, maxLines = 1)
                }
                Spacer(Modifier.width(8.dp))
                Chip(MODE_SHORT[mode] ?: mode) {
                    val order = listOf("rtl", "ltr", "strip", "spread")
                    mode = order[(order.indexOf(mode) + 1) % order.size]
                    vm.setMangaMode(c.tid, mode)
                    vm.say(MODE_HINT[mode] ?: mode)
                }
            }
        }
    }
}

/** Нижня панель: розділи по боках (з того боку, куди гортаємо) і повзунок сторінок. */
@Composable
private fun SliderBar(
    visible: Boolean, page: Int, n: Int, rtl: Boolean, c: MangaRead, onJump: (Int) -> Unit, onChapter: (String) -> Unit,
    modifier: Modifier = Modifier, slider: Boolean = true,
) {
    val p = LocalPal.current
    AnimatedVisibility(visible, enter = fadeIn() + slideInVertically { it }, exit = fadeOut() + slideOutVertically { it }, modifier = modifier) {
        Column(Modifier.fillMaxWidth().background(p.bg2.copy(alpha = .94f)).navigationBarsPadding().padding(horizontal = 12.dp, vertical = 10.dp)) {
            if (slider && n > 1) {
                var drag by remember { mutableStateOf<Float?>(null) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (rtl) "$n" else "1", style = mono(11.sp), color = p.mute)
                    CompositionLocalProvider(LocalLayoutDirection provides if (rtl) LayoutDirection.Rtl else LayoutDirection.Ltr) {
                        Slider(
                            value = drag ?: page.toFloat(), onValueChange = { drag = it },
                            onValueChangeFinished = { drag?.let { onJump(it.roundToInt()) }; drag = null },
                            valueRange = 1f..n.toFloat(), modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
                            colors = SliderDefaults.colors(thumbColor = p.fg, activeTrackColor = p.acc, inactiveTrackColor = p.line),
                        )
                    }
                    Text(if (rtl) "1" else "$n", style = mono(11.sp), color = p.mute)
                }
                drag?.let { Text("стор. ${it.roundToInt()}", style = mono(12.sp), color = p.acc, modifier = Modifier.align(Alignment.CenterHorizontally)) }
            }
            val (l, r) = if (rtl) c.next to c.prev else c.prev to c.next
            if (l != null || r != null) {
                Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Box(Modifier.weight(1f)) { if (l != null) Btn(l.label, { onChapter(l.cid) }, icon = Ic.left, modifier = Modifier.fillMaxWidth()) }
                    Box(Modifier.weight(1f)) { if (r != null) Btn(r.label + "  ›", { onChapter(r.cid) }, modifier = Modifier.fillMaxWidth()) }
                }
            }
        }
    }
}

@Composable
private fun EndCard(c: MangaRead, next: () -> Unit, back: () -> Unit, modifier: Modifier = Modifier) {
    val p = LocalPal.current
    Column(modifier.widthIn(max = 440.dp).padding(28.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("✓ " + (if (c.count > 1) c.label else c.title) + " — прочитано", style = mono(13.sp), color = Color(0xFF9ECE6A))
        if (c.next != null) {
            Text("Далі: ${c.next.label}", style = display(30.sp), color = Color.White)
            Text("${c.next.pages} " + Fmt.plural(c.next.pages, "сторінка", "сторінки", "сторінок"), style = body(14.sp), color = Color(0xFFB0B0B8))
            Btn("Читати далі", next, icon = Ic.play, kind = Kind.Primary, modifier = Modifier.fillMaxWidth())
        } else {
            Text(if (c.count > 1) "Це останній розділ" else "Кінець", style = display(30.sp), color = Color.White)
            Text("Нові розділи з’являться тут, щойно вони будуть у папці на ПК.", style = body(14.sp), color = Color(0xFFB0B0B8))
        }
        Btn("До тайтлу", back, modifier = Modifier.fillMaxWidth())
    }
}

/** Масштаб: розведення двох пальців або подвійний дотик. Поки сторінку збільшено — гортання вимкнене, палець рухає сторінку. */
@Composable
private fun Zoomable(onZoom: (Boolean) -> Unit, onTap: (Float) -> Unit, content: @Composable () -> Unit) {
    var scale by remember { mutableFloatStateOf(1f) }
    var off by remember { mutableStateOf(Offset.Zero) }
    var size by remember { mutableStateOf(IntSize.Zero) }
    fun clamp(o: Offset, s: Float): Offset {
        val mx = size.width * (s - 1) / 2
        val my = size.height * (s - 1) / 2
        return Offset(o.x.coerceIn(-mx, mx), o.y.coerceIn(-my, my))
    }
    Box(
        Modifier.fillMaxSize().onSizeChanged { size = it }
            .pointerInput(Unit) {
                detectTapGestures(
                    onTap = { onTap(it.x / size.width.coerceAtLeast(1)) },
                    onDoubleTap = { pos ->
                        if (scale > 1f) { scale = 1f; off = Offset.Zero } else {
                            scale = 2.5f
                            off = clamp((Offset(size.width / 2f, size.height / 2f) - pos) * 1.5f, 2.5f)
                        }
                        onZoom(scale > 1f)
                    },
                )
            }
            .pointerInput(Unit) {
                awaitEachGesture {
                    awaitFirstDown(requireUnconsumed = false)
                    do {
                        val ev = awaitPointerEvent()
                        val fingers = ev.changes.count { it.pressed }
                        if (fingers >= 2 || scale > 1f) {
                            val ns = (scale * ev.calculateZoom()).coerceIn(1f, 5f)
                            off = if (ns <= 1f) Offset.Zero else clamp(off + ev.calculatePan(), ns)
                            scale = ns
                            onZoom(scale > 1.01f)
                            ev.changes.forEach { if (it.positionChanged()) it.consume() }
                        }
                    } while (ev.changes.any { it.pressed })
                    if (scale < 1.05f && scale != 1f) { scale = 1f; off = Offset.Zero; onZoom(false) }
                }
            },
    ) {
        Box(Modifier.fillMaxSize().graphicsLayer { scaleX = scale; scaleY = scale; translationX = off.x; translationY = off.y }) { content() }
    }
}
