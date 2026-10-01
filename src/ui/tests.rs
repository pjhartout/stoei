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
    let now = Instant::now();
    let generation = store.begin(Section::RunningJobs);
    store.apply(
        Section::RunningJobs,
        generation,
        Ok(Dataset::RunningJobs(vec![
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
        ])),
        now,
    );
    let generation = store.begin(Section::History);
    store.apply(
        Section::History,
        generation,
        Ok(Dataset::History(HistoryResult {
            jobs: vec![HistoryJob {
                id: "10".into(),
                name: "Finished".into(),
                state: "COMPLETED".into(),
                elapsed: "00:20:00".into(),
                std_out: "/tmp/output.log".into(),
                ..Default::default()
            }],
            ..Default::default()
        })),
        now,
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

fn render(ui: &mut Ui, store: &Store, width: u16, height: u16) -> String {
    render_buffer(ui, store, width, height)
        .content
        .iter()
        .map(|cell| cell.symbol())
        .collect()
}

fn render_buffer(ui: &mut Ui, store: &Store, width: u16, height: u16) -> ratatui::buffer::Buffer {
    render_buffer_with_version(ui, store, width, height, "dev")
}

fn render_buffer_with_version(
    ui: &mut Ui,
    store: &Store,
    width: u16,
    height: u16,
    version: &str,
) -> ratatui::buffer::Buffer {
    let logs = LogRing::default();
    let status = RuntimeStatus {
        version,
        update_available: None,
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

fn apply_test_data(store: &mut Store, data: Dataset) {
    let section = data.section();
    let generation = store.begin(section);
    let now = store
        .meta(Section::RunningJobs)
        .last_success
        .unwrap_or_else(Instant::now);
    store.apply(section, generation, Ok(data), now);
}

fn cluster_views(store: &Store) -> [String; 2] {
    let mut ui = Ui::new(Config::default());
    ui.observe_data(store);
    let sidebar = render(&mut ui, store, 160, 36);
    ui.modals.push(Modal::load());
    [sidebar, render(&mut ui, store, 100, 36)]
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
fn missing_cluster_snapshots_never_display_a_capacity_percentage() {
    let mut store = populated_store();
    store.begin(Section::Nodes);
    store.begin(Section::AllUsersJobs);
    for text in cluster_views(&store) {
        assert!(text.contains("Loading cluster…"));
        assert!(text.contains("Loading queue…"));
        assert!(!text.contains('%'));
        assert!(!text.contains("0/0"));
    }
    store.apply(
        Section::Nodes,
        store.generation(Section::Nodes),
        Err("node request failed".into()),
        store.meta(Section::RunningJobs).last_success.unwrap(),
    );
    for text in cluster_views(&store) {
        assert!(text.contains("cluster unavailable"));
        assert!(text.contains("Loading queue…"));
        assert!(!text.contains('%'));
    }
}

#[test]
fn cluster_capacity_and_queue_become_ready_independently() {
    let mut store = populated_store();
    apply_test_data(&mut store, Dataset::Nodes(vec![idle_node()]));
    for text in cluster_views(&store) {
        assert!(text.contains("64/64 free (100.0%)"));
        assert!(text.contains("Loading queue…"));
        assert!(!text.contains("Loading cluster…"));
        assert!(!text.contains("GPUs:"));
    }
    apply_test_data(&mut store, Dataset::AllUsersJobs(Vec::new()));
    for text in cluster_views(&store) {
        assert!(!text.contains("Loading queue…"));
        assert!(!text.contains("Pending:"));
        assert!(text.contains("64/64 free (100.0%)"));
    }
    apply_test_data(&mut store, Dataset::Nodes(Vec::new()));
    for text in cluster_views(&store) {
        assert!(text.contains("0/0 free (n/a)"));
        assert!(!text.contains("100.0%"));
        assert!(!text.contains("Loading cluster…"));
    }
}

#[test]
fn loaded_queue_does_not_invent_unknown_cluster_capacity() {
    let mut store = populated_store();
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
    for text in cluster_views(&store) {
        assert!(text.contains("Loading cluster…"));
        assert!(text.contains("cpu 1j·4c·2G"));
        assert!(!text.contains("Loading queue…"));
        assert!(!text.contains('%'));
    }
}

#[test]
fn cluster_refresh_and_failure_keep_last_successful_capacity_visible() {
    let mut store = populated_store();
    apply_test_data(&mut store, Dataset::Nodes(vec![idle_node()]));
    apply_test_data(&mut store, Dataset::AllUsersJobs(Vec::new()));
    let generation = store.begin(Section::Nodes);
    for text in cluster_views(&store) {
        assert!(text.contains("Refreshing cluster…"));
        assert!(text.contains("64/64 free (100.0%)"));
    }
    store.apply(
        Section::Nodes,
        generation,
        Err("nodes failed".into()),
        store.meta(Section::RunningJobs).last_success.unwrap(),
    );
    for text in cluster_views(&store) {
        assert!(text.contains("Last known cluster"));
        assert!(text.contains("refresh failed"));
        assert!(text.contains("64/64 free (100.0%)"));
    }
}

#[test]
fn unavailable_gpu_hardware_is_distinct_from_allocated_capacity() {
    let mut store = populated_store();
    apply_test_data(
        &mut store,
        Dataset::Nodes(vec![store::Node {
            name: "gpu001".into(),
            state: "DOWN".into(),
            gres: "gpu:h200:8".into(),
            ..idle_node()
        }]),
    );
    for text in cluster_views(&store) {
        assert!(text.contains("H200 0/8 free (0.0%)"));
        assert!(text.contains("8 unavail"));
        assert!(!text.contains("allocated"));
        assert!(!text.contains("100.0%"));
    }
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
                let buffer = render_buffer_with_version(&mut ui, &store, width, height, version);
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
                assert_eq!(
                    buffer[(width / 2, height - 1)].bg,
                    theme::Theme::by_name("nord").border
                );
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
fn array_partition_edits_keep_the_selected_group_when_detail_shows_a_running_task() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    let effects = ui.open_job("123_[0-9%3]", "PENDING", None);
    let Effect::FetchJob { token, .. } = effects[0] else {
        panic!("expected detail request");
    };
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
    let Effect::FetchJob { token, .. } = effects[0] else {
        panic!("expected detail request");
    };
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
    let recovery_row = (4..39)
        .find(|row| line(&buffer, *row).contains("Recovery"))
        .unwrap();
    assert_eq!(buffer[(20, recovery_row + 1)].symbol(), " ");
    assert_ne!(buffer[(21, recovery_row + 1)].symbol(), " ");
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
fn switching_tabs_displays_loaded_rows_without_waiting_for_a_refresh() {
    let mut store = populated_store();
    let generation = store.begin(Section::Nodes);
    store.apply(
        Section::Nodes,
        generation,
        Ok(Dataset::Nodes(vec![store::Node {
            name: "node001".into(),
            state: "IDLE".into(),
            ..Default::default()
        }])),
        Instant::now(),
    );
    let mut ui = Ui::new(Config::default());
    ui.observe_data(&store);
    for switch in [KeyCode::Char('2'), KeyCode::Tab] {
        ui.handle_key(key(switch), &store);
        assert_eq!(ui.active_tab(), 1);
        assert!(render(&mut ui, &store, 80, 24).contains("node001"));
        ui.handle_key(key(KeyCode::BackTab), &store);
        assert_eq!(ui.active_tab(), 0);
        assert!(render(&mut ui, &store, 160, 24).contains("Finished"));
    }
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
    let Effect::FetchJob {
        token: first_token, ..
    } = first[0]
    else {
        panic!("expected a detail fetch");
    };
    ui.handle_key(key(KeyCode::Esc), &store);
    let second = ui.open_job("456_[0-9]", "PENDING", None);
    let Effect::FetchJob {
        token: second_token,
        ref job_id,
        ..
    } = second[0]
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
        token: second_token,
        job_id: "456".into(),
        result: Ok(snapshot("456", "PENDING")),
    });
    assert!(
        matches!(ui.modals.last(), Some(Modal::Job(view)) if !view.loading && view.snapshot.is_some())
    );
    assert!(ui.cache.is_empty());
}

#[test]
fn terminal_cache_reuses_samples_and_live_reopen_always_fetches() {
    let store = populated_store();
    let mut ui = Ui::new(Config::default());
    let effect = ui.open_job("10", "COMPLETED", None);
    let Effect::FetchJob { token, .. } = effect[0] else {
        panic!("expected a detail fetch");
    };
    ui.receive(ActionResult::Job {
        token,
        job_id: "10".into(),
        result: Ok(snapshot("10", "COMPLETED")),
    });
    ui.handle_key(key(KeyCode::Esc), &store);
    assert!(ui.open_job("10", "COMPLETED", None).is_empty());
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
    let Effect::FetchJob { token, .. } = effects[0] else {
        panic!("expected detail");
    };
    ui.receive(ActionResult::Job {
        token,
        job_id: "10".into(),
        result: Ok(snapshot("10", "COMPLETED")),
    });
    let effects = ui.handle_key(key(KeyCode::Char('o')), &store);
    let Effect::FetchLog {
        token, ref path, ..
    } = effects[0]
    else {
        panic!("expected log");
    };
    let path = path.clone();
    ui.receive(ActionResult::Log {
        token,
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
    let Effect::FetchLog { token, .. } = effects[0] else {
        panic!("expected reload");
    };
    let loading = render(&mut ui, &store, 120, 24);
    assert!(loading.contains("line 900"));
    assert!(loading.contains("Loading…"));
    ui.receive(ActionResult::Log {
        token,
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
