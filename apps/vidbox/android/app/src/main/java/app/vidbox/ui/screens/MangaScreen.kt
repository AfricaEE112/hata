package app.vidbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.vidbox.AppVM
import app.vidbox.MangaShow
import app.vidbox.Reader
import app.vidbox.data.Fmt
import app.vidbox.data.MangaChapter
import app.vidbox.data.MangaTitle
import app.vidbox.data.mangaFormat
import app.vidbox.data.mangaSource
import app.vidbox.data.mangaStatus
import app.vidbox.ui.*
import coil.compose.AsyncImage

// Манга: бібліотека з обкладинками, сторінка тайтлу з розділами. Читалка — ReaderScreen.kt.

val MANGA_MODES = listOf("rtl" to "← по сторінці", "ltr" to "по сторінці →", "strip" to "стрічка", "spread" to "розворот")
private val FILTERS = listOf("all" to "Усі", "reading" to "Читаю", "new" to "Нові розділи", "done" to "Прочитано", "none" to "Не почато")

private fun state(t: MangaTitle) = if (t.done) "done" else if (t.lastAt > 0) "reading" else "none"
private fun units(t: MangaTitle, n: Int) = "$n " + if (t.vols) Fmt.plural(n, "том", "томи", "томів") else Fmt.plural(n, "розділ", "розділи", "розділів")
private fun pagesWord(n: Int) = "$n " + Fmt.plural(n, "сторінка", "сторінки", "сторінок")

private fun sub(t: MangaTitle): String = when {
    t.done -> (if (t.single) "${t.pages} стор." else units(t, t.n)) + " · прочитано"
    t.single -> t.cont?.let { "стор. ${it.page} / ${t.pages}" } ?: pagesWord(t.pages)
    t.lastAt > 0 -> (if (t.vols) "т. " else "гл. ") + "${t.read} / ${t.n}"
    else -> units(t, t.n)
}

