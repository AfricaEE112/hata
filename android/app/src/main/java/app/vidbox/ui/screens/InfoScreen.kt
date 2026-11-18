package app.vidbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.vidbox.AppVM
import app.vidbox.Info
import app.vidbox.Player
import app.vidbox.data.Fmt
import app.vidbox.data.Video
import app.vidbox.ui.BigFrame
import app.vidbox.ui.Btn
import app.vidbox.ui.Chip
import app.vidbox.ui.Empty
import app.vidbox.ui.Ic
import app.vidbox.ui.IconBtn
import app.vidbox.ui.Kind
import app.vidbox.ui.LocalPal
import app.vidbox.ui.Meter
import app.vidbox.ui.PAD
import app.vidbox.ui.Shelf
import app.vidbox.ui.SpriteFrame
import app.vidbox.ui.Win
import app.vidbox.ui.body
import app.vidbox.ui.display
import app.vidbox.ui.mono
import kotlin.math.roundToInt

@Composable
fun InfoScreen(vm: AppVM, r: Info) {
    val p = LocalPal.current
    var pickDl by remember { mutableStateOf(false) }
    val lib = vm.lib ?: return Waiting(vm)
    val v = vm.byId[r.id] ?: return Empty("Відео не знайдено", "Можливо, файл перемістили або видалили з папки на ПК.") {
        Btn("Назад", { vm.nav.back() }, icon = Ic.back)
    }
    LaunchedEffect(v.id) { vm.ensureSprite(v) }
    val n = vm.spriteN
    val resume = v.resumable(lib.cfg.resume)
    val state = remember(v.id) { LazyListState() }
    val more = remember(v.id, lib.videos) { vm.moreFromFolder(v) }

    LazyColumn(state = state, contentPadding = PaddingValues(top = 12.dp, bottom = 28.dp), modifier = Modifier.fillMaxSize()) {
        item("media") {
            Win(
                "info — ", Modifier.padding(horizontal = PAD), bold = v.file,
                trailing = {
                    Box(Modifier.clip(RoundedCornerShape(6.dp)).clickable { vm.nav.back() }.padding(2.dp)) {
                        Icon(Ic.close, "Закрити", tint = p.mute, modifier = Modifier.size(18.dp))
                    }
                },
            ) { Screen(vm, v, n) }
        }
        item("play") {
            Btn(
                if (resume) "Продовжити з ${Fmt.dur(v.pos)}" else "Дивитися", { vm.nav.go(Player(v.id)) },
                Modifier.fillMaxWidth().padding(start = PAD, end = PAD, top = 14.dp), icon = Ic.play, kind = Kind.Primary,
            )
        }
        item("head") {
            Column(Modifier.padding(start = PAD, end = PAD, top = 18.dp)) {
                Text(v.title, style = display(28.sp), color = p.fg)
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (v.dur > 0) Chip(Fmt.len(v.dur))
                    if (v.res.isNotEmpty()) Chip(v.res)
                    Chip(v.ext.uppercase())
                    if (v.size > 0) Chip(Fmt.size(v.size))
                }
                if (v.views > 0 || v.vote != 0) {
                    Spacer(Modifier.height(6.dp))
                    Chip("Рейтинг ${v.score.roundToInt()}", on = v.score >= 70)
                }
                if (resume) {
                    Spacer(Modifier.height(14.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Meter((v.pos / v.dur).toFloat(), Modifier.weight(1f))
                        Spacer(Modifier.width(10.dp))
                        Text("Залишилось ${Fmt.len(v.dur - v.pos)}", style = mono(12.sp), color = p.mute)
                        Spacer(Modifier.width(10.dp))
                        Row(
                            Modifier.clip(RoundedCornerShape(6.dp)).clickable { vm.nav.go(Player(v.id, 0.0)) }.padding(6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(Ic.restart, null, tint = p.acc, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(5.dp))
                            Text("З початку", style = mono(12.sp, FontWeight.Bold), color = p.acc)
                        }
                    }
                }
                Spacer(Modifier.height(14.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    IconBtn(Ic.up, { vm.vote(v, 1) }, on = v.vote > 0, desc = "Подобається")
                    IconBtn(Ic.down, { vm.vote(v, -1) }, on = v.vote < 0, desc = "Не подобається")
                    if (r.random) Btn("Інше випадкове", { vm.openRandom(replace = true) }, icon = Ic.dice, kind = Kind.Ghost)
                    val d = vm.dl.items[v.id]
                    when {
                        d?.done == true -> Btn("На телефоні", { vm.nav.go(app.vidbox.Downloads) }, icon = Ic.check, kind = Kind.Ghost)
                        d != null && vm.dl.running(v.id) -> Btn((d.note?.substringAfter(": ")?.let { "ПК $it" } ?: "${(d.progress * 100).toInt()}%") + " · Стоп", { vm.dl.stop(v.id) }, icon = Ic.close, kind = Kind.Ghost)
                        else -> Btn(if (d != null) "Докачати" else "Завантажити", {
                            if (d == null && vm.lib?.ffmpeg == true && v.resKey > 480) pickDl = true else vm.download(v)
                        }, icon = Ic.arrDown, kind = Kind.Ghost)
                    }
                    if (pickDl) DownloadPicker(v, { pickDl = false; vm.download(v, it) }) { pickDl = false }
                }
            }
        }
        item("frames") { Section("Кадри") { Frames(vm, v, n) } }
        item("rating") { Section("Рейтинг") { Rating(v) } }
        item("file") { Section("Файл") { FileInfo(v) } }
        item("more") { Shelf("Ще з цієї папки", more, { vm.nav.replace(Info(it.id)) }) }
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    val p = LocalPal.current
    Column(Modifier.fillMaxWidth().padding(start = PAD, end = PAD, top = 26.dp)) {
        Text(title, style = display(20.sp, FontWeight.Bold), color = p.fg)
        Spacer(Modifier.height(10.dp))
        content()
    }
}

/** Великий кадр; якщо вести пальцем — гортаються кадри з нарізки, як при наведенні на сайті. */
@Composable
private fun Screen(vm: AppVM, v: Video, n: Int) {
    var scrub by remember(v.id) { mutableStateOf<Int?>(null) }
    BoxWithConstraints(
        Modifier.fillMaxWidth().aspectRatio(16f / 9f).background(Color.Black)
            .pointerInput(v.id, v.sprite) {
                if (!v.hasSprite) return@pointerInput
                detectHorizontalDragGestures(
                    onDragStart = { o -> scrub = (o.x / size.width * n).toInt().coerceIn(0, n - 1) },
                    onDragEnd = { scrub = null },
                    onDragCancel = { scrub = null },
                ) { change, _ -> scrub = (change.position.x / size.width * n).toInt().coerceIn(0, n - 1) }
            }
            .pointerInput(v.id) { detectTapGestures(onTap = { vm.nav.go(Player(v.id)) }) },
    ) {
        BigFrame(v, 6, Modifier.fillMaxSize())
        val s = scrub
        if (s != null) {
            SpriteFrame(v, s, Modifier.fillMaxSize())
            Text(
                Fmt.dur(v.frameT(s, n)), style = mono(12.sp, FontWeight.Bold), color = Color.White,
                modifier = Modifier.align(Alignment.BottomStart).padding(10.dp).clip(RoundedCornerShape(5.dp))
                    .background(Color.Black.copy(alpha = .7f)).padding(horizontal = 6.dp, vertical = 2.dp),
            )
            Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(3.dp).background(Color.White.copy(alpha = .2f))) {
                Box(Modifier.fillMaxWidth((s + 1f) / n).height(3.dp).background(LocalPal.current.acc))
            }
        } else if (v.hasSprite) {
            Text(
                "веди пальцем, щоб переглянути кадри", style = mono(11.sp), color = Color.White.copy(alpha = .8f),
                modifier = Modifier.align(Alignment.BottomStart).padding(10.dp).clip(RoundedCornerShape(5.dp))
                    .background(Color.Black.copy(alpha = .55f)).padding(horizontal = 6.dp, vertical = 2.dp),
            )
        }
        Box(
            Modifier.align(Alignment.Center).size(64.dp).clip(RoundedCornerShape(32.dp))
                .background(Brush.linearGradient(listOf(Color.Black.copy(alpha = .55f), Color.Black.copy(alpha = .35f)))),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Ic.play, "Дивитися", tint = Color.White, modifier = Modifier.size(30.dp))
        }
    }
}

@Composable
private fun Frames(vm: AppVM, v: Video, n: Int) {
    val p = LocalPal.current
    val lib = vm.lib ?: return
    if (!v.hasSprite) {
        val pending = lib.ffmpeg && v.sprite == 0L && v.dur > 0
        if (pending) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                repeat(4) { Box(Modifier.weight(1f).aspectRatio(16f / 9f).clip(RoundedCornerShape(6.dp)).background(p.bg3)) }
            }
            Spacer(Modifier.height(8.dp))
        }
        Text(
            when {
                pending -> "Нарізаю кадри з цього відео, кілька секунд…"
                lib.ffmpeg -> "З цього файлу не вдалося взяти кадри."
                else -> "Щоб тут з'явились кадри з відео, поклади ffmpeg.exe і ffprobe.exe поруч з vidbox.py на ПК і перезапусти VidBox."
            },
            style = body(14.sp), color = p.mute,
        )
        return
    }
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val cols = (maxWidth / 84.dp).toInt().coerceIn(4, 6)
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            (0 until n).chunked(cols).forEach { row ->
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    row.forEach { i ->
                        Column(Modifier.weight(1f).clip(RoundedCornerShape(6.dp)).clickable { vm.nav.go(Player(v.id, v.frameT(i, n))) }) {
                            SpriteFrame(v, i, Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(6.dp)).background(p.bg3))
                            Text(Fmt.dur(v.frameT(i, n)), style = mono(10.5.sp), color = p.mute, modifier = Modifier.padding(top = 3.dp))
                        }
                    }
                    repeat(cols - row.size) { Spacer(Modifier.weight(1f)) }
                }
            }
        }
    }
}

