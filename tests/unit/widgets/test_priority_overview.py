"""Unit tests for the PriorityOverviewTab widget."""

import pytest
from stoei.colors import FALLBACK_COLORS, ThemeColors
from stoei.slurm.formatters import fair_share_color, fair_share_status
from stoei.widgets.filterable_table import FilterableDataTable
from stoei.widgets.priority_overview import (
    AccountPriority,
    JobPriority,
    PriorityOverviewTab,
    UserPriority,
    compute_dense_ranks,
)
from textual.app import App
from textual.widgets import Static


class TestUserPriority:
    """Tests for the UserPriority dataclass."""

    def test_user_priority_creation(self) -> None:
        """Test creating a UserPriority object."""
        priority = UserPriority(
            username="testuser",
            account="physics",
            raw_shares="100",
            norm_shares="0.125",
            raw_usage="50000",
            norm_usage="0.075",
            effective_usage="0.15",
            fair_share="0.85",
        )
        assert priority.username == "testuser"
        assert priority.account == "physics"
        assert priority.raw_shares == "100"
        assert priority.norm_shares == "0.125"
        assert priority.raw_usage == "50000"
        assert priority.norm_usage == "0.075"
        assert priority.effective_usage == "0.15"
        assert priority.fair_share == "0.85"
        assert priority.rank == ""

    def test_user_priority_with_rank(self) -> None:
        """Test creating a UserPriority object with rank."""
        priority = UserPriority(
            username="testuser",
            account="physics",
            raw_shares="100",
            norm_shares="0.125",
            raw_usage="50000",
            norm_usage="0.075",
            effective_usage="0.15",
            fair_share="0.85",
            rank="1/5",
        )
        assert priority.rank == "1/5"


class TestAccountPriority:
    """Tests for the AccountPriority dataclass."""

    def test_account_priority_creation(self) -> None:
        """Test creating an AccountPriority object."""
        priority = AccountPriority(
            account="physics",
            raw_shares="100",
            norm_shares="0.25",
            raw_usage="100000",
            norm_usage="0.15",
            effective_usage="0.15",
            fair_share="0.85",
        )
        assert priority.account == "physics"
        assert priority.raw_shares == "100"
        assert priority.norm_shares == "0.25"
        assert priority.raw_usage == "100000"
        assert priority.norm_usage == "0.15"
        assert priority.effective_usage == "0.15"
        assert priority.fair_share == "0.85"
        assert priority.rank == ""


class TestJobPriority:
    """Tests for the JobPriority dataclass."""

    def test_job_priority_creation(self) -> None:
        """Test creating a JobPriority object."""
        priority = JobPriority(
            job_id="12345",
            user="testuser",
            account="physics",
            priority="1500",
            age="100",
            fair_share="800",
            job_size="200",
            partition="300",
            qos="100",
        )
        assert priority.job_id == "12345"
        assert priority.user == "testuser"
        assert priority.account == "physics"
        assert priority.priority == "1500"
        assert priority.age == "100"
        assert priority.fair_share == "800"
        assert priority.job_size == "200"
        assert priority.partition == "300"
        assert priority.qos == "100"


class TestComputeDenseRanks:
    """Tests for dense rank computation."""

    def test_empty_list(self) -> None:
        """Test ranking an empty list."""
        assert compute_dense_ranks([]) == []

    def test_single_element(self) -> None:
        """Test ranking a single element."""
        assert compute_dense_ranks([1.0]) == ["1/1"]

    def test_all_unique(self) -> None:
        """Test ranking with all unique values (already sorted desc)."""
        assert compute_dense_ranks([0.9, 0.7, 0.5, 0.3]) == ["1/4", "2/4", "3/4", "4/4"]

    def test_ties(self) -> None:
        """Test dense ranking with tied values."""
        assert compute_dense_ranks([0.9, 0.7, 0.7, 0.3]) == ["1/4", "2/4", "2/4", "3/4"]

    def test_all_same(self) -> None:
        """Test ranking when all values are the same."""
        assert compute_dense_ranks([0.5, 0.5, 0.5]) == ["1/3", "1/3", "1/3"]


class TestFairShareHelpers:
    """Tests for fair share color and status helper functions."""

    def test_fair_share_status_under_served(self) -> None:
        """Test status for under-served (high FairShare)."""
        assert fair_share_status("0.85") == "Under-served"
        assert fair_share_status("0.50") == "Under-served"

    def test_fair_share_status_fair(self) -> None:
        """Test status for fair (medium FairShare)."""
        assert fair_share_status("0.35") == "Fair"
        assert fair_share_status("0.20") == "Fair"

    def test_fair_share_status_over_served(self) -> None:
        """Test status for over-served (low FairShare)."""
        assert fair_share_status("0.10") == "Over-served"
        assert fair_share_status("0.00") == "Over-served"

    def test_fair_share_status_invalid(self) -> None:
        """Test status for non-numeric value."""
        assert fair_share_status("N/A") == ""

    def test_fair_share_color_returns_string(self) -> None:
        """Test that fair_share_color returns a color string."""
        colors = ThemeColors(
            success=FALLBACK_COLORS["success"],
            warning=FALLBACK_COLORS["warning"],
            error=FALLBACK_COLORS["error"],
            primary=FALLBACK_COLORS["primary"],
            accent=FALLBACK_COLORS["accent"],
            secondary=FALLBACK_COLORS["secondary"],
            foreground=FALLBACK_COLORS["foreground"],
            text_muted=FALLBACK_COLORS["text_muted"],
            background=FALLBACK_COLORS["background"],
            surface=FALLBACK_COLORS["surface"],
            panel=FALLBACK_COLORS["panel"],
            border=FALLBACK_COLORS["border"],
        )
        assert fair_share_color("0.85", colors) == colors.success
        assert fair_share_color("0.35", colors) == colors.warning
        assert fair_share_color("0.10", colors) == colors.error
        assert fair_share_color("invalid", colors) == colors.foreground


