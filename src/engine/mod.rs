mod input;
mod io;
pub mod scheduler;
mod terminal;
mod worker;

use std::collections::VecDeque;
use std::io::{IsTerminal, Stdout};
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, SyncSender, TrySendError};
use std::time::{Duration, Instant};

use crossterm::cursor::{Hide, Show};
use crossterm::event::{
    DisableBracketedPaste, EnableBracketedPaste, Event as TerminalEvent, KeyEventKind,
};
use crossterm::execute;
use crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode,
};
use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;

use crate::VERSION;
use crate::config::Config;
use crate::log::LogRing;
use crate::slurm::{Client, CommandError, ExecRunner, HistoryJob, Runner};
use crate::store::{Dataset, Section, State, Store};
use crate::ui::{ActionResult, Effect, RuntimeStatus, Ui};
use crate::update;

use input::{Directive as InputDirective, Input};
use scheduler::{SECTIONS, Scheduler};
use worker::{Work, Workers};

enum Event {
    Input(TerminalEvent),
    Data {
        section: Section,
        generation: u64,
        result: Result<Dataset, String>,
    },
    Action(ActionResult),
    Completed(Result<Option<HistoryJob>, String>),
    Available(Result<(), String>),
    Latest(Result<String, String>),
    Copy {
        text: String,
        result: Result<(), String>,
    },
    WorkerError(String),
    Quit,
}

fn send_event(events: &SyncSender<Event>, event: Event, stopped: &AtomicBool) -> bool {
    send_event_wait(events, event, stopped, || {
        std::thread::park_timeout(Duration::from_millis(10));
    })
}

fn send_event_wait(
    events: &SyncSender<Event>,
    mut event: Event,
    stopped: &AtomicBool,
    mut wait: impl FnMut(),
) -> bool {
    while !stopped.load(Ordering::Relaxed) {
        match events.try_send(event) {
            Ok(()) => return true,
            Err(TrySendError::Disconnected(_)) => return false,
            Err(TrySendError::Full(pending)) => event = pending,
        }
        wait();
    }
    false
}

struct LoggedRunner {
    inner: ExecRunner,
    logs: LogRing,
}

impl Runner for LoggedRunner {
    fn run(
        &self,
        name: &str,
        arguments: &[String],
        timeout: Duration,
    ) -> Result<String, CommandError> {
        let started = Instant::now();
        let result = self.inner.run(name, arguments, timeout);
        let command = std::iter::once(name.to_owned())
            .chain(arguments.iter().map(|argument| {
                if argument.chars().count() <= 40 {
                    argument.clone()
                } else {
                    format!("{}…", argument.chars().take(39).collect::<String>())
                }
            }))
            .collect::<Vec<_>>()
            .join(" ");
        match &result {
            Ok(output) => self.logs.append(
                "INFO",
                format!(
                    "{command} · {} bytes · {} ms",
                    output.len(),
                    started.elapsed().as_millis()
                ),
            ),
            Err(err) => self.logs.append(
                "ERROR",
                format!("{command} · {} ms · {err}", started.elapsed().as_millis()),
            ),
        }
        result
    }
}

struct Screen {
    terminal: Terminal<CrosstermBackend<Stdout>>,
    original: terminal::State,
    active: bool,
}

impl Screen {
    fn new() -> Result<Self, String> {
        if !std::io::stdin().is_terminal() || !std::io::stdout().is_terminal() {
            return Err("an interactive terminal is required".into());
        }
        let original = terminal::State::capture().map_err(|err| err.to_string())?;
        let terminal = Terminal::new(CrosstermBackend::new(std::io::stdout()))
            .map_err(|err| err.to_string())?;
        let screen = Self {
            terminal,
            original,
            active: false,
        };
        let original = screen.original.clone();
        let previous = std::panic::take_hook();
        std::panic::set_hook(Box::new(move |info| {
            let _ = disable_raw_mode();
            let _ = original.restore();
            let _ = execute!(
                std::io::stdout(),
                DisableBracketedPaste,
                LeaveAlternateScreen,
                Show
            );
            previous(info);
        }));
        Ok(screen)
    }

