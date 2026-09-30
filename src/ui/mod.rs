mod cluster;
mod format;
mod modals;
mod render;
mod table;
mod theme;

use std::collections::VecDeque;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use chrono::NaiveDate;
use crossterm::event::{KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use ratatui::Frame;

use crate::config::Config;
use crate::log::LogRing;
use crate::store::{self, JobDetail, JobUsage, Store};

use modals::{DetailView, Modal};
use table::{Source, TableView};

const CACHE_CAPACITY: usize = 64;
const TOAST_CAPACITY: usize = 4;
const INPUT_LIMIT: usize = 4096;

#[derive(Clone, Debug)]
pub struct JobSnapshot {
    pub detail: JobDetail,
    pub usage: Option<JobUsage>,
    pub note: Option<String>,
}

#[derive(Clone, Debug)]
pub struct Tail {
    pub lines: Vec<String>,
    pub first_line: u64,
    pub total_lines: u64,
    pub path: PathBuf,
}

#[derive(Debug)]
pub enum ActionResult {
    Job {
        token: u64,
        job_id: String,
        result: Result<JobSnapshot, String>,
    },
    Node {
        token: u64,
        name: String,
        result: Result<JobDetail, String>,
    },
    Log {
        token: u64,
        result: Result<Tail, String>,
    },
    Cancel {
        job_id: String,
        result: Result<(), String>,
    },
    Modify {
        job_id: String,
        result: Result<(), String>,
    },
    ConfigSaved(Result<(), String>),
    EditorDone(Result<(), String>),
}

#[derive(Clone, Debug)]
pub enum Effect {
    FetchJob {
        token: u64,
        job_id: String,
        state: String,
        fallback: Option<JobDetail>,
    },
    FetchNode {
        token: u64,
        name: String,
    },
    FetchLog {
        token: u64,
        path: PathBuf,
        max_lines: usize,
    },
    Cancel {
        job_id: String,
    },
    Modify {
        job_id: String,
        fields: Vec<(String, String)>,
    },
    Hold {
        job_id: String,
        hold: bool,
    },
    SaveConfig(Config),
    Editor(PathBuf),
    Copy(String),
    Refresh,
    TabChanged,
    Quit,
}

pub struct RuntimeStatus<'a> {
    pub version: &'a str,
    pub update_available: Option<&'a str>,
    pub unavailable: Option<&'a str>,
    pub logs: &'a LogRing,
    pub today: NaiveDate,
    pub now: Instant,
}

struct CachedDetail {
    id: String,
    state: String,
    snapshot: JobSnapshot,
}

struct Toast {
    text: String,
    expires: Instant,
}

pub struct Ui {
    config: Config,
    active: usize,
    users_pending: bool,
    priority_pane: usize,
    tables: [TableView; 9],
    modals: Vec<Modal>,
    cache: VecDeque<CachedDetail>,
    next_token: u64,
    toasts: VecDeque<Toast>,
    today: NaiveDate,
    log_snapshot: Vec<crate::log::LogEntry>,
    seeded_priority_user: bool,
}

impl Ui {
    pub fn new(config: Config) -> Self {
        Self {
            config,
            active: 0,
            users_pending: false,
            priority_pane: 0,
            tables: std::array::from_fn(|_| TableView::default()),
            modals: Vec::new(),
            cache: VecDeque::new(),
            next_token: 0,
            toasts: VecDeque::new(),
            today: NaiveDate::from_ymd_opt(1970, 1, 1).expect("epoch date is valid"),
            log_snapshot: Vec::new(),
            seeded_priority_user: false,
        }
    }

    pub fn active_tab(&self) -> usize {
        self.active
    }
    pub fn needs_priority(&self) -> bool {
        self.active == 2 || self.active == 3
    }
    pub fn history_visible(&self) -> bool {
        self.active == 0
    }
    pub fn config(&self) -> &Config {
        &self.config
    }