@Composable
private fun MangaCover(vm: AppVM, t: MangaTitle, modifier: Modifier = Modifier) {
    val p = LocalPal.current
    Box(modifier.aspectRatio(2f / 3f).clip(RoundedCornerShape(10.dp)).background(p.bg3).border(1.dp, p.line, RoundedCornerShape(10.dp))) {
        Text((t.title.trim().firstOrNull() ?: '?').uppercase(), style = mono(30.sp, FontWeight.Bold), color = p.mute, modifier = Modifier.align(Alignment.Center))
        AsyncImage(model = vm.api.url(t.cover), contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
    }
}

@Composable
private fun MangaCard(vm: AppVM, t: MangaTitle) {
    val p = LocalPal.current
    Column(Modifier.clip(RoundedCornerShape(10.dp)).clickable { vm.nav.go(MangaShow(t.tid)) }) {
        Box {
            MangaCover(vm, t, Modifier.fillMaxWidth())
            when {
                t.new > 0 -> MBadge("+${t.new} " + Fmt.plural(t.new, "нова", "нові", "нових"), p.acc, p.on)
                t.done -> MBadge("✓ прочитано", p.bg2, p.mute)
            }
            if (!t.done && t.progress > 0f) Meter(t.progress, Modifier.align(Alignment.BottomCenter).fillMaxWidth(), track = Color.Black.copy(alpha = .45f))
        }
        Spacer(Modifier.height(6.dp))
        Text(t.title, style = body(13.sp, FontWeight.SemiBold), color = p.fg, maxLines = 2, overflow = TextOverflow.Ellipsis)
        Text((t.meta?.year?.takeIf { it > 0 }?.let { "$it · " } ?: "") + sub(t), style = body(11.5.sp), color = p.mute, maxLines = 1)
    }
}

@Composable
private fun MBadge(text: String, bg: Color, fg: Color) {
    Text(text, style = mono(10.5.sp, FontWeight.Bold), color = fg,
        modifier = Modifier.padding(6.dp).clip(RoundedCornerShape(6.dp)).background(bg).padding(horizontal = 6.dp, vertical = 3.dp))
}

/** Картка «Продовжити читати»: одразу в читалку на тій сторінці, де зупинився. */
@Composable
private fun ContCard(vm: AppVM, t: MangaTitle) {
    val p = LocalPal.current
    val c = t.cont ?: return
    Row(
        Modifier.width(280.dp).clip(RoundedCornerShape(12.dp)).background(p.bg2.copy(alpha = .85f)).border(1.dp, p.line, RoundedCornerShape(12.dp))
            .clickable { vm.nav.go(Reader(c.cid, c.page)) }.padding(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MangaCover(vm, t, Modifier.width(54.dp))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(t.title, style = body(14.sp, FontWeight.SemiBold), color = p.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text((if (t.single || c.label.isEmpty()) "" else c.label + " · ") + "стор. ${c.page} / ${c.pages}", style = mono(11.5.sp), color = p.acc, maxLines = 1)
            Spacer(Modifier.height(6.dp))
            Meter((c.page - 1f) / c.pages.coerceAtLeast(1), Modifier.fillMaxWidth())
            Spacer(Modifier.height(4.dp))
            Text(Fmt.ago(t.lastAt), style = body(11.5.sp), color = p.mute)
        }
    }
}

@Composable
fun MangaScreen(vm: AppVM) {
    LaunchedEffect(Unit) { vm.loadManga() }
    val p = LocalPal.current
    val d = vm.mangaList
    val w = LocalConfiguration.current.screenWidthDp
    val cols = if (w >= 840) 6 else if (w >= 600) 4 else 3
    val full = GridItemSpan(cols)
    LazyVerticalGrid(
        GridCells.Fixed(cols), state = vm.nav.grid("manga"), modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = PAD, end = PAD, top = 14.dp, bottom = 28.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item(span = { full }) { PromptLine("~/манга", "ls") }
        item(span = { full }) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text("Манга", style = display(38.sp), color = p.fg)
                d?.titles?.size?.takeIf { it > 0 }?.let {
                    Spacer(Modifier.width(12.dp))
                    Text("$it", style = mono(13.sp), color = p.mute, modifier = Modifier.padding(bottom = 6.dp))
                }
            }
        }
        when {
            d == null -> item(span = { full }) { Lead("Завантажую…") }
            d.folder.isEmpty() || d.missing -> item(span = { full }) {
                Empty(if (d.missing) "Папку не знайдено" else "Папку не вказано",
                    if (d.missing) "Папки ${d.folder} зараз немає. Можливо, диск від’єднано."
                    else "Вкажи папку з мангою на сайті: Налаштування → Манга. Кожна підпапка або архів .zip/.cbz стане тайтлом.")
            }
            d.titles.isEmpty() -> item(span = { full }) { Empty("Поки порожньо", if (d.scanning) "Переглядаю папку…" else "У папці з мангою поки нічого немає.") }
            else -> {
                val cont = d.titles.filter { it.cont != null && it.lastAt > 0 }.sortedByDescending { it.lastAt }.take(8)
                if (cont.isNotEmpty()) {
                    item(span = { full }) { Text("Продовжити читати", style = body(17.sp, FontWeight.Bold), color = p.fg) }
                    item(span = { full }) {
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(end = PAD)) {
                            items(cont, key = { it.tid }) { ContCard(vm, it) }
                        }
                    }
                }
                item(span = { full }) {
                    Row(Modifier.horizontalScroll(rememberScrollState()).padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FILTERS.forEach { (k, l) ->
                            val n = if (k == "all") null else d.titles.count { if (k == "new") it.new > 0 else state(it) == k }
                            Chip(l + (n?.let { " $it" } ?: ""), on = vm.mangaFilter == k) { vm.pickMangaFilter(k) }
                        }
                    }
                }
                val list = d.titles.filter { vm.mangaFilter == "all" || if (vm.mangaFilter == "new") it.new > 0 else state(it) == vm.mangaFilter }
                if (list.isEmpty()) item(span = { full }) { Lead("Тут поки порожньо.", Modifier.padding(top = 8.dp)) }
                items(list, key = { it.tid }) { MangaCard(vm, it) }
            }
        }
    }
}

