use std::collections::BTreeMap;

use ratatui::Terminal;
use ratatui::backend::TestBackend;

use crate::store::{Dataset, HistoryJob, HistoryResult, RunningJob, Section};

use super::*;

fn key(code: KeyCode) -> KeyEvent {
    KeyEvent::new(code, KeyModifiers::NONE)
}
fn ctrl(ch: char) -> KeyEvent {
    KeyEvent::new(KeyCode::Char(ch), KeyModifiers::CONTROL)
}

fn populated_store() -> Store {
    let mut store = Store::new();
    store.user = "alice".into();
    apply_test_data(
        &mut store,
        Dataset::RunningJobs(vec![
            RunningJob {
                id: "123".into(),
                name: "train 日本語".into(),
                state: "RUNNING".into(),
                time: "01:00:00".into(),
                nodes: "1".into(),
                node_list: "node001".into(),
                ..Default::default()
            },
            RunningJob {
                id: "456_[0-9]".into(),
                name: "Pending Array".into(),
                state: "PENDING".into(),
                ..Default::default()
            },
        ]),
    );
    apply_test_data(
        &mut store,
        Dataset::History(HistoryResult {
            jobs: vec![HistoryJob {
                id: "10".into(),
                name: "Finished".into(),
                state: "COMPLETED".into(),
                elapsed: "00:20:00".into(),
                std_out: "/tmp/output.log".into(),
                ..Default::default()
            }],
            ..Default::default()
        }),
    );
    store
}

fn snapshot(id: &str, state: &str) -> JobSnapshot {
    JobSnapshot {
        detail: JobDetail {
            fields: BTreeMap::from([
                ("JobId".into(), id.into()),
                ("JobState".into(), state.into()),
                ("JobName".into(), "model".into()),
                ("StdOut".into(), "/tmp/output.log".into()),
            ]),
            source: "scontrol".into(),
        },
        usage: None,
        note: None,
    }
}

fn job_read(effects: &[Effect]) -> ReadToken {
    let [Effect::FetchJob { token, .. }] = effects else {
        panic!("expected a job detail request");
    };
    token.clone()
}

fn gpu_snapshot() -> GpuSnapshot {
    GpuSnapshot {
        devices: vec![store::GpuDevice {
            node: "gpu001".into(),
            index: 2,
            name: "NVIDIA H100".into(),
            uuid: "GPU-test".into(),
            memory_used_bytes: Some(12 << 30),
            memory_total_bytes: Some(80 << 30),
            utilization_percent: Some(65.0),
        }],
        warnings: Vec::new(),
    }
}

#[test]
fn gpu_snapshots_are_requested_and_refreshed_only_by_modal_keys() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    assert!(matches!(
        ui.open_job("123", "RUNNING", None).as_slice(),
        [Effect::FetchJob { .. }]
    ));
    let effects = ui.handle_key(key(KeyCode::Char('v')), &store);
    let [Effect::FetchGpu { token, job_id }] = effects.as_slice() else {
        panic!("expected an on-demand GPU query");
    };
    assert_eq!(job_id, "123");
    assert!(render(&mut ui, &store, 100, 24).contains("Loading"));
    assert!(ui.handle_key(key(KeyCode::Char('r')), &store).is_empty());
    ui.receive(ActionResult::Gpu {
        token: token.clone(),
        job_id: job_id.clone(),
        result: Ok(gpu_snapshot()),
    });
    let text = render(&mut ui, &store, 100, 24);
    assert!(text.contains("gpu001 · GPU 2 · NVIDIA H100"));
    assert!(text.contains("65%"));
    assert!(text.contains("12.0G / 80.0G"));
    let refresh = ui.handle_key(key(KeyCode::Char('r')), &store);
    let [Effect::FetchGpu { token: next, .. }] = refresh.as_slice() else {
        panic!("expected a manual GPU refresh");
    };
    assert!(!next.ptr_eq(token));
    assert_eq!(token.strong_count(), 0);
    assert!(render(&mut ui, &store, 100, 24).contains("previous snapshot"));
    ui.receive(ActionResult::Gpu {
        token: next.clone(),
        job_id: "123".into(),
        result: Err("SSH connection failed".into()),
    });
    let text = render(&mut ui, &store, 100, 24);
    assert!(text.contains("SSH connection failed"));
    assert!(text.contains("previous snapshot"));
    assert!(text.contains("12.0G / 80.0G"));
    assert!(ui.handle_key(key(KeyCode::Esc), &store).is_empty());
    assert!(matches!(ui.modals.last(), Some(Modal::Job(_))));
}

#[test]
fn gpu_results_for_closed_or_other_requests_are_ignored() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    let parent = job_read(&ui.open_job("123", "RUNNING", None));
    let effects = ui.handle_key(key(KeyCode::Char('v')), &store);
    let [Effect::FetchGpu { token: first, .. }] = effects.as_slice() else {
        panic!("expected a GPU query");
    };
    ui.handle_key(key(KeyCode::Esc), &store);
    assert_eq!(first.strong_count(), 0);
    let effects = ui.handle_key(key(KeyCode::Char('v')), &store);
    let [Effect::FetchGpu { token: second, .. }] = effects.as_slice() else {
        panic!("expected another GPU query");
    };
    for (token, job_id) in [(first, "123"), (second, "456")] {
        ui.receive(ActionResult::Gpu {
            token: token.clone(),
            job_id: job_id.into(),
            result: Ok(gpu_snapshot()),
        });
        assert!(
            matches!(ui.modals.last(), Some(Modal::Gpu(view)) if view.loading && view.snapshot.is_none())
        );
    }
    ui.handle_key(key(KeyCode::Esc), &store);
    ui.receive(ActionResult::Gpu {
        token: second.clone(),
        job_id: "123".into(),
        result: Ok(gpu_snapshot()),
    });
    assert!(matches!(ui.modals.last(), Some(Modal::Job(_))));
    assert!(parent.upgrade().is_some());
    ui.handle_key(key(KeyCode::Esc), &store);
    assert!(parent.upgrade().is_none());
}

