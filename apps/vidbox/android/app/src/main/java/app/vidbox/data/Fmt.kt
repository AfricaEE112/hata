package app.vidbox.data

import java.time.LocalDate
import java.time.format.TextStyle
import java.util.Locale
import kotlin.math.floor
import kotlin.math.roundToInt
import kotlin.math.roundToLong

/** Ті самі підписи, що й на сайті. */
object Fmt {
    private val uk = Locale("uk")

    fun dur(sec: Double): String {
        if (!(sec > 0) || sec.isInfinite()) return "0:00"
        val s = sec.roundToLong()
        val h = s / 3600
        val m = s % 3600 / 60
        val x = s % 60
        return (if (h > 0) "$h:" + m.toString().padStart(2, '0') else "$m") + ":" + x.toString().padStart(2, '0')
    }

    fun len(sec: Double): String {
        if (!(sec > 0)) return ""
        val h = floor(sec / 3600).toInt()
        val m = (sec % 3600 / 60).roundToInt()
        return when {
            h > 0 -> "$h год $m хв"
            m > 0 -> "$m хв"
            else -> "${sec.roundToInt()} с"
        }
    }

    fun size(b: Long): String = when {
        b <= 0 -> ""
        b >= 1099511627776 -> String.format(uk, "%.2f ТБ", b / 1099511627776.0)
        b >= 1073741824 -> String.format(uk, "%.1f ГБ", b / 1073741824.0)
        b >= 1048576 -> "${(b / 1048576.0).roundToInt()} МБ"
        else -> "${maxOf(1, (b / 1024.0).roundToInt())} КБ"
    }

    fun ago(ts: Double): String {
        if (ts <= 0) return "ніколи"
        val d = (System.currentTimeMillis() / 1000.0 - ts) / 86400
        return when {
            d < 1.0 / 24 -> "щойно"
            d < 1 -> "${(d * 24).roundToInt()} год тому"
            d < 2 -> "вчора"
            d < 30 -> "${d.roundToInt()} дн. тому"
            d < 365 -> "${(d / 30).roundToInt()} міс. тому"
            else -> "${(d / 365).roundToInt()} р. тому"
        }
    }

    fun date(ts: Double): String {
        if (ts <= 0) return ""
        val d = java.time.Instant.ofEpochSecond(ts.toLong()).atZone(java.time.ZoneId.systemDefault()).toLocalDate()
        return "${d.dayOfMonth} ${month(d)} ${d.year}"
    }

    private fun month(d: LocalDate) = d.month.getDisplayName(TextStyle.FULL, uk)

    /** «9–15 листопада» для підбірки тижня. */
    fun weekRange(start: String, end: String): String = try {
        val a = LocalDate.parse(start)
        val b = LocalDate.parse(end)
        if (a.month == b.month) "${a.dayOfMonth}–${b.dayOfMonth} ${month(b)}" else "${a.dayOfMonth} ${month(a)} – ${b.dayOfMonth} ${month(b)}"
    } catch (e: Exception) {
        ""
    }

    fun plural(n: Int, a: String, b: String, c: String): String {
        val m10 = n % 10
        val m100 = n % 100
        return if (m10 == 1 && m100 != 11) a else if (m10 in 2..4 && (m100 < 10 || m100 >= 20)) b else c
    }

    fun views(n: Int) = "$n " + plural(n, "перегляд", "перегляди", "переглядів")
    fun videos(n: Int) = "$n відео"
    fun pct(x: Double?) = ((x ?: 0.0) * 100).roundToInt()

    fun shortFolder(f: String): String {
        val p = f.split('/')
        return if (p.size > 1) p.drop(1).joinToString(" / ") else f
    }

    fun uptime(sec: Long): String {
        val d = sec / 86400
        val h = sec % 86400 / 3600
        val m = sec % 3600 / 60
        return listOfNotNull(if (d > 0) "$d дн" else null, if (h > 0) "$h год" else null, "$m хв").joinToString(" ")
    }
}