    fn enter(&mut self) -> Result<(), String> {
        enable_raw_mode().map_err(|err| err.to_string())?;
        self.active = true;
        execute!(
            self.terminal.backend_mut(),
            EnterAlternateScreen,
            EnableBracketedPaste,
            Hide
        )
        .map_err(|err| err.to_string())?;
        self.terminal.clear().map_err(|err| err.to_string())
    }

    fn leave(&mut self) -> Result<(), String> {
        if !self.active {
            return self.original.restore().map_err(|err| err.to_string());
        }
        self.active = false;
        let raw = disable_raw_mode();
        let state = self.original.restore();
        let screen = execute!(
            self.terminal.backend_mut(),
            DisableBracketedPaste,
            LeaveAlternateScreen,
            Show
        );
        raw.and(state).and(screen).map_err(|err| err.to_string())
    }
}

impl Drop for Screen {
    fn drop(&mut self) {
        let _ = self.leave();
        let _ = self.original.restore();
        let _ = execute!(
            self.terminal.backend_mut(),
            DisableBracketedPaste,
            LeaveAlternateScreen,
            Show
        );
    }
}

struct Runtime {
    ui: Ui,
    store: Store,
    scheduler: Scheduler,
    workers: Workers,
    events: Receiver<Event>,
    input: Input,
    logs: LogRing,
    screen: Screen,
    latest: Option<String>,
    unavailable: Option<String>,
    dirty: bool,
    suspended: bool,
    quit: bool,
}

pub fn run(
    config: Config,
    config_path: PathBuf,
    journal_path: PathBuf,
    config_error: Option<String>,
) -> Result<(), String> {
    let logs = LogRing::default();
    logs.append(
        "INFO",
        format!("stoei {VERSION} · config {}", config_path.display()),
    );
    let shutdown = Arc::new(AtomicBool::new(false));
    let runner: Arc<dyn Runner> = Arc::new(LoggedRunner {
        inner: ExecRunner::new(shutdown.clone()),
        logs: logs.clone(),
    });
    let user = std::env::var("USER")
        .or_else(|_| std::env::var("USERNAME"))
        .map_err(|_| "cannot resolve username")?;
    let client = Arc::new(Client::new(runner, user.clone(), journal_path));
    let (events_tx, events) = mpsc::sync_channel(64);
    let mut screen = Screen::new()?;
    let input = Input::new(events_tx.clone(), shutdown.clone())?;
    screen.enter()?;
    let workers = Workers::new(client, config_path, events_tx, shutdown)?;
    let now = Instant::now();
    let scheduler = Scheduler::new(now, &config, u64::from(std::process::id()));
    let mut store = Store::default();
    store.user = user;
    let mut runtime = Runtime {
        ui: Ui::new(config),
        store,
        scheduler,
        workers,
        events,
        input,
        logs,
        screen,
        latest: None,
        unavailable: None,
        dirty: true,
        suspended: false,
        quit: false,
    };
    if let Some(err) = config_error {
        runtime.notify(format!("Config: {err}; using defaults"));
    }
    runtime.workers.enqueue(Work::Available)?;
    if update::semver(VERSION).is_some() {
        runtime.workers.enqueue(Work::Latest)?;
    }
    runtime.event_loop()
}

impl Runtime {
    fn notify(&mut self, message: String) {
        self.logs.append("INFO", message.clone());
        self.ui.notify(message);
        self.dirty = true;
    }

    fn event_loop(&mut self) -> Result<(), String> {
        while !self.quit && !self.input.stopped() {
            let now = Instant::now();
            self.dirty |= self.ui.expire(now);
            self.dispatch_due(now);
            if self.dirty && !self.suspended {
                self.draw()?;
            }
            let event = match self.next_deadline() {
                Some(deadline) => match self
                    .events
                    .recv_timeout(deadline.saturating_duration_since(Instant::now()))
                {
                    Ok(event) => Some(event),
                    Err(mpsc::RecvTimeoutError::Timeout) => None,
                    Err(mpsc::RecvTimeoutError::Disconnected) => {
                        return Err("event channel disconnected".into());
                    }
                },
                None => Some(
                    self.events
                        .recv()
                        .map_err(|_| "event channel disconnected")?,
                ),
            };
            if let Some(event) = event {
                self.process(event)?;
            }
        }
        self.screen.leave()
    }