#[test]
fn gpu_popup_distinguishes_unavailable_readings_from_zero_and_reports_partial_failures() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.open_job("123", "RUNNING", None);
    let effects = ui.handle_key(key(KeyCode::Char('v')), &store);
    let [Effect::FetchGpu { token, .. }] = effects.as_slice() else {
        panic!("expected a GPU query");
    };
    let mut data = gpu_snapshot();
    data.devices[0].memory_used_bytes = None;
    data.devices[0].utilization_percent = None;
    data.warnings.push("gpu002: SSH unavailable".into());
    ui.receive(ActionResult::Gpu {
        token: token.clone(),
        job_id: "123".into(),
        result: Ok(data.clone()),
    });
    let text = render(&mut ui, &store, 100, 30);
    assert!(text.contains("gpu002: SSH unavailable"));
    assert!(text.contains("GPU utilization......... n/a"));
    assert!(text.contains("n/a / 80.0G"));
    data.devices[0].memory_used_bytes = Some(0);
    data.devices[0].utilization_percent = Some(0.0);
    ui.receive(ActionResult::Gpu {
        token: token.clone(),
        job_id: "123".into(),
        result: Ok(data),
    });
    let text = render(&mut ui, &store, 100, 30);
    assert!(text.contains("GPU utilization......... 0%"));
    assert!(text.contains("0B / 80.0G"));
}

fn render(ui: &mut Ui, store: &Store, width: u16, height: u16) -> String {
    render_buffer(ui, store, width, height)
        .content
        .iter()
        .map(|cell| cell.symbol())
        .collect()
}

fn render_buffer(ui: &mut Ui, store: &Store, width: u16, height: u16) -> ratatui::buffer::Buffer {
    render_buffer_with_release(ui, store, width, height, "dev", None)
}

fn render_buffer_with_release(
    ui: &mut Ui,
    store: &Store,
    width: u16,
    height: u16,
    version: &str,
    update_available: Option<&str>,
) -> ratatui::buffer::Buffer {
    let logs = LogRing::default();
    let status = RuntimeStatus {
        version,
        update_available,
        unavailable: None,
        logs: &logs,
        today: NaiveDate::from_ymd_opt(2026, 9, 30).unwrap(),
        now: store
            .meta(Section::RunningJobs)
            .last_updated
            .unwrap_or_else(Instant::now),
    };
    let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
    terminal
        .draw(|frame| ui.render(frame, store, &status))
        .unwrap();
    terminal.backend().buffer().clone()
}

fn line(buffer: &ratatui::buffer::Buffer, row: u16) -> String {
    (0..buffer.area.width)
        .map(|col| buffer[(col, row)].symbol())
        .collect()
}

fn apply_test_data(store: &mut Store, data: Dataset) -> store::ApplyOutcome {
    let section = data.section();
    let generation = store.begin(section);
    let now = store
        .meta(Section::RunningJobs)
        .last_success
        .unwrap_or_else(Instant::now);
    store.apply(section, generation, Ok(data), now)
}

fn assert_cluster_views(store: &Store, visible: &[&str], absent: &[&str]) {
    let mut ui = Ui::new(Config::default());
    ui.observe_data(store);
    let sidebar = render(&mut ui, store, 160, 36);
    ui.modals.push(Modal::load());
    for text in [sidebar, render(&mut ui, store, 100, 36)] {
        for expected in visible {
            assert!(text.contains(expected), "missing {expected:?}");
        }
        for unexpected in absent {
            assert!(!text.contains(unexpected), "unexpected {unexpected:?}");
        }
    }
}

fn idle_node() -> store::Node {
    store::Node {
        name: "cpu001".into(),
        state: "IDLE".into(),
        cpu_tot: "64".into(),
        cpu_alloc: "0".into(),
        real_mem: "65536".into(),
        alloc_mem: "0".into(),
        ..Default::default()
    }
}

#[test]
fn personal_resource_totals_refresh_with_jobs_before_cluster_data_arrives() {
    let mut store = populated_store();
    let mut jobs = store.running_jobs.clone();
    jobs[0].tres = "cpu=8,mem=4G,gres/gpu=2,gres/gpu:a100=2".into();
    apply_test_data(&mut store, Dataset::RunningJobs(jobs.clone()));
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    let banner = line(&render_buffer(&mut ui, &store, 160, 24), 2);
    assert!(banner.contains("cpu 8"));
    assert!(banner.contains("mem 4G"));
    assert!(banner.contains("gpu 2×A100"));
    assert!(!banner.contains("Loading usage"));

    apply_test_data(
        &mut store,
        Dataset::AllUsersJobs(vec![store::AllUsersJob {
            user: "alice".into(),
            state: "RUNNING".into(),
            tres: "cpu=99,mem=99G".into(),
            ..Default::default()
        }]),
    );
    jobs[0].tres = "cpu=16,mem=32G,gres/gpu:h100=4".into();
    apply_test_data(&mut store, Dataset::RunningJobs(jobs));
    ui.observe_data(&store);
    let banner = line(&render_buffer(&mut ui, &store, 160, 24), 2);
    assert!(banner.contains("cpu 16"));
    assert!(banner.contains("mem 32G"));
    assert!(banner.contains("gpu 4×H100"));
    apply_test_data(&mut store, Dataset::RunningJobs(Vec::new()));
    ui.observe_data(&store);
    let banner = line(&render_buffer(&mut ui, &store, 160, 24), 2);
    assert!(banner.contains("no running jobs"));
    assert!(!banner.contains("cpu 99"));
}

#[test]
fn refresh_indicator_stays_visible_until_every_fetch_finishes() {
    let mut store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    let running_generation = store.begin(Section::RunningJobs);
    let cluster_generation = store.begin(Section::AllUsersJobs);
    for width in [18, 36, 80, 120] {
        let buffer = render_buffer(&mut ui, &store, width, 24);
        assert!(
            line(&buffer, 23).contains("Refreshing…"),
            "missing indicator at width {width}"
        );
    }
    assert!(render(&mut ui, &store, 120, 24).contains("train"));
    let now = store.meta(Section::RunningJobs).last_success.unwrap();
    store.apply(
        Section::RunningJobs,
        running_generation,
        Ok(Dataset::RunningJobs(store.running_jobs.clone())),
        now,
    );
    let buffer = render_buffer(&mut ui, &store, 120, 24);
    assert!(line(&buffer, 23).contains("Refreshing…"));
    store.apply(
        Section::AllUsersJobs,
        cluster_generation,
        Err("squeue unavailable".into()),
        now,
    );
    let buffer = render_buffer(&mut ui, &store, 120, 24);
    assert!(!line(&buffer, 23).contains("Refreshing…"));
    assert!(line(&buffer, 23).contains("sync 0s"));
    assert!(render(&mut ui, &store, 120, 24).contains("train"));
}