@Composable
fun MangaShowScreen(vm: AppVM, tid: String) {
    LaunchedEffect(tid) { vm.loadMangaShow(tid) }
    val p = LocalPal.current
    val t = vm.mangaShows[tid]
    var ask by remember { mutableStateOf<Pair<MangaChapter, List<String>>?>(null) }
    LazyColumn(state = vm.nav.list("manga/$tid"), contentPadding = PaddingValues(top = 14.dp, bottom = 28.dp), modifier = Modifier.fillMaxSize()) {
        if (t == null) {
            item { Lead("Завантажую…", Modifier.padding(horizontal = PAD)) }
            return@LazyColumn
        }
        val c = t.cont
        val first = t.chapters.firstOrNull()
        item { PromptLine("~/манга/" + t.title, "ls", Modifier.padding(horizontal = PAD)) }
        item {
            Row(Modifier.padding(horizontal = PAD, vertical = 10.dp), verticalAlignment = Alignment.Bottom) {
                MangaCover(vm, t, Modifier.width(118.dp))
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f)) {
                    Text(t.title, style = display(26.sp), color = p.fg, maxLines = 3, overflow = TextOverflow.Ellipsis)
                    t.meta?.alt?.takeIf { it.isNotEmpty() }?.let {
                        Text(it.joinToString(" · "), style = body(12.5.sp), color = p.mute, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                    Spacer(Modifier.height(4.dp))
                    Text(if (t.single) pagesWord(t.pages) else units(t, t.n) + if (t.read > 0) " · прочитано ${t.read}" else "", style = body(13.5.sp), color = p.mute)
                }
            }
        }
        item {
            Row(Modifier.padding(horizontal = PAD).padding(bottom = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (c != null) {
                    Btn(if (t.single || c.label.isEmpty()) "Продовжити · стор. ${c.page}" else "Продовжити · ${c.label}", { vm.nav.go(Reader(c.cid, c.page)) },
                        icon = Ic.play, kind = Kind.Primary, modifier = Modifier.weight(1f, fill = false))
                    if (first != null) Btn("З початку", { vm.nav.go(Reader(first.cid, 1)) })
                } else if (first != null) {
                    Btn(if (t.done) "Читати ще раз" else "Почати читати", { vm.nav.go(Reader(first.cid, 1)) }, icon = Ic.play, kind = Kind.Primary)
                }
            }
        }
        item {
            Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = PAD).padding(bottom = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("читати", style = body(13.sp), color = p.mute)
                Spacer(Modifier.width(2.dp))
                MANGA_MODES.forEach { (k, l) -> Chip(l, on = t.mode == k) { vm.setMangaMode(tid, k) } }
            }
        }
        t.meta?.let { m -> item { MangaMetaBlock(m) } }
        if (!t.single) {
            item {
                Row(Modifier.padding(horizontal = PAD).padding(top = 6.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(if (t.vols) "Томи" else "Розділи", style = body(17.sp, FontWeight.Bold), color = p.fg)
                    Spacer(Modifier.width(8.dp))
                    Text("${t.n}", style = mono(12.sp), color = p.mute)
                    Spacer(Modifier.weight(1f))
                    Chip(if (vm.mangaNewest) "↓ нові зверху" else "↑ з першої") { vm.mangaNewest = !vm.mangaNewest }
                }
            }
            val list = if (vm.mangaNewest) t.chapters.reversed() else t.chapters
            items(list, key = { it.cid }) { ch ->
                ChapterRow(ch, ch.cid == c?.cid, onOpen = { vm.nav.go(Reader(ch.cid, if (!ch.done && ch.page > 0) ch.page else 1)) }) {
                    if (ch.done) vm.markManga(tid, listOf(ch.cid), false)
                    else {
                        val i = t.chapters.indexOfFirst { it.cid == ch.cid }
                        val before = t.chapters.take(i).filter { !it.done }.map { it.cid }
                        if (before.isEmpty()) vm.markManga(tid, listOf(ch.cid), true) else ask = ch to before
                    }
                }
            }
        }
    }
    ask?.let { (ch, before) ->
        AlertDialog(
            onDismissRequest = { ask = null },
            title = { Text("Позначити прочитаним") },
            text = { Text("Позначити прочитаними й ${before.size} " + Fmt.plural(before.size, "попередній розділ", "попередні розділи", "попередніх розділів") + "?") },
            confirmButton = { TextButton({ vm.markManga(tid, before + ch.cid, true); ask = null }) { Text("Так, усі") } },
            dismissButton = { TextButton({ vm.markManga(tid, listOf(ch.cid), true); ask = null }) { Text("Лише цей") } },
        )
    }
}

@Composable
private fun ChapterRow(ch: MangaChapter, cur: Boolean, onOpen: () -> Unit, onTick: () -> Unit) {
    val p = LocalPal.current
    val part = !ch.done && ch.page > 0
    Row(
        Modifier.padding(horizontal = PAD - 6.dp, vertical = 1.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp))
            .then(if (cur) Modifier.border(1.dp, p.acc, RoundedCornerShape(10.dp)) else Modifier)
            .clickable(onClick = onOpen).padding(start = 10.dp, top = 8.dp, bottom = 8.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(when { ch.new && !ch.done -> p.acc; cur -> p.acc2; ch.done -> p.line; else -> Color.Transparent })
            .border(1.dp, if (ch.done || ch.new || cur) Color.Transparent else p.line, CircleShape))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(ch.label, style = body(14.5.sp, if (ch.done) FontWeight.Normal else FontWeight.SemiBold), color = if (ch.done) p.mute else p.fg,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            val status = when { ch.done -> " · прочитано"; part -> " · стор. ${ch.page} / ${ch.pages}"; ch.new -> " · нова"; else -> "" }
            Text(listOf(ch.sub, pagesWord(ch.pages)).filter { it.isNotEmpty() }.joinToString(" · ") + status, style = body(12.sp),
                color = if (part || (ch.new && !ch.done)) p.acc else p.mute, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (part) {
                Spacer(Modifier.height(5.dp))
                Meter(ch.page.toFloat() / ch.pages.coerceAtLeast(1), Modifier.fillMaxWidth(.6f))
            }
        }
        Box(
            Modifier.size(42.dp).clip(RoundedCornerShape(9.dp)).clickable(onClick = onTick),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Ic.check, if (ch.done) "Позначити непрочитаним" else "Позначити прочитаним", tint = if (ch.done) p.acc else p.mute.copy(alpha = .6f), modifier = Modifier.size(20.dp))
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MangaMetaBlock(m: app.vidbox.data.MangaMeta) {
    val p = LocalPal.current
    var open by rememberSaveable { mutableStateOf(false) }
    Column(Modifier.padding(horizontal = PAD).padding(bottom = 12.dp)) {
        val who = listOfNotNull(
            m.artists.takeIf { it.isNotEmpty() }?.let { "автор: " + it.joinToString(", ") },
            m.series.takeIf { it.isNotEmpty() }?.let { "серія: " + it.joinToString(", ") },
            m.lang.takeIf { it.isNotEmpty() }?.let { "мова: $it" },
        )
        if (who.isNotEmpty()) {
            Text(who.joinToString("   "), style = body(13.sp), color = p.fg)
            Spacer(Modifier.height(8.dp))
        }
        val facts = listOfNotNull(
            m.year.takeIf { it > 0 }?.toString(), mangaFormat(m.format).takeIf { it.isNotEmpty() },
            m.chapters.takeIf { it > 0 }?.let { "$it розд." }, mangaStatus(m.status).takeIf { it.isNotEmpty() },
            m.score.takeIf { it > 0 }?.let { "★ " + String.format(java.util.Locale.US, "%.1f", it / 10.0).replace('.', ',') },
        )
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            facts.forEach { Tag(it, p.fg) }
            m.genres.take(if (open) 60 else 14).forEach { Tag(it, p.mute) }
        }
        if (m.desc.isNotBlank()) {
            Spacer(Modifier.height(10.dp))
            Text(m.desc, style = body(13.5.sp), color = p.mute, maxLines = if (open) Int.MAX_VALUE else 4, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable { open = !open })
        }
        if (m.desc.isNotBlank() || m.genres.size > 14) {
            Text(if (open) "Згорнути" else "Детальніше", style = mono(12.sp, FontWeight.Bold), color = p.acc,
                modifier = Modifier.padding(top = 4.dp).clip(RoundedCornerShape(6.dp)).clickable { open = !open }.padding(vertical = 4.dp))
        }
        Text("Дані з ${mangaSource(m)}", style = body(11.5.sp), color = p.mute.copy(alpha = .8f), modifier = Modifier.padding(top = 6.dp))
    }
}

@Composable
private fun Tag(text: String, color: Color) {
    val p = LocalPal.current
    Text(text, style = mono(11.5.sp), color = color,
        modifier = Modifier.clip(RoundedCornerShape(6.dp)).border(1.dp, p.line, RoundedCornerShape(6.dp)).padding(horizontal = 7.dp, vertical = 4.dp))
}
