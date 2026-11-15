package app.vidbox.ui

import android.graphics.drawable.BitmapDrawable
import android.util.LruCache
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.vidbox.AppVM
import app.vidbox.data.Fmt
import app.vidbox.data.Video
import coil.compose.AsyncImage
import coil.imageLoader
import coil.request.ImageRequest
import kotlinx.coroutines.delay
import kotlin.math.max
import kotlin.math.roundToInt

val LocalVM = staticCompositionLocalOf<AppVM> { error("no vm") }

val PAD = 16.dp

/** Курсор терміналу: половину часу видно, половину ні. */
val Blink = Easing { if (it < 0.5f) 0f else 1f }

// ── логотип «▶_»: трикутник-промпт і курсор, що блимає ──
@Composable
fun Mark(size: Dp = 30.dp, blink: Boolean = true) {
    val p = LocalPal.current
    val cursor = if (blink) {
        val t = rememberInfiniteTransition(label = "cur")
        t.animateFloat(1f, 0f, infiniteRepeatable(tween(1100, easing = Blink), RepeatMode.Restart), label = "blink").value
    } else 1f
    Box(
        Modifier.size(size).clip(RoundedCornerShape(size * 0.27f)).background(p.bg3)
            .border(1.dp, p.acc.copy(alpha = .6f), RoundedCornerShape(size * 0.27f)),
    ) {
        Canvas(Modifier.fillMaxSize().padding(size * 0.18f)) {
            val w = this.size.width
            val tri = Path().apply {
                moveTo(w * 4f / 24f, w * 5f / 24f)
                lineTo(w * 4f / 24f, w * 19f / 24f)
                lineTo(w * 14f / 24f, w * 12f / 24f)
                close()
            }
            drawPath(tri, p.acc)
            drawRoundRect(
                p.acc2.copy(alpha = cursor), topLeft = Offset(w * 15f / 24f, w * 16.6f / 24f),
                size = Size(w * 6.5f / 24f, w * 2.4f / 24f), cornerRadius = CornerRadius(w * .5f / 24f),
            )
        }
    }
}

@Composable
fun Brand(size: Int = 17) {
    val p = LocalPal.current
    Row(verticalAlignment = Alignment.CenterVertically) {
        Mark((size * 1.75f).dp)
        Spacer(Modifier.width(10.dp))
        Text(
            buildAnnotatedString {
                withStyle(SpanStyle(color = p.fg)) { append("vid") }
                withStyle(SpanStyle(color = p.acc, fontWeight = FontWeight.Bold)) { append("box") }
            },
            style = mono(size.sp, FontWeight.Bold),
        )
    }
}

// ── рядок терміналу: [vidbox@host ~/шлях]$ команда█ ──
@Composable
fun PromptLine(path: String, cmd: String, modifier: Modifier = Modifier) {
    val vm = LocalVM.current
    val p = LocalPal.current
    val t = rememberInfiniteTransition(label = "prompt")
    val on = t.animateFloat(1f, 0f, infiniteRepeatable(tween(1100, easing = Blink)), label = "c").value
    Text(
        buildAnnotatedString {
            withStyle(SpanStyle(color = p.acc)) { append("[vidbox@${vm.host} $path]$ ") }
            withStyle(SpanStyle(color = p.fg)) { append(cmd) }
            withStyle(SpanStyle(color = p.fg.copy(alpha = on))) { append("█") }
        },
        style = mono(12.5.sp), modifier = modifier,
    )
}

// ── вікно як у bspwm: смужка з трьома крапками і заголовком ──
@Composable
fun Win(title: String, modifier: Modifier = Modifier, bold: String = "", trailing: @Composable (() -> Unit)? = null, content: @Composable () -> Unit) {
    val p = LocalPal.current
    Column(
        modifier.clip(RoundedCornerShape(10.dp)).background(p.bg2.copy(alpha = .78f))
            .border(1.dp, p.line, RoundedCornerShape(10.dp)),
    ) {
        Row(
            Modifier.fillMaxWidth().background(Color.Black.copy(alpha = .18f)).padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            repeat(3) {
                Box(Modifier.padding(end = 6.dp).size(7.dp).clip(CircleShape).background(p.mute.copy(alpha = .45f)))
            }
            Spacer(Modifier.width(6.dp))
            Text(
                buildAnnotatedString {
                    withStyle(SpanStyle(color = p.mute)) { append(title) }
                    withStyle(SpanStyle(color = p.fg)) { append(bold) }
                },
                style = mono(11.5.sp), maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f),
            )
            trailing?.invoke()
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(p.line))
        content()
    }
}

