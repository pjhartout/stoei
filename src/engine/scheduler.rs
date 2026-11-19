use std::time::{Duration, Instant};

use crate::config::Config;
use crate::store::{Section, State, Store};

pub const SECTIONS: [Section; 7] = [
    Section::RunningJobs,
    Section::History,
    Section::AllUsersJobs,
    Section::Nodes,
    Section::FairShare,
    Section::PendingPrio,
    Section::PriorityConfig,
];

#[derive(Clone, Copy)]
struct Schedule {
    next: Instant,
    dispatched: Option<Instant>,
    failures: u32,
}

pub struct Scheduler {
    schedules: [Schedule; 7],
    fast: Duration,
    seed: u64,
    history_pending: bool,
}

fn index(section: Section) -> usize {
    SECTIONS
        .iter()
        .position(|candidate| *candidate == section)
        .expect("known section")
}

fn cooldown(section: Section) -> Duration {
    match section {
        Section::RunningJobs => Duration::from_secs(10),
        Section::History | Section::AllUsersJobs => Duration::from_secs(120),
        _ => Duration::from_secs(300),
    }
}

impl Scheduler {
    pub fn new(now: Instant, config: &Config, seed: u64) -> Self {
        let mut schedules = [Schedule {
            next: now,
            dispatched: None,
            failures: 0,
        }; 7];
        for (section, offset) in [
            (Section::History, 250),
            (Section::AllUsersJobs, 750),
            (Section::Nodes, 1500),
        ] {
            schedules[index(section)].next += Duration::from_millis(offset);
        }
        Self {
            schedules,
            fast: Duration::from_secs_f64(config.clone().clamped().refresh_interval),
            seed: seed.max(1),
            history_pending: false,
        }
    }

    pub fn configure(&mut self, now: Instant, config: &Config) {
        self.fast = Duration::from_secs_f64(config.clone().clamped().refresh_interval);
        for section in SECTIONS {
            if self.history_pending(section) {
                continue;
            }
            let period = self.period(section);
            self.schedules[index(section)].next = now + period;
        }
    }

    pub(super) fn history_pending(&self, section: Section) -> bool {
        section == Section::History && self.history_pending
    }

    pub(super) fn accept_history(
        &mut self,
        fetched_days: u32,
        requested_days: u32,
        now: Instant,
    ) -> bool {
        if fetched_days == requested_days {
            return true;
        }
        self.history_pending = true;
        self.schedules[index(Section::History)].next = now;
        false
    }

    fn period(&self, section: Section) -> Duration {
        self.fast
            * match section {
                Section::RunningJobs => 1,
                Section::Nodes => 8,
                Section::FairShare | Section::PendingPrio | Section::PriorityConfig => 12,
                _ => 4,
            }
    }

    fn eligible(&self, section: Section, history: bool, priority: bool, store: &Store) -> bool {
        if self.history_pending(section) {
            return true;
        }
        store.meta(section).state != State::Loading
            && match section {
                Section::History => history,
                Section::FairShare | Section::PendingPrio => priority,
                Section::PriorityConfig => priority && store.meta(section).state != State::Loaded,
                _ => true,
            }
    }

    pub fn due(&self, now: Instant, history: bool, priority: bool, store: &Store) -> Vec<Section> {
        SECTIONS
            .into_iter()
            .filter(|section| {
                self.eligible(*section, history, priority, store)
                    && self.schedules[index(*section)].next <= now
            })
            .collect()
    }

    pub fn next_deadline(&self, history: bool, priority: bool, store: &Store) -> Option<Instant> {
        SECTIONS
            .into_iter()
            .filter(|section| self.eligible(*section, history, priority, store))
            .map(|section| self.schedules[index(section)].next)
            .min()
    }