    fn next_deadline(&self) -> Option<Instant> {
        self.scheduler
            .next_deadline(
                self.ui.history_visible(),
                self.ui.needs_priority(),
                &self.store,
            )
            .into_iter()
            .chain(self.ui.next_deadline())
            .min()
    }

    fn draw(&mut self) -> Result<(), String> {
        let status = RuntimeStatus {
            version: VERSION,
            update_available: self.latest.as_deref(),
            logs: &self.logs,
            today: chrono::Local::now().date_naive(),
            unavailable: self.unavailable.as_deref(),
            now: Instant::now(),
        };
        self.screen
            .terminal
            .draw(|frame| self.ui.render(frame, &self.store, &status))
            .map_err(|err| err.to_string())?;
        self.dirty = false;
        Ok(())
    }

    fn dispatch_due(&mut self, now: Instant) {
        for section in self.scheduler.due(
            now,
            self.ui.history_visible(),
            self.ui.needs_priority(),
            &self.store,
        ) {
            self.dispatch(section, now, false);
        }
    }

    fn dispatch(&mut self, section: Section, now: Instant, force: bool) {
        if self.store.meta(section).state == State::Loading {
            return;
        }
        let generation = self
            .store
            .generation(section)
            .checked_add(1)
            .expect("request generation exhausted");
        let work = Work::Fetch {
            section,
            generation,
            days: self.ui.config().job_history_days,
            force,
        };
        match self.workers.enqueue(work) {
            Ok(()) => {
                assert_eq!(self.store.begin(section), generation);
                self.scheduler.dispatched(section, now);
                self.dirty = true;
            }
            Err(_) => self.scheduler.deferred(section, now),
        }
    }

    fn process(&mut self, event: Event) -> Result<(), String> {
        match event {
            Event::Input(input) => self.process_input(input)?,
            Event::Data {
                section,
                generation,
                result,
            } => self.process_data(section, generation, result),
            Event::Action(result) => self.process_action(result)?,
            Event::Completed(Ok(Some(job))) => {
                if let Err(err) = self.store.add_completed_job(job) {
                    self.notify(err);
                }
                self.ui.observe_data(&self.store);
                self.dirty = true;
            }
            Event::Completed(Err(err)) => self
                .logs
                .append("ERROR", format!("completion lookup: {err}")),
            Event::Completed(Ok(None)) => self.request_history(true),
            Event::Available(result) => {
                if let Err(err) = &result {
                    self.logs.append("ERROR", err.clone());
                }
                self.unavailable = result.err();
                self.dirty = true;
            }
            Event::Latest(Ok(tag)) if update::is_newer(VERSION, &tag) => {
                self.latest = Some(tag);
                self.dirty = true;
            }
            Event::Latest(_) => {}
            Event::Copy { text, result } => self.notify(match result {
                Ok(()) => "Copied path".into(),
                Err(_) => text,
            }),
            Event::WorkerError(err) => {
                self.notify(err);
                self.quit = true;
                let _ = self.input.send(InputDirective::Stop);
            }
            Event::Quit => {
                self.quit = true;
                let _ = self.input.send(InputDirective::Stop);
            }
        }
        Ok(())
    }

    fn process_input(&mut self, input: TerminalEvent) -> Result<(), String> {
        let effects = match input {
            TerminalEvent::Key(key) if key.kind != KeyEventKind::Release => {
                self.ui.handle_key(key, &self.store)
            }
            TerminalEvent::Resize(_, _) => {
                self.dirty = true;
                Vec::new()
            }
            TerminalEvent::Paste(text) => {
                self.ui.handle_paste(&text, &self.store);
                Vec::new()
            }
            _ => Vec::new(),
        };
        self.effects(effects)?;
        let directive = if self.quit {
            Some(InputDirective::Stop)
        } else if self.suspended {
            None
        } else {
            Some(InputDirective::Read)
        };
        if let Some(directive) = directive {
            self.input
                .send(directive)
                .map_err(|_| "input reader stopped")?;
        }
        Ok(())
    }

