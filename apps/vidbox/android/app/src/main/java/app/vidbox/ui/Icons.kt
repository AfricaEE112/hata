package app.vidbox.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

/** Лінійні іконки з сайту (ті самі контури 24×24, лінія 1.8). */
object Ic {
    private fun circle(cx: Float, cy: Float, r: Float) = "M${cx - r} ${cy}a$r $r 0 1 0 ${2 * r} 0a$r $r 0 1 0 ${-2 * r} 0z"

    private fun rect(x: Float, y: Float, w: Float, h: Float, r: Float = 0f): String {
        if (r <= 0f) return "M$x ${y}h${w}v${h}h${-w}z"
        return "M${x + r} ${y}h${w - 2 * r}a$r $r 0 0 1 $r ${r}v${h - 2 * r}a$r $r 0 0 1 ${-r} ${r}h${-(w - 2 * r)}a$r $r 0 0 1 ${-r} ${-r}v${-(h - 2 * r)}a$r $r 0 0 1 $r ${-r}z"
    }

    private fun make(name: String, stroke: List<String>, fill: List<String> = emptyList()): ImageVector =
        ImageVector.Builder(name = name, defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = 24f, viewportHeight = 24f).apply {
            stroke.forEach {
                addPath(
                    pathData = addPathNodes(it), stroke = SolidColor(Color.Black), strokeLineWidth = 1.8f,
                    strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round,
                )
            }
            fill.forEach { addPath(pathData = addPathNodes(it), fill = SolidColor(Color.Black)) }
        }.build()

