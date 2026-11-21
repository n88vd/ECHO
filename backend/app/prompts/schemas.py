MEMORY_TYPES = ["fact", "event", "commitment", "decision", "idea", "learning", "object_location", "person_info", "question"]
SENSITIVITY = ["pii", "financial", "health", "credential"]


def _obj(props: dict, nullable: bool = False) -> dict:
    o = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    return {"anyOf": [o, {"type": "null"}]} if nullable else o


_S = {"type": "string"}
_SA = {"type": "array", "items": _S}
_N = {"type": "number"}
_B = {"type": "boolean"}

UNDERSTAND = _obj({
    "title_en": _S,
    "summary_en": _S,
    "topics": _SA,
    "remember_this": _B,
    "utterances_en": {"type": "array", "items": _obj({"id": _S, "text_en": _S})},
    "memories": {
        "type": "array",
        "items": _obj({
            "type": {"type": "string", "enum": MEMORY_TYPES},
            "content_en": _S,
            "content_native": _S,
            "evidence_utterance_ids": _SA,
            "subject": _S,
            "people": _SA,
            "places": _SA,
            "objects": _SA,
            "topics": _SA,
            "time_ref_text": _S,
            "resolved_start": _S,
            "resolved_end": _S,
            "commitment": _obj(
                {"owner": {"type": "string", "enum": ["user", "other"]}, "counterparty": _S, "action": _S, "due": _S},
                nullable=True,
            ),
            "decision": _obj({"choice": _S, "rationale": _S, "alternatives": _SA}, nullable=True),
            "importance": _N,
            "confidence": _N,
            "sensitivity": {"type": "array", "items": {"type": "string", "enum": SENSITIVITY}},
        }),
    },
})

QUERY_PARSE = _obj({
    "query_en": _S,
    "language": _S,
    "intent": {"type": "string", "enum": ["recall", "list", "summary", "chitchat", "unknown"]},
    "people": _SA,
    "objects": _SA,
    "memory_types": {"type": "array", "items": {"type": "string", "enum": MEMORY_TYPES}},
    "time_from": _S,
    "time_to": _S,
    "wants_latest": _B,
})

RERANK = _obj({"ranked_ids": _SA})

COMMITMENT_CHECK = _obj({"resolved": {"type": "array", "items": _obj({"commitment_id": _S, "evidence_utterance_id": _S})}})
