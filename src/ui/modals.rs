use std::path::PathBuf;

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};

use crate::config::{Config, THEMES};
use crate::store::{self, JobDetail, Store};

use super::{Effect, JobSnapshot, Tail, Ui, append_bounded};

pub(super) enum Modal {
    Job(DetailView),
    Node(NodeView),
    Info {
        name: String,
        account: bool,
        scroll: u16,
        horizontal: u16,
    },
    Log(LogView),
    Modify(ModifyView),
    Cancel {
        id: String,
        yes: bool,
    },
    Input {
        text: String,
        error: Option<String>,
    },
    Settings(SettingsView),
    Help {
        scroll: u16,
        horizontal: u16,
    },
    Load {
        scroll: u16,
        horizontal: u16,
    },
}

pub(super) struct DetailView {
    pub token: u64,
    pub id: String,
    pub state: String,
    pub snapshot: Option<JobSnapshot>,
    pub loading: bool,
    pub error: Option<String>,
    pub scroll: u16,
    pub horizontal: u16,
}

pub(super) struct NodeView {
    pub token: u64,
    pub name: String,
    pub detail: Option<JobDetail>,
    pub loading: bool,
    pub error: Option<String>,
    pub scroll: u16,
    pub horizontal: u16,
}

pub(super) struct LogView {
    pub token: u64,
    pub path: PathBuf,
    pub label: String,
    pub tail: Option<Tail>,
    pub loading: bool,
    pub error: Option<String>,
    pub offset: usize,
    pub horizontal: u16,
    pub height: usize,
    pub show_lines: bool,
    pub search: String,
    pub searching: bool,
    pub matches: Vec<usize>,
    pub matched: usize,
}

pub(super) struct ModifyRow {
    pub key: String,
    pub target: String,
    pub value: String,
}

pub(super) struct ModifyView {
    pub id: String,
    pub rows: Vec<ModifyRow>,
    pub selected: usize,
    pub editing: bool,
    pub input: String,
    pub error: Option<String>,
    pub pending_id: Option<String>,
}

pub(super) struct SettingsView {
    pub draft: Config,
    pub values: [String; 5],
    pub field: usize,
    pub error: Option<String>,
    pub saving: bool,
}

impl Modal {
    pub fn node(token: u64, name: String) -> Self {
        Self::Node(NodeView {
            token,
            name,
            detail: None,
            loading: true,
            error: None,
            scroll: 0,
            horizontal: 0,
        })
    }
    pub fn info(name: String, account: bool) -> Self {
        Self::Info {
            name,
            account,
            scroll: 0,
            horizontal: 0,
        }
    }
    pub fn help() -> Self {
        Self::Help {
            scroll: 0,
            horizontal: 0,
        }
    }
    pub fn load() -> Self {
        Self::Load {
            scroll: 0,
            horizontal: 0,
        }
    }
    pub fn cancel(id: String) -> Self {
        Self::Cancel { id, yes: false }
    }
    pub fn job_input() -> Self {
        Self::Input {
            text: String::new(),
            error: None,
        }
    }
    pub fn settings(config: Config) -> Self {
        let values = [
            config.theme.clone(),
            config.refresh_interval.to_string(),
            config.job_history_days.to_string(),
            config.log_viewer_lines.to_string(),
            config.keybind_mode.clone(),
        ];
        Self::Settings(SettingsView {
            draft: config,
            values,
            field: 0,
            error: None,
            saving: false,
        })
    }
}

type Response = (bool, Vec<Effect>, Option<Modal>);