#[test]
fn cluster_capacity_can_load_before_the_queue_and_become_empty() {
    let mut store = populated_store();
    store.begin(Section::Nodes);
    store.begin(Section::AllUsersJobs);
    assert_cluster_views(
        &store,
        &["Loading cluster…", "Loading queue…"],
        &["%", "0/0"],
    );
    apply_test_data(&mut store, Dataset::Nodes(vec![idle_node()]));
    assert_cluster_views(
        &store,
        &["64/64 free (100.0%)", "Loading queue…"],
        &["Loading cluster…", "GPUs:"],
    );
    apply_test_data(&mut store, Dataset::AllUsersJobs(Vec::new()));
    assert_cluster_views(
        &store,
        &["64/64 free (100.0%)"],
        &["Loading queue…", "Pending:"],
    );
    apply_test_data(&mut store, Dataset::Nodes(Vec::new()));
    assert_cluster_views(&store, &["0/0 free (n/a)"], &["100.0%", "Loading cluster…"]);
}

#[test]
fn queue_can_load_first_and_node_refreshes_only_show_last_successful_capacity() {
    let mut store = populated_store();
    let now = store.meta(Section::RunningJobs).last_success.unwrap();
    store.begin(Section::AllUsersJobs);
    let failed = store.begin(Section::Nodes);
    store.apply(Section::Nodes, failed, Err("nodes unavailable".into()), now);
    assert_cluster_views(
        &store,
        &["cluster unavailable", "Loading queue…"],
        &["%", "0/0"],
    );

    let retry = store.begin(Section::Nodes);
    apply_test_data(
        &mut store,
        Dataset::AllUsersJobs(vec![store::AllUsersJob {
            id: "500".into(),
            user: "alice".into(),
            state: "PENDING".into(),
            partition: "cpu".into(),
            tres: "cpu=4,mem=2G".into(),
            ..Default::default()
        }]),
    );
    assert_cluster_views(
        &store,
        &["Loading cluster…", "cpu 1j·4c·2G"],
        &["Loading queue…", "%"],
    );
    store.apply(
        Section::Nodes,
        retry,
        Ok(Dataset::Nodes(vec![idle_node()])),
        now,
    );
    let refresh = store.begin(Section::Nodes);
    assert_cluster_views(
        &store,
        &["Refreshing cluster…", "64/64 free (100.0%)", "cpu 1j·4c·2G"],
        &[],
    );
    store.apply(
        Section::Nodes,
        refresh,
        Err("nodes unavailable".into()),
        now,
    );
    assert_cluster_views(
        &store,
        &[
            "Last known cluster · refresh failed",
            "64/64 free (100.0%)",
            "cpu 1j·4c·2G",
        ],
        &["Refreshing cluster…"],
    );
}

#[test]
fn missing_gpu_allocations_and_unavailable_hardware_use_the_same_inventory_in_both_views() {
    let mut store = populated_store();
    apply_test_data(
        &mut store,
        Dataset::Nodes(vec![
            store::Node {
                name: "gpu001".into(),
                state: "DOWN".into(),
                gres: "gpu:h200:8".into(),
                ..idle_node()
            },
            store::Node {
                name: "gpu002".into(),
                state: "MIXED".into(),
                cpu_alloc: "32".into(),
                alloc_mem: "32768".into(),
                cfg_tres: "cpu=64,mem=64G,gres/gpu=4".into(),
                gres: "gpu:h100:4(S:0-1)".into(),
                ..idle_node()
            },
        ]),
    );
    assert_cluster_views(
        &store,
        &[
            "H200 0/8 free (0.0%) · 8 unavail",
            "H100 0–4/4 free · 4 unknown",
        ],
        &["allocated", "100.0%"],
    );

    let mut ui = Ui::new(Config::default());
    ui.handle_key(key(KeyCode::Char('2')), &store);
    let buffer = render_buffer(&mut ui, &store, 180, 32);
    let (y, row) = (0..buffer.area.height)
        .map(|y| (y, line(&buffer, y)))
        .find(|(_, text)| text.contains("gpu002"))
        .expect("mixed node row");
    let (before_percent, _) = row.split_once("N/A").expect("unknown GPU usage");
    assert!(before_percent.trim_end().ends_with("?/4"));
    let x = before_percent.chars().count() as u16;
    assert_eq!(
        buffer[(x, y)].fg,
        theme::Theme::by_name(&ui.config().theme).text
    );
}

#[test]
fn familiar_chrome_keeps_tab_divider_and_quit_controls_in_place() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    for (version, label) in [("dev", "dev"), ("1.2.3", "v1.2.3"), ("v1.2.3", "v1.2.3")] {
        for (tab, title) in [('1', "1 Jobs"), ('4', "4 Priority"), ('5', "5 Logs")] {
            ui.handle_key(key(KeyCode::Char(tab)), &store);
            for (width, height) in [(40, 12), (60, 24), (80, 24), (100, 24), (160, 32)] {
                let buffer =
                    render_buffer_with_release(&mut ui, &store, width, height, version, None);
                let header = line(&buffer, 0);
                assert!(header.starts_with(&format!(" stoei  {label} ")));
                assert!(header.contains(title), "active tab missing: {header}");
                assert_eq!(line(&buffer, 1), "─".repeat(usize::from(width)));
                let footer = line(&buffer, height - 1);
                assert!(footer.contains("? help"));
                assert!(footer.contains("q quit"));
                if width >= 80 {
                    assert!(header.contains("5 Logs"));
                    assert!(footer.ends_with(" sync 0s "));
                }
                let theme = theme::Theme::by_name("nord");
                assert_eq!(buffer[(width / 2, height - 1)].bg, theme.border);
                if width >= 72 {
                    assert!(footer.starts_with(" stoei "));
                    assert_eq!(buffer[(0, height - 1)].bg, theme.accent);
                }
                assert_eq!(buffer[(width - 1, height - 1)].bg, theme.accent_alt);
            }
        }
    }
}

