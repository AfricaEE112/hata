package app.vidbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.vidbox.AppVM
import app.vidbox.Player
import app.vidbox.data.Fmt
import app.vidbox.ui.*
import coil.compose.AsyncImage

@Composable
fun DownloadsScreen(vm: AppVM) {
    val p = LocalPal.current
    val list = vm.dl.items.values.sortedByDescending { if (it.done) 0 else 1 }
    LazyColumn(state = vm.nav.list("downloads"), contentPadding = PaddingValues(top = 14.dp, bottom = 28.dp), modifier = Modifier.fillMaxSize()) {
        item { PromptLine("~/завантажене", "du -sh *", Modifier.padding(horizontal = PAD)) }
        item { PageTitle("На телефоні", if (list.isEmpty()) "" else Fmt.size(vm.dl.usedBytes), Modifier.padding(top = 6.dp)) }
        item {
            Lead("Ці відео граються без ПК і без інтернету. Вони зберігаються всередині апки, а не в галереї, і видаляються разом з нею.",
                Modifier.padding(horizontal = PAD, vertical = 8.dp))
        }
        if (list.isEmpty()) item {
            Empty("Поки порожньо", "Відкрий відео й натисни «Завантажити».")
        }
        items(list, key = { it.v.id }) { d ->
            val v = d.v
            val running = vm.dl.running(v.id)
            Row(
                Modifier.padding(horizontal = PAD - 6.dp, vertical = 3.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp))
                    .clickable(enabled = d.done) { vm.nav.go(Player(v.id)) }.padding(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.width(120.dp).aspectRatio(16f / 9f).clip(RoundedCornerShape(8.dp)).background(p.bg3)) {
                    val t = vm.dl.thumb(v.id)
                    if (t.exists()) AsyncImage(model = t, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                    if (d.done && v.dur > 0 && v.pos > 5) Meter((v.pos / v.dur).toFloat(), Modifier.align(Alignment.BottomCenter).fillMaxWidth(), track = Color.Black.copy(alpha = .45f))
                }
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(v.title, style = body(14.sp, FontWeight.SemiBold), color = p.fg, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.height(3.dp))
                    Text(
                        when {
                            d.done -> listOf(if (v.dur > 0) Fmt.len(v.dur) else "", if (d.h > 0) "${d.h}p" else "", Fmt.size(d.bytes)).filter { it.isNotEmpty() }.joinToString(" · ")
                            running && d.note != null -> d.note
                            running -> "Завантажую ${(d.progress * 100).toInt()}% · ${Fmt.size(d.bytes)} з ${Fmt.size(d.total)}"
                            else -> (d.error ?: "Зупинено") + " · ${Fmt.size(d.bytes)} з ${Fmt.size(d.total)}"
                        },
                        style = body(12.sp), color = if (!d.done && !running) Color(0xFFFF8A7A) else p.mute, maxLines = 2,
                    )
                    if (running && d.note == null) Meter(d.progress, Modifier.padding(top = 6.dp).fillMaxWidth())
                }
                Spacer(Modifier.width(6.dp))
                when {
                    running -> IconBtn(Ic.close, { vm.dl.stop(v.id) }, size = 38.dp, desc = "Зупинити")
                    !d.done -> IconBtn(Ic.refresh, { vm.download(v) }, size = 38.dp, desc = "Докачати")
                }
                IconBtn(Ic.close, { vm.dl.remove(v.id); vm.say("Видалено з телефона") }, size = 38.dp, desc = "Видалити з телефона",
                    tint = if (running) null else p.mute)
            }
        }
    }
}