@Composable
private fun Rating(v: Video) {
    val p = LocalPal.current
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(96.dp)) {
            Text("${v.score.roundToInt()}", style = display(52.sp), color = p.fg)
            Text("зі 100", style = mono(11.sp), color = p.mute)
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            MiniBar("Досмотр", v.avg?.toFloat() ?: 0f, if (v.avg != null) "${Fmt.pct(v.avg)}%" else "—")
            MiniBar("Вертаєшся", v.pop.toFloat(), "${Fmt.pct(v.pop)}%")
            MiniBar("Оцінка", if (v.vote > 0) 1f else if (v.vote < 0) 0f else .5f, if (v.vote > 0) "лайк" else if (v.vote < 0) "дизл." else "—")
        }
    }
    Spacer(Modifier.height(10.dp))
    Text(
        if (v.views > 0) "${Fmt.views(v.views)}, востаннє ${Fmt.ago(v.last)}." else "Ще не дивився. Рейтинг складеться після перегляду.",
        style = body(13.5.sp), color = p.mute,
    )
}

@Composable
private fun FileInfo(v: Video) {
    val rows = listOfNotNull(
        "Назва" to v.file,
        "Папка" to v.folder.split('/').joinToString(" / "),
        "Формат" to v.ext.uppercase() + if (v.ready) ", є копія MP4 на ПК" else "",
        listOf(v.vc.uppercase(), if (v.w > 0) "${v.w}×${v.h}" else "").filter { it.isNotEmpty() }.joinToString(", ").takeIf { it.isNotEmpty() }?.let { "Відео" to it },
        v.ac.takeIf { it.isNotEmpty() }?.let { "Звук" to it.uppercase() },
        "Розмір" to Fmt.size(v.size),
        "Додано" to Fmt.date(v.added),
    )
    val p = LocalPal.current
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        rows.forEach { (k, value) ->
            Row {
                Text(k, style = mono(12.sp), color = p.mute, modifier = Modifier.width(78.dp).padding(top = 1.dp))
                Text(value, style = body(14.sp), color = p.fg, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** Якість завантаження: оригінал або копія меншої роздільності, яку спершу готує ПК. */
@Composable
private fun DownloadPicker(v: app.vidbox.data.Video, onPick: (Int) -> Unit, onClose: () -> Unit) {
    val p = LocalPal.current
    val mb = { kbps: Int -> app.vidbox.data.Fmt.size((kbps * 125L * v.dur).toLong()) }
    val opts = buildList {
        add(Triple(0, "Оригінал", listOf(v.res, v.vc.uppercase(), app.vidbox.data.Fmt.size(v.size)).filter { it.isNotEmpty() }.joinToString(" · ")))
        if (v.resKey > 1080) add(Triple(1080, "1080p", "≈ ${mb(6128)}, ПК спершу перекодує"))
        if (v.resKey > 720) add(Triple(720, "720p", "≈ ${mb(3128)}, ПК спершу перекодує"))
        add(Triple(480, "480p", "≈ ${mb(1628)}, найменший файл"))
    }
    androidx.compose.ui.window.Dialog(onDismissRequest = onClose) {
        app.vidbox.ui.Win("wget — ", Modifier.widthIn(max = 420.dp), bold = "якість") {
            Column(Modifier.padding(vertical = 6.dp)) {
                opts.forEach { (h, name, hint) ->
                    Column(Modifier.fillMaxWidth().clickable { onPick(h) }.padding(horizontal = 16.dp, vertical = 11.dp)) {
                        Text(name, style = body(15.sp, FontWeight.Medium), color = p.fg)
                        Text(hint, style = body(12.sp), color = p.mute)
                    }
                }
            }
        }
    }
}