#[test]
fn release_prompt_fits_on_the_bottom_row_with_both_key_presets() {
    let store = populated_store();
    let theme = theme::Theme::by_name("nord");
    for (mode, quit) in [("vim", "q quit"), ("emacs", "C-q quit")] {
        let mut ui = Ui::new(Config {
            keybind_mode: mode.into(),
            ..Default::default()
        });
        ui.observe_data(&store);
        ui.notify("Saved".into());
        for (width, height) in [(18, 12), (40, 12), (80, 12), (191, 58)] {
            let buffer =
                render_buffer_with_release(&mut ui, &store, width, height, "1.2.3", Some("v1.2.4"));
            let row = height - 1;
            let footer = line(&buffer, row);
            let prompt = footer.find("Run stoei update").expect("update prompt");
            let prompt_cell = &buffer[(prompt as u16, row)];
            assert_eq!(prompt_cell.bg, theme.border);
            assert_eq!(prompt_cell.fg, theme.accent_alt);
            assert_eq!(line(&buffer, row - 1).trim(), "Saved");
            if width >= 40 {
                assert!(prompt < footer.find(quit).expect("quit hint"));
            }
            if width >= 80 {
                assert!(footer.contains("for v1.2.4"));
                assert!(footer.ends_with(" sync 0s "));
            }
            if width == 191 {
                assert!(footer.starts_with(" stoei  b sidebar "));
                assert!(footer.find("L load").expect("context hints") < prompt);
                assert_eq!(buffer[(0, row)].bg, theme.accent);
                assert_eq!(buffer[(width - 1, row)].bg, theme.accent_alt);
                assert!((0..width).all(|x| buffer[(x, row - 1)].bg == theme.background));
            }
        }
    }
}

#[test]
fn development_build_label_is_explained_in_help() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    assert!(line(&render_buffer(&mut ui, &store, 100, 24), 0).contains(" dev "));
    ui.modals.push(Modal::help());
    assert!(render(&mut ui, &store, 100, 24).contains("stoei · local development build"));
}

#[test]
fn cancelling_a_selected_row_uses_the_confirmed_scope() {
    for (row, target, prompt) in [
        (
            "123_[5-9,12%3]",
            "123_[5-9,12]",
            "Cancel array tasks 123_[5-9,12]?",
        ),
        ("123", "123", "Cancel job 123 (all tasks if an array)?"),
    ] {
        let mut store = Store::new();
        let jobs = [(row, "PENDING"), ("123_4", "RUNNING")].map(|(id, state)| RunningJob {
            id: id.into(),
            state: state.into(),
            ..RunningJob::default()
        });
        apply_test_data(&mut store, Dataset::RunningJobs(jobs.into()));
        let mut ui = Ui::new(Config::default());
        ui.observe_data(&store);
        ui.handle_key(key(KeyCode::Char('c')), &store);
        assert!(render(&mut ui, &store, 100, 24).contains(prompt));
        assert!(ui.handle_key(key(KeyCode::Enter), &store).is_empty());
        assert!(ui.modals.is_empty());

        ui.handle_key(key(KeyCode::Char('c')), &store);
        ui.handle_key(key(KeyCode::Tab), &store);
        let effects = ui.handle_key(key(KeyCode::Enter), &store);
        assert!(matches!(effects.as_slice(), [Effect::Cancel { job_id }] if job_id == target));
    }
}

#[test]
fn array_partition_edits_keep_the_selected_group_when_detail_shows_a_running_task() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    let effects = ui.open_job("123_[0-9%3]", "PENDING", None);
    let token = job_read(&effects);
    let mut value = snapshot("123", "RUNNING");
    value
        .detail
        .fields
        .insert("ArrayJobId".into(), "123".into());
    ui.receive(ActionResult::Job {
        token,
        job_id: "123".into(),
        result: Ok(value),
    });
    ui.handle_key(key(KeyCode::Char('m')), &store);
    ui.handle_key(key(KeyCode::Down), &store);
    ui.handle_key(key(KeyCode::Enter), &store);
    for ch in "cpu".chars() {
        ui.handle_key(key(KeyCode::Char(ch)), &store);
    }
    let effects = ui.handle_key(key(KeyCode::Enter), &store);
    assert!(
        matches!(effects.as_slice(), [Effect::Modify { job_id, fields }] if job_id == "123_[0-9%3]" && fields == &[("Partition".into(), "cpu".into())])
    );
    let effects = ui.receive(ActionResult::Modify {
        job_id: "123_[0-9%3]".into(),
        result: Err("task started while applying partition".into()),
    });
    assert!(
        matches!(effects.as_slice(), [Effect::Refresh, Effect::FetchJob { job_id, .. }] if job_id == "123")
    );
    let Some(Modal::Modify(view)) = ui.modals.last() else {
        panic!("failed edit must remain open");
    };
    assert_eq!(view.input, "cpu");
    assert_eq!(view.pending_id, None);
    assert_eq!(
        view.error.as_deref(),
        Some("task started while applying partition")
    );
    assert!(render(&mut ui, &store, 100, 40).contains("task started while applying partition"));
    assert!(ui.toasts.is_empty());
    assert!(matches!(
        ui.handle_key(key(KeyCode::Enter), &store).as_slice(),
        [Effect::Modify { .. }]
    ));
    let effects = ui.receive(ActionResult::Modify {
        job_id: "123_[0-9%3]".into(),
        result: Ok(()),
    });
    assert!(
        matches!(effects.as_slice(), [Effect::Refresh, Effect::FetchJob { job_id, .. }] if job_id == "123")
    );
    assert!(matches!(ui.modals.last(), Some(Modal::Job(_))));
}

#[test]
fn active_priority_pane_stays_visible_beside_a_wide_sidebar() {
    let mut store = populated_store();
    apply_test_data(&mut store, Dataset::Nodes(vec![idle_node()]));
    apply_test_data(
        &mut store,
        Dataset::AllUsersJobs(vec![store::AllUsersJob {
            id: "500_[0-999]".into(),
            user: "alice".into(),
            state: "PENDING".into(),
            partition: "gpu-production-partition".into(),
            tres: "cpu=64,mem=2G,gres/gpu:h200=8".into(),
            ..Default::default()
        }]),
    );
    let mut ui = Ui::new(Config::default());
    ui.handle_key(key(KeyCode::Char('4')), &store);
    for (pane, label) in [
        ('m', "m My Priority"),
        ('u', "u Active Users"),
        ('a', "a Accounts"),
        ('j', "j Jobs"),
    ] {
        ui.handle_key(key(KeyCode::Char(pane)), &store);
        for width in [55, 80, 100] {
            let buffer = render_buffer(&mut ui, &store, width, 24);
            let header = line(&buffer, 2);
            assert!(
                header.contains(label),
                "active pane missing at {width}: {header}"
            );
            let col = header.find(label).unwrap() as u16;
            assert_eq!(buffer[(col, 2)].bg, theme::Theme::by_name("nord").accent);
        }
    }
}

