package app.vidbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.vidbox.AppVM
import app.vidbox.Info
import app.vidbox.Playlist
import app.vidbox.Playlists
import app.vidbox.data.Fmt
import app.vidbox.data.LEN_GROUPS
import app.vidbox.data.LenGroup
import app.vidbox.data.Video
import app.vidbox.data.lenGroup
import app.vidbox.ui.Btn
import app.vidbox.ui.Chip
import app.vidbox.ui.Cover
import app.vidbox.ui.Empty
import app.vidbox.ui.Ic
import app.vidbox.ui.IconBtn
import app.vidbox.ui.Kind
import app.vidbox.ui.Lead
import app.vidbox.ui.LocalPal
import app.vidbox.ui.PAD
import app.vidbox.ui.PageTitle
import app.vidbox.ui.PromptLine
import app.vidbox.ui.SpriteFrame
import app.vidbox.ui.Thumb
import app.vidbox.ui.Win
import app.vidbox.ui.body
import app.vidbox.ui.display
import app.vidbox.ui.mono

/** Обкладинка плейлиста 2×2. Якщо відео менше чотирьох — добираємо інші кадри з тих самих відео. */
@Composable
fun Mosaic(list: List<Video>, modifier: Modifier = Modifier) {
    val p = LocalPal.current
    val four = list.sortedByDescending { it.added }.take(4)
    val extra = four.filter { it.hasSprite }
    val frames = listOf(9, 15, 6, 18)
    Column(modifier.clip(RoundedCornerShape(8.dp)), verticalArrangement = Arrangement.spacedBy(3.dp)) {
        for (row in 0..1) {
            Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                for (col in 0..1) {
                    val k = row * 2 + col
                    val cell = Modifier.weight(1f).aspectRatio(16f / 9f).background(p.bg3)
                    when {
                        k < four.size -> Cover(four[k], cell)
                        extra.isNotEmpty() -> {
                            val j = k - four.size
                            SpriteFrame(extra[j % extra.size], frames[j % frames.size], cell)
                        }
                        else -> Box(cell)
                    }
                }
            }
        }
    }
}

@Composable
fun PlCard(vm: AppVM, g: LenGroup, modifier: Modifier = Modifier, compact: Boolean = false) {
    val p = LocalPal.current
    val list = vm.plItems(g.id)
    val dur = list.sumOf { it.dur }
    Win("~/плейлисти/", modifier, bold = "${g.file}.m3u") {
        Column(Modifier.clickable { vm.nav.go(Playlist(g.id)) }.padding(12.dp)) {
            Mosaic(list, Modifier.fillMaxWidth())
            Spacer(Modifier.height(12.dp))
            Text(g.name, style = display(22.sp), color = p.fg)
            if (!compact) Text(g.hint, style = body(13.5.sp), color = p.mute)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Chip(Fmt.videos(list.size))
                if (dur > 0) Chip(Fmt.len(dur))
            }
            Spacer(Modifier.height(12.dp))
            if (list.isNotEmpty()) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Btn("Відтворити", { vm.playQueue(g.id) }, Modifier.weight(1f, fill = !compact), icon = Ic.play, kind = Kind.Primary)
                    if (compact) IconBtn(Ic.dice, { vm.playQueue(g.id, shuffle = true) }, desc = "Перемішати")
                    else Btn("Перемішати", { vm.playQueue(g.id, shuffle = true) }, icon = Ic.dice)
                }
            } else {
                Text("Поки порожньо", style = mono(12.5.sp), color = p.mute, modifier = Modifier.height(42.dp).padding(top = 12.dp))
            }
        }
    }
}