    pub fn observe_data(&mut self, store: &Store) {
        self.rebuild_active(store);
        if self.active != 4 {
            self.log_snapshot = Vec::new();
        }
        let active = self.table_index();
        for (index, table) in self.tables.iter_mut().enumerate() {
            if index != active {
                table.indices = Vec::new();
            }
        }
        self.cache.retain(|entry| {
            store.merged_jobs().iter().any(|job| {
                store::normalize_array_job_id(&job.id) == entry.id && job.state == entry.state
            })
        });
        if active == 4 && !self.seeded_priority_user && !store.ranked_users().is_empty() {
            let source = Source::Shares(store.ranked_users(), false);
            if let Some(position) = self.tables[4]
                .indices
                .iter()
                .position(|index| source.key(*index) == store.user)
            {
                self.tables[4].cursor = position;
                self.tables[4].selected_key = Some(store.user.clone());
            }
            self.seeded_priority_user = true;
        }
    }

    pub fn notify(&mut self, message: String) {
        self.notify_at(message, Instant::now());
    }

    pub fn notify_at(&mut self, message: String, now: Instant) {
        if self.toasts.len() == TOAST_CAPACITY {
            self.toasts.pop_front();
        }
        self.toasts.push_back(Toast {
            text: format::clean(&message),
            expires: now + Duration::from_secs(20),
        });
        debug_assert!(self.toasts.len() <= TOAST_CAPACITY);
    }

    pub fn next_deadline(&self) -> Option<Instant> {
        self.toasts.front().map(|toast| toast.expires)
    }

    pub fn expire(&mut self, now: Instant) -> bool {
        let before = self.toasts.len();
        self.toasts.retain(|toast| toast.expires > now);
        before != self.toasts.len()
    }

