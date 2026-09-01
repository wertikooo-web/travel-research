"""Regression coverage for a real model quirk observed live: forced tool-use
occasionally wraps the whole payload under one extra key (e.g.
{"trip_brief": {...fields...}}) instead of emitting the schema's fields at
the top level. Unhandled, that silently validates to an all-null/empty
result instead of raising — worse than an error, a wrong-looking success.
"""

from app.llm.anthropic_provider import _unwrap_if_nested as unwrap_brief
from app.llm.candidate_provider import _unwrap_if_nested as unwrap_candidates
from app.llm.provider import deep_json_decode, unwrap_self_nested_keys


def test_unwrap_brief_passthrough_when_fields_already_present():
    data = {"travellers": [], "origin": None}
    assert unwrap_brief(data) == data


def test_unwrap_brief_unwraps_single_extra_wrapper_key():
    inner = {"travellers": [{"type": "adult"}], "budget": {"max_total": 100}}
    wrapped = {"trip_brief": inner}
    assert unwrap_brief(wrapped) == inner


def test_unwrap_brief_leaves_unrecognized_multi_key_payload_alone():
    data = {"foo": 1, "bar": 2}
    assert unwrap_brief(data) == data


def test_unwrap_candidates_passthrough_when_key_present():
    data = {"candidates": []}
    assert unwrap_candidates(data) == data


def test_unwrap_candidates_unwraps_single_extra_wrapper_key():
    inner = {"candidates": [{"destination_name": "Tenerife"}]}
    wrapped = {"result": inner}
    assert unwrap_candidates(wrapped) == inner


def test_deep_json_decode_handles_top_level_string():
    assert deep_json_decode('{"travellers": []}') == {"travellers": []}


def test_deep_json_decode_handles_a_single_field_stringified():
    # observed live: top-level keys were correct, but the "travellers" value
    # itself was a JSON-encoded string instead of a native list
    data = {
        "travellers": '{"travellers":[{"type":"adult","travel_passport":"RO"}]}',
        "budget": {"max_total": 4000},
    }
    decoded = deep_json_decode(data)
    assert decoded["budget"] == {"max_total": 4000}
    assert decoded["travellers"] == {"travellers": [{"type": "adult", "travel_passport": "RO"}]}


def test_deep_json_decode_leaves_plain_strings_alone():
    data = {"text": "Кишинёв", "note": "not json"}
    assert deep_json_decode(data) == data


def test_unwrap_self_nested_collapses_field_wrapped_under_its_own_name():
    # observed live: {"travellers": {"travellers": [...]}} instead of {"travellers": [...]}
    data = {"travellers": {"travellers": [{"type": "adult"}]}, "budget": {"max_total": 100}}
    assert unwrap_self_nested_keys(data) == {"travellers": [{"type": "adult"}], "budget": {"max_total": 100}}


def test_unwrap_self_nested_does_not_touch_legitimate_single_key_objects():
    # {"visa": {"easy_required": null}} must survive untouched — "easy_required" != "visa"
    data = {"visa": {"easy_required": None}}
    assert unwrap_self_nested_keys(data) == data
