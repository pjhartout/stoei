"""Unit tests for the PriorityOverviewTab widget."""

import pytest
from stoei.widgets.priority_overview import (
    AccountPriority,
    JobPriority,
    PriorityOverviewTab,
    UserPriority,
)


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
        """Test that initial active subtab is users."""
        assert priority_tab.active_subtab == "users"

    async def test_update_user_priorities(self) -> None:
        """Test updating user priorities - requires mounted widget."""
        from textual.app import App

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

    async def test_update_account_priorities(self) -> None:
        """Test updating account priorities - requires mounted widget."""
        from textual.app import App

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

    async def test_update_job_priorities(self) -> None:
        """Test updating job priorities - requires mounted widget."""
        from textual.app import App

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
        from textual.app import App

        class PriorityTestApp(App[None]):
            def compose(self):
                yield PriorityOverviewTab(id="priority-overview")

        app = PriorityTestApp()
        async with app.run_test(size=(80, 24)):
            priority_tab = app.query_one("#priority-overview", PriorityOverviewTab)

            assert priority_tab.active_subtab == "users"

            priority_tab.switch_subtab("accounts")
            assert priority_tab.active_subtab == "accounts"

            priority_tab.switch_subtab("jobs")
            assert priority_tab.active_subtab == "jobs"

            priority_tab.switch_subtab("users")
            assert priority_tab.active_subtab == "users"

    async def test_update_from_sshare_data(self) -> None:
        """Test updating from raw sshare data."""
        from textual.app import App

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
        from textual.app import App

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


class TestPriorityOverviewSorting:
    """Tests for priority sorting behavior."""

    async def test_user_priorities_sorted_by_fair_share(self) -> None:
        """Test that user priorities are sorted by fair share descending."""
        from textual.app import App

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

    async def test_job_priorities_sorted_by_priority(self) -> None:
        """Test that job priorities are sorted by priority descending."""
        from textual.app import App

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