impl Ui {
    pub(super) fn handle_modal(&mut self, key: KeyEvent, store: &Store) -> Vec<Effect> {
        if key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL) {
            return vec![Effect::Quit];
        }
        let Some(mut modal) = self.modals.pop() else {
            return Vec::new();
        };
        let (keep, effects, next) = match &mut modal {
            Modal::Job(view) => self.handle_detail(key, view),
            Modal::Node(view) => {
                let keep = scroll_key(key, &mut view.scroll, &mut view.horizontal);
                (keep, Vec::new(), None)
            }
            Modal::Info {
                scroll, horizontal, ..
            }
            | Modal::Help { scroll, horizontal }
            | Modal::Load { scroll, horizontal } => {
                let keep = scroll_key(key, scroll, horizontal);
                (keep, Vec::new(), None)
            }
            Modal::Cancel { id, yes } => handle_cancel(key, id, yes),
            Modal::Input { text, error } => self.handle_job_input(key, text, error, store),
            Modal::Log(view) => self.handle_log(key, view),
            Modal::Modify(view) => handle_modify(key, view),
            Modal::Settings(view) => handle_settings(key, view),
        };
        if keep {
            self.modals.push(modal);
        }
        if let Some(next) = next {
            self.modals.push(next);
        }
        debug_assert!(self.modals.len() <= 4);
        effects
    }

    fn handle_detail(&mut self, key: KeyEvent, view: &mut DetailView) -> Response {
        if key.code == KeyCode::Char('r') && !view.loading {
            view.token = self.token();
            view.loading = true;
            return (
                true,
                vec![Effect::FetchJob {
                    token: view.token,
                    job_id: view.id.clone(),
                    state: view.state.clone(),
                    fallback: view
                        .snapshot
                        .as_ref()
                        .map(|snapshot| snapshot.detail.clone()),
                }],
                None,
            );
        }
        if let KeyCode::Char(ch @ ('o' | 'e')) = key.code {
            let path = view
                .snapshot
                .as_ref()
                .and_then(|snapshot| {
                    snapshot
                        .detail
                        .fields
                        .get(if ch == 'o' { "StdOut" } else { "StdErr" })
                })
                .filter(|path| {
                    !path.is_empty() && !["(null)", "N/A", "None"].contains(&path.as_str())
                })
                .cloned();
            if let Some(path) = path {
                return self.log_response(
                    PathBuf::from(path),
                    if ch == 'o' { "stdout" } else { "stderr" },
                );
            }
            self.notify("No log path is available for this job".into());
            return (true, Vec::new(), None);
        }
        if key.code == KeyCode::Char('m')
            && let Some(snapshot) = &view.snapshot
        {
            return (
                true,
                Vec::new(),
                Some(Modal::Modify(modify_view(&view.id, &snapshot.detail))),
            );
        }
        let keep = scroll_key(key, &mut view.scroll, &mut view.horizontal);
        (keep, Vec::new(), None)
    }

    fn log_response(&mut self, path: PathBuf, label: &str) -> Response {
        let token = self.token();
        let view = LogView {
            token,
            path: path.clone(),
            label: label.into(),
            tail: None,
            loading: true,
            error: None,
            offset: usize::MAX,
            horizontal: 0,
            height: 1,
            show_lines: true,
            search: String::new(),
            searching: false,
            matches: Vec::new(),
            matched: 0,
        };
        (
            true,
            vec![Effect::FetchLog {
                token,
                path,
                max_lines: self.config.log_viewer_lines,
            }],
            Some(Modal::Log(view)),
        )
    }

    fn handle_job_input(
        &mut self,
        key: KeyEvent,
        text: &mut String,
        error: &mut Option<String>,
        store: &Store,
    ) -> Response {
        if matches!(key.code, KeyCode::Esc) {
            return (false, Vec::new(), None);
        }
        if key.code == KeyCode::Enter {
            let id = text.trim();
            if !valid_job_id(id) {
                *error = Some("Enter a numeric job ID or an array task ID (123_4)".into());
                return (true, Vec::new(), None);
            }
            let state = store
                .merged_jobs()
                .iter()
                .find(|job| job.id == id || store::normalize_array_job_id(&job.id) == id)
                .map(|job| job.state.as_str())
                .unwrap_or("");
            let effects = self.open_job(id, state, store.journal_detail(id));
            let next = self.modals.pop();
            return (false, effects, next);
        }
        edit_key(key, text);
        *error = None;
        (true, Vec::new(), None)
    }

    fn handle_log(&mut self, key: KeyEvent, view: &mut LogView) -> Response {
        if view.searching {
            match key.code {
                KeyCode::Esc => view.searching = false,
                KeyCode::Enter => {
                    view.searching = false;
                    view.find_matches();
                }
                _ => {
                    edit_key(key, &mut view.search);
                }
            }
            return (true, Vec::new(), None);
        }
        match key.code {
            KeyCode::Esc | KeyCode::Char('q') => return (false, Vec::new(), None),
            KeyCode::Char('/') => view.searching = true,
            KeyCode::Char('n') => view.next_match(false),
            KeyCode::Char('N') => view.next_match(true),
            KeyCode::Char('r') if !view.loading => {
                view.token = self.token();
                view.loading = true;
                return (
                    true,
                    vec![Effect::FetchLog {
                        token: view.token,
                        path: view.path.clone(),
                        max_lines: self.config.log_viewer_lines,
                    }],
                    None,
                );
            }
            KeyCode::Char('c') => {
                return (
                    true,
                    vec![Effect::Copy(view.path.to_string_lossy().into_owned())],
                    None,
                );
            }
            KeyCode::Char('e') => return (true, vec![Effect::Editor(view.path.clone())], None),
            KeyCode::Char('l') => view.show_lines = !view.show_lines,
            KeyCode::Char('g') | KeyCode::Home => view.offset = 0,
            KeyCode::Char('G') | KeyCode::End => view.offset = view.max_offset(),
            KeyCode::Up | KeyCode::Char('k') => view.offset = view.offset.saturating_sub(1),
            KeyCode::Down | KeyCode::Char('j') => {
                view.offset = view.offset.saturating_add(1).min(view.max_offset())
            }
            KeyCode::PageUp => view.offset = view.offset.saturating_sub(view.height.max(1)),
            KeyCode::PageDown => {
                view.offset = view
                    .offset
                    .saturating_add(view.height.max(1))
                    .min(view.max_offset())
            }
            KeyCode::Left => view.horizontal = view.horizontal.saturating_sub(8),
            KeyCode::Right => view.horizontal = view.horizontal.saturating_add(8).min(8192),
            _ => {}
        }
        (true, Vec::new(), None)
    }

    pub(super) fn receive_node(
        &mut self,
        token: u64,
        name: String,
        result: Result<JobDetail, String>,
    ) {
        let Some(Modal::Node(view)) = self.modals.iter_mut().find(
            |modal| matches!(modal, Modal::Node(view) if view.token == token && view.name == name),
        ) else {
            return;
        };
        view.loading = false;
        match result {
            Ok(detail) => {
                view.detail = Some(detail);
                view.error = None;
            }
            Err(error) => view.error = Some(error),
        }
    }

    pub(super) fn receive_log(&mut self, token: u64, result: Result<Tail, String>) {
        let Some(Modal::Log(view)) = self
            .modals
            .iter_mut()
            .find(|modal| matches!(modal, Modal::Log(view) if view.token == token))
        else {
            return;
        };
        view.loading = false;
        match result {
            Ok(tail) => {
                if tail.path != view.path {
                    return;
                }
                let at_bottom = view.tail.is_none() || view.offset >= view.max_offset();
                view.tail = Some(tail);
                view.error = None;
                view.offset = if at_bottom {
                    view.max_offset()
                } else {
                    view.offset.min(view.max_offset())
                };
                view.find_matches();
            }
            Err(error) => view.error = Some(error),
        }
    }

    pub(super) fn reload_log(&mut self) -> Vec<Effect> {
        let token = self.token();
        let Some(Modal::Log(view)) = self.modals.last_mut() else {
            return Vec::new();
        };
        view.token = token;
        view.loading = true;
        vec![Effect::FetchLog {
            token,
            path: view.path.clone(),
            max_lines: self.config.log_viewer_lines,
        }]
    }

    pub(super) fn receive_modify(&mut self, id: String, result: Result<(), String>) -> Vec<Effect> {
        let position = self.modals.iter().position(|modal| matches!(modal, Modal::Modify(view) if view.pending_id.as_deref() == Some(id.as_str())));
        if let Err(error) = result {
            if let Some(position) = position {
                if let Modal::Modify(view) = &mut self.modals[position] {
                    view.pending_id = None;
                    view.error = Some(error);
                }
            } else {
                self.notify(error);
            }
            return Vec::new();
        }
        if let Some(position) = position {
            self.modals.remove(position);
        }
        self.invalidate(&id);
        self.notify(format!("Job {id} updated"));
        let token = self.token();
        let mut effects = vec![Effect::Refresh];
        if let Some(Modal::Job(view)) = self
            .modals
            .iter_mut()
            .rev()
            .find(|modal| matches!(modal, Modal::Job(_)))
        {
            view.token = token;
            view.loading = true;
            effects.push(Effect::FetchJob {
                token,
                job_id: view.id.clone(),
                state: view.state.clone(),
                fallback: view
                    .snapshot
                    .as_ref()
                    .map(|snapshot| snapshot.detail.clone()),
            });
        }
        effects
    }

    pub(super) fn receive_config(&mut self, result: Result<(), String>) -> Vec<Effect> {
        let Some(position) = self
            .modals
            .iter()
            .position(|modal| matches!(modal, Modal::Settings(view) if view.saving))
        else {
            return Vec::new();
        };
        match result {
            Ok(()) => {
                if let Modal::Settings(view) = self.modals.remove(position) {
                    self.config = view.draft;
                }
                self.notify("Settings saved".into());
                vec![Effect::Refresh]
            }
            Err(error) => {
                if let Modal::Settings(view) = &mut self.modals[position] {
                    view.saving = false;
                    view.error = Some(error);
                }
                Vec::new()
            }
        }
    }

    pub(super) fn paste_modal(&mut self, text: &str) {
        match self.modals.last_mut() {
            Some(Modal::Input {
                text: target,
                error,
            }) => {
                append_bounded(target, text);
                *error = None;
            }
            Some(Modal::Log(view)) if view.searching => append_bounded(&mut view.search, text),
            Some(Modal::Modify(view)) if view.editing && view.pending_id.is_none() => {
                append_bounded(&mut view.input, text)
            }
            Some(Modal::Settings(view)) if (1..=3).contains(&view.field) && !view.saving => {
                append_bounded(&mut view.values[view.field], text)
            }
            _ => {}
        }
    }
}