    fn process_data(&mut self, section: Section, generation: u64, result: Result<Dataset, String>) {
        if generation < self.store.generation(section) {
            return;
        }
        let warning = match &result {
            Ok(Dataset::History(history)) => history.warning.clone(),
            _ => None,
        };
        let now = Instant::now();
        let outcome = self.store.apply(section, generation, result, now);
        if !outcome.accepted {
            return;
        }
        let error = self.store.meta(section).err.clone();
        self.scheduler.finished(section, error.is_some(), now);
        if let Some(message) = outcome.notification {
            self.notify(match error {
                Some(err) => format!("{message}: {err}"),
                None => message,
            });
        }
        if let Some(warning) = warning {
            self.notify(warning);
        }
        match outcome.completed_ids.as_slice() {
            [] => {}
            [id] => {
                if let Err(err) = self.workers.enqueue(Work::Completed(id.clone())) {
                    self.logs.append("ERROR", err);
                    self.request_history(true);
                }
            }
            _ => self.request_history(true),
        }
        self.ui.observe_data(&self.store);
        self.dirty = true;
    }

    fn process_action(&mut self, result: ActionResult) -> Result<(), String> {
        if let Some((level, message)) = action_feedback(&result) {
            self.logs.append(level, message);
        }
        let editor_done = matches!(&result, ActionResult::EditorDone(_));
        let saved = matches!(&result, ActionResult::ConfigSaved(Ok(())));
        if editor_done {
            self.screen.enter()?;
            self.suspended = false;
        }
        let effects = self.ui.receive(result);
        self.effects(effects)?;
        if saved {
            self.scheduler.configure(Instant::now(), self.ui.config());
            self.request_history(true);
        }
        if editor_done {
            self.input
                .send(InputDirective::Read)
                .map_err(|_| "input reader stopped")?;
        }
        self.dirty = true;
        Ok(())
    }

    fn request_history(&mut self, urgent: bool) {
        let now = Instant::now();
        if self.scheduler.request(Section::History, now, urgent) {
            self.dispatch(Section::History, now, urgent);
        }
    }

    fn effects(&mut self, effects: Vec<Effect>) -> Result<(), String> {
        let mut pending = VecDeque::from(effects);
        for _ in 0..64 {
            let Some(effect) = pending.pop_front() else {
                self.dirty = true;
                return Ok(());
            };
            match effect {
                Effect::Quit => self.quit = true,
                Effect::Refresh => self.refresh(),
                Effect::TabChanged => self.enter_tab(),
                Effect::Editor(path) => {
                    self.screen.leave()?;
                    self.suspended = true;
                    self.input
                        .send(InputDirective::Editor(path))
                        .map_err(|_| "input reader stopped")?;
                }
                effect => {
                    if let Err(err) = self.workers.enqueue(Work::Action(effect.clone())) {
                        self.logs.append("ERROR", err.clone());
                        if let Some(result) = failed_action(effect, err.clone()) {
                            let followups = self.ui.receive(result);
                            if pending.len() + followups.len() > 64 {
                                return Err("too many chained UI actions".into());
                            }
                            pending.extend(followups);
                        } else {
                            self.notify(err);
                        }
                    }
                }
            }
        }
        self.dirty = true;
        if pending.is_empty() {
            Ok(())
        } else {
            Err("too many chained UI actions".into())
        }
    }