// ── кнопки ──
enum class Kind { Primary, Normal, Ghost }

@Composable
fun Btn(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, icon: ImageVector? = null, kind: Kind = Kind.Normal, enabled: Boolean = true) {
    val p = LocalPal.current
    val shape = RoundedCornerShape(8.dp)
    val bg = when (kind) {
        Kind.Primary -> Brush.horizontalGradient(listOf(p.acc, p.acc.copy(alpha = .88f)))
        Kind.Normal -> Brush.linearGradient(listOf(p.bg3, p.bg3))
        Kind.Ghost -> Brush.linearGradient(listOf(Color.Transparent, Color.Transparent))
    }
    val fg = if (kind == Kind.Primary) p.on else p.fg
    Row(
        modifier
            .then(if (kind == Kind.Primary) Modifier.shadow(14.dp, shape, ambientColor = p.acc, spotColor = p.acc) else Modifier)
            .clip(shape).background(bg)
            .then(if (kind != Kind.Primary) Modifier.border(1.dp, p.line, shape) else Modifier)
            .clickable(enabled = enabled, onClick = onClick)
            .heightIn(min = 42.dp).padding(horizontal = 15.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        if (icon != null) {
            Icon(icon, null, tint = fg.copy(alpha = if (enabled) 1f else .5f), modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(9.dp))
        }
        Text(text, style = mono(13.5.sp, FontWeight.Bold), color = fg.copy(alpha = if (enabled) 1f else .5f), maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
fun IconBtn(icon: ImageVector, onClick: () -> Unit, modifier: Modifier = Modifier, on: Boolean = false, size: Dp = 42.dp, desc: String? = null, tint: Color? = null) {
    val p = LocalPal.current
    val shape = RoundedCornerShape(9.dp)
    Box(
        modifier.size(size).clip(shape)
            .background(if (on) p.acc.copy(alpha = .14f) else Color.Black.copy(alpha = .22f))
            .border(1.dp, if (on) p.acc.copy(alpha = .5f) else p.line, shape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, desc, tint = tint ?: if (on) p.acc else p.fg, modifier = Modifier.size(size * 0.48f))
    }
}

@Composable
fun Chip(text: String, modifier: Modifier = Modifier, on: Boolean = false, onClick: (() -> Unit)? = null) {
    val p = LocalPal.current
    val shape = RoundedCornerShape(7.dp)
    Text(
        text, style = mono(12.sp), color = if (on) p.on else p.fg, maxLines = 1,
        modifier = modifier.clip(shape).background(if (on) p.acc else Color.Black.copy(alpha = .25f))
            .border(1.dp, if (on) p.acc else p.line, shape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
}

/** Тонка смужка прогресу. */
@Composable
fun Meter(value: Float, modifier: Modifier = Modifier, color: Color? = null, track: Color? = null) {
    val p = LocalPal.current
    Box(modifier.height(4.dp).clip(RoundedCornerShape(2.dp)).background(track ?: p.line)) {
        Box(Modifier.fillMaxHeight().fillMaxWidth(value.coerceIn(0f, 1f)).background(color ?: p.acc))
    }
}

@Composable
fun SectionHead(title: String, sub: String = "", modifier: Modifier = Modifier, trailing: @Composable (() -> Unit)? = null) {
    val p = LocalPal.current
    Row(modifier.fillMaxWidth().padding(horizontal = PAD), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.width(3.dp).height(if (sub.isEmpty()) 20.dp else 38.dp).clip(RoundedCornerShape(2.dp)).background(p.acc))
        Spacer(Modifier.width(11.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = display(21.sp, FontWeight.Bold), color = p.fg)
            if (sub.isNotEmpty()) Text(sub, style = body(13.sp), color = p.mute, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        trailing?.invoke()
    }
}

@Composable
fun Lead(text: String, modifier: Modifier = Modifier) {
    Text(text, style = body(15.sp), color = LocalPal.current.mute, modifier = modifier.padding(horizontal = PAD).widthIn(max = 640.dp))
}

@Composable
fun PageTitle(text: String, count: String = "", modifier: Modifier = Modifier) {
    val p = LocalPal.current
    Row(modifier.padding(horizontal = PAD), verticalAlignment = Alignment.Bottom) {
        Text(text, style = display(38.sp), color = p.fg)
        if (count.isNotEmpty()) {
            Spacer(Modifier.width(12.dp))
            Text(count, style = mono(13.sp), color = p.mute, modifier = Modifier.padding(bottom = 6.dp))
        }
    }
}

@Composable
fun Empty(title: String, text: String, modifier: Modifier = Modifier, actions: @Composable () -> Unit = {}) {
    val p = LocalPal.current
    Column(modifier.fillMaxWidth().padding(PAD * 2), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(title, style = display(26.sp), color = p.fg)
        Spacer(Modifier.height(10.dp))
        Text(text, style = body(15.sp), color = p.mute, modifier = Modifier.widthIn(max = 420.dp))
        Spacer(Modifier.height(18.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) { actions() }
    }
}

// ── картинки: обкладинка, кадр з нарізки, великий кадр ──
private val sprites = LruCache<String, ImageBitmap>(16)

@Composable
fun rememberSprite(url: String?): ImageBitmap? {
    val ctx = LocalContext.current
    var bmp by remember(url) { mutableStateOf(url?.let { sprites.get(it) }) }
    LaunchedEffect(url) {
        if (url == null || bmp != null) return@LaunchedEffect
        val req = ImageRequest.Builder(ctx).data(url).size(coil.size.Size.ORIGINAL).build()
        val d = ctx.imageLoader.execute(req).drawable
        (d as? BitmapDrawable)?.bitmap?.asImageBitmap()?.let {
            sprites.put(url, it)
            bmp = it
        }
    }
    return bmp
}

@Composable
fun SpriteFrame(v: Video, index: Int, modifier: Modifier = Modifier) {
    val vm = LocalVM.current
    val n = vm.spriteN
    val bmp = rememberSprite(if (v.hasSprite) vm.api.spriteUrl(v) else null)
    Canvas(modifier) {
        val b = bmp ?: return@Canvas
        val fw = b.width / n
        val fh = b.height
        if (fw <= 0 || fh <= 0 || size.width <= 0f || size.height <= 0f) return@Canvas
        val scale = max(size.width / fw, size.height / fh)
        val sw = (size.width / scale).roundToInt().coerceIn(1, fw)
        val sh = (size.height / scale).roundToInt().coerceIn(1, fh)
        val sx = index.coerceIn(0, n - 1) * fw + (fw - sw) / 2
        val sy = (fh - sh) / 2
        drawImage(
            b, srcOffset = IntOffset(sx, sy), srcSize = IntSize(sw, sh),
            dstSize = IntSize(size.width.roundToInt(), size.height.roundToInt()), filterQuality = FilterQuality.Medium,
        )
    }
}

@Composable
fun Placeholder(v: Video, modifier: Modifier = Modifier) {
    val h = v.hue.toFloat()
    Box(
        modifier.background(Brush.linearGradient(listOf(Color.hsl(h, .35f, .26f), Color.hsl((h + 50f) % 360f, .35f, .12f)))),
        contentAlignment = Alignment.Center,
    ) {
        Text(v.initial, style = display(34.sp), color = Color.White.copy(alpha = .55f))
    }
}

/** Обкладинка: знімок з ПК, або кадр з нарізки, або кольорова заглушка. */
@Composable
fun Cover(v: Video, modifier: Modifier = Modifier, frame: Int = 3) {
    val vm = LocalVM.current
    Box(modifier) {
        when {
            v.thumb > 0 -> AsyncImage(model = vm.api.thumbUrl(v), contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            v.hasSprite -> SpriteFrame(v, frame, Modifier.fillMaxSize())
            else -> Placeholder(v, Modifier.fillMaxSize())
        }
    }
}

/** Великий кадр (до 1280 px) з ПК — для банера й вікна з інфою. */
@Composable
fun BigFrame(v: Video, i: Int, modifier: Modifier = Modifier) {
    val vm = LocalVM.current
    Box(modifier) {
        Cover(v, Modifier.fillMaxSize(), i)
        if (v.hasSprite) AsyncImage(model = vm.api.frameUrl(v, i), contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
    }
}

@Composable
fun Badge(text: String, modifier: Modifier = Modifier, accent: Boolean = false) {
    val p = LocalPal.current
    Text(
        text, style = mono(11.sp, FontWeight.Bold), color = if (accent) p.on else Color.White,
        modifier = modifier.clip(RoundedCornerShape(5.dp)).background(if (accent) p.acc else Color.Black.copy(alpha = .68f))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

@Composable
fun Thumb(v: Video, modifier: Modifier = Modifier, rank: Int? = null, small: Boolean = false, showLen: Boolean = true, content: @Composable BoxScope.() -> Unit = {}) {
    val p = LocalPal.current
    Box(modifier.aspectRatio(16f / 9f).clip(RoundedCornerShape(8.dp)).background(p.bg3)) {
        Cover(v, Modifier.fillMaxSize())
        if (v.views > 0 || v.vote != 0) Badge("★ ${v.score.roundToInt()}", Modifier.align(Alignment.TopStart).padding(6.dp), accent = v.score >= 70)
        if (v.prep && !small) Badge(v.ext.uppercase(), Modifier.align(Alignment.TopEnd).padding(6.dp))
        if (showLen && v.dur > 0) Badge(Fmt.dur(v.dur), Modifier.align(Alignment.BottomEnd).padding(6.dp))
        if (v.pos > 0 && v.dur > 0) {
            Meter((v.pos / v.dur).toFloat(), Modifier.align(Alignment.BottomCenter).fillMaxWidth(), track = Color.White.copy(alpha = .2f))
        }
        if (rank != null) {
            Text(
                "$rank", style = display(46.sp).copy(shadow = Shadow(Color.Black.copy(alpha = .8f), Offset(0f, 3f), 14f)),
                color = Color.White, modifier = Modifier.align(Alignment.BottomStart).padding(start = 10.dp, bottom = 2.dp),
            )
        }
        content()
    }
}

@Composable
fun VideoCard(v: Video, onClick: () -> Unit, modifier: Modifier = Modifier, meta: List<String>? = null, rank: Int? = null, small: Boolean = false) {
    val p = LocalPal.current
    val m = (meta ?: listOf(Fmt.shortFolder(v.folder), if (v.views > 0) Fmt.views(v.views) else "")).filter { it.isNotEmpty() }
    Column(modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onClick)) {
        Thumb(v, Modifier.fillMaxWidth(), rank = rank, small = small)
        Spacer(Modifier.height(8.dp))
        Text(v.title, style = body(if (small) 13.5.sp else 14.5.sp, FontWeight.Medium), color = p.fg, maxLines = 2, overflow = TextOverflow.Ellipsis)
        if (m.isNotEmpty()) Text(m.joinToString("   "), style = body(12.5.sp), color = p.mute, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(4.dp))
    }
}

/** Полиця: заголовок і стрічка карток, що гортається вбік. */
@Composable
fun Shelf(
    title: String,
    list: List<Video>,
    onOpen: (Video) -> Unit,
    sub: String = "",
    small: Boolean = false,
    ranked: Boolean = false,
    meta: ((Video) -> List<String>)? = null,
    trailing: @Composable (() -> Unit)? = null,
) {
    if (list.isEmpty()) return
    Column(Modifier.fillMaxWidth().padding(top = 26.dp)) {
        SectionHead(title, sub, trailing = trailing)
        Spacer(Modifier.height(12.dp))
        LazyRow(contentPadding = PaddingValues(horizontal = PAD), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            items(list.size, key = { list[it].id }) { i ->
                val v = list[i]
                VideoCard(v, { onOpen(v) }, Modifier.width(if (small) 172.dp else 216.dp), meta = meta?.invoke(v), rank = if (ranked) i + 1 else null, small = small)
            }
        }
    }
}

// ── тло: крапки, як на сайті, і світіння акцентного кольору ──
fun Modifier.backdrop(p: Pal, glow: Color? = null): Modifier = drawBehind {
    drawRect(p.bg)
    drawRect(
        Brush.radialGradient(listOf((glow ?: p.acc).copy(alpha = .16f), Color.Transparent), center = Offset(size.width * .2f, 0f), radius = size.width * 1.2f),
    )
    val step = 22.dp.toPx()
    val r = 0.9.dp.toPx()
    val c = p.fg.copy(alpha = .05f)
    var y = step / 2
    while (y < size.height) {
        var x = step / 2
        while (x < size.width) {
            drawCircle(c, r, Offset(x, y))
            x += step
        }
        y += step
    }
}

// ── сповіщення в стилі dunst ──
@Composable
fun ToastHost(vm: AppVM, modifier: Modifier = Modifier) {
    val p = LocalPal.current
    val t = vm.toast
    LaunchedEffect(t?.id) {
        if (t != null) {
            delay(if (t.action != null) 5500 else 3500)
            if (vm.toast?.id == t.id) vm.toast = null
        }
    }
    Box(modifier.fillMaxWidth().statusBarsPadding().padding(top = 62.dp, start = PAD, end = PAD), contentAlignment = Alignment.TopEnd) {
        AnimatedVisibility(t != null, enter = fadeIn() + slideInVertically { -it / 2 }, exit = fadeOut() + slideOutVertically { -it / 2 }) {
            val last = remember { mutableStateOf(t) }
            if (t != null) last.value = t
            val shown = last.value ?: return@AnimatedVisibility
            Row(
                Modifier.widthIn(max = 420.dp).shadow(18.dp, RoundedCornerShape(8.dp))
                    .clip(RoundedCornerShape(8.dp)).background(p.bg2).border(1.dp, p.acc.copy(alpha = .8f), RoundedCornerShape(8.dp))
                    .clickable { vm.toast = null }.padding(horizontal = 14.dp, vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f, fill = false)) {
                    Text("vidbox", style = mono(11.sp), color = p.acc)
                    Text(shown.text, style = mono(12.5.sp), color = p.fg)
                }
                if (shown.action != null) {
                    Spacer(Modifier.width(12.dp))
                    Text(
                        shown.action, style = mono(12.5.sp, FontWeight.Bold), color = p.acc,
                        modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable { shown.onAction?.invoke(); vm.toast = null }.padding(8.dp),
                    )
                }
            }
        }
    }
}

/** Перемикач на кілька варіантів (як .seg на сайті). */
@Composable
fun Seg(options: List<Pair<String, ImageVector?>>, selected: Int, onSelect: (Int) -> Unit, modifier: Modifier = Modifier) {
    val p = LocalPal.current
    Row(
        modifier.clip(RoundedCornerShape(9.dp)).background(Color.Black.copy(alpha = .25f)).border(1.dp, p.line, RoundedCornerShape(9.dp)).padding(3.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        options.forEachIndexed { i, (label, icon) ->
            val on = i == selected
            Row(
                Modifier.weight(1f).clip(RoundedCornerShape(7.dp))
                    .background(if (on) p.acc.copy(alpha = .16f) else Color.Transparent)
                    .border(1.dp, if (on) p.acc.copy(alpha = .5f) else Color.Transparent, RoundedCornerShape(7.dp))
                    .clickable { onSelect(i) }.padding(vertical = 9.dp, horizontal = 6.dp),
                horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically,
            ) {
                if (icon != null) {
                    Icon(icon, null, tint = if (on) p.acc else p.mute, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(6.dp))
                }
                Text(label, style = body(13.sp, FontWeight.Medium), color = if (on) p.acc else p.mute, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}
