package ai.echo.app.data

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable data class AuthUser(val id: String, val email: String? = null, val name: String? = null)

@Serializable data class AuthSession(
    val access_token: String,
    val refresh_token: String,
    val expires_at: Long? = null,
    val expires_in: Long? = null,
    val user: AuthUser,
)

@Serializable data class SegmentMeta(
    val segment_id: String,
    val sha256: String,
    val duration_ms: Int,
    val started_at: String,
    val source: String,
    val sample_rate: Int = 16000,
    val speech_ratio: Double? = null,
    val session_hint: String? = null,
    val pinned: Boolean = false,
    val device_id: String? = null,
    val lat: Double? = null,
    val lng: Double? = null,
    val accuracy_m: Double? = null,
    val locality: String? = null,
    val content_type: String = "audio/ogg",
)

@Serializable data class SegmentResult(val segment_id: String, val status: String)

@Serializable data class Status(
    val speech_minutes_today: Double = 0.0,
    val asks_today: Int = 0,
    val segments_pending: Int = 0,
    val conversations_processing: Int = 0,
    val last_upload_at: String? = null,
    val memories: Int = 0,
    val open_commitments: Int = 0,
    val people: Int = 0,
    val voice_enrolled: Boolean = false,
)

@Serializable data class Evidence(
    val utterance_id: String,
    val quote_native: String? = null,
    val quote_en: String? = null,
    val speaker: String? = null,
    val segment_id: String? = null,
    val start_ms: Int? = null,
)

@Serializable data class Citation(
    val id: String,
    val kind: String,
    val type: String,
    val content: String,
    val content_native: String? = null,
    val captured_at: String,
    val conversation_id: String? = null,
    val superseded: Boolean = false,
    val evidence: List<Evidence> = emptyList(),
)

@Serializable data class AskResponse(
    val ask_id: String,
    val answer: String,
    val answer_language: String,
    val citations: List<Citation> = emptyList(),
    val tts_url: String? = null,
    val transcript: String? = null,
    val latency_ms: Int = 0,
)

@Serializable data class AskRequest(val query: String, val language: String? = null, val speak: Boolean = false)

@Serializable data class MemoryBrief(val id: String, val type: String, val content: String, val importance: Double = 0.5, val pinned: Boolean = false)

@Serializable data class PersonRef(val id: String, val name: String)

@Serializable data class TimelineItem(
    val id: String,
    val started_at: String,
    val ended_at: String? = null,
    val status: String,
    val title: String,
    val summary: String? = null,
    val languages: List<String> = emptyList(),
    val pinned: Boolean = false,
    val in_transit: Boolean = false,
    val speaker_count: Int? = null,
    val place: String? = null,
    val people: List<PersonRef> = emptyList(),
    val memories: List<MemoryBrief> = emptyList(),
    val memory_count: Int = 0,
)

@Serializable data class Timeline(val items: List<TimelineItem>, val next_before: String? = null)

@Serializable data class SpeakerRef(val id: String? = null, val label: String? = null, val is_user: Boolean? = null)

@Serializable data class EvidenceDetail(
    val utterance_id: String,
    val quote_native: String? = null,
    val quote_en: String? = null,
    val language: String? = null,
    val speaker: SpeakerRef = SpeakerRef(),
    val spoken_at: String? = null,
    val start_ms: Int? = null,
    val end_ms: Int? = null,
    val audio_url: String? = null,
)

@Serializable data class EntityRef(val id: String, val kind: String, val name: String, val role: String)
@Serializable data class LinkRef(val kind: String, val direction: String, val memory_id: String, val content: String, val captured_at: String? = null)
@Serializable data class ConversationRef(val id: String? = null, val title: String? = null, val started_at: String? = null)
@Serializable data class CommitmentRef(val owner: String, val action: String, val due_at: String? = null, val status: String)

@Serializable data class MemoryDetail(
    val id: String,
    val type: String,
    val content: String,
    val content_native: String? = null,
    val importance: Double,
    val confidence: Double,
    val pinned: Boolean,
    val sensitivity: List<String> = emptyList(),
    val captured_at: String,
    val time_start: String? = null,
    val place: String? = null,
    val superseded_by: String? = null,
    val conversation: ConversationRef = ConversationRef(),
    val evidence: List<EvidenceDetail> = emptyList(),
    val entities: List<EntityRef> = emptyList(),
    val links: List<LinkRef> = emptyList(),
    val commitment: CommitmentRef? = null,
)

@Serializable data class ConvSpeaker(val id: String, val label: String, val is_user: Boolean, val person_id: String? = null)
@Serializable data class ConvUtterance(
    val id: String,
    val text_native: String,
    val text_en: String? = null,
    val language: String? = null,
    val speaker: SpeakerRef = SpeakerRef(),
    val spoken_at: String? = null,
    val start_ms: Int = 0,
    val provisional: Boolean = false,
)
@Serializable data class ConvSegment(val id: String, val started_at: String, val duration_ms: Int, val audio_url: String? = null)

@Serializable data class ConversationDetail(
    val id: String,
    val title: String? = null,
    val summary: String? = null,
    val status: String,
    val started_at: String,
    val place: String? = null,
    val languages: List<String> = emptyList(),
    val speakers: List<ConvSpeaker> = emptyList(),
    val utterances: List<ConvUtterance> = emptyList(),
    val segments: List<ConvSegment> = emptyList(),
    val memories: List<MemoryBrief> = emptyList(),
)

@Serializable data class Commitment(
    val memory_id: String,
    val owner: String,
    val action: String,
    val content: String,
    val counterparty: String? = null,
    val due_at: String? = null,
    val status: String,
    val captured_at: String? = null,
)
@Serializable data class Commitments(val items: List<Commitment>)

@Serializable data class Person(
    val id: String, val name: String, val summary: String? = null, val last_interaction_at: String? = null,
    val interactions: Int = 0, val open_commitments: Int = 0,
)
@Serializable data class People(val items: List<Person>)

@Serializable data class Reminder(
    val id: String, val kind: String, val title: String, val body: String? = null, val fire_at: String,
    val status: String, val commitment_id: String? = null,
)
@Serializable data class DigestRef(val id: String, val day: String)
@Serializable data class SyncResponse(val cursor: String, val server_time: String, val reminders: List<Reminder>, val latest_digest: DigestRef? = null)

@Serializable data class Digest(val id: String, val day: String, val content: String)
@Serializable data class DigestEnvelope(val digest: Digest? = null)

@Serializable data class ServerSettings(
    val display_name: String? = null,
    val timezone: String = "Asia/Kolkata",
    val answer_language: String = "en-IN",
    val audio_retention_days: Int? = null,
    val retention_forever: Boolean = false,
    val quiet_hours: List<JsonElement> = emptyList(),
    val earbud_policy: String = "when_no_media",
    val location_enabled: Boolean = true,
    val daily_digest_time: String = "21:00",
    val speech_cap_min_per_day: Int = 360,
    val email: String? = null,
)