#[test]
fn detail_modals_keep_the_original_centered_fraction_and_reach_long_values() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    let effects = ui.open_job("123", "RUNNING", None);
    let token = job_read(&effects);
    let mut value = snapshot("123", "RUNNING");
    value.detail.fields.insert(
        "StdOut".into(),
        format!("/tmp/{}/output.log", "long-path-".repeat(20)),
    );
    ui.receive(ActionResult::Job {
        token,
        job_id: "123".into(),
        result: Ok(value),
    });
    let first = render_buffer(&mut ui, &store, 100, 24);
    assert_eq!(first[(7, 2)].symbol(), "╭");
    assert_eq!(first[(91, 21)].symbol(), "╯");
    for _ in 0..20 {
        ui.handle_key(key(KeyCode::Down), &store);
    }
    for _ in 0..40 {
        ui.handle_key(key(KeyCode::Right), &store);
    }
    let end = render(&mut ui, &store, 100, 24);
    assert!(end.contains("output.log"));
    ui.handle_key(key(KeyCode::Right), &store);
    assert_eq!(end, render(&mut ui, &store, 100, 24));
}

#[test]
fn settings_remain_compact_and_keep_the_focused_field_visible() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.modals.push(Modal::settings(Config::default()));
    let buffer = render_buffer(&mut ui, &store, 100, 24);
    assert_eq!(buffer[(17, 3)].symbol(), "╭");
    assert_eq!(buffer[(82, 19)].symbol(), "╯");
    assert!(line(&buffer, 7).contains("‹ nord ›"));
    for (width, height) in [(55, 12), (55, 7), (100, 24)] {
        let mut ui = Ui::new(Config::default());
        ui.modals.push(Modal::settings(Config::default()));
        for _ in 0..4 {
            ui.handle_key(key(KeyCode::Down), &store);
        }
        let text = render(&mut ui, &store, width, height);
        assert!(text.contains("‹ vim ›"));
        assert!(text.contains("Esc"));
    }
}

#[test]
fn compact_settings_keep_save_and_validation_errors_visible() {
    let store = populated_store();
    for (width, height) in [(80, 18), (55, 12)] {
        let mut ui = Ui::new(Config::default());
        ui.modals.push(Modal::settings(Config::default()));
        assert!(matches!(
            ui.handle_key(ctrl('s'), &store).first(),
            Some(Effect::SaveConfig(_))
        ));
        ui.receive(ActionResult::ConfigSaved(Err("disk full".into())));
        assert!(render(&mut ui, &store, width, height).contains("disk full"));
        let Some(Modal::Settings(view)) = ui.modals.last_mut() else {
            panic!("expected settings");
        };
        view.values[1] = "invalid".into();
        view.field = 1;
        assert!(ui.handle_key(ctrl('s'), &store).is_empty());
        let text = render(&mut ui, &store, width, height);
        assert!(text.contains("Refresh interval must be a number"));
        assert!(text.contains("invalid▏"));
    }
}

#[test]
fn long_priority_summary_values_wrap_inside_the_main_pane() {
    let mut store = populated_store();
    apply_test_data(
        &mut store,
        Dataset::AllUsersJobs(vec![store::AllUsersJob {
            id: "500_[0-999]".into(),
            user: "alice".into(),
            state: "PENDING".into(),
            partition: "gpu-production-partition".into(),
            tres: "cpu=64,mem=2G,gres/gpu:h200=8".into(),
            ..Default::default()
        }]),
    );
    apply_test_data(
        &mut store,
        Dataset::FairShare(vec![store::FairShareEntry {
            user: "alice".into(),
            account: "physics".into(),
            norm_shares: "0.1".into(),
            effectv_usage: "0.8".into(),
            fair_share: "0.125".into(),
            raw_usage: "1000".into(),
            ..Default::default()
        }]),
    );
    apply_test_data(
        &mut store,
        Dataset::PriorityConfig(crate::slurm::parse_priority_config(include_str!(
            "../../tests/fixtures/scontrol_config.txt"
        ))),
    );
    let mut ui = Ui::new(Config::default());
    ui.handle_key(key(KeyCode::Char('4')), &store);
    let buffer = render_buffer(&mut ui, &store, 100, 40);
    let main_width = (0..100)
        .find(|col| buffer[(*col, 2)].symbol() == "╭")
        .unwrap();
    let text: String = (4..39)
        .flat_map(|row| (0..main_width).map(move |col| (col, row)))
        .map(|pos| buffer[pos].symbol())
        .collect();
    let words = text.split_whitespace().collect::<Vec<_>>().join(" ");
    assert!(words.contains("without jobs to reach 1× your share"));
    assert!(words.contains("Heavily over-served"));
    assert!(words.contains("Partition 100"));
}

#[test]
fn multiple_associations_do_not_invent_hidden_users() {
    let mut store = populated_store();
    let entry = store::FairShareEntry {
        user: "alice".into(),
        account: "physics".into(),
        norm_shares: "0.1".into(),
        effectv_usage: "0.8".into(),
        fair_share: "0.125".into(),
        raw_usage: "1000".into(),
        ..Default::default()
    };
    apply_test_data(
        &mut store,
        Dataset::FairShare(vec![
            entry.clone(),
            store::FairShareEntry {
                account: "biology".into(),
                ..entry
            },
        ]),
    );
    let mut ui = Ui::new(Config::default());
    ui.handle_key(key(KeyCode::Char('4')), &store);
    ui.handle_key(key(KeyCode::Char('u')), &store);
    let text = render(&mut ui, &store, 100, 24);
    assert!(text.contains("1 active users"));
    assert!(!text.contains("without recent usage hidden"));
}

