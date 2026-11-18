package app.vidbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import app.vidbox.AnimeShow
import app.vidbox.AppVM
import app.vidbox.Settings
import app.vidbox.data.AnimeTitle
import app.vidbox.data.Fmt
import app.vidbox.ui.*
import coil.compose.AsyncImage

private fun eps(n: Int) = "$n " + Fmt.plural(n, "серія", "серії", "серій")

@Composable
fun AnimeScreen(vm: AppVM) {
    LaunchedEffect(Unit) { vm.loadAnime() }
    val p = LocalPal.current
    val d = vm.animeList
    val cols = if (LocalConfiguration.current.screenWidthDp >= 840) 6 else if (LocalConfiguration.current.screenWidthDp >= 600) 4 else 3
    val full = GridItemSpan(cols)
    LazyVerticalGrid(
        GridCells.Fixed(cols), state = vm.nav.grid("anime"), modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = PAD, end = PAD, top = 14.dp, bottom = 28.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item(span = { full }) { PromptLine("~/аніме", "ls") }
        item(span = { full }) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text("Аніме", style = display(38.sp), color = p.fg)
                d?.titles?.size?.takeIf { it > 0 }?.let {
                    Spacer(Modifier.width(12.dp))
                    Text("$it", style = mono(13.sp), color = p.mute, modifier = Modifier.padding(bottom = 6.dp))
                }
            }
        }
        when {
            d == null -> item(span = { full }) { Lead("Завантажую…") }
            d.folder.isEmpty() -> item(span = { full }) {
                Empty("Папку не вказано", "Вкажи папку з аніме на сайті: Налаштування → Аніме. Кожна підпапка стане тайтлом, файли в ній — серіями.") {
                    Btn("Налаштування", { vm.nav.go(Settings) }, icon = Ic.sliders)
                }
            }
            d.titles.isEmpty() -> item(span = { full }) { Empty("Поки порожньо", "У папці з аніме немає відео. Поклади кожен тайтл в окрему підпапку.") }
            else -> {
                val cont = d.titles.filter { it.cont != null }.sortedByDescending { it.lastAt }
                if (cont.isNotEmpty()) {
                    item(span = { full }) { Text("Продовжити", style = body(17.sp, FontWeight.Bold), color = p.fg) }
                    items(cont, key = { "c" + it.sid }) { AnimeCard(vm, it) }
                    item(span = { full }) { Text("Усі тайтли", style = body(17.sp, FontWeight.Bold), color = p.fg, modifier = Modifier.padding(top = 8.dp)) }
                }
                items(d.titles, key = { it.sid }) { AnimeCard(vm, it) }
            }
        }
    }
}

