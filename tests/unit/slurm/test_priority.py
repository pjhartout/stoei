"""Tests for priority-related SLURM commands and parsers."""

from pathlib import Path

import pytest
from stoei.slurm.commands import get_fair_share_priority, get_pending_job_priority
from stoei.slurm.parser import parse_sprio_output, parse_sshare_output


class TestGetFairSharePriority:
    """Tests for get_fair_share_priority function."""

    def test_returns_entries_list(self, mock_slurm_path: Path) -> None:
        """Test that function returns a list of entries."""
        entries, error = get_fair_share_priority()

        assert error is None
        assert isinstance(entries, list)
        assert len(entries) > 0

    def test_entry_structure(self, mock_slurm_path: Path) -> None:
        """Test that each entry has the expected fields."""
        entries, error = get_fair_share_priority()

        assert error is None
        # Each entry should have 8 fields
        for entry in entries:
            assert len(entry) >= 8
            # Account is always present
            assert entry[0]  # Account should not be empty for any entry

    def test_includes_account_and_user_entries(self, mock_slurm_path: Path) -> None:
        """Test that both account-level and user-level entries are returned."""
        entries, error = get_fair_share_priority()

        assert error is None

        # Find account entries (empty user field)
        account_entries = [e for e in entries if not e[1].strip()]
        # Find user entries (non-empty user field)
        user_entries = [e for e in entries if e[1].strip()]

        assert len(account_entries) > 0
        assert len(user_entries) > 0


class TestGetPendingJobPriority:
    """Tests for get_pending_job_priority function."""

    def test_returns_entries_list(self, mock_slurm_path: Path) -> None:
        """Test that function returns a list of entries."""
        entries, error = get_pending_job_priority()

        assert error is None
        assert isinstance(entries, list)

    def test_entry_structure(self, mock_slurm_path: Path) -> None:
        """Test that each entry has the expected fields."""
        entries, error = get_pending_job_priority()

        assert error is None
        # Each entry should have 9 fields
        for entry in entries:
            assert len(entry) >= 9
            # JobID should be present
            assert entry[0]

    def test_entries_have_numeric_priority(self, mock_slurm_path: Path) -> None:
        """Test that priority values are numeric."""
        entries, error = get_pending_job_priority()

        assert error is None
        for entry in entries:
            # Priority is at index 3
            try:
                float(entry[3])
            except ValueError:
                pytest.fail(f"Priority value '{entry[3]}' is not numeric")


class TestParseSshareOutput:
    """Tests for parse_sshare_output function."""

    def test_separates_user_and_account_entries(self) -> None:
        """Test that user and account entries are correctly separated."""
        entries = [
            ("physics", "", "100", "0.25", "1000", "0.15", "0.15", "0.85"),
            ("physics", "user10", "50", "0.125", "500", "0.075", "0.15", "0.85"),
            ("chemistry", "", "100", "0.25", "2000", "0.30", "0.30", "0.70"),
        ]

        user_priorities, account_priorities = parse_sshare_output(entries)

        assert len(user_priorities) == 1
        assert len(account_priorities) == 2

        # Check user entry
        assert user_priorities[0]["User"] == "user10"
        assert user_priorities[0]["Account"] == "physics"

        # Check account entries
        accounts = {p["Account"] for p in account_priorities}
        assert "physics" in accounts
        assert "chemistry" in accounts

    def test_handles_empty_input(self) -> None:
        """Test that empty input returns empty lists."""
        user_priorities, account_priorities = parse_sshare_output([])

        assert user_priorities == []
        assert account_priorities == []

    def test_preserves_all_fields(self) -> None:
        """Test that all fields are preserved in output."""
        entries = [
            ("physics", "user10", "50", "0.125", "500", "0.075", "0.15", "0.85"),
        ]

        user_priorities, _ = parse_sshare_output(entries)

        assert len(user_priorities) == 1
        user = user_priorities[0]
        assert user["Account"] == "physics"
        assert user["User"] == "user10"
        assert user["RawShares"] == "50"
        assert user["NormShares"] == "0.125"
        assert user["RawUsage"] == "500"
        assert user["NormUsage"] == "0.075"
        assert user["EffectvUsage"] == "0.15"
        assert user["FairShare"] == "0.85"


class TestParseSprioOutput:
    """Tests for parse_sprio_output function."""

    def test_parses_job_priority_entries(self) -> None:
        """Test that job priority entries are correctly parsed."""
        entries = [
            ("12345", "user10", "physics", "1500", "100", "800", "200", "300", "100"),
            ("12346", "user11", "chemistry", "1200", "80", "600", "150", "270", "100"),
        ]

        job_priorities = parse_sprio_output(entries)

        assert len(job_priorities) == 2

        # Check that jobs are sorted by priority descending
        assert job_priorities[0]["Priority"] == "1500"
        assert job_priorities[1]["Priority"] == "1200"

    def test_handles_empty_input(self) -> None:
        """Test that empty input returns empty list."""
        job_priorities = parse_sprio_output([])
        assert job_priorities == []

    def test_preserves_all_fields(self) -> None:
        """Test that all fields are preserved in output."""
        entries = [
            ("12345", "user10", "physics", "1500", "100", "800", "200", "300", "100"),
        ]

        job_priorities = parse_sprio_output(entries)

        assert len(job_priorities) == 1
        job = job_priorities[0]
        assert job["JobID"] == "12345"
        assert job["User"] == "user10"
        assert job["Account"] == "physics"
        assert job["Priority"] == "1500"
        assert job["Age"] == "100"
        assert job["FairShare"] == "800"
        assert job["JobSize"] == "200"
        assert job["Partition"] == "300"
        assert job["QOS"] == "100"

    def test_sorts_by_priority_descending(self) -> None:
        """Test that jobs are sorted by priority in descending order."""
        entries = [
            ("12345", "user10", "physics", "1000", "100", "800", "200", "300", "100"),
            ("12346", "user11", "chemistry", "1500", "80", "600", "150", "270", "100"),
            ("12347", "user12", "biology", "1200", "90", "700", "180", "280", "100"),
        ]

        job_priorities = parse_sprio_output(entries)

        priorities = [float(j["Priority"]) for j in job_priorities]
        assert priorities == sorted(priorities, reverse=True)