#[test]
fn my_priority_pane_opens_the_selected_owned_job_from_the_original_indices() {
    let mut store = populated_store();
    apply_test_data(
        &mut store,
        Dataset::PendingPrio(vec![
            store::PriorityEntry {
                job_id: "999".into(),
                user: "bob".into(),
                partition: "gpu".into(),
                priority: 500,
                ..Default::default()
            },
            store::PriorityEntry {
                job_id: "789".into(),
                user: "alice".into(),
                partition: "gpu".into(),
                priority: 100,
                ..Default::default()
            },
        ]),
    );
    let mut ui = Ui::new(Config::default());
    ui.handle_key(key(KeyCode::Char('4')), &store);
    let text = render(&mut ui, &store, 160, 32);
    assert!(text.contains("Your pending jobs (1)"));
    assert!(text.contains("789"));
    assert!(!text.contains("999"));
    let effects = ui.handle_key(key(KeyCode::Enter), &store);
    assert!(matches!(&effects[0], Effect::FetchJob { job_id, .. } if job_id == "789"));
}

#[test]
fn all_tabs_and_modals_render_without_a_terminal_or_scheduler() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    for active in 0..5 {
        ui.active = active;
        for (width, height) in [(1, 1), (17, 4), (55, 7), (80, 24), (160, 32)] {
            render(&mut ui, &store, width, height);
        }
    }
    for modal in [
        Modal::help(),
        Modal::load(),
        Modal::settings(Config::default()),
        Modal::cancel("123".into()),
        Modal::job_input(),
        Modal::info("alice".into(), false),
    ] {
        ui.modals.push(modal);
        assert!(!render(&mut ui, &store, 100, 24).is_empty());
        render(&mut ui, &store, 18, 5);
        ui.modals.pop();
    }
    ui.active = 0;
    let text = render(&mut ui, &store, 160, 24);
    assert!(text.contains("train 日"));
    assert!(text.contains('本'));
    assert!(text.contains('語'));
    assert!(text.contains("alice"));
    assert!(text.contains("Finished"));
}

#[test]
fn table_refreshes_follow_the_active_source_and_switching_tabs_uses_the_latest_rows() {
    let mut store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    let Some(Effect::FetchJob { token, job_id, .. }) = ui.open_job("10", "COMPLETED", None).pop()
    else {
        panic!("expected a detail request");
    };
    ui.receive(ActionResult::Job {
        token,
        job_id,
        result: Ok(snapshot("10", "COMPLETED")),
    });
    ui.handle_key(key(KeyCode::Esc), &store);

    // Defer the history delivery so an unrelated rebuild or cache prune would be observable.
    let history = store.history_jobs.clone();
    let removed = apply_test_data(&mut store, Dataset::History(HistoryResult::default()));
    let nodes = apply_test_data(&mut store, Dataset::Nodes(vec![idle_node()]));
    let status_only = apply_test_data(&mut store, Dataset::History(HistoryResult::default()));
    let changes = [nodes.changed, status_only.changed];
    assert_eq!(changes, [Some(Section::Nodes), None]);
    for section in changes.into_iter().flatten() {
        ui.dataset_changed(&store, section);
    }
    assert_eq!(ui.tables[0].indices.len(), 3);
    assert_eq!(ui.cache.len(), 1);
    ui.dataset_changed(&store, removed.changed.expect("removed history row"));
    assert_eq!(ui.tables[0].indices.len(), 2);
    assert!(ui.cache.is_empty());

    ui.handle_key(key(KeyCode::Char('2')), &store);
    assert!(render(&mut ui, &store, 80, 24).contains("cpu001"));
    let restored = apply_test_data(
        &mut store,
        Dataset::History(HistoryResult {
            jobs: history,
            ..Default::default()
        }),
    );
    ui.dataset_changed(&store, restored.changed.expect("restored history row"));
    assert!(ui.tables[0].indices.is_empty());
    ui.handle_key(key(KeyCode::BackTab), &store);
    assert!(render(&mut ui, &store, 160, 24).contains("Finished"));
    ui.handle_key(key(KeyCode::Tab), &store);
    assert_eq!(ui.active_tab(), 1);
}

#[test]
fn narrow_tables_preserve_column_widths_and_stop_at_the_last_column() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    let initial = render(&mut ui, &store, 80, 24);
    assert!(initial.contains("456_[0-9]"));
    assert!(initial.contains("Pending Array"));
    assert!(initial.contains("Finished"));
    assert!(initial.contains("COMPLETED"));

    for _ in 0..8 {
        ui.handle_key(key(KeyCode::Right), &store);
    }
    let last_columns = render(&mut ui, &store, 80, 24);
    assert!(last_columns.contains("Node List"));
    assert!(last_columns.contains("node001"));
    assert!(last_columns.contains("Timeline"));
    for _ in 0..8 {
        ui.handle_key(key(KeyCode::Right), &store);
    }
    assert_eq!(render(&mut ui, &store, 80, 24), last_columns);
}

#[test]
fn modal_and_filter_keys_capture_globals_and_panes_override_refresh() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    ui.handle_key(key(KeyCode::Char('/')), &store);
    assert!(ui.handle_key(key(KeyCode::Char('q')), &store).is_empty());
    assert_eq!(ui.tables[0].filter, "q");
    assert!(matches!(
        ui.handle_key(ctrl('c'), &store).first(),
        Some(Effect::Quit)
    ));
    ui.handle_key(key(KeyCode::Esc), &store);
    ui.handle_key(key(KeyCode::Char('?')), &store);
    assert!(ui.handle_key(key(KeyCode::Char('q')), &store).is_empty());
    assert!(ui.modals.is_empty());
    ui.handle_key(key(KeyCode::Char('3')), &store);
    assert!(ui.needs_priority());
    assert!(ui.handle_key(key(KeyCode::Char('r')), &store).is_empty());
    assert!(!ui.users_pending);
    ui.handle_key(key(KeyCode::Char('p')), &store);
    assert!(ui.users_pending);
    assert!(!render(&mut ui, &store, 80, 24).contains("r refresh"));
    assert!(matches!(
        ui.handle_key(ctrl('c'), &store).first(),
        Some(Effect::Quit)
    ));
}

#[test]
fn stale_closed_or_other_job_results_do_not_reopen_or_replace_a_modal() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    let first = ui.open_job("123", "RUNNING", None);
    let first_token = job_read(&first);
    ui.handle_key(key(KeyCode::Esc), &store);
    let second = ui.open_job("456_[0-9]", "PENDING", None);
    let [
        Effect::FetchJob {
            token: second_token,
            job_id,
            ..
        },
    ] = second.as_slice()
    else {
        panic!("expected a detail fetch");
    };
    assert_eq!(job_id, "456");
    ui.receive(ActionResult::Job {
        token: first_token,
        job_id: "123".into(),
        result: Ok(snapshot("123", "RUNNING")),
    });
    assert!(
        matches!(ui.modals.last(), Some(Modal::Job(view)) if view.loading && view.id == "456" && view.snapshot.is_none())
    );
    ui.receive(ActionResult::Job {
        token: second_token.clone(),
        job_id: "456".into(),
        result: Ok(snapshot("456", "PENDING")),
    });
    assert!(
        matches!(ui.modals.last(), Some(Modal::Job(view)) if !view.loading && view.snapshot.is_some())
    );
    assert!(ui.cache.is_empty());
}