@Composable
private fun Poster(vm: AppVM, t: AnimeTitle, modifier: Modifier = Modifier) {
    val p = LocalPal.current
    Box(modifier.aspectRatio(2f / 3f).clip(RoundedCornerShape(10.dp)).background(p.bg3).border(1.dp, p.line, RoundedCornerShape(10.dp))) {
        Text((t.title.trim().firstOrNull() ?: '?').uppercase(), style = mono(30.sp, FontWeight.Bold), color = p.mute, modifier = Modifier.align(Alignment.Center))
        AsyncImage(model = vm.api.url(t.cover), contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
    }
}

@Composable
private fun AnimeCard(vm: AppVM, t: AnimeTitle) {
    val p = LocalPal.current
    Column(Modifier.clip(RoundedCornerShape(10.dp)).clickable { vm.nav.go(AnimeShow(t.sid)) }) {
        Box {
            Poster(vm, t, Modifier.fillMaxWidth())
            val c = t.cont
            if (c != null) {
                Text("Серія ${c.ep}", style = mono(10.5.sp, FontWeight.Bold), color = p.on,
                    modifier = Modifier.padding(6.dp).clip(RoundedCornerShape(6.dp)).background(p.acc).padding(horizontal = 6.dp, vertical = 3.dp))
                if (c.dur > 0 && c.pos > 5) Meter((c.pos / c.dur).toFloat(), Modifier.align(Alignment.BottomCenter).fillMaxWidth(), track = Color.Black.copy(alpha = .45f))
            } else if (t.n > 0 && t.watched == t.n) {
                Text("Переглянуто", style = mono(10.5.sp, FontWeight.Bold), color = p.mute,
                    modifier = Modifier.padding(6.dp).clip(RoundedCornerShape(6.dp)).background(p.bg2).padding(horizontal = 6.dp, vertical = 3.dp))
            }
        }
        Spacer(Modifier.height(6.dp))
        Text(t.title, style = body(13.sp, FontWeight.SemiBold), color = p.fg, maxLines = 2, overflow = TextOverflow.Ellipsis)
        Text(eps(t.n) + if (t.watched in 1 until t.n) " · ${t.watched} перегл." else "", style = body(11.5.sp), color = p.mute, maxLines = 1)
    }
}

@Composable
fun AnimeShowScreen(vm: AppVM, sid: String) {
    LaunchedEffect(sid) { vm.loadAnimeShow(sid) }
    val p = LocalPal.current
    val t = vm.animeShows[sid]
    LazyColumn(state = vm.nav.list("anime/$sid"), contentPadding = PaddingValues(top = 14.dp, bottom = 28.dp), modifier = Modifier.fillMaxSize()) {
        if (t == null) {
            item { Lead("Завантажую…", Modifier.padding(horizontal = PAD)) }
            return@LazyColumn
        }
        val c = t.cont
        val startId = c?.id ?: t.eps.firstOrNull()?.v?.id
        item { PromptLine("~/аніме/" + t.title, "ls", Modifier.padding(horizontal = PAD)) }
        item {
            Row(Modifier.padding(horizontal = PAD, vertical = 10.dp), verticalAlignment = Alignment.Bottom) {
                Poster(vm, t, Modifier.width(118.dp))
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f)) {
                    Text(t.title, style = display(26.sp), color = p.fg, maxLines = 3, overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.height(4.dp))
                    Text(eps(t.n) + if (t.watched > 0) " · переглянуто ${t.watched} з ${t.n}" else "", style = body(13.5.sp), color = p.mute)
                    Spacer(Modifier.height(12.dp))
                    if (startId != null) {
                        val label = if (c == null) "Дивитися з першої" else if (c.pos > 5) "Продовжити серію ${c.ep}" else "Дивитися серію ${c.ep}"
                        Btn(label, { vm.playAnime(t, startId) }, icon = Ic.play, kind = Kind.Primary)
                    }
                }
            }
        }
        items(t.eps, key = { it.v.id }) { e ->
            val cur = e.v.id == startId
            Row(
                Modifier.padding(horizontal = PAD - 6.dp, vertical = 2.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp))
                    .then(if (cur) Modifier.border(1.dp, p.acc, RoundedCornerShape(10.dp)) else Modifier)
                    .clickable { vm.playAnime(t, e.v.id) }.padding(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Thumb(e.v.copy(pos = if (e.done) 0.0 else e.v.pos), Modifier.width(118.dp), small = true, showLen = false)
                Spacer(Modifier.width(12.dp))
                Text("${e.ep}", style = mono(14.sp, FontWeight.Bold), color = if (cur) p.acc else p.mute, modifier = Modifier.widthIn(min = 26.dp))
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    Text("Серія ${e.ep}" + if (e.name.isNotEmpty()) " · ${e.name}" else "", style = body(14.sp, FontWeight.SemiBold),
                        color = if (e.done) p.mute else p.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    val left = if (!e.done && e.v.pos > 5 && e.v.dur > 0) " · залишилось ${Fmt.len(e.v.dur - e.v.pos)}" else ""
                    Text((if (e.v.dur > 0) Fmt.len(e.v.dur) else "") + (if (e.done) " · переглянуто" else left), style = body(12.sp), color = p.mute)
                }
            }
        }
    }
}
