package app.vidbox.ui.screens

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.collectIsDraggedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.vidbox.AppVM
import app.vidbox.Info
import app.vidbox.Player
import app.vidbox.Playlists
import app.vidbox.data.Fmt
import app.vidbox.data.LEN_GROUPS
import app.vidbox.data.Video
import app.vidbox.data.Week
import app.vidbox.ui.BigFrame
import app.vidbox.ui.Btn
import app.vidbox.ui.Chip
import app.vidbox.ui.Empty
import app.vidbox.ui.Ic
import app.vidbox.ui.IconBtn
import app.vidbox.ui.Kind
import app.vidbox.ui.LocalPal
import app.vidbox.ui.PAD
import app.vidbox.ui.PromptLine
import app.vidbox.ui.SectionHead
import app.vidbox.ui.Shelf
import app.vidbox.ui.Win
import app.vidbox.ui.body
import app.vidbox.ui.display
import app.vidbox.ui.mono
import kotlinx.coroutines.delay
import kotlin.math.roundToInt

fun spotList(week: Week?, by: Map<String, Video>): List<Video> {
    if (week == null) return emptyList()
    val ids = listOfNotNull(week.hero) + week.sections.flatMap { it.ids }
    return ids.distinct().mapNotNull { by[it] }.take(6)
}

fun spotDesc(v: Video, resume: Boolean): String {
    val where = "З папки «${Fmt.shortFolder(v.folder)}»."
    if (v.resumable(resume)) return "$where Ти зупинився на ${Fmt.dur(v.pos)}, залишилось ${Fmt.len(v.dur - v.pos)}."
    if (v.views > 0) return "$where Переглянуто ${v.views} ${Fmt.plural(v.views, "раз", "рази", "разів")}, востаннє ${Fmt.ago(v.last)}. Рейтинг ${v.score.roundToInt()} зі 100."
    return "$where Ти його ще не дивився, додано ${Fmt.ago(v.added)}."
}