#[test]
fn terminal_detail_retries_failed_accounting_and_keeps_successful_results() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    let token = job_read(&ui.open_job("10", "COMPLETED", None));
    let mut failed = snapshot("10", "COMPLETED");
    failed.note = Some("Efficiency unavailable: accounting timeout".into());
    ui.receive(ActionResult::Job {
        token,
        job_id: "10".into(),
        result: Ok(failed.clone()),
    });
    ui.handle_key(key(KeyCode::Esc), &store);
    let retry = ui.open_job("10", "COMPLETED", None);
    assert!(
        matches!(retry.as_slice(), [Effect::FetchJob { fallback: Some(detail), .. }] if detail == &failed.detail)
    );
    assert!(render(&mut ui, &store, 120, 40).contains("accounting timeout"));
    let mut recovered = snapshot("10", "COMPLETED");
    let usage = JobUsage {
        source: "sacct".into(),
        ..JobUsage::default()
    };
    recovered.usage = Some(usage.clone());
    ui.receive(ActionResult::Job {
        token: job_read(&retry),
        job_id: "10".into(),
        result: Ok(recovered),
    });
    ui.handle_key(key(KeyCode::Esc), &store);
    assert!(ui.open_job("10", "COMPLETED", None).is_empty());
    let token = job_read(&ui.handle_key(key(KeyCode::Char('r')), &store));
    ui.receive(ActionResult::Job {
        token,
        job_id: "10".into(),
        result: Ok(failed),
    });
    ui.handle_key(key(KeyCode::Esc), &store);
    assert!(matches!(
        ui.open_job("10", "", None).as_slice(),
        [Effect::FetchJob { .. }]
    ));
    let Some(Modal::Job(view)) = ui.modals.last() else {
        panic!("expected job detail");
    };
    assert_eq!(view.snapshot.as_ref().unwrap().usage.as_ref(), Some(&usage));
    assert!(render(&mut ui, &store, 120, 40).contains("previous accounting result"));
    ui.handle_key(key(KeyCode::Esc), &store);
    let effect = ui.open_job("123_4", "RUNNING", None);
    assert!(matches!(&effect[0], Effect::FetchJob { job_id, .. } if job_id == "123_4"));
}

#[test]
fn notifications_have_deadlines_only_while_visible_and_stay_bounded() {
    let mut ui = Ui::new(Config::default());
    let now = Instant::now();
    assert_eq!(ui.next_deadline(), None);
    for index in 0..8 {
        ui.notify_at(format!("Notice {index}"), now);
    }
    assert_eq!(ui.toasts.len(), TOAST_CAPACITY);
    assert_eq!(ui.next_deadline(), Some(now + Duration::from_secs(20)));
    assert!(!ui.expire(now + Duration::from_secs(19)));
    assert!(ui.expire(now + Duration::from_secs(20)));
    assert_eq!(ui.next_deadline(), None);
}

#[test]
fn settings_only_apply_after_successful_persistence() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.handle_key(key(KeyCode::Char('s')), &store);
    let Some(Modal::Settings(view)) = ui.modals.last_mut() else {
        panic!("expected settings");
    };
    view.values[0] = "dracula".into();
    assert!(
        matches!(ui.handle_key(ctrl('s'), &store).first(), Some(Effect::SaveConfig(config)) if config.theme == "dracula")
    );
    assert_eq!(ui.config().theme, "nord");
    ui.receive(ActionResult::ConfigSaved(Err("read-only directory".into())));
    assert_eq!(ui.config().theme, "nord");
    assert!(
        matches!(ui.modals.last(), Some(Modal::Settings(view)) if !view.saving && view.error.is_some())
    );
    ui.handle_key(ctrl('s'), &store);
    ui.receive(ActionResult::ConfigSaved(Ok(())));
    assert_eq!(ui.config().theme, "dracula");
    assert!(ui.modals.is_empty());
}

#[test]
fn detail_log_keeps_original_line_numbers_and_editor_handoff_effect() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    let effects = ui.open_job("10", "COMPLETED", None);
    let token = job_read(&effects);
    ui.receive(ActionResult::Job {
        token,
        job_id: "10".into(),
        result: Ok(snapshot("10", "COMPLETED")),
    });
    let effects = ui.handle_key(key(KeyCode::Char('o')), &store);
    let [Effect::FetchLog { token, path, .. }] = effects.as_slice() else {
        panic!("expected log");
    };
    let path = path.clone();
    ui.receive(ActionResult::Log {
        token: token.clone(),
        result: Ok(Tail {
            lines: vec!["line 900".into(), "line 901".into()],
            first_line: 900,
            total_lines: 901,
            path: path.clone(),
        }),
    });
    let text = render(&mut ui, &store, 120, 24);
    assert!(text.contains("900 │ line 900"));
    let effects = ui.handle_key(key(KeyCode::Char('r')), &store);
    let [Effect::FetchLog { token, .. }] = effects.as_slice() else {
        panic!("expected reload");
    };
    let loading = render(&mut ui, &store, 120, 24);
    assert!(loading.contains("line 900"));
    assert!(loading.contains("Loading…"));
    ui.receive(ActionResult::Log {
        token: token.clone(),
        result: Err("reload failed".into()),
    });
    let failed = render(&mut ui, &store, 120, 24);
    assert!(failed.contains("line 900"));
    assert!(failed.contains("reload failed"));
    assert!(
        matches!(ui.handle_key(key(KeyCode::Char('e')), &store).first(), Some(Effect::Editor(value)) if *value == path)
    );
    ui.handle_key(key(KeyCode::Esc), &store);
    assert!(matches!(ui.modals.last(), Some(Modal::Job(_))));
}

