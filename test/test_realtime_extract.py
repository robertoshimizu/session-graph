"""Tests for pipeline.realtime_extract — transcript parsing and watermarking."""

import json

from pipeline.realtime_extract import (
    extract_last_assistant_text,
    _message_hash,
    is_already_processed,
    mark_processed,
)


class TestExtractLastAssistantText:
    def test_extracts_last_assistant(self, tmp_path, sample_jsonl_content):
        f = tmp_path / "transcript.jsonl"
        f.write_text(sample_jsonl_content)
        text, ts = extract_last_assistant_text(str(f))
        # Last assistant message is "You're welcome!"
        assert text == "You're welcome!"
        assert ts == "2026-02-20T10:01:00Z"

    def test_handles_string_content_blocks(self, tmp_path):
        lines = [
            {"type": "assistant", "message": {
                "content": ["Hello from string block"],
                "timestamp": "2026-01-01T00:00:00Z",
            }},
        ]
        f = tmp_path / "transcript.jsonl"
        f.write_text("\n".join(json.dumps(entry) for entry in lines))
        text, ts = extract_last_assistant_text(str(f))
        assert text == "Hello from string block"

    def test_returns_none_on_empty(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        text, ts = extract_last_assistant_text(str(f))
        assert text is None
        assert ts is None

    def test_returns_none_on_user_only(self, tmp_path):
        lines = [
            {"type": "user", "message": {"content": [{"type": "text", "text": "Hello"}]}},
        ]
        f = tmp_path / "transcript.jsonl"
        f.write_text("\n".join(json.dumps(entry) for entry in lines))
        text, ts = extract_last_assistant_text(str(f))
        assert text is None

    def test_skips_invalid_json_lines(self, tmp_path):
        content = 'not json\n{"type":"assistant","message":{"content":[{"type":"text","text":"valid"}],"timestamp":"2026-01-01T00:00:00Z"}}'
        f = tmp_path / "transcript.jsonl"
        f.write_text(content)
        text, ts = extract_last_assistant_text(str(f))
        assert text == "valid"

    def test_multiple_text_blocks_joined(self, tmp_path):
        lines = [
            {"type": "assistant", "message": {
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "text", "text": "Part 2"},
                ],
            }},
        ]
        f = tmp_path / "transcript.jsonl"
        f.write_text("\n".join(json.dumps(entry) for entry in lines))
        text, _ = extract_last_assistant_text(str(f))
        assert text == "Part 1\nPart 2"


class TestMessageHash:
    def test_deterministic(self):
        assert _message_hash("hello") == _message_hash("hello")

    def test_different_for_different_input(self):
        assert _message_hash("hello") != _message_hash("world")

    def test_length_16(self):
        assert len(_message_hash("test")) == 16


class TestWatermarking:
    def test_not_processed_initially(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pipeline.realtime_extract.WATERMARK_DIR", tmp_path)
        assert not is_already_processed("sess-001", "some text")

    def test_mark_then_check(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pipeline.realtime_extract.WATERMARK_DIR", tmp_path)
        mark_processed("sess-001", "some text")
        assert is_already_processed("sess-001", "some text")

    def test_different_text_not_processed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pipeline.realtime_extract.WATERMARK_DIR", tmp_path)
        mark_processed("sess-001", "some text")
        assert not is_already_processed("sess-001", "different text")

    def test_different_session_not_processed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pipeline.realtime_extract.WATERMARK_DIR", tmp_path)
        mark_processed("sess-001", "some text")
        assert not is_already_processed("sess-002", "some text")

    def test_watermark_file_created(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pipeline.realtime_extract.WATERMARK_DIR", tmp_path)
        mark_processed("sess-001", "test")
        wm_file = tmp_path / ".watermark-sess-001"
        assert wm_file.exists()
        assert wm_file.read_text().strip() == _message_hash("test")
