"""Tests for pipeline.triple_extraction — entity validation, normalization, and parsing."""

import json

from pipeline.triple_extraction import (
    is_valid_entity,
    normalize_entity,
    normalize_predicate,
    normalize_triple,
    _is_truncated,
    _salvage_truncated_json,
    _parse_triples_response,
    PREDICATE_VOCABULARY,
)


# ---- is_valid_entity() ----

class TestIsValidEntity:
    # --- Basic rejections ---
    def test_empty(self):
        assert not is_valid_entity("")

    def test_single_char(self):
        assert not is_valid_entity("x")

    def test_stopwords(self):
        for sw in ("exit", "yes", "no", "null", "undefined", "true", "false"):
            assert not is_valid_entity(sw), f"Stopword '{sw}' should be rejected"

    # --- Whitelist bypass ---
    def test_whitelisted_short_terms(self):
        for term in ("ai", "api", "sdk", "llm", "rdf", "mcp", "git", "go", "js"):
            assert is_valid_entity(term), f"Whitelisted term '{term}' should pass"

    # --- Special character prefixes ---
    def test_hex_color(self):
        assert not is_valid_entity("#ff0000")

    def test_npm_scope(self):
        assert not is_valid_entity("@radix-ui/react-dialog")

    def test_dollar_prefix(self):
        assert not is_valid_entity("$PATH")

    def test_glob_pattern(self):
        assert not is_valid_entity("*.ts")

    def test_dotfile(self):
        assert not is_valid_entity(".env")

    def test_cli_flag(self):
        assert not is_valid_entity("--verbose")

    def test_colon_prefix(self):
        assert not is_valid_entity(":3000")

    def test_tilde_prefix(self):
        assert not is_valid_entity("~/.config")

    # --- Paths ---
    def test_unix_path(self):
        assert not is_valid_entity("/usr/bin/python")

    def test_windows_path(self):
        assert not is_valid_entity("C:\\Users\\test")

    # --- Filenames ---
    def test_python_file(self):
        assert not is_valid_entity("__init__.py")

    def test_config_json(self):
        assert not is_valid_entity("config.json")

    def test_auth_utils_ts(self):
        assert not is_valid_entity("auth-utils.ts")

    def test_dockerfile_not_filename(self):
        # "dockerfile" has no extension, should pass
        assert is_valid_entity("dockerfile")

    # --- Medical / ICD codes ---
    def test_icd_code_short(self):
        assert not is_valid_entity("a021")

    def test_icd_code_decimal(self):
        assert not is_valid_entity("k25.0")

    def test_icd_underscore(self):
        assert not is_valid_entity("ansied_022_001")

    # --- Protocol codes ---
    def test_protocol_code(self):
        assert not is_valid_entity("cefaleia_007")

    # --- snake_case identifiers ---
    def test_snake_case_3seg(self):
        assert not is_valid_entity("anthropic_api_key")

    def test_snake_case_2seg_passes(self):
        # 2-segment snake_case should pass (not caught by 3+ filter)
        # but may be caught by other filters depending on content
        assert is_valid_entity("knowledge_graph")

    # --- Numeric prefixes ---
    def test_numeric_prefix(self):
        assert not is_valid_entity("0 bytes data")

    # --- Version strings ---
    def test_version_string(self):
        assert not is_valid_entity("5.0.0")

    def test_decimal_confidence(self):
        assert not is_valid_entity("0.75 confidence")

    # --- Dimensions ---
    def test_px_dimension(self):
        assert not is_valid_entity("1400px")

    def test_css_dimension_in_phrase(self):
        assert not is_valid_entity("height 280px")

    # --- Pure numbers ---
    def test_pure_number(self):
        assert not is_valid_entity("42")

    # --- IP addresses ---
    def test_ip_address(self):
        assert not is_valid_entity("192.168.1.1")

    # --- Duration/measurement ---
    def test_duration(self):
        assert not is_valid_entity("120 seconds")

    def test_measurement_mb(self):
        assert not is_valid_entity("500ms")

    # --- Hex / git hashes ---
    def test_hex_hash(self):
        assert not is_valid_entity("7f9ef80")

    # --- Quantity phrases ---
    def test_quantity(self):
        assert not is_valid_entity("80 tests")

    # --- Ordinal phrases ---
    def test_ordinal(self):
        assert not is_valid_entity("7th character")

    # --- Fraction ---
    def test_fraction(self):
        assert not is_valid_entity("3/4")

    # --- Percentage ---
    def test_percentage(self):
        assert not is_valid_entity("50% discount")

    # --- Brackets ---
    def test_brackets(self):
        assert not is_valid_entity("candidates[0]")

    # --- Parentheses (function calls) ---
    def test_function_call(self):
        assert not is_valid_entity("express.json()")

    # --- Two-char ambiguous ---
    def test_two_char_noise(self):
        assert not is_valid_entity("bp")
        assert not is_valid_entity("ct")

    def test_two_char_whitelisted_passes(self):
        assert is_valid_entity("ai")
        assert is_valid_entity("db")

    # --- 4+ word phrases ---
    def test_four_word_phrase(self):
        assert not is_valid_entity("this is too long")

    def test_three_word_phrase_passes(self):
        assert is_valid_entity("graph query language")

    # --- Valid entities that should pass ---
    def test_valid_entities(self):
        valid = [
            "neo4j", "python", "docker", "kubernetes",
            "graph database", "knowledge graph", "triple store",
            "claude agent sdk",
        ]
        for entity in valid:
            assert is_valid_entity(entity), f"'{entity}' should be valid"


