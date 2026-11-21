package ai.echo.app.ui

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

private val zone: ZoneId get() = ZoneId.systemDefault()
private val timeFmt = DateTimeFormatter.ofPattern("h:mm a")
private val dayFmt = DateTimeFormatter.ofPattern("EEE, d MMM")
private val fullFmt = DateTimeFormatter.ofPattern("d MMM yyyy, h:mm a")

fun parseInstant(s: String?): Instant? = s?.let { runCatching { Instant.parse(it) }.getOrNull() ?: runCatching { java.time.OffsetDateTime.parse(it).toInstant() }.getOrNull() }

fun timeOf(s: String?): String = parseInstant(s)?.atZone(zone)?.format(timeFmt) ?: ""
fun fullOf(s: String?): String = parseInstant(s)?.atZone(zone)?.format(fullFmt) ?: ""

fun dayLabel(s: String?): String {
    val d = parseInstant(s)?.atZone(zone)?.toLocalDate() ?: return ""
    val today = LocalDate.now(zone)
    return when (ChronoUnit.DAYS.between(d, today)) {
        0L -> "Today"
        1L -> "Yesterday"
        else -> d.format(dayFmt)
    }
}

fun relative(s: String?): String {
    val i = parseInstant(s) ?: return ""
    val mins = ChronoUnit.MINUTES.between(i, Instant.now())
    return when {
        mins < 1 -> "just now"
        mins < 60 -> "${mins}m ago"
        mins < 60 * 24 -> "${mins / 60}h ago"
        else -> dayLabel(s)
    }
}

fun greeting(): String {
    val h = java.time.LocalTime.now().hour
    return when {
        h < 12 -> "Good morning"
        h < 17 -> "Good afternoon"
        else -> "Good evening"
    }
}

private val citeRegex = Regex("\\[(m|u):([0-9a-f\\-]{8,36})]")

/** Replaces [m:id] markers with superscript numbers; returns text and ordered ids. */
fun renderCitations(text: String): Pair<String, List<String>> {
    val ids = mutableListOf<String>()
    val sup = "⁰¹²³⁴⁵⁶⁷⁸⁹"
    val out = citeRegex.replace(text) { m ->
        val id = m.groupValues[2]
        if (id !in ids) ids += id
        val n = (ids.indexOf(id) + 1).toString().map { sup[it - '0'] }.joinToString("")
        n
    }
    return out.replace(Regex("\\s+([⁰¹²³⁴⁵⁶⁷⁸⁹])"), "$1") to ids
}
