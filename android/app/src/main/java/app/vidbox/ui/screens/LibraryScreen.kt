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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridScope
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import app.vidbox.AppVM
import app.vidbox.Info
import app.vidbox.data.Fmt
import app.vidbox.data.LEN_GROUPS
import app.vidbox.data.Natural
import app.vidbox.data.SORTS
import app.vidbox.data.UNKNOWN_LEN
import app.vidbox.data.Video
import app.vidbox.data.sortDef
import app.vidbox.data.sorter
import app.vidbox.ui.Btn
import app.vidbox.ui.Chip
import app.vidbox.ui.Ic
import app.vidbox.ui.IconBtn
import app.vidbox.ui.LocalPal
import app.vidbox.ui.PromptLine
import app.vidbox.ui.Seg
import app.vidbox.ui.VideoCard
import app.vidbox.ui.Win
import app.vidbox.ui.body
import app.vidbox.ui.display
import app.vidbox.ui.mono

private data class Group(val key: String, val name: String, val hint: String, val list: List<Video>, val playable: Boolean)

private fun libMeta(v: Video, sort: String, grouped: Boolean): List<String> {
    val extra = when (sort) {
        "size" -> Fmt.size(v.size)
        "res" -> v.res
        "dur" -> Fmt.len(v.dur)
        "added" -> "додано " + Fmt.ago(v.added)
        "last" -> if (v.last > 0) "дивився " + Fmt.ago(v.last) else "ще не дивився"
        else -> if (v.views > 0) Fmt.views(v.views) else if (grouped) Fmt.size(v.size) else ""
    }
    return listOf(if (grouped) "" else Fmt.shortFolder(v.folder), extra)
}

