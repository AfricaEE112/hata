package app.vidbox.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import app.vidbox.R

/** Ті самі 10 тем, що й на сайті (кольори взяті зі style.css). */
data class Pal(
    val id: String,
    val name: String,
    val hint: String,
    val bg: Color,
    val bg2: Color,
    val bg3: Color,
    val line: Color,
    val fg: Color,
    val mute: Color,
    val acc: Color,
    val acc2: Color,
    val on: Color,
    /** Світла тема (Папір): інша схема Material і темні значки в рядку стану. */
    val light: Boolean = false,
    /** Схема з панелі Хати. */
    val hata: Boolean = false,
)

private fun c(hex: Long) = Color(0xFF000000 or hex)

val PALS = listOf(
    Pal("arch", "Arch", "Фірмовий синій Arch Linux", c(0x0c0f14), c(0x141922), c(0x1c2330), c(0x2a3344), c(0xe1e6ef), c(0x8590a3), c(0x1793d1), c(0x56c5f2), c(0x031018)),
    Pal("tokyo", "Tokyo Night", "Нічне місто, синій з бузковим", c(0x16161e), c(0x1a1b26), c(0x24283b), c(0x2f3549), c(0xc0caf5), c(0x7a83a8), c(0x7aa2f7), c(0xbb9af7), c(0x11131c)),
    Pal("catppuccin", "Catppuccin", "Mocha: м’які пастельні кольори", c(0x11111b), c(0x1e1e2e), c(0x313244), c(0x45475a), c(0xcdd6f4), c(0x9399b2), c(0xcba6f7), c(0x89b4fa), c(0x1e1e2e)),
    Pal("dracula", "Dracula", "Класика: фіолетовий і рожевий", c(0x1e1f29), c(0x282a36), c(0x343746), c(0x44475a), c(0xf8f8f2), c(0x9ea4c8), c(0xbd93f9), c(0xff79c6), c(0x21222c)),
    Pal("gruvbox", "Gruvbox", "Теплий ретро-помаранчевий", c(0x1d2021), c(0x282828), c(0x3c3836), c(0x504945), c(0xebdbb2), c(0xa89984), c(0xfe8019), c(0xb8bb26), c(0x1d2021)),
    Pal("cinema", "Cinema", "Глибокий синій, як зал кінотеатру", c(0x070b14), c(0x0e1524), c(0x18223a), c(0x24324f), c(0xe8eef8), c(0x8b9ab5), c(0x2ea8ff), c(0x8a6bff), c(0x03111f)),
    Pal("nord", "Nord", "Спокійний сіро-блакитний", c(0x21262f), c(0x2b313c), c(0x363e4c), c(0x454e60), c(0xeceff4), c(0x9aa5b9), c(0x88c0d0), c(0xb48ead), c(0x1b222c)),
    Pal("sweet", "Sweet", "Неоновий рожевий і бірюза", c(0x100e1a), c(0x1a1729), c(0x272239), c(0x3a3354), c(0xf5f1ff), c(0xa69fc6), c(0xff4fd8), c(0x38d9f5), c(0x24061f)),
    Pal("exodia", "Exodia", "Фіолетовий з кислотно-зеленим", c(0x09060f), c(0x130e1e), c(0x1e162f), c(0x30254a), c(0xefe9ff), c(0xa395c8), c(0xb56bff), c(0x46f59a), c(0x14061f)),
    Pal("projector", "Проєктор", "Тепле бурштинове світло", c(0x0f1420), c(0x161d2b), c(0x1f2839), c(0x2c3649), c(0xede6d8), c(0x8f99aa), c(0xf2b544), c(0xff7a59), c(0x1c1508)),
    // схеми панелі Хати
    Pal("chai", "Чай", "Теплий темний з м’ятним", c(0x161511), c(0x1d1b16), c(0x28251e), c(0x4d473d), c(0xece4d2), c(0xa39a86), c(0x7cc6b1), c(0xe3c16f), c(0x14130f), hata = true),
    Pal("nich", "Ніч", "Глибокий синій", c(0x181825), c(0x1e1e2e), c(0x313244), c(0x45475a), c(0xcdd6f4), c(0xa6adc8), c(0x89b4fa), c(0xcba6f7), c(0x11111b), hata = true),
    Pal("lain", "lain", "Холодний сірий", c(0x16181e), c(0x1c1e25), c(0x272a33), c(0x4a5062), c(0xdfe3ee), c(0x9aa1b4), c(0xb4c3f0), c(0xe8a0b4), c(0x161820), hata = true),
    Pal("yahoda", "Ягода", "Ягідний з рожевим", c(0x220c1b), c(0x2a1022), c(0x3a1630), c(0x6b2f5a), c(0xf6dcec), c(0xc99bb8), c(0xf4a6d7), c(0xc9a4f5), c(0x2a1022), hata = true),
    Pal("nothing", "nothing", "Чорний і білий з червоним", c(0x000000), c(0x0a0a0a), c(0x161616), c(0x3a3a3a), c(0xf2f2f2), c(0xa3a3a3), c(0xf2f2f2), c(0xe8352f), c(0x000000), hata = true),
    Pal("papir", "Папір", "Світла, як папір", c(0xe9e1cf), c(0xf3ecdc), c(0xe0d6c0), c(0xb9ad95), c(0x2a261f), c(0x655b4b), c(0x2f7d6d), c(0x946a0c), c(0xf6f1e5), light = true, hata = true),
)

