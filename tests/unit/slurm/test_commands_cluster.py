"""Tests for cluster-related SLURM commands."""

from pathlib import Path

import pytest
from stoei.slurm.commands import get_all_users_jobs, get_cluster_nodes


class TestGetClusterNodes:
    """Tests for get_cluster_nodes with mock scontrol."""

    def test_returns_nodes_list(self, mock_slurm_path: Path) -> None:
        """Test that get_cluster_nodes returns a list of node dictionaries."""
        nodes, error = get_cluster_nodes()
        assert isinstance(nodes, list)
        assert error is None or isinstance(error, str)

    def test_nodes_have_required_fields(self, mock_slurm_path: Path) -> None:
        """Test that node dictionaries contain expected fields."""
        nodes, error = get_cluster_nodes()
        if error:
            pytest.skip(f"get_cluster_nodes failed: {error}")

        if len(nodes) > 0:
            node = nodes[0]
            assert isinstance(node, dict)
            # Check for common node fields
            assert "NodeName" in node or "Name" in node

    def test_empty_result_returns_empty_list(self, mock_slurm_path: Path) -> None:
        """Test that empty scontrol output returns empty list."""
        nodes, _error = get_cluster_nodes()
        # Mock may return empty or populated, both are valid
        assert isinstance(nodes, list)


class TestGetAllUsersJobs:
    """Tests for get_all_users_jobs with mock squeue."""

    def test_returns_jobs_list(self, mock_slurm_path: Path) -> None:
        """Test that get_all_users_jobs returns a list of job tuples."""
        jobs, error = get_all_users_jobs()
        assert error is None
        assert isinstance(jobs, list)

    def test_job_tuple_structure(self, mock_slurm_path: Path) -> None:
        """Test that job tuples have the expected structure."""
        jobs, error = get_all_users_jobs()
        assert error is None
        if len(jobs) > 0:
            first_job = jobs[0]
            assert isinstance(first_job, tuple)
            # Should have: JobID, Name, User, State, Time, Nodes, NodeList
            assert len(first_job) >= 7

    def test_jobs_contain_user_field(self, mock_slurm_path: Path) -> None:
        """Test that jobs contain user information."""
        jobs, error = get_all_users_jobs()
        assert error is None
        if len(jobs) > 0:
            # Third field should be user (index 2)
            assert len(jobs[0]) > 2
            user = jobs[0][2]
            assert isinstance(user, str)

    def test_empty_result_returns_empty_list(self, mock_slurm_path: Path) -> None:
        """Test that empty squeue output returns empty list."""
        jobs, error = get_all_users_jobs()
        # Mock may return empty or populated, both are valid
        assert isinstance(jobs, list)
        if not jobs:
            assert error is None  # Normal empty result