# ---- normalize_entity() ----

class TestNormalizeEntity:
    def test_lowercase(self):
        assert normalize_entity("Neo4j") == "neo4j"

    def test_strip_whitespace(self):
        assert normalize_entity("  python  ") == "python"

    def test_collapse_spaces(self):
        assert normalize_entity("graph   database") == "graph database"

    def test_strip_trailing_punctuation(self):
        assert normalize_entity("neo4j.") == "neo4j"
        assert normalize_entity("neo4j,") == "neo4j"
        assert normalize_entity("neo4j;") == "neo4j"
        assert normalize_entity("neo4j:") == "neo4j"

    def test_combined(self):
        assert normalize_entity("  Graph   Database.  ") == "graph database"


# ---- normalize_predicate() ----

class TestNormalizePredicate:
    def test_exact_match(self):
        for pred in PREDICATE_VOCABULARY:
            assert normalize_predicate(pred) == pred

    def test_snake_case_conversion(self):
        assert normalize_predicate("is_part_of") == "isPartOf"
        assert normalize_predicate("depends_on") == "dependsOn"
        assert normalize_predicate("built_with") == "builtWith"

    def test_space_separated(self):
        assert normalize_predicate("is part of") == "isPartOf"

    def test_hyphenated(self):
        assert normalize_predicate("depends-on") == "dependsOn"

    def test_case_insensitive(self):
        assert normalize_predicate("USES") == "uses"
        assert normalize_predicate("IsPartOf") == "isPartOf"

    def test_fallback_to_relatedTo(self):
        assert normalize_predicate("unknownPredicate") == "relatedTo"
        assert normalize_predicate("invented_by") == "relatedTo"

    def test_strips_whitespace(self):
        assert normalize_predicate("  uses  ") == "uses"


# ---- normalize_triple() ----

class TestNormalizeTriple:
    def test_normalizes_all_fields(self):
        result = normalize_triple({
            "subject": "  Neo4j  ",
            "predicate": "is_type_of",
            "object": "Graph Database.",
        })
        assert result == {
            "subject": "neo4j",
            "predicate": "isTypeOf",
            "object": "graph database",
        }


# ---- _is_truncated() ----