    pub fn request(&mut self, section: Section, now: Instant, force: bool, store: &Store) -> bool {
        if store.meta(section).state == State::Loading {
            return false;
        }
        let schedule = &mut self.schedules[index(section)];
        if !force
            && (schedule
                .dispatched
                .is_some_and(|last| now.saturating_duration_since(last) < cooldown(section))
                || (schedule.failures > 0 && schedule.next > now))
        {
            return false;
        }
        schedule.next = now;
        true
    }

    pub fn dispatched(&mut self, section: Section, now: Instant) {
        if section == Section::History {
            self.history_pending = false;
        }
        let period = self.jitter(self.period(section));
        let schedule = &mut self.schedules[index(section)];
        schedule.dispatched = Some(now);
        schedule.next = now + period;
    }

    pub fn deferred(&mut self, section: Section, now: Instant, force: bool) {
        if section == Section::History && force {
            self.history_pending = true;
        }
        self.schedules[index(section)].next = now + Duration::from_secs(1);
    }

    pub fn finished(&mut self, section: Section, failed: bool, now: Instant) {
        let slot = index(section);
        if failed {
            self.schedules[slot].failures = self.schedules[slot].failures.saturating_add(1).min(16);
            let multiplier = 1_u32 << self.schedules[slot].failures;
            let base = self.period(section);
            let limit = Duration::from_secs(900).max(base * 2);
            let period = (base * multiplier).min(limit);
            self.schedules[slot].next = now + self.jitter(period).min(limit);
        } else {
            self.schedules[slot].failures = 0;
            let period = self.jitter(self.period(section));
            self.schedules[slot].next = now + period;
        }
    }