    fn refresh(&mut self) {
        let now = Instant::now();
        let mut dispatched = false;
        for section in SECTIONS {
            if matches!(
                section,
                Section::FairShare | Section::PendingPrio | Section::PriorityConfig
            ) && !self.ui.needs_priority()
            {
                continue;
            }
            if section == Section::PriorityConfig && self.store.meta(section).state == State::Loaded
            {
                continue;
            }
            if self.store.meta(section).state == State::Loading {
                continue;
            }
            if self
                .scheduler
                .request(section, now, section == Section::RunningJobs)
            {
                self.dispatch(section, now, false);
                dispatched = true;
            }
        }
        let _ = self.workers.enqueue(Work::Available);
        self.notify(if dispatched {
            "Refresh requested".into()
        } else {
            "Data is fresh or a refresh is already running".into()
        });
    }

    fn enter_tab(&mut self) {
        let now = Instant::now();
        if self.ui.history_visible() {
            self.request_history(false);
        }
        if self.ui.needs_priority() {
            for section in [
                Section::FairShare,
                Section::PendingPrio,
                Section::PriorityConfig,
            ] {
                if section == Section::PriorityConfig
                    && self.store.meta(section).state == State::Loaded
                {
                    continue;
                }
                self.scheduler.request(section, now, false);
            }
        }
    }
}

impl Drop for Runtime {
    fn drop(&mut self) {
        self.input.stop();
    }
}

fn action_feedback(result: &ActionResult) -> Option<(&'static str, String)> {
    let (operation, result) = match result {
        ActionResult::Job { job_id, result, .. } => {
            return match result {
                Err(err) => Some(("ERROR", format!("job {job_id}: {err}"))),
                Ok(snapshot) => snapshot
                    .note
                    .as_ref()
                    .map(|note| ("WARN", format!("job {job_id}: {note}"))),
            };
        }
        ActionResult::Node { name, result, .. } => {
            return result
                .as_ref()
                .err()
                .map(|err| ("ERROR", format!("node {name}: {err}")));
        }
        ActionResult::Log { result, .. } => {
            return Some(match result {
                Ok(tail) => (
                    "INFO",
                    format!(
                        "opened log {} · {} lines",
                        tail.path.display(),
                        tail.lines.len()
                    ),
                ),
                Err(err) => ("ERROR", format!("log: {err}")),
            });
        }
        ActionResult::Cancel { job_id, result } => (format!("cancel job {job_id}"), result),
        ActionResult::Modify { job_id, result } => (format!("modify job {job_id}"), result),
        ActionResult::ConfigSaved(result) => ("save settings".into(), result),
        ActionResult::EditorDone(result) => ("editor".into(), result),
    };
    Some(match result {
        Ok(()) => ("INFO", format!("{operation}: done")),
        Err(err) => ("ERROR", format!("{operation}: {err}")),
    })
}

fn failed_action(effect: Effect, error: String) -> Option<ActionResult> {
    Some(match effect {
        Effect::FetchJob { token, job_id, .. } => ActionResult::Job {
            token,
            job_id,
            result: Err(error),
        },
        Effect::FetchNode { token, name } => ActionResult::Node {
            token,
            name,
            result: Err(error),
        },
        Effect::FetchLog { token, .. } => ActionResult::Log {
            token,
            result: Err(error),
        },
        Effect::Cancel { job_id } => ActionResult::Cancel {
            job_id,
            result: Err(error),
        },
        Effect::Modify { job_id, .. } | Effect::Hold { job_id, .. } => ActionResult::Modify {
            job_id,
            result: Err(error),
        },
        Effect::SaveConfig(_) => ActionResult::ConfigSaved(Err(error)),
        _ => return None,
    })
}

#[cfg(test)]
mod event_tests {
    use super::*;

    #[test]
    fn full_event_queue_does_not_trap_a_stopping_worker() {
        let (events, receiver) = mpsc::sync_channel(1);
        events.try_send(Event::Quit).unwrap();
        let stopped = AtomicBool::new(false);
        let mut waits = 0;
        assert!(!send_event_wait(&events, Event::Quit, &stopped, || {
            waits += 1;
            stopped.store(true, Ordering::Relaxed);
        }));
        assert_eq!(waits, 1);
        assert!(matches!(receiver.try_recv(), Ok(Event::Quit)));
        assert!(matches!(
            receiver.try_recv(),
            Err(mpsc::TryRecvError::Empty)
        ));
    }
}