class TestIsTruncated:
    def test_empty_not_truncated(self):
        assert not _is_truncated("")
        assert not _is_truncated("  ")

    def test_complete_json_not_truncated(self):
        assert not _is_truncated('[{"subject":"a","predicate":"b","object":"c"}]')

    def test_missing_closing_bracket(self):
        assert _is_truncated('[{"subject":"a","predicate":"b","object":"c"}')

    def test_unmatched_braces(self):
        assert _is_truncated('[{"subject":"a","predicate":"b","object":"c"}, {"subject":')

    def test_trailing_comma(self):
        assert _is_truncated('[{"subject":"a","predicate":"b","object":"c"},')

    def test_trailing_colon(self):
        assert _is_truncated('{"key":')

    def test_trailing_quote(self):
        assert _is_truncated('[{"subject":"a","predicate":"b","object":"')

    def test_trailing_open_brace(self):
        assert _is_truncated('[{')


# ---- _salvage_truncated_json() ----

class TestSalvageTruncatedJson:
    def test_salvages_complete_objects(self):
        raw = '[{"subject":"neo4j","predicate":"uses","object":"cypher"}, {"subject":"py'
        result = _salvage_truncated_json(raw)
        assert result is not None
        assert len(result) == 1
        assert result[0]["subject"] == "neo4j"

    def test_salvages_multiple_objects(self):
        raw = '[{"subject":"a","predicate":"b","object":"c"},{"subject":"d","predicate":"e","object":"f"}, {"subject":"g","pred'
        result = _salvage_truncated_json(raw)
        assert result is not None
        assert len(result) == 2

    def test_returns_none_on_no_complete_objects(self):
        raw = '[{"subject":"neo'
        result = _salvage_truncated_json(raw)
        assert result is None

    def test_returns_none_on_empty(self):
        result = _salvage_truncated_json("")
        assert result is None


# ---- _parse_triples_response() ----

class TestParseTripleResponse:
    def test_valid_json_array(self):
        raw = json.dumps([
            {"subject": "Neo4j", "predicate": "uses", "object": "Cypher"},
        ])
        result = _parse_triples_response(raw)
        assert result is not None
        assert len(result) == 1
        assert result[0]["subject"] == "neo4j"  # normalized
        assert result[0]["predicate"] == "uses"

    def test_empty_array(self):
        result = _parse_triples_response("[]")
        assert result == []

    def test_dict_wrapper(self):
        raw = json.dumps({"triples": [
            {"subject": "Python", "predicate": "uses", "object": "pip"},
        ]})
        result = _parse_triples_response(raw)
        assert result is not None
        assert len(result) == 1

    def test_json_in_markdown_fences(self):
        raw = 'Here are the triples:\n```json\n[{"subject":"docker","predicate":"uses","object":"containers"}]\n```'
        result = _parse_triples_response(raw)
        assert result is not None
        assert len(result) == 1

    def test_filters_invalid_entities(self):
        raw = json.dumps([
            {"subject": "Neo4j", "predicate": "uses", "object": "Cypher"},
            {"subject": "__init__.py", "predicate": "isPartOf", "object": "project"},
        ])
        result = _parse_triples_response(raw)
        assert result is not None
        assert len(result) == 1  # filename entity filtered out

    def test_filters_incomplete_triples(self):
        raw = json.dumps([
            {"subject": "Neo4j", "predicate": "uses"},  # missing object
            {"subject": "Python", "predicate": "uses", "object": "pip"},
        ])
        result = _parse_triples_response(raw)
        assert result is not None
        assert len(result) == 1

    def test_max_10_triples(self):
        triples = [
            {"subject": f"tool{i}", "predicate": "uses", "object": f"lib{i}"}
            for i in range(15)
        ]
        raw = json.dumps(triples)
        result = _parse_triples_response(raw)
        assert result is not None
        assert len(result) == 10

    def test_returns_none_on_garbage(self):
        result = _parse_triples_response("this is not json at all")
        assert result is None

    def test_truncated_json_salvage(self):
        raw = '[{"subject":"neo4j","predicate":"uses","object":"cypher"},{"subject":"py'
        result = _parse_triples_response(raw)
        assert result is not None
        assert len(result) == 1
        assert result[0]["subject"] == "neo4j"

    def test_normalizes_predicates(self):
        raw = json.dumps([
            {"subject": "Docker", "predicate": "depends_on", "object": "Linux"},
        ])
        result = _parse_triples_response(raw)
        assert result is not None
        assert result[0]["predicate"] == "dependsOn"