/** id «hata» — тема йде за схемою, вибраною в панелі Хати (сервер каже, яка вона зараз). */
fun pal(id: String, hata: String? = null): Pal {
    val real = if (id == "hata") hata ?: "chai" else id
    return PALS.firstOrNull { it.id == real } ?: PALS[0]
}

val LocalPal = staticCompositionLocalOf { PALS[0] }

object Fonts {
    val display = FontFamily(
        Font(R.font.inter_display_extrabold, FontWeight.ExtraBold),
        Font(R.font.inter_display_bold, FontWeight.Bold),
    )
    val mono = FontFamily(
        Font(R.font.dejavu_mono, FontWeight.Normal),
        Font(R.font.dejavu_mono_bold, FontWeight.Bold),
    )
}

/** Заголовки: Inter Display, щільно, як на сайті. */
fun display(size: TextUnit, weight: FontWeight = FontWeight.ExtraBold) =
    TextStyle(fontFamily = Fonts.display, fontWeight = weight, fontSize = size, lineHeight = size * 1.08f, letterSpacing = (-0.025).em)

/** Термінальний моноширинний шрифт: промпти, кнопки, чипи, час. */
fun mono(size: TextUnit, weight: FontWeight = FontWeight.Normal) =
    TextStyle(fontFamily = Fonts.mono, fontWeight = weight, fontSize = size, lineHeight = size * 1.35f)

/** Звичайний текст: системний шрифт Android (на сайті з телефона так само). */
fun body(size: TextUnit = 15.sp, weight: FontWeight = FontWeight.Normal) =
    TextStyle(fontWeight = weight, fontSize = size, lineHeight = size * 1.42f)

@Composable
fun VidBoxTheme(p: Pal, content: @Composable () -> Unit) {
    val scheme = if (p.light) androidx.compose.material3.lightColorScheme(
        primary = p.acc, onPrimary = p.on, secondary = p.acc2, onSecondary = p.on,
        background = p.bg, onBackground = p.fg, surface = p.bg2, onSurface = p.fg,
        surfaceVariant = p.bg3, onSurfaceVariant = p.mute, outline = p.line, outlineVariant = p.line,
        surfaceContainer = p.bg2, surfaceContainerHigh = p.bg3, surfaceContainerHighest = p.bg3,
        surfaceContainerLow = p.bg2, surfaceContainerLowest = p.bg,
    ) else darkColorScheme(
        primary = p.acc, onPrimary = p.on, secondary = p.acc2, onSecondary = p.on,
        background = p.bg, onBackground = p.fg, surface = p.bg2, onSurface = p.fg,
        surfaceVariant = p.bg3, onSurfaceVariant = p.mute, outline = p.line, outlineVariant = p.line,
        surfaceContainer = p.bg2, surfaceContainerHigh = p.bg3, surfaceContainerHighest = p.bg3,
        surfaceContainerLow = p.bg2, surfaceContainerLowest = p.bg,
    )
    CompositionLocalProvider(LocalPal provides p) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