impl LogView {
    pub fn max_offset(&self) -> usize {
        self.tail.as_ref().map_or(0, |tail| {
            tail.lines.len().saturating_sub(self.height.max(1))
        })
    }
    pub fn find_matches(&mut self) {
        self.matches.clear();
        if !self.search.is_empty() {
            let needle = self.search.to_lowercase();
            if let Some(tail) = &self.tail {
                self.matches.extend(
                    tail.lines
                        .iter()
                        .enumerate()
                        .filter(|(_, line)| line.to_lowercase().contains(&needle))
                        .map(|(index, _)| index),
                );
            }
        }
        self.matched = self
            .matches
            .iter()
            .position(|index| *index >= self.offset)
            .unwrap_or(0);
        if let Some(index) = self.matches.get(self.matched) {
            self.offset = (*index).min(self.max_offset());
        }
    }
    fn next_match(&mut self, reverse: bool) {
        if self.matches.is_empty() {
            return;
        }
        self.matched = if reverse {
            (self.matched + self.matches.len() - 1) % self.matches.len()
        } else {
            (self.matched + 1) % self.matches.len()
        };
        self.offset = self.matches[self.matched].min(self.max_offset());
    }
}

fn handle_cancel(key: KeyEvent, id: &str, yes: &mut bool) -> Response {
    match key.code {
        KeyCode::Esc | KeyCode::Char('n') | KeyCode::Char('q') => (false, Vec::new(), None),
        KeyCode::Left | KeyCode::Right | KeyCode::Tab | KeyCode::BackTab => {
            *yes = !*yes;
            (true, Vec::new(), None)
        }
        KeyCode::Char('y') => (false, vec![Effect::Cancel { job_id: id.into() }], None),
        KeyCode::Enter => (
            false,
            if *yes {
                vec![Effect::Cancel { job_id: id.into() }]
            } else {
                Vec::new()
            },
            None,
        ),
        _ => (true, Vec::new(), None),
    }
}