class TestPriorityOverviewTab:
    """Tests for the PriorityOverviewTab widget."""

    @pytest.fixture
    def priority_tab(self) -> PriorityOverviewTab:
        """Create a PriorityOverviewTab widget for testing."""
        return PriorityOverviewTab(id="test-priority-tab")

    def test_initial_priorities_empty(self, priority_tab: PriorityOverviewTab) -> None:
        """Test that initial priorities lists are empty."""
        assert priority_tab.user_priorities == []
        assert priority_tab.account_priorities == []
        assert priority_tab.job_priorities == []

    def test_initial_active_subtab(self, priority_tab: PriorityOverviewTab) -> None:
        """Test that initial active subtab is 'mine'."""
        assert priority_tab.active_subtab == "mine"

    def test_current_username_default(self) -> None:
        """Test that current_username defaults to empty string."""
        tab = PriorityOverviewTab(id="test")
        assert tab._current_username == ""

    def test_current_username_set(self) -> None:
        """Test that current_username can be set via constructor."""
        tab = PriorityOverviewTab(current_username="testuser", id="test")
        assert tab._current_username == "testuser"

    async def test_update_user_priorities(self) -> None:
        """Test updating user priorities - requires mounted widget."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)
            priorities = [
                UserPriority(
                    username="user1",
                    account="physics",
                    raw_shares="100",
                    norm_shares="0.125",
                    raw_usage="50000",
                    norm_usage="0.075",
                    effective_usage="0.15",
                    fair_share="0.85",
                ),
                UserPriority(
                    username="user2",
                    account="chemistry",
                    raw_shares="50",
                    norm_shares="0.0625",
                    raw_usage="100000",
                    norm_usage="0.15",
                    effective_usage="0.30",
                    fair_share="0.70",
                ),
            ]
            priority_tab.update_user_priorities(priorities)
            # Should be sorted by fair share descending
            assert len(priority_tab.user_priorities) == 2
            assert priority_tab.user_priorities[0].username == "user1"  # 0.85 > 0.70
            # Should have ranks computed
            assert priority_tab.user_priorities[0].rank == "1/2"
            assert priority_tab.user_priorities[1].rank == "2/2"

    async def test_update_account_priorities(self) -> None:
        """Test updating account priorities - requires mounted widget."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)
            priorities = [
                AccountPriority(
                    account="physics",
                    raw_shares="100",
                    norm_shares="0.25",
                    raw_usage="100000",
                    norm_usage="0.15",
                    effective_usage="0.15",
                    fair_share="0.85",
                ),
                AccountPriority(
                    account="chemistry",
                    raw_shares="100",
                    norm_shares="0.25",
                    raw_usage="200000",
                    norm_usage="0.30",
                    effective_usage="0.30",
                    fair_share="0.70",
                ),
            ]
            priority_tab.update_account_priorities(priorities)
            # Should be sorted by fair share descending
            assert len(priority_tab.account_priorities) == 2
            assert priority_tab.account_priorities[0].account == "physics"
            # Should have ranks computed
            assert priority_tab.account_priorities[0].rank == "1/2"
            assert priority_tab.account_priorities[1].rank == "2/2"

    async def test_update_job_priorities(self) -> None:
        """Test updating job priorities - requires mounted widget."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)
            priorities = [
                JobPriority(
                    job_id="12345",
                    user="user1",
                    account="physics",
                    priority="1500",
                    age="100",
                    fair_share="800",
                    job_size="200",
                    partition="300",
                    qos="100",
                ),
                JobPriority(
                    job_id="12346",
                    user="user2",
                    account="chemistry",
                    priority="1200",
                    age="80",
                    fair_share="600",
                    job_size="150",
                    partition="270",
                    qos="100",
                ),
            ]
            priority_tab.update_job_priorities(priorities)
            # Should be sorted by priority descending
            assert len(priority_tab.job_priorities) == 2
            assert priority_tab.job_priorities[0].job_id == "12345"

    async def test_switch_subtab(self) -> None:
        """Test switching between subtabs."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)

            assert priority_tab.active_subtab == "mine"

            priority_tab.switch_subtab("users")
            assert priority_tab.active_subtab == "users"

            priority_tab.switch_subtab("accounts")
            assert priority_tab.active_subtab == "accounts"

            priority_tab.switch_subtab("jobs")
            assert priority_tab.active_subtab == "jobs"

            priority_tab.switch_subtab("mine")
            assert priority_tab.active_subtab == "mine"

    async def test_update_from_sshare_data(self) -> None:
        """Test updating from raw sshare data."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)

            sshare_data = [
                ("physics", "", "100", "0.25", "100000", "0.15", "0.15", "0.85"),
                ("physics", "user10", "50", "0.125", "50000", "0.075", "0.15", "0.85"),
                ("chemistry", "", "100", "0.25", "200000", "0.30", "0.30", "0.70"),
            ]

            priority_tab.update_from_sshare_data(sshare_data)

            # Should have 1 user and 2 accounts
            assert len(priority_tab.user_priorities) == 1
            assert len(priority_tab.account_priorities) == 2

    async def test_update_from_sprio_data(self) -> None:
        """Test updating from raw sprio data."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)

            sprio_data = [
                ("12345", "user10", "physics", "1500", "100", "800", "200", "300", "100"),
                ("12346", "user11", "chemistry", "1200", "80", "600", "150", "270", "100"),
            ]

            priority_tab.update_from_sprio_data(sprio_data)

            assert len(priority_tab.job_priorities) == 2
            # Should be sorted by priority descending
            assert priority_tab.job_priorities[0].job_id == "12345"

    async def test_my_priority_summary_no_data(self) -> None:
        """Test 'My Priority' summary when user is not found."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(current_username="unknown_user", id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)
            # Update with data that doesn't include the current user
            priorities = [
                UserPriority("user1", "physics", "100", "0.125", "50000", "0.075", "0.15", "0.85"),
            ]
            priority_tab.update_user_priorities(priorities)
            # Summary should show "not found" message
            summary = app.query_one("#my-priority-summary", Static)
            assert "No fair-share data found" in summary.content

    async def test_my_priority_summary_with_data(self) -> None:
        """Test 'My Priority' summary when user has data."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(current_username="user1", id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)
            priorities = [
                UserPriority("user1", "physics", "100", "0.125", "50000", "0.075", "0.15", "0.85"),
                UserPriority("user2", "chemistry", "50", "0.0625", "100000", "0.15", "0.30", "0.70"),
            ]
            priority_tab.update_user_priorities(priorities)
            summary = app.query_one("#my-priority-summary", Static)
            content = summary.content
            assert "Your Priority" in content
            assert "physics" in content

    async def test_user_highlighting(self) -> None:
        """Test that current user's row is highlighted with >> prefix."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(current_username="user1", id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)
            priorities = [
                UserPriority("user1", "physics", "100", "0.125", "50000", "0.075", "0.15", "0.85"),
                UserPriority("user2", "chemistry", "50", "0.0625", "100000", "0.15", "0.30", "0.70"),
            ]
            priority_tab.update_user_priorities(priorities)

            # Switch to users subtab and check the data
            priority_tab.switch_subtab("users")
            filterable = priority_tab.query_one("#user-priority-filterable-table", FilterableDataTable)
            table = filterable.query_one("#user_priority_table")
            # The first row (user1) should have >> prefix in the User column
            row_data = table.get_row_at(0)
            assert ">> user1" in str(row_data[1])


class TestPriorityOverviewSorting:
    """Tests for priority sorting behavior."""

    async def test_user_priorities_sorted_by_fair_share(self) -> None:
        """Test that user priorities are sorted by fair share descending."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)
            priorities = [
                UserPriority("user1", "acct", "100", "0.1", "1000", "0.1", "0.1", "0.50"),
                UserPriority("user2", "acct", "100", "0.1", "1000", "0.1", "0.1", "0.90"),
                UserPriority("user3", "acct", "100", "0.1", "1000", "0.1", "0.1", "0.70"),
            ]
            priority_tab.update_user_priorities(priorities)

            # Should be sorted: user2 (0.90), user3 (0.70), user1 (0.50)
            assert priority_tab.user_priorities[0].username == "user2"
            assert priority_tab.user_priorities[1].username == "user3"
            assert priority_tab.user_priorities[2].username == "user1"

            # Ranks should be computed
            assert priority_tab.user_priorities[0].rank == "1/3"
            assert priority_tab.user_priorities[1].rank == "2/3"
            assert priority_tab.user_priorities[2].rank == "3/3"

    async def test_job_priorities_sorted_by_priority(self) -> None:
        """Test that job priorities are sorted by priority descending."""

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)
            priorities = [
                JobPriority("job1", "u", "a", "1000", "0", "0", "0", "0", "0"),
                JobPriority("job2", "u", "a", "1500", "0", "0", "0", "0", "0"),
                JobPriority("job3", "u", "a", "1200", "0", "0", "0", "0", "0"),
            ]
            priority_tab.update_job_priorities(priorities)

            # Should be sorted: job2 (1500), job3 (1200), job1 (1000)
            assert priority_tab.job_priorities[0].job_id == "job2"
            assert priority_tab.job_priorities[1].job_id == "job3"
            assert priority_tab.job_priorities[2].job_id == "job1"