#[test]
fn emacs_filter_and_settings_bindings_work_without_vim_globals() {
    let store = populated_store();
    let config = Config {
        keybind_mode: "emacs".into(),
        ..Config::default()
    };
    let mut ui = Ui::new(config);
    ui.observe_data(&store);
    ui.handle_key(ctrl('s'), &store);
    assert!(ui.tables[0].editing_filter);
    ui.handle_key(key(KeyCode::Esc), &store);
    ui.handle_key(ctrl(','), &store);
    assert!(matches!(ui.modals.last(), Some(Modal::Settings(_))));
}

fn rendered_sidebar_width(buffer: &ratatui::buffer::Buffer) -> u16 {
    (0..buffer.area.width)
        .find(|x| buffer[(*x, 2)].symbol() == "╭")
        .map_or(0, |x| buffer.area.width - x)
}

#[test]
fn sidebar_resizing_preserves_table_space_and_survives_collapse_and_terminal_changes() {
    let mut store = populated_store();
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    let initial = rendered_sidebar_width(&render_buffer(&mut ui, &store, 120, 24));
    ui.handle_key(key(KeyCode::Char(']')), &store);
    assert_eq!(
        rendered_sidebar_width(&render_buffer(&mut ui, &store, 120, 24)),
        initial + 4
    );
    for _ in 0..30 {
        ui.handle_key(key(KeyCode::Char(']')), &store);
    }
    let preferred = rendered_sidebar_width(&render_buffer(&mut ui, &store, 120, 24));
    assert_eq!(120 - preferred, 60);
    assert_eq!(
        100 - rendered_sidebar_width(&render_buffer(&mut ui, &store, 100, 24)),
        60
    );
    assert_eq!(
        rendered_sidebar_width(&render_buffer(&mut ui, &store, 160, 24)),
        preferred
    );

    ui.handle_key(key(KeyCode::Char('b')), &store);
    let collapsed = render_buffer(&mut ui, &store, 180, 24);
    assert_eq!(rendered_sidebar_width(&collapsed), 0);
    assert!(!line(&collapsed, 3).contains("Cluster Load"));
    ui.handle_key(key(KeyCode::Char('b')), &store);
    assert_eq!(
        rendered_sidebar_width(&render_buffer(&mut ui, &store, 180, 24)),
        preferred
    );
    for (width, height) in [(80, 24), (160, 8), (12, 4)] {
        assert_eq!(
            rendered_sidebar_width(&render_buffer(&mut ui, &store, width, height)),
            0
        );
        assert_eq!(
            rendered_sidebar_width(&render_buffer(&mut ui, &store, 160, 24)),
            preferred
        );
    }
    ui.handle_key(key(KeyCode::Char('=')), &store);
    let automatic = rendered_sidebar_width(&render_buffer(&mut ui, &store, 160, 24));
    assert!(automatic < preferred);
    apply_test_data(
        &mut store,
        Dataset::AllUsersJobs(vec![store::AllUsersJob {
            id: "500".into(),
            state: "PENDING".into(),
            partition: "a-partition-name-that-is-much-wider-than-the-sidebar".into(),
            tres: "cpu=128,mem=512G".into(),
            ..Default::default()
        }]),
    );
    ui.observe_data(&store);
    assert_eq!(
        rendered_sidebar_width(&render_buffer(&mut ui, &store, 160, 24)),
        automatic
    );
}

#[test]
fn sidebar_vertical_scroll_reaches_pending_resources_without_moving_selection() {
    let mut store = populated_store();
    apply_test_data(&mut store, Dataset::Nodes(vec![idle_node()]));
    apply_test_data(
        &mut store,
        Dataset::AllUsersJobs(vec![store::AllUsersJob {
            id: "500".into(),
            state: "PENDING".into(),
            partition: "cpu".into(),
            tres: "cpu=913,mem=682G".into(),
            ..Default::default()
        }]),
    );
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    render_buffer(&mut ui, &store, 120, 14);
    for _ in 0..20 {
        ui.handle_key(key(KeyCode::Char('[')), &store);
    }
    let first = render_buffer(&mut ui, &store, 120, 14);
    assert_eq!(rendered_sidebar_width(&first), 24);
    assert!(!render(&mut ui, &store, 120, 14).contains("1j·913c·682G"));
    let cursor = ui.tables[0].cursor;
    for _ in 0..30 {
        ui.handle_key(KeyEvent::new(KeyCode::Down, KeyModifiers::ALT), &store);
    }
    let scrolled = render(&mut ui, &store, 120, 14);
    assert!(scrolled.contains("1j·913c·682G"));
    assert!(scrolled.contains("Cluster Load"));
    assert_eq!(ui.tables[0].cursor, cursor);
    ui.observe_data(&store);
    assert!(render(&mut ui, &store, 120, 14).contains("1j·913c·682G"));
    ui.handle_key(key(KeyCode::Down), &store);
    assert_ne!(ui.tables[0].cursor, cursor);

    apply_test_data(&mut store, Dataset::Nodes(Vec::new()));
    apply_test_data(&mut store, Dataset::AllUsersJobs(Vec::new()));
    ui.observe_data(&store);
    let refreshed = render(&mut ui, &store, 120, 36);
    assert!(refreshed.contains("0/0 free (n/a)"));
    assert!(!refreshed.contains("1j·913c·682G"));
}

#[test]
fn sidebar_shortcuts_remain_literal_filter_text_in_both_key_presets() {
    let mut store = populated_store();
    apply_test_data(
        &mut store,
        Dataset::RunningJobs(vec![RunningJob {
            id: "789".into(),
            name: "b[]=".into(),
            state: "RUNNING".into(),
            ..Default::default()
        }]),
    );
    for mode in ["vim", "emacs"] {
        let mut ui = Ui::new(Config {
            keybind_mode: mode.into(),
            ..Config::default()
        });
        ui.observe_data(&store);
        let width = rendered_sidebar_width(&render_buffer(&mut ui, &store, 120, 24));
        ui.handle_key(
            if mode == "emacs" {
                ctrl('s')
            } else {
                key(KeyCode::Char('/'))
            },
            &store,
        );
        for ch in "b[]=".chars() {
            ui.handle_key(key(KeyCode::Char(ch)), &store);
        }
        assert_eq!(
            rendered_sidebar_width(&render_buffer(&mut ui, &store, 120, 24)),
            width
        );
        assert_eq!(ui.tables[0].filter, "b[]=");
        assert_eq!(ui.tables[0].indices.len(), 1);
        assert_eq!(
            source_for(0, &store, &[]).key(ui.tables[0].indices[0]),
            "789"
        );
    }
}