fn modify_view(id: &str, detail: &JobDetail) -> ModifyView {
    let mut rows = Vec::new();
    if let Some(leader) = detail
        .fields
        .get("ArrayJobId")
        .filter(|value| !value.is_empty() && value.as_str() != "N/A")
    {
        rows.push(ModifyRow {
            key: "ArrayTaskThrottle".into(),
            target: leader.clone(),
            value: detail
                .fields
                .get("ArrayTaskThrottle")
                .cloned()
                .unwrap_or_default(),
        });
    }
    rows.extend(
        ["Partition", "TimeLimit", "QOS", "Nice", "JobName"]
            .into_iter()
            .map(|key| ModifyRow {
                key: key.into(),
                target: id.into(),
                value: detail.fields.get(key).cloned().unwrap_or_default(),
            }),
    );
    let held = detail
        .fields
        .get("Priority")
        .is_some_and(|priority| priority == "0")
        || detail
            .fields
            .get("Reason")
            .is_some_and(|reason| reason.contains("JobHeld"));
    rows.push(ModifyRow {
        key: if held { "Release" } else { "Hold" }.into(),
        target: id.into(),
        value: String::new(),
    });
    rows.push(ModifyRow {
        key: "Other Key=Value".into(),
        target: id.into(),
        value: String::new(),
    });
    ModifyView {
        id: id.into(),
        rows,
        selected: 0,
        editing: false,
        input: String::new(),
        error: None,
        pending_id: None,
    }
}