@Composable
fun LibraryScreen(vm: AppVM) {
    val p = LocalPal.current
    val lib = vm.lib ?: return Waiting(vm)
    val u = vm.ui
    val gen = vm.rndGen
    val q = vm.query
    val folder = vm.folder
    var picker by remember { mutableStateOf(false) }

    val list = remember(lib.videos, u, q, folder, gen) {
        var vs = lib.videos
        if (folder != null) vs = vs.filter { it.folder == folder || it.folder.startsWith("$folder/") }
        val words = q.lowercase().split(Regex("\\s+")).filter { it.isNotEmpty() }
        if (words.isNotEmpty()) vs = vs.filter { v -> val t = (v.title + " " + v.folder + " " + v.file).lowercase(); words.all { t.contains(it) } }
        vs.sortedWith(sorter(u.sort, u.dir, vm.rndMap()))
    }
    val groups = remember(list, u.group) {
        when (u.group) {
            "folders" -> list.groupBy { it.folder }.toSortedMap(Natural).map { (f, vs) -> Group(f, Fmt.shortFolder(f), "", vs, false) }
            "duration" -> (LEN_GROUPS + UNKNOWN_LEN).map { g -> Group(g.id, g.name, g.hint, list.filter(g.test), g !== UNKNOWN_LEN) }.filter { it.list.isNotEmpty() }
            else -> emptyList()
        }
    }
    val grouped = u.group != "all"

    LazyVerticalGrid(
        columns = GridCells.Adaptive(158.dp),
        state = vm.nav.grid("lib"),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 28.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        full("prompt") { PromptLine("~/бібліотека", vm.libCmd()) }
        full("title") {
            Row(verticalAlignment = Alignment.Bottom) {
                Text("Бібліотека", style = display(38.sp), color = p.fg)
                Spacer(Modifier.width(12.dp))
                Text(Fmt.videos(list.size), style = mono(13.sp), color = p.mute, modifier = Modifier.padding(bottom = 6.dp))
                Spacer(Modifier.weight(1f))
                app.vidbox.ui.Btn("Рейтинг", { vm.nav.go(app.vidbox.Top) }, icon = app.vidbox.ui.Ic.bars, kind = app.vidbox.ui.Kind.Ghost)
            }
        }
        full("search") { SearchField(vm) }
        full("group") {
            Seg(
                listOf("Усі" to Ic.grid, "Папки" to Ic.folder, "Тривалість" to Ic.clock),
                when (u.group) { "folders" -> 1; "duration" -> 2; else -> 0 },
                { vm.changeUi(u.copy(group = listOf("all", "folders", "duration")[it])) },
                Modifier.fillMaxWidth(),
            )
        }
        full("sort") {
            val s = sortDef(u.sort)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Row(
                    Modifier.weight(1f).heightIn(min = 42.dp).clip(RoundedCornerShape(8.dp)).background(Color.Black.copy(alpha = .25f))
                        .border(1.dp, p.line, RoundedCornerShape(8.dp)).clickable { picker = true }.padding(horizontal = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(s.label, style = body(14.sp, FontWeight.SemiBold), color = p.fg, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Icon(Ic.chev, null, tint = p.mute, modifier = Modifier.size(18.dp))
                }
                if (u.sort == "random") {
                    Btn("Перемішати", { vm.reshuffle() }, icon = Ic.dice)
                } else {
                    Btn(if (u.dir == "asc") s.asc else s.desc, { vm.changeUi(u.copy(dir = if (u.dir == "asc") "desc" else "asc")) }, icon = if (u.dir == "asc") Ic.arrUp else Ic.arrDown)
                }
            }
        }
        full("folders") {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                item { Chip("Усі папки", on = folder == null) { vm.folder = null } }
                items(lib.folders, key = { it }) { f -> Chip(Fmt.shortFolder(f), on = folder == f) { vm.folder = if (folder == f) null else f } }
            }
        }
        if (list.isEmpty()) full("empty") {
            Text(
                if (q.isNotBlank()) "Нічого не знайшлося за запитом «$q». Спробуй інше слово або обери «Усі папки»." else "У цій папці немає відео.",
                style = body(15.sp), color = p.mute, modifier = Modifier.padding(vertical = 30.dp),
            )
        }
        if (!grouped) {
            items(list, key = { it.id }) { v -> VideoCard(v, { vm.nav.go(Info(v.id)) }, meta = libMeta(v, u.sort, false)) }
        } else {
            groups.forEach { g ->
                val closed = vm.collapsed[u.group + g.key] == true
                full("g-" + g.key) { GroupHead(vm, g, closed) { vm.collapsed[u.group + g.key] = !closed } }
                if (!closed) items(g.list, key = { it.id }) { v -> VideoCard(v, { vm.nav.go(Info(v.id)) }, meta = libMeta(v, u.sort, true)) }
            }
        }
    }

    if (picker) {
        Dialog(onDismissRequest = { picker = false }) {
            Win("sort --by", Modifier.fillMaxWidth()) {
                Column(Modifier.verticalScroll(rememberScrollState()).padding(vertical = 6.dp)) {
                    SORTS.forEach { s ->
                        val on = s.id == u.sort
                        Row(
                            Modifier.fillMaxWidth().clickable {
                                picker = false
                                vm.changeUi(u.copy(sort = s.id, dir = if (s.id == u.sort) u.dir else s.first))
                            }.padding(horizontal = 16.dp, vertical = 13.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(s.label, style = body(15.sp, if (on) FontWeight.SemiBold else FontWeight.Normal), color = if (on) p.acc else p.fg, modifier = Modifier.weight(1f))
                            if (on) Icon(Ic.check, null, tint = p.acc, modifier = Modifier.size(20.dp))
                        }
                    }
                }
            }
        }
    }
}

private fun LazyGridScope.full(key: String, content: @Composable () -> Unit) {
    item(key = key, span = { GridItemSpan(maxLineSpan) }) { content() }
}

@Composable
private fun GroupHead(vm: AppVM, g: Group, closed: Boolean, toggle: () -> Unit) {
    val p = LocalPal.current
    val size = g.list.sumOf { it.size }
    val dur = g.list.sumOf { it.dur }
    Column(Modifier.fillMaxWidth()) {
    Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Row(
            Modifier.weight(1f).clip(RoundedCornerShape(8.dp)).clickable(onClick = toggle).padding(vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Ic.chev, null, tint = p.acc, modifier = Modifier.size(20.dp).rotate(if (closed) -90f else 0f))
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                Text(g.name, style = display(20.sp, FontWeight.Bold), color = p.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    listOf(Fmt.videos(g.list.size), Fmt.size(size), Fmt.len(dur)).filter { it.isNotEmpty() }.joinToString(", "),
                    style = mono(11.5.sp), color = p.mute,
                )
            }
        }
        if (g.playable) IconBtn(Ic.play, { vm.playQueue(g.key) }, desc = "Відтворити все", tint = p.acc)
    }
    Spacer(Modifier.height(6.dp))
    Box(Modifier.fillMaxWidth().height(1.dp).background(p.line))
    }
}

@Composable
private fun SearchField(vm: AppVM) {
    val p = LocalPal.current
    val focus = remember { FocusRequester() }
    val fm = LocalFocusManager.current
    LaunchedEffect(vm.focusSearch) {
        if (vm.focusSearch) {
            vm.focusSearch = false
            runCatching { focus.requestFocus() }
        }
    }
    Row(
        Modifier.fillMaxWidth().height(46.dp).clip(RoundedCornerShape(9.dp)).background(Color.Black.copy(alpha = .25f))
            .border(1.dp, p.line, RoundedCornerShape(9.dp)).padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Ic.search, null, tint = p.mute, modifier = Modifier.size(19.dp))
        Spacer(Modifier.width(10.dp))
        Box(Modifier.weight(1f)) {
            if (vm.query.isEmpty()) Text("пошук за назвою чи папкою", style = mono(13.5.sp), color = p.mute)
            BasicTextField(
                value = vm.query, onValueChange = { vm.query = it }, singleLine = true,
                textStyle = mono(14.sp).copy(color = p.fg), cursorBrush = SolidColor(p.acc),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { fm.clearFocus() }),
                modifier = Modifier.fillMaxWidth().focusRequester(focus),
            )
        }
        if (vm.query.isNotEmpty()) {
            Box(Modifier.clip(RoundedCornerShape(6.dp)).clickable { vm.query = "" }.padding(4.dp)) {
                Icon(Ic.close, "Очистити", tint = p.mute, modifier = Modifier.size(18.dp))
            }
        }
    }
}