@Composable
fun PlaylistsScreen(vm: AppVM) {
    if (vm.lib == null) return Waiting(vm)
    LazyColumn(state = vm.nav.list("pl"), contentPadding = PaddingValues(top = 14.dp, bottom = 28.dp), modifier = Modifier.fillMaxSize()) {
        item { PromptLine("~/плейлисти", "ls *.m3u", Modifier.padding(horizontal = PAD)) }
        item { PageTitle("Плейлисти", modifier = Modifier.padding(top = 6.dp)) }
        item {
            Lead("Збираються самі за тривалістю відео. Нові файли потрапляють у потрібний плейлист автоматично, а відтворення йде підряд, одне за одним.", Modifier.padding(top = 6.dp, bottom = 18.dp))
        }
        LEN_GROUPS.forEach { g ->
            item(g.id) { PlCard(vm, g, Modifier.padding(horizontal = PAD, vertical = 8.dp).widthIn(max = 560.dp)) }
        }
    }
}

@Composable
fun PlaylistScreen(vm: AppVM, id: String) {
    val p = LocalPal.current
    if (vm.lib == null) return Waiting(vm)
    val g = lenGroup(id) ?: return Empty("Такого плейлиста немає", "Можливо, посилання застаріло.") {
        Btn("Усі плейлисти", { vm.nav.go(Playlists) }, icon = Ic.list)
    }
    val list = vm.plItems(id)
    val dur = list.sumOf { it.dur }
    val unseen = list.count { it.views == 0 }
    LazyColumn(state = vm.nav.list("pl/$id"), contentPadding = PaddingValues(top = 14.dp, bottom = 28.dp), modifier = Modifier.fillMaxSize()) {
        item { PromptLine("~/плейлисти", "cat ${g.file}.m3u", Modifier.padding(horizontal = PAD)) }
        item {
            Column(Modifier.padding(horizontal = PAD, vertical = 14.dp)) {
                Mosaic(list, Modifier.fillMaxWidth().widthIn(max = 420.dp).border(1.dp, p.line, RoundedCornerShape(8.dp)))
                Spacer(Modifier.height(16.dp))
                Text("Плейлист", style = mono(12.sp), color = p.acc)
                Text(g.name, style = display(40.sp), color = p.fg)
                Text(g.hint, style = body(15.sp), color = p.mute)
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Chip(Fmt.videos(list.size))
                    if (dur > 0) Chip(Fmt.len(dur))
                    if (unseen > 0) Chip("$unseen ще не бачив", on = true)
                }
                Spacer(Modifier.height(14.dp))
                if (list.isNotEmpty()) Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Btn("Відтворити все", { vm.playQueue(id) }, icon = Ic.play, kind = Kind.Primary)
                    Btn("Перемішати", { vm.playQueue(id, shuffle = true) }, icon = Ic.dice)
                }
            }
        }
        if (list.isEmpty()) item {
            Text(
                "Поки порожньо. Сюди потраплять відео потрібної тривалості, щойно VidBox їх прочитає.",
                style = body(15.sp), color = p.mute, modifier = Modifier.padding(PAD),
            )
        }
        itemsIndexed(list, key = { _, v -> v.id }) { i, v -> Track(vm, id, i, v) }
    }
}

@Composable
private fun Track(vm: AppVM, pl: String, i: Int, v: Video) {
    val p = LocalPal.current
    Row(
        Modifier.fillMaxWidth().clickable { vm.playQueue(pl, v.id) }.padding(start = 6.dp, end = PAD, top = 7.dp, bottom = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text((i + 1).toString().padStart(2, '0'), style = mono(12.5.sp), color = p.mute, modifier = Modifier.width(34.dp).padding(start = 8.dp))
        Thumb(v, Modifier.width(118.dp), small = true, showLen = false)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(v.title, style = body(14.5.sp, FontWeight.Medium), color = p.fg, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(Fmt.shortFolder(v.folder) + if (v.views > 0) "   " + Fmt.views(v.views) else "", style = body(12.5.sp), color = p.mute, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.width(8.dp))
        Text(Fmt.dur(v.dur), style = mono(12.5.sp), color = p.mute)
        Box(Modifier.padding(start = 6.dp).clip(RoundedCornerShape(8.dp)).clickable { vm.nav.go(Info(v.id)) }.padding(8.dp)) {
            Icon(Ic.info, "Детальніше", tint = p.mute, modifier = Modifier.width(20.dp).height(20.dp))
        }
    }
}