fn handle_modify(key: KeyEvent, view: &mut ModifyView) -> Response {
    if view.pending_id.is_some() {
        return (true, Vec::new(), None);
    }
    if view.editing {
        match key.code {
            KeyCode::Esc => {
                view.editing = false;
                view.error = None;
            }
            KeyCode::Enter => return submit_modify(view),
            _ => {
                edit_key(key, &mut view.input);
                view.error = None;
            }
        }
        return (true, Vec::new(), None);
    }
    match key.code {
        KeyCode::Esc | KeyCode::Char('q') => return (false, Vec::new(), None),
        KeyCode::Up | KeyCode::Char('k') => view.selected = view.selected.saturating_sub(1),
        KeyCode::Down | KeyCode::Char('j') | KeyCode::Tab => {
            view.selected = (view.selected + 1).min(view.rows.len() - 1)
        }
        KeyCode::Enter => {
            let row = &view.rows[view.selected];
            if row.key == "Hold" || row.key == "Release" {
                view.pending_id = Some(row.target.clone());
                return (
                    true,
                    vec![Effect::Hold {
                        job_id: row.target.clone(),
                        hold: row.key == "Hold",
                    }],
                    None,
                );
            }
            view.input = row.value.clone();
            view.editing = true;
            view.error = None;
        }
        _ => {}
    }
    (true, Vec::new(), None)
}

fn submit_modify(view: &mut ModifyView) -> Response {
    let row = &view.rows[view.selected];
    let value = view.input.trim();
    if value.is_empty() || value == row.value {
        view.editing = false;
        view.error = None;
        return (true, Vec::new(), None);
    }
    let fields = if row.key == "Other Key=Value" {
        let Some((key, value)) = value.split_once('=') else {
            view.error = Some("Use Key=Value".into());
            return (true, Vec::new(), None);
        };
        if key.trim().is_empty()
            || value.trim().is_empty()
            || !key
                .chars()
                .all(|ch| ch.is_ascii_alphanumeric() || ch == '_')
        {
            view.error = Some("Use a field name and a nonempty value".into());
            return (true, Vec::new(), None);
        }
        vec![(key.trim().into(), value.trim().into())]
    } else {
        vec![(row.key.clone(), value.into())]
    };
    view.pending_id = Some(row.target.clone());
    (
        true,
        vec![Effect::Modify {
            job_id: row.target.clone(),
            fields,
        }],
        None,
    )
}

fn handle_settings(key: KeyEvent, view: &mut SettingsView) -> Response {
    if view.saving {
        return (true, Vec::new(), None);
    }
    if key.code == KeyCode::Esc {
        return (false, Vec::new(), None);
    }
    if key.code == KeyCode::Char('s') && key.modifiers.contains(KeyModifiers::CONTROL)
        || key.code == KeyCode::Enter && view.field == 4
    {
        return match settings_config(view) {
            Ok(config) => {
                view.draft = config.clone();
                view.saving = true;
                (true, vec![Effect::SaveConfig(config)], None)
            }
            Err(error) => {
                view.error = Some(error);
                (true, Vec::new(), None)
            }
        };
    }
    match key.code {
        KeyCode::Up | KeyCode::BackTab => view.field = (view.field + 4) % 5,
        KeyCode::Down | KeyCode::Tab | KeyCode::Enter => view.field = (view.field + 1) % 5,
        KeyCode::Left | KeyCode::Right if view.field == 0 || view.field == 4 => {
            let options: &[&str] = if view.field == 0 {
                &THEMES
            } else {
                &["vim", "emacs"]
            };
            let index = options
                .iter()
                .position(|value| *value == view.values[view.field])
                .unwrap_or(0);
            let next = (index
                + if key.code == KeyCode::Right {
                    1
                } else {
                    options.len() - 1
                })
                % options.len();
            view.values[view.field] = options[next].into();
        }
        _ if (1..=3).contains(&view.field) => {
            edit_key(key, &mut view.values[view.field]);
        }
        _ => {}
    }
    view.error = None;
    (true, Vec::new(), None)
}