/** Поки бібліотека не прийшла: або чекаємо, або кажемо, що ПК не відповідає. */
@Composable
fun Waiting(vm: AppVM) {
    val p = LocalPal.current
    Column(Modifier.fillMaxSize().padding(PAD), verticalArrangement = Arrangement.Center) {
        PromptLine("~", "vidbox --connect ${vm.prefs.server.removePrefix("http://")}")
        Spacer(Modifier.height(14.dp))
        if (vm.offline == null) {
            Text("Підключаюсь до комп'ютера…", style = display(26.sp), color = p.fg)
        } else {
            Text("Немає зв'язку з комп'ютером", style = display(26.sp), color = p.fg)
            Spacer(Modifier.height(8.dp))
            Text("Перевір, що VidBox запущений на ПК і телефон у тій самій Wi-Fi мережі.", style = body(15.sp), color = p.mute)
            Spacer(Modifier.height(18.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Btn("Спробувати знову", { vm.refresh() }, icon = Ic.refresh, kind = Kind.Primary)
                Btn("Інший ПК", { vm.disconnect() }, icon = Ic.monitor)
            }
        }
    }
}

@Composable
fun HomeScreen(vm: AppVM) {
    val p = LocalPal.current
    val lib = vm.lib ?: return Waiting(vm)
    val vs = lib.videos
    if (vs.isEmpty()) {
        Empty("Тут поки порожньо", "VidBox не знайшов відео у вибраних папках. Додай папку в налаштуваннях на комп'ютері. Підходять mp4, mkv, webm, mov, avi та інші.") {
            Btn("Пересканувати", { vm.rescan() }, icon = Ic.refresh, kind = Kind.Primary)
        }
        return
    }
    val resume = lib.cfg.resume
    val week = vm.week
    val spot = remember(week, vm.byId) { spotList(week, vm.byId) }
    val cont = remember(vs, resume) { vs.filter { it.resumable(resume) }.sortedByDescending { it.posAt }.take(12) }
    val best = remember(vs) { vs.filter { it.views > 0 }.sortedByDescending { it.score }.take(10) }
    val recent = remember(vs) { vs.sortedByDescending { it.added }.take(14) }
    val open: (Video) -> Unit = { vm.nav.go(Info(it.id)) }

    LazyColumn(state = vm.nav.list("home"), contentPadding = PaddingValues(top = 14.dp, bottom = 28.dp), modifier = Modifier.fillMaxSize()) {
        item("prompt") { PromptLine("~", "vidbox --week ${week?.week ?: "…"}", Modifier.padding(horizontal = PAD)) }
        if (spot.isNotEmpty()) item("spot") { Hero(vm, spot, resume) }
        item("cont") {
            Shelf("Продовжити перегляд", cont, open, meta = { listOf(Fmt.shortFolder(it.folder), "ще " + Fmt.len(it.dur - it.pos)) })
        }
        item("pl") {
            Column(Modifier.padding(top = 26.dp)) {
                SectionHead("Плейлисти", "Збираються самі за тривалістю") {
                    Btn("Усі", { vm.nav.go(Playlists) }, icon = Ic.list, kind = Kind.Ghost)
                }
                Spacer(Modifier.height(12.dp))
                LazyRow(contentPadding = PaddingValues(horizontal = PAD), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    items(LEN_GROUPS, key = { it.id }) { g -> PlCard(vm, g, Modifier.width(272.dp), compact = true) }
                }
            }
        }
        if (week != null && week.sections.isNotEmpty()) item("week") { WeekWin(vm, week) }
        if (best.size >= 3) item("best") { Shelf("Найкраще за рейтингом", best, open, sub = "Десятка, яку ти дивишся найохочіше", ranked = true) }
        item("recent") { Shelf("Нещодавно додані", recent, open, meta = { listOf(Fmt.shortFolder(it.folder), Fmt.ago(it.added)) }) }
        item("foot") {
            var foot = "У бібліотеці ${vs.size} відео. Цього тижня переглянуто ${Fmt.len(lib.weekSec).ifEmpty { "0 хв" }}."
            if (lib.spritesPending > 0) foot += " Нарізки кадрів ще готуються у фоні: залишилось ${lib.spritesPending}."
            else if (!lib.ffmpeg) foot += " Щоб з'явились нарізки кадрів, поклади ffmpeg.exe поруч з vidbox.py."
            Text(foot, style = mono(12.sp), color = p.mute, modifier = Modifier.padding(start = PAD, end = PAD, top = 30.dp))
        }
    }
}

@Composable
private fun Hero(vm: AppVM, list: List<Video>, resume: Boolean) {
    val p = LocalPal.current
    val pager = rememberPagerState { list.size }
    val dragged by pager.interactionSource.collectIsDraggedAsState()
    val timer = remember { Animatable(0f) }
    LaunchedEffect(pager.currentPage, dragged, list.size) {
        timer.snapTo(0f)
        if (dragged || list.size < 2) return@LaunchedEffect
        timer.animateTo(1f, tween(8000, easing = LinearEasing))
        pager.animateScrollToPage((pager.currentPage + 1) % list.size)
    }
    Column(Modifier.padding(top = 14.dp)) {
        HorizontalPager(pager, contentPadding = PaddingValues(horizontal = PAD), pageSpacing = 10.dp, key = { list[it].id }) { i ->
            val v = list[i]
            Box(
                Modifier.fillMaxWidth().aspectRatio(0.98f).clip(RoundedCornerShape(12.dp))
                    .border(1.dp, p.line, RoundedCornerShape(12.dp)).clickable { vm.nav.go(Info(v.id)) },
            ) {
                BigFrame(v, 6, Modifier.fillMaxSize())
                Box(
                    Modifier.fillMaxSize().background(
                        Brush.verticalGradient(0f to Color.Transparent, .22f to p.bg.copy(alpha = .1f), .48f to p.bg.copy(alpha = .72f), .66f to p.bg.copy(alpha = .93f), 1f to p.bg),
                    ),
                )
                Column(Modifier.align(Alignment.BottomStart).padding(16.dp)) {
                    Text("#${i + 1} " + if (i == 0) "відео тижня" else "у підбірці тижня", style = mono(12.sp), color = p.acc)
                    Spacer(Modifier.height(6.dp))
                    Text(v.title, style = display(29.sp), color = p.fg, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        if (v.dur > 0) Chip(Fmt.len(v.dur))
                        if (v.res.isNotEmpty()) Chip(v.res)
                        if (v.views > 0 || v.vote != 0) Chip("★ ${v.score.roundToInt()}", on = v.score >= 70) else Chip("нове для тебе", on = true)
                    }
                    Spacer(Modifier.height(10.dp))
                    Text(spotDesc(v, resume), style = body(13.5.sp), color = p.fg.copy(alpha = .78f), maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.height(14.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Btn(if (v.resumable(resume)) "Продовжити" else "Дивитися", { vm.nav.go(Player(v.id)) }, icon = Ic.play, kind = Kind.Primary)
                        Btn("Детальніше", { vm.nav.go(Info(v.id)) }, icon = Ic.info)
                    }
                }
            }
        }
        if (list.size > 1) {
            Row(Modifier.fillMaxWidth().padding(horizontal = PAD, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    (pager.currentPage + 1).toString().padStart(2, '0') + " / " + list.size.toString().padStart(2, '0'),
                    style = mono(12.5.sp, FontWeight.Bold), color = p.fg,
                )
                Spacer(Modifier.width(12.dp))
                Box(Modifier.weight(1f).height(2.dp).clip(RoundedCornerShape(1.dp)).background(p.line)) {
                    Box(Modifier.fillMaxWidth(timer.value).height(2.dp).background(p.acc))
                }
            }
        }
    }
}

@Composable
private fun WeekWin(vm: AppVM, week: Week) {
    val p = LocalPal.current
    Win("~/підбірка-тижня/", Modifier.padding(start = PAD, end = PAD, top = 30.dp), bold = week.week) {
        Column(Modifier.padding(bottom = 16.dp)) {
            Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 12.dp, top = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Підбірка тижня", style = display(25.sp), color = p.fg)
                    Text(Fmt.weekRange(week.start, week.end), style = mono(12.sp), color = p.mute)
                }
                IconBtn(Ic.refresh, { vm.refreshWeek() }, desc = "Зібрати іншу підбірку")
            }
            week.sections.forEach { s ->
                val list = s.ids.mapNotNull { vm.byId[it] }
                Box(Modifier.padding(horizontal = 0.dp)) {
                    Shelf(s.title, list, { vm.nav.go(Info(it.id)) }, sub = s.sub, small = true)
                }
            }
        }
    }
}