    pub fn handle_key(&mut self, key: KeyEvent, store: &Store) -> Vec<Effect> {
        if key.kind == KeyEventKind::Release {
            return Vec::new();
        }
        if key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL) {
            return vec![Effect::Quit];
        }
        if !self.modals.is_empty() {
            return self.handle_modal(key, store);
        }
        let index = self.table_index();
        if self.tables[index].editing_filter {
            self.handle_filter(key, store);
            return Vec::new();
        }
        if self.quit_key(key) {
            return vec![Effect::Quit];
        }
        if key.code == KeyCode::Esc {
            self.tables[index].filter.clear();
            self.rebuild_active(store);
            return Vec::new();
        }
        if let KeyCode::Char(ch @ '1'..='5') = key.code {
            self.active = usize::from(ch as u8 - b'1');
            self.observe_data(store);
            return vec![Effect::TabChanged];
        }
        if key.code == KeyCode::Tab || key.code == KeyCode::BackTab {
            self.active = (self.active + if key.code == KeyCode::Tab { 1 } else { 4 }) % 5;
            self.observe_data(store);
            return vec![Effect::TabChanged];
        }
        if self.open_global_modal(key) {
            return Vec::new();
        }
        if let Some(effects) = self.pane_key(key, store) {
            return effects;
        }
        if self.binding(key, 'r', 'r') {
            return vec![Effect::Refresh];
        }
        if self.binding(key, '/', 's') {
            self.tables[index].editing_filter = true;
            return Vec::new();
        }
        if self.binding(key, 'o', 'o') {
            self.sort_active(store);
            return Vec::new();
        }
        if self.active == 0 && key.code == KeyCode::Char('i') {
            self.modals.push(Modal::job_input());
            return Vec::new();
        }
        if self.active == 0 && key.code == KeyCode::Char('c') {
            return self.request_cancel(store);
        }
        if key.code == KeyCode::Enter {
            return self.open_selected(store);
        }
        self.navigate(key, store);
        Vec::new()
    }

    fn open_global_modal(&mut self, key: KeyEvent) -> bool {
        let modal = if self.binding(key, '?', 'h') {
            Modal::help()
        } else if self.settings_key(key) {
            Modal::settings(self.config.clone())
        } else if key.code == KeyCode::Char('L') {
            Modal::load()
        } else {
            return false;
        };
        self.modals.push(modal);
        true
    }

    pub fn handle_paste(&mut self, text: &str, store: &Store) {
        let text: String = text.chars().filter(|ch| !ch.is_control()).collect();
        if self.modals.is_empty() {
            let index = self.table_index();
            if self.tables[index].editing_filter {
                append_bounded(&mut self.tables[index].filter, &text);
                self.rebuild_active(store);
            }
        } else {
            self.paste_modal(&text);
        }
    }

    fn handle_filter(&mut self, key: KeyEvent, store: &Store) {
        let index = self.table_index();
        match key.code {
            KeyCode::Esc => {
                self.tables[index].filter.clear();
                self.tables[index].editing_filter = false;
            }
            KeyCode::Enter => self.tables[index].editing_filter = false,
            KeyCode::Backspace => {
                self.tables[index].filter.pop();
            }
            KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                self.tables[index].filter.clear()
            }
            KeyCode::Char(ch)
                if !key
                    .modifiers
                    .intersects(KeyModifiers::CONTROL | KeyModifiers::ALT) =>
            {
                append_bounded(&mut self.tables[index].filter, &ch.to_string())
            }
            _ => {}
        }
        self.rebuild_active(store);
    }

    fn pane_key(&mut self, key: KeyEvent, store: &Store) -> Option<Vec<Effect>> {
        if key
            .modifiers
            .intersects(KeyModifiers::CONTROL | KeyModifiers::ALT)
        {
            return None;
        }
        if self.active == 2 {
            match key.code {
                KeyCode::Char('r') => self.users_pending = false,
                KeyCode::Char('p') => self.users_pending = true,
                _ => return None,
            }
            self.observe_data(store);
            return Some(Vec::new());
        }
        if self.active == 3 {
            self.priority_pane = match key.code {
                KeyCode::Char('m') => 0,
                KeyCode::Char('u') => 1,
                KeyCode::Char('a') => 2,
                KeyCode::Char('j') => 3,
                _ => return None,
            };
            self.observe_data(store);
            return Some(vec![Effect::TabChanged]);
        }
        None
    }

    fn binding(&self, key: KeyEvent, vim: char, emacs: char) -> bool {
        if self.config.keybind_mode == "emacs" {
            key.code == KeyCode::Char(emacs) && key.modifiers.contains(KeyModifiers::CONTROL)
        } else {
            key.code == KeyCode::Char(vim)
                && !key
                    .modifiers
                    .intersects(KeyModifiers::CONTROL | KeyModifiers::ALT)
        }
    }

    fn quit_key(&self, key: KeyEvent) -> bool {
        self.binding(key, 'q', 'q')
            || key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL)
    }
    fn settings_key(&self, key: KeyEvent) -> bool {
        self.binding(key, 's', ',')
    }

    fn table_index(&self) -> usize {
        match self.active {
            0 => 0,
            1 => 1,
            2 => {
                if self.users_pending {
                    3
                } else {
                    2
                }
            }
            3 => match self.priority_pane {
                2 => 5,
                3 => 6,
                0 => 8,
                _ => 4,
            },
            _ => 7,
        }
    }

    fn rebuild_active(&mut self, store: &Store) {
        let index = self.table_index();
        if index == 7 {
            self.tables[index].rebuild(&Source::Logs(&self.log_snapshot), self.today);
        } else {
            self.tables[index].rebuild(&source_for(index, store), self.today);
        }
    }

    fn sort_active(&mut self, store: &Store) {
        let index = self.table_index();
        if index == 7 {
            self.tables[index].cycle_sort(&Source::Logs(&self.log_snapshot), self.today);
        } else {
            self.tables[index].cycle_sort(&source_for(index, store), self.today);
        }
    }

    fn navigate(&mut self, key: KeyEvent, store: &Store) {
        let index = self.table_index();
        let amount = match key.code {
            KeyCode::Up => Some(-1),
            KeyCode::Down => Some(1),
            KeyCode::PageUp => Some(-(self.tables[index].height.max(1) as isize)),
            KeyCode::PageDown => Some(self.tables[index].height.max(1) as isize),
            KeyCode::Char('k') if self.config.keybind_mode == "vim" => Some(-1),
            KeyCode::Char('j') if self.config.keybind_mode == "vim" => Some(1),
            KeyCode::Char('p') if key.modifiers.contains(KeyModifiers::CONTROL) => Some(-1),
            KeyCode::Char('n') if key.modifiers.contains(KeyModifiers::CONTROL) => Some(1),
            KeyCode::Left => {
                self.tables[index].horizontal = self.tables[index].horizontal.saturating_sub(8);
                return;
            }
            KeyCode::Right => {
                self.tables[index].horizontal = self.tables[index].horizontal.saturating_add(8);
                return;
            }
            _ => None,
        };
        let source = if index == 7 {
            Source::Logs(&self.log_snapshot)
        } else {
            source_for(index, store)
        };
        if let Some(amount) = amount {
            self.tables[index].move_by(amount, &source);
        }
        if matches!(key.code, KeyCode::Home | KeyCode::Char('g')) {
            self.tables[index].edge(false, &source);
        }
        if matches!(key.code, KeyCode::End | KeyCode::Char('G')) {
            self.tables[index].edge(true, &source);
        }
    }

    fn token(&mut self) -> u64 {
        self.next_token = self
            .next_token
            .checked_add(1)
            .expect("modal generation exhausted");
        self.next_token
    }

    fn open_selected(&mut self, store: &Store) -> Vec<Effect> {
        let index = self.table_index();
        let Some(row) = self.tables[index].selected() else {
            return Vec::new();
        };
        match self.active {
            0 => {
                let job = &store.merged_jobs()[row];
                self.open_job(&job.id, &job.state, history_detail(store, &job.id))
            }
            1 => {
                let node = &store.node_displays()[row];
                let token = self.token();
                self.modals.push(Modal::node(token, node.name.clone()));
                vec![Effect::FetchNode {
                    token,
                    name: node.name.clone(),
                }]
            }
            2 => {
                let user = if self.users_pending {
                    &store.pending_user_stats()[row].username
                } else {
                    &store.running_user_stats()[row].username
                };
                self.modals.push(Modal::info(user.clone(), false));
                Vec::new()
            }
            3 if self.priority_pane == 1 => {
                self.modals.push(Modal::info(
                    store.ranked_users()[row].entry.user.clone(),
                    false,
                ));
                Vec::new()
            }
            3 if self.priority_pane == 2 => {
                self.modals.push(Modal::info(
                    store.ranked_accounts()[row].entry.account.clone(),
                    true,
                ));
                Vec::new()
            }
            3 if self.priority_pane == 0 || self.priority_pane == 3 => {
                let id = &store.ranked_pending()[row].entry.job_id;
                self.open_job(id, "PENDING", None)
            }
            _ => Vec::new(),
        }
    }

    fn open_job(&mut self, id: &str, state: &str, fallback: Option<JobDetail>) -> Vec<Effect> {
        let id = store::normalize_array_job_id(id);
        let token = self.token();
        let cached = self
            .cache
            .iter()
            .find(|entry| entry.id == id && (state.is_empty() || entry.state == state))
            .map(|entry| entry.snapshot.clone());
        let terminal_cached = cached.as_ref().is_some_and(|snapshot| {
            snapshot
                .detail
                .fields
                .get("JobState")
                .is_some_and(|state| store::is_terminal_state(state))
        });
        self.modals.push(Modal::Job(DetailView {
            token,
            id: id.clone(),
            state: state.into(),
            snapshot: cached,
            loading: !terminal_cached,
            error: None,
            scroll: 0,
            horizontal: 0,
        }));
        if terminal_cached {
            Vec::new()
        } else {
            vec![Effect::FetchJob {
                token,
                job_id: id,
                state: state.into(),
                fallback,
            }]
        }
    }

    fn request_cancel(&mut self, store: &Store) -> Vec<Effect> {
        if let Some(row) = self.tables[0].selected() {
            let job = &store.merged_jobs()[row];
            if job.active && !store::is_terminal_state(&job.state) {
                self.modals.push(Modal::cancel(job.id.clone()));
            }
        }
        Vec::new()
    }

    pub fn receive(&mut self, result: ActionResult) -> Vec<Effect> {
        match result {
            ActionResult::Job {
                token,
                job_id,
                result,
            } => self.receive_job(token, job_id, result),
            ActionResult::Node {
                token,
                name,
                result,
            } => {
                self.receive_node(token, name, result);
                Vec::new()
            }
            ActionResult::Log { token, result } => {
                self.receive_log(token, result);
                Vec::new()
            }
            ActionResult::Cancel { job_id, result } => match result {
                Ok(()) => {
                    self.notify(format!("Job {job_id} cancelled"));
                    self.invalidate(&job_id);
                    vec![Effect::Refresh]
                }
                Err(error) => {
                    self.notify(error);
                    Vec::new()
                }
            },
            ActionResult::Modify { job_id, result } => self.receive_modify(job_id, result),
            ActionResult::ConfigSaved(result) => self.receive_config(result),
            ActionResult::EditorDone(result) => {
                if let Err(error) = result {
                    self.notify(error);
                }
                self.reload_log()
            }
        }
    }

    fn receive_job(
        &mut self,
        token: u64,
        id: String,
        result: Result<JobSnapshot, String>,
    ) -> Vec<Effect> {
        let Some(Modal::Job(view)) = self.modals.iter_mut().find(
            |modal| matches!(modal, Modal::Job(view) if view.token == token && view.id == id),
        ) else {
            return Vec::new();
        };
        view.loading = false;
        match result {
            Ok(snapshot) => {
                view.state = snapshot
                    .detail
                    .fields
                    .get("JobState")
                    .cloned()
                    .unwrap_or_else(|| view.state.clone());
                view.error = None;
                view.snapshot = Some(snapshot.clone());
                self.cache.retain(|entry| entry.id != id);
                if store::is_terminal_state(&view.state) {
                    if self.cache.len() == CACHE_CAPACITY {
                        self.cache.pop_front();
                    }
                    self.cache.push_back(CachedDetail {
                        id,
                        state: view.state.clone(),
                        snapshot,
                    });
                }
            }
            Err(error) => {
                view.error = Some(error);
            }
        }
        debug_assert!(self.cache.len() <= CACHE_CAPACITY);
        Vec::new()
    }

    fn invalidate(&mut self, id: &str) {
        let family = id.split('_').next().unwrap_or(id);
        self.cache
            .retain(|entry| entry.id.split('_').next().unwrap_or(&entry.id) != family);
    }

    pub fn render(&mut self, frame: &mut Frame<'_>, store: &Store, status: &RuntimeStatus<'_>) {
        if self.today != status.today {
            self.today = status.today;
        }
        if self.active == 4 {
            self.log_snapshot = status.logs.snapshot();
            self.tables[7].rebuild(&Source::Logs(&self.log_snapshot), self.today);
        }
        self.render_frame(frame, store, status);
    }
}