fn settings_config(view: &SettingsView) -> Result<Config, String> {
    let refresh: f64 = view.values[1]
        .parse()
        .map_err(|_| "Refresh interval must be a number")?;
    let days: u32 = view.values[2]
        .parse()
        .map_err(|_| "History days must be an integer")?;
    let lines: usize = view.values[3]
        .parse()
        .map_err(|_| "Log lines must be an integer")?;
    if !refresh.is_finite() || !(120.0..=300.0).contains(&refresh) {
        return Err("Refresh interval must be between 120 and 300 seconds".into());
    }
    if !(1..=90).contains(&days) {
        return Err("History days must be between 1 and 90".into());
    }
    if !(500..=100_000).contains(&lines) {
        return Err("Log lines must be between 500 and 100000".into());
    }
    Ok(Config {
        theme: view.values[0].clone(),
        refresh_interval: refresh,
        job_history_days: days,
        log_viewer_lines: lines,
        keybind_mode: view.values[4].clone(),
    })
}

fn edit_key(key: KeyEvent, text: &mut String) {
    match key.code {
        KeyCode::Backspace => {
            text.pop();
        }
        KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => text.clear(),
        KeyCode::Char(ch)
            if !key
                .modifiers
                .intersects(KeyModifiers::CONTROL | KeyModifiers::ALT) =>
        {
            append_bounded(text, &ch.to_string())
        }
        _ => {}
    }
}

fn scroll_key(key: KeyEvent, scroll: &mut u16, horizontal: &mut u16) -> bool {
    match key.code {
        KeyCode::Esc | KeyCode::Char('q') => return false,
        KeyCode::Up | KeyCode::Char('k') => *scroll = scroll.saturating_sub(1),
        KeyCode::Down | KeyCode::Char('j') => *scroll = scroll.saturating_add(1),
        KeyCode::PageUp => *scroll = scroll.saturating_sub(15),
        KeyCode::PageDown => *scroll = scroll.saturating_add(15),
        KeyCode::Home | KeyCode::Char('g') => *scroll = 0,
        KeyCode::End | KeyCode::Char('G') => *scroll = u16::MAX,
        KeyCode::Left | KeyCode::Char('h') => *horizontal = horizontal.saturating_sub(8),
        KeyCode::Right | KeyCode::Char('l') => *horizontal = horizontal.saturating_add(8),
        _ => {}
    }
    true
}

