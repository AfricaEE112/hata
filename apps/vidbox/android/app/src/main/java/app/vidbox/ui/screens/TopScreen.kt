package app.vidbox.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.vidbox.AppVM
import app.vidbox.Info
import app.vidbox.data.Fmt
import app.vidbox.data.Video
import app.vidbox.data.sorter
import app.vidbox.ui.Empty
import app.vidbox.ui.Lead
import app.vidbox.ui.LocalPal
import app.vidbox.ui.Meter
import app.vidbox.ui.PAD
import app.vidbox.ui.PageTitle
import app.vidbox.ui.PromptLine
import app.vidbox.ui.Thumb
import app.vidbox.ui.body
import app.vidbox.ui.display
import app.vidbox.ui.mono
import kotlin.math.roundToInt

@Composable
fun TopScreen(vm: AppVM) {
    val p = LocalPal.current
    val lib = vm.lib ?: return Waiting(vm)
    val rated = remember(lib.videos) { lib.videos.filter { it.views > 0 || it.vote != 0 }.sortedWith(sorter("score", "desc", emptyMap())) }
    val rest = lib.videos.size - rated.size
    LazyColumn(state = vm.nav.list("top"), contentPadding = PaddingValues(top = 14.dp, bottom = 28.dp), modifier = Modifier.fillMaxSize()) {
        item { PromptLine("~/рейтинг", "sort -k score -rn | head -${rated.size}", Modifier.padding(horizontal = PAD)) }
        item { PageTitle("Рейтинг", modifier = Modifier.padding(top = 6.dp)) }
        item {
            Lead(
                "Складається сам із того, як ти дивишся: наскільки досматриваєш відео (45%), як часто до нього вертаєшся, і свіжі перегляди тут важать більше (40%), плюс твої лайки й дизлайки (15%).",
                Modifier.padding(top = 6.dp, bottom = 14.dp),
            )
        }
        if (rated.isEmpty()) item { Empty("Рейтинг ще порожній", "Подивись кілька відео, і він збереться сам.") }
        itemsIndexed(rated, key = { _, v -> v.id }) { i, v -> RankRow(vm, i + 1, v) }
        if (rest > 0 && rated.isNotEmpty()) item {
            Text(
                "Ще $rest відео без оцінки. Вони з'являться тут, щойно ти їх переглянеш.",
                style = mono(12.sp), color = p.mute, modifier = Modifier.padding(start = PAD, end = PAD, top = 20.dp),
            )
        }
    }
}

@Composable
private fun RankRow(vm: AppVM, n: Int, v: Video) {
    val p = LocalPal.current
    Row(
        Modifier.fillMaxWidth().clickable { vm.nav.go(Info(v.id)) }.padding(horizontal = PAD, vertical = 9.dp).widthIn(max = 900.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "$n", style = display(if (n <= 3) 26.sp else 20.sp), color = if (n <= 3) p.acc else p.mute,
            textAlign = TextAlign.Center, modifier = Modifier.width(34.dp),
        )
        Spacer(Modifier.width(8.dp))
        Thumb(v, Modifier.width(112.dp), small = true, showLen = false)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(v.title, style = body(14.5.sp, FontWeight.Medium), color = p.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(5.dp))
            MiniBar("Досмотр", v.avg?.toFloat() ?: 0f, if (v.avg != null) "${Fmt.pct(v.avg)}%" else "—")
            MiniBar("Вертаєшся", v.pop.toFloat(), "${Fmt.pct(v.pop)}%")
            Text(
                Fmt.views(v.views) + when { v.vote > 0 -> ", лайк"; v.vote < 0 -> ", дизлайк"; else -> "" },
                style = body(12.sp), color = p.mute,
            )
        }
        Spacer(Modifier.width(10.dp))
        Text("${v.score.roundToInt()}", style = display(28.sp), color = p.fg)
    }
}

@Composable
fun MiniBar(label: String, value: Float, text: String) {
    val p = LocalPal.current
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label, style = mono(10.5.sp), color = p.mute, modifier = Modifier.width(74.dp))
        Meter(value, Modifier.weight(1f))
        Text(text, style = mono(10.5.sp), color = p.mute, modifier = Modifier.width(34.dp), textAlign = TextAlign.End)
    }
}
