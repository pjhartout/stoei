"""Unit tests for the expand_nodelist() function in stoei.slurm.nodelist."""

from stoei.slurm.nodelist import expand_nodelist


class TestExpandNodelist:
    """Tests for expand_nodelist()."""

    def test_plain_hostname(self) -> None:
        """Single plain hostname returns a one-element set."""
        assert expand_nodelist("node01") == {"node01"}

    def test_simple_range(self) -> None:
        """Bracket range expands to all hostnames in the range."""
        assert expand_nodelist("node[01-04]") == {"node01", "node02", "node03", "node04"}

    def test_bracket_comma_list(self) -> None:
        """Comma-separated list inside brackets expands correctly."""
        assert expand_nodelist("node[01,03,05]") == {"node01", "node03", "node05"}

    def test_mixed_range_and_list_in_brackets(self) -> None:
        """Mixed range and explicit indices inside brackets."""
        assert expand_nodelist("node[01-03,07]") == {
            "node01",
            "node02",
            "node03",
            "node07",
        }

    def test_plain_comma_separated(self) -> None:
        """Comma-separated plain hostnames without brackets."""
        assert expand_nodelist("node01,node02") == {"node01", "node02"}

    def test_mixed_plain_and_bracket(self) -> None:
        """Mix of plain hostname and bracket expression."""
        assert expand_nodelist("node01,node[03-05]") == {
            "node01",
            "node03",
            "node04",
            "node05",
        }

    def test_multiple_bracket_groups(self) -> None:
        """Two separate bracket groups with different prefixes."""
        assert expand_nodelist("gpu[01-02],cpu[01-02]") == {
            "gpu01",
            "gpu02",
            "cpu01",
            "cpu02",
        }

    def test_zero_padded_range(self) -> None:
        """Zero-padded ranges preserve padding width."""
        assert expand_nodelist("node[001-003]") == {"node001", "node002", "node003"}

    def test_single_element_range(self) -> None:
        """A range where start == end yields one hostname."""
        assert expand_nodelist("node[05-05]") == {"node05"}

    def test_unpadded_range(self) -> None:
        """Range without zero-padding expands correctly."""
        assert expand_nodelist("node[8-10]") == {"node8", "node9", "node10"}

    def test_empty_string(self) -> None:
        """Empty input returns empty set."""
        assert expand_nodelist("") == set()

    def test_whitespace_only(self) -> None:
        """Whitespace-only input returns empty set."""
        assert expand_nodelist("   ") == set()

    def test_pending_none(self) -> None:
        """'(None)' placeholder from PENDING jobs returns empty set."""
        assert expand_nodelist("(None)") == set()

    def test_pending_resources(self) -> None:
        """'(Resources)' placeholder from PENDING jobs returns empty set."""
        assert expand_nodelist("(Resources)") == set()

    def test_pending_priority(self) -> None:
        """'(Priority)' placeholder from PENDING jobs returns empty set."""
        assert expand_nodelist("(Priority)") == set()

    def test_pending_any_paren(self) -> None:
        """Any string starting with '(' is treated as a PENDING placeholder."""
        assert expand_nodelist("(AssocMaxJobsLimit)") == set()

    def test_truncated_open_bracket(self) -> None:
        """Truncated expression with unclosed bracket returns empty set gracefully."""
        result = expand_nodelist("node[01-")
        assert result == set()

    def test_deduplication_same_node_multiple_groups(self) -> None:
        """Overlapping node groups deduplicate correctly."""
        result = expand_nodelist("node[01-03],node[02-04]")
        assert result == {"node01", "node02", "node03", "node04"}

    def test_large_range(self) -> None:
        """Larger ranges are handled correctly."""
        result = expand_nodelist("node[01-10]")
        expected = {f"node{str(i).zfill(2)}" for i in range(1, 11)}
        assert result == expected