fn valid_job_id(value: &str) -> bool {
    if value.len() > 128 {
        return false;
    }
    let mut parts = value.split('_');
    let Some(leader) = parts.next() else {
        return false;
    };
    if leader.is_empty()
        || !leader.chars().all(|ch| ch.is_ascii_digit())
        || leader.parse::<u64>().is_err()
    {
        return false;
    }
    if let Some(task) = parts.next()
        && (task.is_empty()
            || !task.chars().all(|ch| ch.is_ascii_digit())
            || task.parse::<u64>().is_err())
    {
        return false;
    }
    parts.next().is_none()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(code: KeyCode) -> KeyEvent {
        KeyEvent::new(code, KeyModifiers::NONE)
    }

    fn scroll_position(modal: &Modal) -> (u16, u16) {
        match modal {
            Modal::Job(view) => (view.scroll, view.horizontal),
            Modal::Node(view) => (view.scroll, view.horizontal),
            Modal::Info {
                scroll, horizontal, ..
            }
            | Modal::Help { scroll, horizontal }
            | Modal::Load { scroll, horizontal } => (*scroll, *horizontal),
            _ => panic!("expected a scrollable modal"),
        }
    }

    #[test]
    fn details_help_and_load_pan_without_moving_the_selected_line() {
        let modals = [
            Modal::Job(DetailView {
                token: 1,
                id: "123".into(),
                state: "RUNNING".into(),
                snapshot: None,
                loading: false,
                error: None,
                scroll: 0,
                horizontal: 0,
            }),
            Modal::node(2, "n001".into()),
            Modal::info("alice".into(), false),
            Modal::help(),
            Modal::load(),
        ];
        let store = Store::default();
        for modal in modals {
            let mut ui = Ui::new(Config::default());
            ui.modals.push(modal);
            assert!(ui.handle_modal(key(KeyCode::Right), &store).is_empty());
            ui.handle_modal(key(KeyCode::Char('l')), &store);
            assert_eq!(scroll_position(ui.modals.last().unwrap()), (0, 16));
            ui.handle_modal(key(KeyCode::Down), &store);
            ui.handle_modal(key(KeyCode::Left), &store);
            assert_eq!(scroll_position(ui.modals.last().unwrap()), (1, 8));
            ui.handle_modal(key(KeyCode::Char('h')), &store);
            assert_eq!(scroll_position(ui.modals.last().unwrap()), (1, 0));
            ui.handle_modal(key(KeyCode::Esc), &store);
            assert!(ui.modals.is_empty());
        }
    }

    #[test]
    fn modal_scroll_offsets_saturate_at_both_bounds() {
        let mut scroll = 0;
        let mut horizontal = 0;
        assert!(scroll_key(key(KeyCode::Left), &mut scroll, &mut horizontal));
        assert_eq!((scroll, horizontal), (0, 0));
        scroll = u16::MAX;
        horizontal = u16::MAX - 1;
        scroll_key(key(KeyCode::Right), &mut scroll, &mut horizontal);
        scroll_key(key(KeyCode::Down), &mut scroll, &mut horizontal);
        assert_eq!((scroll, horizontal), (u16::MAX, u16::MAX));
        assert!(!scroll_key(key(KeyCode::Esc), &mut scroll, &mut horizontal));
        assert_eq!((scroll, horizontal), (u16::MAX, u16::MAX));
    }

    #[test]
    fn cancellation_defaults_to_no_and_needs_an_explicit_choice() {
        let mut yes = false;
        assert!(
            handle_cancel(key(KeyCode::Enter), "123", &mut yes)
                .1
                .is_empty()
        );
        handle_cancel(key(KeyCode::Tab), "123", &mut yes);
        assert!(
            matches!(handle_cancel(key(KeyCode::Enter), "123", &mut yes).1.first(), Some(Effect::Cancel { job_id }) if job_id == "123")
        );
    }

    #[test]
    fn array_throttle_targets_the_leader_and_raw_fields_validate_inline() {
        let mut detail = JobDetail::default();
        detail.fields.insert("ArrayJobId".into(), "123".into());
        let mut view = modify_view("123_4", &detail);
        view.input = "8".into();
        assert!(
            matches!(submit_modify(&mut view).1.first(), Some(Effect::Modify { job_id, fields }) if job_id == "123" && fields[0] == ("ArrayTaskThrottle".into(), "8".into()))
        );
        let mut view = modify_view("123_4", &detail);
        view.selected = view.rows.len() - 1;
        view.input = "bad".into();
        assert!(submit_modify(&mut view).1.is_empty());
        assert!(view.error.is_some());
    }

    #[test]
    fn literal_log_search_wraps_both_directions() {
        let mut view = LogView {
            token: 1,
            path: "log".into(),
            label: "stdout".into(),
            tail: Some(Tail {
                lines: vec!["Alpha [1]".into(), "nothing".into(), "ALPHA [1]".into()],
                first_line: 90,
                total_lines: 92,
                path: "log".into(),
            }),
            loading: false,
            error: None,
            offset: 0,
            horizontal: 0,
            height: 1,
            show_lines: true,
            search: "[1]".into(),
            searching: false,
            matches: Vec::new(),
            matched: 0,
        };
        view.find_matches();
        assert_eq!(view.matches, [0, 2]);
        view.next_match(true);
        assert_eq!(view.offset, 2);
        view.next_match(false);
        assert_eq!(view.offset, 0);
    }
}