fn source_for(index: usize, store: &Store) -> Source<'_> {
    match index {
        0 => Source::Jobs(store.merged_jobs()),
        1 => Source::Nodes(store.node_displays()),
        2 => Source::Running(store.running_user_stats()),
        3 => Source::Pending(store.pending_user_stats()),
        4 => Source::Shares(store.ranked_users(), false),
        5 => Source::Accounts(store.ranked_accounts(), &store.fair_share),
        8 => Source::MyPriority(store.ranked_pending(), &store.user),
        _ => Source::Priority(store.ranked_pending()),
    }
}

fn append_bounded(target: &mut String, text: &str) {
    let remaining = INPUT_LIMIT.saturating_sub(target.len());
    let mut end = text.len().min(remaining);
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    target.push_str(&text[..end]);
    debug_assert!(target.len() <= INPUT_LIMIT);
}

fn history_detail(store: &Store, id: &str) -> Option<JobDetail> {
    let id = store::normalize_array_job_id(id);
    store
        .history_jobs
        .iter()
        .find(|job| store::normalize_array_job_id(&job.id) == id)
        .map(|job| {
            let fields = [
                ("JobId", &job.id),
                ("JobName", &job.name),
                ("JobState", &job.state),
                ("RunTime", &job.elapsed),
                ("ExitCode", &job.exit_code),
                ("Restarts", &job.restart),
                ("NodeList", &job.node_list),
                ("SubmitTime", &job.submit),
                ("StartTime", &job.start),
                ("EndTime", &job.end),
                ("StdOut", &job.std_out),
                ("StdErr", &job.std_err),
            ]
            .into_iter()
            .filter(|(_, value)| !value.trim().is_empty())
            .map(|(key, value)| (key.into(), value.clone()))
            .collect();
            JobDetail {
                fields,
                source: "journal".into(),
            }
        })
}

#[cfg(test)]
mod tests;