    val play = make("play", emptyList(), listOf("M7 4.5v15l12.5-7.5z"))
    val pause = make("pause", emptyList(), listOf(rect(6.5f, 4.5f, 4f, 15f, 1f), rect(13.5f, 4.5f, 4f, 15f, 1f)))
    val info = make("info", listOf(circle(12f, 12f, 9f), "M12 11v5.5M12 7.6v.2"))
    val close = make("close", listOf("M6 6l12 12M18 6 6 18"))
    val up = make("up", listOf("M7.5 10.5v9.5h-3.5v-9.5zM7.5 10.5 11 3.5c1.4 0 2.5 1.1 2.5 2.5v3h5a2 2 0 0 1 2 2.3l-1.1 6.9a2 2 0 0 1-2 1.8H7.5"))
    val down = make("down", listOf("M16.5 13.5V4H20v9.5zM16.5 13.5 13 20.5c-1.4 0-2.5-1.1-2.5-2.5v-3h-5a2 2 0 0 1-2-2.3l1.1-6.9a2 2 0 0 1 2-1.8h9.9"))
    val dice = make(
        "dice",
        listOf(rect(3.5f, 3.5f, 17f, 17f, 4f), circle(8.5f, 8.5f, .6f), circle(15.5f, 8.5f, .6f), circle(12f, 12f, .6f), circle(8.5f, 15.5f, .6f), circle(15.5f, 15.5f, .6f)),
    )
    val refresh = make("refresh", listOf("M20 12a8 8 0 1 1-2.4-5.7M20 4v5h-5"))
    val restart = make("restart", listOf("M4 12a8 8 0 1 0 2.4-5.7M4 4v5h5"))
    val left = make("left", listOf("m15 18-6-6 6-6"))
    val right = make("right", listOf("m9 18 6-6-6-6"))
    val next = make("next", listOf("M5.5 5v14l10-7zM18.5 5v14"))
    val chev = make("chev", listOf("m6 9 6 6 6-6"))
    val star = make("star", listOf("m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"))
    val arrDown = make("arrDown", listOf("M12 5v14M6.5 13.5 12 19l5.5-5.5"))
    val arrUp = make("arrUp", listOf("M12 19V5M6.5 10.5 12 5l5.5 5.5"))
    val grid = make("grid", listOf(rect(4f, 4f, 6.5f, 6.5f, 1.5f), rect(13.5f, 4f, 6.5f, 6.5f, 1.5f), rect(4f, 13.5f, 6.5f, 6.5f, 1.5f), rect(13.5f, 13.5f, 6.5f, 6.5f, 1.5f)))
    val folder = make("folder", listOf("M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"))
    val back10 = make("back10", listOf("M4.6 13a7.5 7.5 0 1 0 2.1-6.4M4.5 3.8v4h4"))
    val fwd10 = make("fwd10", listOf("M19.4 13a7.5 7.5 0 1 1-2.1-6.4M19.5 3.8v4h-4"))
    val pip = make("pip", listOf(rect(3f, 5f, 18f, 14f, 2f)), listOf(rect(12f, 11.5f, 7f, 5.5f, 1f)))
    val film = make("film", listOf(rect(3f, 4f, 18f, 16f, 2f), "M7.5 4v16M16.5 4v16M3 9h4.5M3 15h4.5M16.5 9H21M16.5 15H21"))
    val chip = make("chip", listOf(rect(6f, 6f, 12f, 12f, 2f), rect(9.5f, 9.5f, 5f, 5f, 1f), "M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"))
    val disk = make("disk", listOf("M4 6a8 3 0 1 0 16 0a8 3 0 1 0-16 0z", "M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"))
    val clock = make("clock", listOf(circle(12f, 12f, 8.5f), "M12 7.5V12l3 2"))
    val list = make("list", listOf("M9 6h11M9 12h11M9 18h11", "M4.5 5v2M4.5 11v2M4.5 17v2"))
    val search = make("search", listOf(circle(11f, 11f, 7f), "m20 20-3.5-3.5"))
    val sliders = make("sliders", listOf("M4 7h10M18 7h2M4 17h4M12 17h8", circle(16f, 7f, 2f), circle(10f, 17f, 2f)))
    val home = make("home", listOf("M3.5 10.5 12 3.5l8.5 7V20a1 1 0 0 1-1 1H15v-6H9v6H4.5a1 1 0 0 1-1-1z"))
    val bars = make("bars", listOf("M4 20v-6h5v6M9.5 20V7h5v13M15 20v-9h5v9M3 20.5h18"))
    val back = make("back", listOf("M19 12H5M11 6l-6 6 6 6"))
    val lock = make("lock", listOf(rect(5f, 10.5f, 14f, 10f, 2f), "M8 10.5V7.5a4 4 0 0 1 8 0v3"))
    val monitor = make("monitor", listOf(rect(3f, 4f, 18f, 12f, 2f), "M8 20h8M12 16v4"))
    val volume = make("volume", listOf("M4 9.5h3.5L12 6v12l-4.5-3.5H4z", "M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"))
    val sun = make("sun", listOf(circle(12f, 12f, 3.6f), "M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"))
    val speed = make("speed", listOf("M4.5 17a8 8 0 1 1 15 0", "M12 13.5l3.5-4.5"))
    val cc = make("cc", listOf(rect(3f, 5f, 18f, 14f, 2.5f), "M10.6 10.2A2.3 2.3 0 1 0 10.6 13.8", "M17.1 10.2A2.3 2.3 0 1 0 17.1 13.8"))
    val fit = make("fit", listOf("M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"))
    val rotate = make("rotate", listOf("M4.5 12a7.5 7.5 0 0 1 13-5.1M19.5 12a7.5 7.5 0 0 1-13 5.1M17.5 3.5v3.5H14M6.5 20.5V17H10"))
    val book = make("book", listOf("M12 6.5C10 5 7 4.5 3.5 5v13c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5V5C17 4.5 14 5 12 6.5zM12 6.5v13"))
    val anime = make("anime", listOf(rect(5f, 3f, 14f, 18f, 2f), "M5 16l4-4 3 3 2-2 5 5", circle(14.5f, 8f, 1.6f)))
    val check = make("check", listOf("M5 12.5l4.5 4.5L19 7"))
    val external = make("external", listOf("M14 5h5v5M19 5l-8 8M18 14v4a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 5 18V8a1.5 1.5 0 0 1 1.5-1.5h4"))
    val wifi = make("wifi", listOf("M3 9.5a13 13 0 0 1 18 0M6 13a8.5 8.5 0 0 1 12 0M9 16.5a4 4 0 0 1 6 0", circle(12f, 19.5f, .6f)))
}
