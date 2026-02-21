"""Tests for pipeline.link_entities.is_linkable_entity() — second-level entity filter."""

from pipeline.link_entities import is_linkable_entity


class TestIsLinkableEntity:
    # --- Basic rejections ---
    def test_empty(self):
        assert not is_linkable_entity("")
        assert not is_linkable_entity("   ")

    def test_single_char(self):
        assert not is_linkable_entity("x")

    # --- Whitelist bypass ---
    def test_whitelisted(self):
        for term in ("ai", "api", "sdk", "llm", "rdf", "git", "mcp", "go"):
            assert is_linkable_entity(term), f"'{term}' should pass whitelist"

    # --- Filenames ---
    def test_filename_py(self):
        assert not is_linkable_entity("server.py")

    def test_filename_json(self):
        assert not is_linkable_entity("config.json")

    def test_filename_ts(self):
        assert not is_linkable_entity("auth-utils.ts")

    def test_filename_exe(self):
        assert not is_linkable_entity("program.exe")

    # --- Special char prefixes ---
    def test_hash_prefix(self):
        assert not is_linkable_entity("#ff0000")

    def test_at_prefix(self):
        assert not is_linkable_entity("@radix-ui")

    def test_dollar_prefix(self):
        assert not is_linkable_entity("$HOME")

    def test_cli_flag(self):
        assert not is_linkable_entity("--verbose")

    def test_dot_prefix(self):
        assert not is_linkable_entity(".gitignore")

    # --- Numeric prefixes ---
    def test_numeric_prefix(self):
        assert not is_linkable_entity("3 files")

    # --- Version strings ---
    def test_version(self):
        assert not is_linkable_entity("2.5.1")

    def test_decimal_start(self):
        assert not is_linkable_entity("0.75")

    # --- Two-char noise ---
    def test_two_char_noise(self):
        assert not is_linkable_entity("bp")
        assert not is_linkable_entity("zz")

    def test_two_char_whitelisted(self):
        assert is_linkable_entity("ai")
        assert is_linkable_entity("js")

    # --- Brackets ---
    def test_brackets(self):
        assert not is_linkable_entity("arr[0]")

    # --- Parentheses ---
    def test_parens(self):
        assert not is_linkable_entity("func()")

    # --- npm scoped packages ---
    def test_npm_scope(self):
        assert not is_linkable_entity("@types/node")

    # --- CSS dimensions ---
    def test_css_dim(self):
        assert not is_linkable_entity("100px")
        assert not is_linkable_entity("50vh")

    # --- Percentages ---
    def test_percent(self):
        assert not is_linkable_entity("50%")

    # --- Paths ---
    def test_multi_segment_path(self):
        assert not is_linkable_entity("src/components/auth")

    def test_simple_path(self):
        assert not is_linkable_entity("pipeline/common")

    # --- Medical / ICD codes ---
    def test_icd_code(self):
        assert not is_linkable_entity("a021")
        assert not is_linkable_entity("j45")

    def test_icd_underscore(self):
        assert not is_linkable_entity("ansied_022_001")

    # --- snake_case 3+ segments ---
    def test_snake_3seg(self):
        assert not is_linkable_entity("anthropic_api_key")

    # --- Protocol codes ---
    def test_protocol_code(self):
        assert not is_linkable_entity("dengue_008")

    # --- Glob patterns ---
    def test_glob(self):
        assert not is_linkable_entity("*.py")

    # --- Pure numeric ---
    def test_pure_number(self):
        assert not is_linkable_entity("42")
        assert not is_linkable_entity("3.14")

    # --- Config-like (key=value) ---
    def test_config_like(self):
        assert not is_linkable_entity("key=value")

    # --- Quoted strings ---
    def test_single_quoted(self):
        assert not is_linkable_entity("'hello'")

    def test_double_quoted(self):
        assert not is_linkable_entity('"world"')

    # --- Dimension patterns ---
    def test_dimension(self):
        assert not is_linkable_entity("1920x1080")

    # --- Lone punctuation ---
    def test_percent_char_prefix(self):
        assert not is_linkable_entity("% something")

    # --- Valid entities that should pass ---
    def test_valid_entities(self):
        valid = [
            "neo4j", "python", "docker", "kubernetes",
            "graph database", "knowledge graph",
            "claude", "langchain", "fuseki",
            "wikidata", "sparql", "cypher",
        ]
        for entity in valid:
            assert is_linkable_entity(entity), f"'{entity}' should be linkable"