    fn jitter(&mut self, base: Duration) -> Duration {
        self.seed ^= self.seed << 13;
        self.seed ^= self.seed >> 7;
        self.seed ^= self.seed << 17;
        let jittered = base.mul_f64((90 + self.seed % 21) as f64 / 100.0);
        jittered.max(Duration::from_secs(120))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn idle_deadline_is_the_refresh_not_a_frame_timer() {
        let now = Instant::now();
        let mut store = Store::default();
        let mut scheduler = Scheduler::new(now, &Config::default(), 1);
        for section in [
            Section::RunningJobs,
            Section::History,
            Section::AllUsersJobs,
            Section::Nodes,
        ] {
            scheduler.dispatched(section, now);
        }
        assert!(
            scheduler.next_deadline(true, false, &store).unwrap() >= now + Duration::from_secs(120)
        );
        assert!(
            scheduler
                .due(now + Duration::from_secs(1), true, false, &store)
                .is_empty()
        );
        store.begin(Section::RunningJobs);
        assert!(
            !scheduler
                .due(now + Duration::from_secs(3600), true, false, &store)
                .contains(&Section::RunningJobs)
        );
    }

    #[test]
    fn hidden_data_does_not_create_overdue_wakeups() {
        let now = Instant::now();
        let store = Store::default();
        let mut scheduler = Scheduler::new(now, &Config::default(), 2);
        for section in [Section::RunningJobs, Section::AllUsersJobs, Section::Nodes] {
            scheduler.dispatched(section, now);
        }
        assert!(
            scheduler.next_deadline(false, false, &store).unwrap()
                >= now + Duration::from_secs(120)
        );
        assert!(
            scheduler
                .due(now, true, true, &store)
                .contains(&Section::PriorityConfig)
        );
        assert!(
            !scheduler
                .due(now, false, false, &store)
                .contains(&Section::History)
        );
    }

    #[test]
    fn forced_requests_bypass_cooldowns_and_failure_backoff() {
        let now = Instant::now();
        let store = Store::new();
        for section in SECTIONS {
            let mut scheduler = Scheduler::new(now, &Config::default(), 3);
            for failed in [false, true] {
                scheduler.dispatched(section, now);
                scheduler.finished(section, failed, now);
                assert!(!scheduler.request(section, now + Duration::from_secs(1), false, &store));
                assert!(scheduler.request(section, now + Duration::from_secs(1), true, &store));
                scheduler.dispatched(section, now + Duration::from_secs(1));
                scheduler.finished(section, failed, now + Duration::from_secs(1));
                assert!(scheduler.request(section, now + Duration::from_secs(2), true, &store));
            }
        }
    }

    #[test]
    fn forced_requests_share_fetches_in_flight() {
        let now = Instant::now();
        let mut scheduler = Scheduler::new(now, &Config::default(), 4);
        let mut store = Store::new();
        for section in SECTIONS {
            scheduler.dispatched(section, now);
            store.begin(section);
            assert!(!scheduler.request(section, now + Duration::from_secs(1), true, &store));
        }
        assert!(
            scheduler
                .due(now + Duration::from_secs(1), true, true, &store)
                .is_empty()
        );
        store.apply(
            Section::RunningJobs,
            store.generation(Section::RunningJobs),
            Ok(crate::store::Dataset::RunningJobs(Vec::new())),
            now + Duration::from_secs(1),
        );
        assert!(scheduler.request(
            Section::RunningJobs,
            now + Duration::from_secs(1),
            true,
            &store
        ));
        assert_eq!(
            scheduler.due(now + Duration::from_secs(1), true, true, &store),
            [Section::RunningJobs]
        );
    }

    #[test]
    fn history_window_changes_coalesce_across_inflight_and_deferred_fetches() {
        let now = Instant::now();
        let mut config = Config::default();
        let mut scheduler = Scheduler::new(now, &config, 1);
        let mut store = Store::new();
        let section = Section::History;
        let initial_window = config.job_history_days;
        store.begin(section);
        scheduler.dispatched(section, now);

        for days in [30, 14] {
            config.job_history_days = days;
            scheduler.configure(now, &config);
            assert!(!scheduler.request(section, now, true, &store));
            assert!(!scheduler.due(now, true, false, &store).contains(&section));
        }
        assert!(!scheduler.accept_history(initial_window, config.job_history_days, now));
        assert_eq!(scheduler.due(now, false, false, &store), [section]);

        scheduler.deferred(section, now, true);
        config.job_history_days = 90;
        scheduler.configure(now, &config);
        let retry = now + Duration::from_secs(1);
        assert_eq!(scheduler.next_deadline(false, false, &store), Some(retry));
        assert_eq!(scheduler.due(retry, false, false, &store), [section]);
        assert!(scheduler.history_pending(section));

        let latest_window = config.job_history_days;
        let generation = store.begin(section);
        scheduler.dispatched(section, retry);
        for days in [14, latest_window, latest_window] {
            config.job_history_days = days;
            scheduler.configure(retry, &config);
            assert!(!scheduler.request(section, retry, true, &store));
        }
        assert!(scheduler.accept_history(latest_window, config.job_history_days, retry));
        assert!(!scheduler.history_pending(section));
        store.apply(
            section,
            generation,
            Err("controller unavailable".into()),
            retry,
        );
        scheduler.finished(section, true, retry);
        assert!(scheduler.due(retry, true, false, &store).is_empty());
        assert!(!scheduler.request(section, retry, false, &store));
        assert!(scheduler.request(section, retry, true, &store));
        scheduler.deferred(section, retry, true);
        assert_eq!(
            scheduler.due(retry + Duration::from_secs(1), false, false, &store),
            [section]
        );
    }

    #[test]
    fn failures_never_accelerate_background_refreshes() {
        let now = Instant::now();
        let store = Store::new();
        for interval in [120.0, 300.0] {
            let config = Config {
                refresh_interval: interval,
                ..Default::default()
            };
            for section in SECTIONS {
                let mut scheduler = Scheduler::new(now, &config, 5);
                scheduler.finished(section, false, now);
                let healthy = scheduler.schedules[index(section)].next;
                for _ in 0..20 {
                    scheduler.finished(section, true, now);
                    let retry = scheduler.schedules[index(section)].next;
                    assert!(retry > healthy, "failed {section:?} retried sooner");
                    assert!(!scheduler.request(section, healthy, false, &store));
                }
            }
        }
    }
}
