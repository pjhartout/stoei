use std::collections::BTreeMap;
use std::time::{Duration, Instant};

use chrono::NaiveDate;

use super::*;

fn running(id: &str, state: &str) -> RunningJob {
    RunningJob {
        id: id.into(),
        state: state.into(),
        ..RunningJob::default()
    }
}

fn history(id: &str, state: &str) -> HistoryJob {
    HistoryJob {
        id: id.into(),
        state: state.into(),
        ..HistoryJob::default()
    }
}

fn history_data(jobs: Vec<HistoryJob>) -> Dataset {
    Dataset::History(HistoryResult {
        jobs,
        ..HistoryResult::default()
    })
}

fn apply(store: &mut Store, data: Dataset, now: Instant) -> ApplyOutcome {
    let section = data.section();
    let generation = store.begin(section);
    store.apply(section, generation, Ok(data), now)
}

#[test]
fn obsolete_results_cannot_create_or_replace_a_snapshot() {
    let now = Instant::now();
    let section = Section::RunningJobs;
    let mut store = Store::new();
    let first = store.begin(section);
    let current = store.begin(section);
    let jobs = Dataset::RunningJobs(vec![running("1", "RUNNING")]);
    assert!(!store.apply(section, first, Ok(jobs.clone()), now).accepted);
    assert!(!store.has_data(section));
    assert!(!store.settled(section));
    assert_eq!(
        store.apply(section, current, Ok(jobs), now).changed,
        Some(section)
    );

    let stale = store.begin(section);
    let current = store.begin(section);
    let later = now + Duration::from_secs(2);
    for result in [Ok(Dataset::RunningJobs(Vec::new())), Err("outage".into())] {
        let outcome = store.apply(section, stale, result, later);
        assert!(!outcome.accepted);
        assert_eq!(outcome.changed, None);
        assert!(outcome.notification.is_none());
        assert!(outcome.completed_ids.is_empty());
        assert_eq!(store.running_jobs[0].id, "1");
        assert_eq!(store.generation(section), current);
        assert_eq!(store.meta(section).state, State::Loading);
        assert_eq!(store.meta(section).last_success, Some(now));
        assert_eq!(store.meta(section).last_updated, Some(now));
    }
    let outcome = store.apply(
        section,
        current,
        Ok(Dataset::RunningJobs(Vec::new())),
        later,
    );
    assert_eq!(outcome.changed, Some(section));
    assert_eq!(outcome.completed_ids, ["1"]);
    assert!(outcome.notification.is_none());
    assert!(!store.any_loading());
}

#[test]
fn recurring_refresh_errors_preserve_the_snapshot_and_notify_once_until_recovery() {
    let now = Instant::now();
    let section = Section::RunningJobs;
    let mut store = Store::new();
    let jobs = Dataset::RunningJobs(vec![running("1", "RUNNING")]);
    apply(&mut store, jobs.clone(), now);
    for offset in 1..=3 {
        let when = now + Duration::from_secs(offset);
        let generation = store.begin(section);
        assert_eq!(store.meta(section).state, State::Loading);
        assert!(store.has_data(section));
        let outcome = store.apply(section, generation, Err("squeue unavailable".into()), when);
        assert_eq!(outcome.notification.is_some(), offset == 1);
        assert_eq!(outcome.changed, None);
        assert!(outcome.completed_ids.is_empty());
        assert_eq!(store.running_jobs[0].id, "1");
        assert_eq!(store.meta(section).state, State::Error);
        assert_eq!(store.meta(section).last_success, Some(now));
        assert_eq!(store.meta(section).last_updated, Some(when));
    }
    let when = now + Duration::from_secs(4);
    let recovery = apply(&mut store, jobs.clone(), when);
    assert_eq!(
        recovery.notification.as_deref(),
        Some("running_jobs: data refresh recovered")
    );
    assert_eq!(recovery.changed, None);
    assert_eq!(store.meta(section).last_success, Some(when));
    assert!(store.meta(section).err.is_none());
    assert!(apply(&mut store, jobs, when).notification.is_none());
    let generation = store.begin(section);
    assert!(
        store
            .apply(section, generation, Err("down".into()), when)
            .notification
            .is_some()
    );
}

#[test]
fn sections_become_ready_independently_including_successful_empty_snapshots() {
    let now = Instant::now();
    let mut store = Store::new();
    for section in [Section::Nodes, Section::History] {
        let generation = store.begin(section);
        assert!(
            store
                .apply(section, generation, Err("down".into()), now)
                .notification
                .is_some()
        );
        assert!(store.settled(section));
        assert!(!store.has_data(section));
    }
    assert_eq!(
        apply(&mut store, Dataset::AllUsersJobs(Vec::new()), now).changed,
        None
    );
    assert_eq!(store.meta(Section::AllUsersJobs).last_success, Some(now));
    assert!(!store.has_data(Section::Nodes));
    let outcome = apply(&mut store, Dataset::Nodes(Vec::new()), now);
    assert!(outcome.notification.unwrap().contains("recovered"));
    assert_eq!(outcome.changed, None);
    assert_eq!(store.meta(Section::Nodes).last_success, Some(now));
    assert_eq!(store.meta(Section::History).state, State::Error);
}

#[test]
fn invalid_refreshes_report_the_reason_and_preserve_the_previous_dataset() {
    let now = Instant::now();
    for (data, reason) in [
        (Dataset::Nodes(Vec::new()), "received nodes"),
        (
            Dataset::RunningJobs(vec![RunningJob::default(); MAX_ROWS + 1]),
            "row limit",
        ),
    ] {
        let mut store = Store::new();
        let section = Section::RunningJobs;
        apply(
            &mut store,
            Dataset::RunningJobs(vec![running("1", "RUNNING")]),
            now,
        );
        let generation = store.begin(section);
        let outcome = store.apply(section, generation, Ok(data), now);
        assert!(outcome.notification.is_some());
        assert_eq!(outcome.changed, None);
        assert_eq!(store.meta(section).state, State::Error);
        assert!(store.meta(section).err.as_ref().unwrap().contains(reason));
        assert_eq!(store.running_jobs[0].id, "1");
    }
}

#[test]
fn completion_overlay_survives_stale_journal_and_is_absorbed_by_terminal_record() {
    let now = Instant::now();
    let mut store = Store::new();
    apply(
        &mut store,
        history_data(vec![history("1", "RUNNING"), history("2", "COMPLETED")]),
        now,
    );
    let completion = HistoryJob {
        elapsed: "00:05:00".into(),
        ..history("1", "COMPLETED")
    };
    assert!(store.add_completed_job(completion.clone()).unwrap());
    assert!(!store.add_completed_job(completion.clone()).unwrap());
    assert_eq!(store.history_jobs.len(), 2);
    assert_eq!(store.history_jobs[0].state, "COMPLETED");
    apply(&mut store, history_data(vec![history("1", "RUNNING")]), now);
    assert_eq!(store.history_jobs.len(), 1);
    assert_eq!(store.history_jobs[0].elapsed, "00:05:00");
    let final_record = HistoryJob {
        elapsed: "00:06:00".into(),
        ..completion
    };
    apply(&mut store, history_data(vec![final_record]), now);
    assert!(store.completed.is_empty());
    assert_eq!(store.history_jobs[0].elapsed, "00:06:00");
    assert_eq!(store.merged_jobs()[0].state, "COMPLETED");
}

#[test]
fn repeated_completion_newest_record_wins_and_live_rows_deduplicate() {
    let now = Instant::now();
    let mut store = Store::new();
    apply(
        &mut store,
        Dataset::RunningJobs(vec![running("1", "RUNNING")]),
        now,
    );
    store.add_completed_job(history("1", "FAILED")).unwrap();
    store.add_completed_job(history("1", "COMPLETED")).unwrap();
    assert_eq!(store.history_jobs.len(), 1);
    assert_eq!(store.merged_jobs().len(), 1);
    assert!(store.merged_jobs()[0].active);
    apply(&mut store, Dataset::RunningJobs(Vec::new()), now);
    assert_eq!(store.merged_jobs()[0].state, "COMPLETED");
    assert!(!store.merged_jobs()[0].active);
    assert!(store.add_completed_job(history("2", "COMPLETING")).is_err());
}

#[test]
fn merged_history_waits_for_successful_live_snapshot_before_relabeling() {
    let now = Instant::now();
    let mut store = Store::new();
    apply(&mut store, history_data(vec![history("1", "RUNNING")]), now);
    assert_eq!(store.merged_jobs()[0].state, "RUNNING");
    let generation = store.begin(Section::RunningJobs);
    store.apply(Section::RunningJobs, generation, Err("down".into()), now);
    assert_eq!(store.merged_jobs()[0].state, "RUNNING");
    apply(&mut store, Dataset::RunningJobs(Vec::new()), now);
    assert_eq!(store.merged_jobs()[0].state, "UNKNOWN");
}

#[test]
fn array_range_deduplicates_leader_but_concrete_task_keeps_its_own_identity() {
    let merged = merge_jobs(
        &[running("10_[0-9]", "PENDING"), running("20_3", "RUNNING")],
        &[
            history("10", "PENDING"),
            history("20_3", "RUNNING"),
            history("20_4", "COMPLETED"),
        ],
        true,
    );
    assert_eq!(merged.len(), 3);
    assert_eq!(
        merged.iter().map(|job| job.id.as_str()).collect::<Vec<_>>(),
        ["10_[0-9]", "20_3", "20_4"]
    );
}

#[test]
fn merged_jobs_group_by_state_then_newest_start_and_stable_id() {
    let jobs = [
        RunningJob {
            start_time: "2026-09-30T10:00:00".into(),
            ..running("4", "RUNNING")
        },
        running("7", "FAILED"),
        running("1", "PENDING"),
        running("6", "COMPLETING"),
        RunningJob {
            start_time: "2026-09-30T11:00:00".into(),
            ..running("3", "RUNNING")
        },
    ];
    let merged = merge_jobs(&jobs, &[history("8", "COMPLETED")], true);
    assert_eq!(
        merged.iter().map(|job| job.id.as_str()).collect::<Vec<_>>(),
        ["1", "3", "4", "6", "7", "8"]
    );
    assert!(merged.last().unwrap().nodes.is_empty());
}

#[test]
fn journal_detail_preserves_log_paths_and_outcome() {
    let job = HistoryJob {
        std_out: "/work/out.log".into(),
        std_err: "/work/err.log".into(),
        restart: "3".into(),
        exit_code: "1:0".into(),
        ..history("123", "FAILED")
    };
    let detail = journal_detail(&job);
    assert_eq!(detail.fields["StdOut"], "/work/out.log");
    assert_eq!(detail.fields["StdErr"], "/work/err.log");
    assert_eq!(detail.fields["JobState"], "FAILED");
    assert_eq!(detail.fields["Restarts"], "3");
}

fn gpu_node(name: &str, state: &str, model: &str, total: u64, allocated: u64) -> Node {
    Node {
        name: name.into(),
        state: state.into(),
        cpu_tot: "64".into(),
        cpu_alloc: "8".into(),
        real_mem: "4096".into(),
        alloc_mem: "1024".into(),
        gres: format!("gpu:{model}:{total}"),
        cfg_tres: format!("cpu=64,gres/gpu={total},gres/gpu:{model}={total}"),
        alloc_tres: format!("gres/gpu={allocated},gres/gpu:{model}={allocated}"),
        ..Node::default()
    }
}

#[test]
fn node_and_cluster_views_share_known_and_missing_gpu_allocations() {
    let now = Instant::now();
    let mut store = Store::new();
    for (state, cfg, alloc, expected) in [
        ("MIXED", "gres/gpu=4", "cpu=48,gres/gpu=3", Some(3)),
        ("MIXED", "gres/gpu=4", "cpu=8", Some(0)),
        ("ALLOCATED", "", "gres/gpu=0", Some(0)),
        ("IDLE", "", "", Some(0)),
        ("MIXED", "gres/gpu=4", "", None),
        ("MIXED", "", "(null)", None),
        ("MIXED", "", "cpu=8,gres/gpu=N/A", None),
    ] {
        let node = Node {
            name: "gpu1".into(),
            state: state.into(),
            gres: "gpu:l40s:4(S:0)".into(),
            cfg_tres: cfg.into(),
            alloc_tres: alloc.into(),
            ..Node::default()
        };
        apply(&mut store, Dataset::Nodes(vec![node]), now);
        let row = &store.node_displays()[0];
        let cluster = store.cluster_stats();
        assert_eq!(row.gpu_types, "4x L40S");
        assert_eq!(row.gpus_alloc, expected, "{state} {cfg} {alloc}");
        assert_eq!(row.gpu_usage_pct(), expected.map(|n| n as f64 * 25.0));
        assert_eq!(cluster.gpus, cluster.gpus_by_type["L40S"]);
        assert_eq!(cluster.gpus.total, row.gpus_total);
        assert_eq!(cluster.gpus.allocated, expected.unwrap_or(0));
        assert_eq!(cluster.gpus.unknown, if expected.is_none() { 4 } else { 0 });
        assert_eq!(cluster.gpus.known_free(), expected.map_or(0, |n| 4 - n));
    }

    for (allocation, used, a100, h200) in [
        ("gres/gpu=1", 1, (1, 1), (1, 1)),
        ("gres/gpu=3", 3, (0, 1), (0, 1)),
        ("gres/gpu=1,gres/gpu:h200=1", 1, (2, 0), (1, 0)),
    ] {
        let node = Node {
            name: "gpu2".into(),
            state: "MIXED".into(),
            cfg_tres: "gres/gpu=4".into(),
            gres: "gpu:a100:2,gpu:h200:2".into(),
            alloc_tres: allocation.into(),
            ..Node::default()
        };
        apply(&mut store, Dataset::Nodes(vec![node]), now);
        assert_eq!(store.node_displays()[0].gpus_alloc, Some(used));
        assert_eq!(store.cluster_stats().gpus.known_free(), 4 - used);
        for (model, expected) in [("A100", a100), ("H200", h200)] {
            let capacity = &store.cluster_stats().gpus_by_type[model];
            assert_eq!(
                (capacity.known_free(), capacity.unknown),
                expected,
                "{allocation} {model}"
            );
        }
    }
}

#[test]
fn unavailable_nodes_keep_their_reported_usage_outside_schedulable_capacity() {
    for state in ["ALLOCATED+DRAIN", "MIXED+DRAIN"] {
        let nodes = vec![
            Node {
                cpu_alloc: "0".into(),
                alloc_mem: "0".into(),
                ..gpu_node("online", "IDLE", "h200", 4, 0)
            },
            Node {
                cpu_alloc: "32".into(),
                alloc_mem: "2048".into(),
                ..gpu_node("draining", state, "a100", 8, 4)
            },
            gpu_node("down", "DOWN", "a100", 8, 0),
            Node {
                state: "DOWN+DRAIN+NOT_RESPONDING".into(),
                cfg_tres: "gres/gpu=22,gres/gpu:h100_pcie_1g.10gb=16,gres/gpu:h100_pcie_2g.20gb=6"
                    .into(),
                ..Node::default()
            },
        ];
        let mut store = Store::new();
        apply(&mut store, Dataset::Nodes(nodes), Instant::now());
        let stats = store.cluster_stats();
        assert_eq!(
            (stats.total_nodes, stats.free_nodes, stats.allocated_nodes),
            (1, 1, 0)
        );
        assert_eq!((stats.draining_nodes, stats.offline_nodes), (1, 2));
        assert_eq!((stats.total_cpus, stats.allocated_cpus), (64, 0));
        assert_eq!(
            (stats.total_memory_gb, stats.allocated_memory_gb),
            (4.0, 0.0)
        );
        assert_eq!(
            (stats.free_cpus_pct(), stats.free_memory_pct()),
            (100.0, 100.0)
        );
        assert_eq!(
            stats.gpus,
            GpuCapacity {
                total: 42,
                unavailable: 38,
                ..Default::default()
            }
        );
        assert_eq!(stats.gpus_by_type["H200"].known_free(), 4);
        assert_eq!(stats.gpus_by_type["A100"].unavailable, 16);
        assert_eq!(stats.gpus_by_type["H100_PCIE_1G.10GB"].unavailable, 16);
        assert_eq!(stats.gpus_by_type["H100_PCIE_2G.20GB"].unavailable, 6);
        assert!(!stats.gpus_by_type.contains_key("GPU"));
        let draining = &store.node_displays()[1];
        assert_eq!(
            (
                draining.cpus_alloc,
                draining.memory_alloc_gb,
                draining.gpus_alloc
            ),
            (32, 2.0, Some(4))
        );
    }
}

fn job(id: &str, user: &str, state: &str, tres: &str) -> AllUsersJob {
    AllUsersJob {
        id: id.into(),
        user: user.into(),
        state: state.into(),
        tres: tres.into(),
        ..AllUsersJob::default()
    }
}

#[test]
fn pending_arrays_multiply_resources_and_normalize_reason_buckets() {
    let jobs = [
        AllUsersJob {
            partition: "gpu".into(),
            reason: "ReqNodeNotAvail, UnavailableNodes:gpu1".into(),
            ..job("1_[0-3]", "alice", "PD", "cpu=2,mem=4G,gres/gpu:a100=1")
        },
        AllUsersJob {
            partition: "gpu".into(),
            reason: "ReqNodeNotAvail, UnavailableNodes:gpu2".into(),
            ..job("2", "alice", "PENDING", "cpu=4,mem=8G,gres/gpu:a100=2")
        },
        job("3", "alice", "RUNNING", "cpu=100"),
    ];
    let queue = aggregate_pending_queue(&jobs);
    let partition = &queue["gpu"];
    assert_eq!(queue.len(), 1);
    assert_eq!(
        (
            partition.jobs_count,
            partition.cpus,
            partition.memory_gb,
            partition.gpus_by_type["A100"]
        ),
        (5, 12, 24.0, 6)
    );
    let users = aggregate_pending_user_stats(&jobs);
    assert_eq!(users.len(), 1);
    assert_eq!(users[0].pending_cpus, 12);
    assert_eq!(users[0].pending_reasons, "5x ReqNodeNotAvail");
}

#[test]
fn running_users_resolve_generic_models_deduplicate_nodes_and_classify_arrays() {
    let models = BTreeMap::from([
        ("gpu01".into(), "L40S".into()),
        ("gpu02".into(), "L40S".into()),
    ]);
    let jobs = [
        AllUsersJob {
            node_list: "gpu[01-02]".into(),
            ..job("1_0", "alice", "RUNNING", "cpu=8,mem=4G,gres/gpu=2")
        },
        AllUsersJob {
            node_list: "gpu01".into(),
            ..job(
                "1_1",
                "alice",
                "RUNNING",
                "cpu=4,gres/gpu=1,gres/gpu:l40s=1",
            )
        },
        AllUsersJob {
            num_nodes: "4-8".into(),
            node_list: "gpu01".into(),
            ..job("2", "alice", "RUNNING", "")
        },
        job("3_[0-9]", "alice", "PENDING", "cpu=100,gres/gpu=100"),
    ];
    let users = aggregate_user_stats(&jobs, &models);
    assert_eq!(users[0].job_count, 3);
    assert_eq!(users[0].total_cpus, 16);
    assert_eq!(users[0].total_gpus, 3);
    assert_eq!(users[0].gpu_types, "3x L40S");
    assert_eq!(
        (
            users[0].total_nodes,
            users[0].array_count,
            users[0].plain_job_count,
            users[0].generic_gpu_jobs
        ),
        (2, 1, 1, 1)
    );
}

#[test]
fn personal_job_stats_use_the_job_list_and_survive_stale_cluster_updates() {
    let now = Instant::now();
    let mut store = Store::new();
    store.user = "alice".into();
    let jobs = vec![
        RunningJob {
            node_list: "gpu[01-02]".into(),
            tres: "cpu=8,mem=4G,gres/gpu=2".into(),
            ..running("1_0", "RUNNING")
        },
        RunningJob {
            node_list: "gpu01".into(),
            tres: "cpu=4,mem=2G,gres/gpu=1,gres/gpu:l40s=1".into(),
            ..running("1_1", "RUNNING")
        },
        RunningJob {
            node_list: "cpu01".into(),
            tres: "cpu=2,mem=1G".into(),
            ..running("2", "COMPLETING")
        },
        RunningJob {
            tres: "cpu=1000,mem=1000G,gres/gpu=1000".into(),
            ..running("3_[0-9]", "PENDING")
        },
        RunningJob {
            tres: "cpu=1000,mem=1000G,gres/gpu=1000".into(),
            ..running("4", "COMPLETED")
        },
    ];
    apply(&mut store, Dataset::RunningJobs(jobs), now);
    let stats = store.my_job_stats().clone();
    assert_eq!(
        (stats.total_cpus, stats.total_memory_gb, stats.total_gpus),
        (14, 7.0, 3)
    );
    assert_eq!(
        (
            stats.job_count,
            stats.array_count,
            stats.plain_job_count,
            stats.total_nodes
        ),
        (3, 1, 1, 3)
    );
    assert!(!store.has_data(Section::AllUsersJobs));

    apply(
        &mut store,
        Dataset::AllUsersJobs(vec![job("old", "alice", "RUNNING", "cpu=99,mem=99G")]),
        now,
    );
    assert_eq!(store.my_job_stats(), &stats);
    apply(
        &mut store,
        Dataset::Nodes(vec![
            Node {
                name: "gpu01".into(),
                gres: "gpu:l40s:4".into(),
                ..Node::default()
            },
            Node {
                name: "gpu02".into(),
                gres: "gpu:l40s:4".into(),
                ..Node::default()
            },
        ]),
        now,
    );
    assert_eq!(store.my_job_stats().gpu_types, "3x L40S");
    assert_eq!(store.my_job_stats().total_cpus, 14);

    apply(
        &mut store,
        Dataset::RunningJobs(vec![running("3_[0-9]", "PENDING")]),
        now,
    );
    assert_eq!(store.my_job_stats().job_count, 0);
    assert_eq!(store.my_job_stats().total_cpus, 0);
    assert_eq!(store.my_job_stats().total_memory_gb, 0.0);
    assert_eq!(store.my_job_stats().total_gpus, 0);
    assert_eq!(store.my_job_stats().total_nodes, 0);
    apply(
        &mut store,
        Dataset::AllUsersJobs(vec![job("old", "alice", "RUNNING", "cpu=99,mem=99G")]),
        now,
    );
    assert_eq!(store.my_job_stats().job_count, 0);
}

#[test]
fn personal_job_stats_keep_the_last_snapshot_during_refresh_and_failure() {
    let now = Instant::now();
    let mut store = Store::new();
    apply(
        &mut store,
        Dataset::RunningJobs(vec![RunningJob {
            tres: "cpu=8,mem=4G".into(),
            ..running("1", "RUNNING")
        }]),
        now,
    );
    let stats = store.my_job_stats().clone();
    let stale = store.begin(Section::RunningJobs);
    let current = store.begin(Section::RunningJobs);
    assert_eq!(store.my_job_stats(), &stats);
    assert!(
        !store
            .apply(
                Section::RunningJobs,
                stale,
                Ok(Dataset::RunningJobs(Vec::new())),
                now
            )
            .accepted
    );
    assert_eq!(store.my_job_stats(), &stats);
    store.apply(
        Section::RunningJobs,
        current,
        Err("squeue unavailable".into()),
        now,
    );
    assert_eq!(store.my_job_stats(), &stats);
    apply(&mut store, Dataset::RunningJobs(Vec::new()), now);
    assert_eq!(store.my_job_stats().job_count, 0);
    assert_eq!(store.my_job_stats().total_cpus, 0);
}

#[test]
fn mixed_or_unknown_node_models_leave_generic_gpu_requests_generic() {
    let models = BTreeMap::from([
        ("gpu01".into(), "A100".into()),
        ("gpu02".into(), "L40S".into()),
    ]);
    let jobs = [AllUsersJob {
        node_list: "gpu[01-02]".into(),
        ..job("1", "alice", "RUNNING", "gres/gpu=2")
    }];
    assert_eq!(aggregate_user_stats(&jobs, &models)[0].gpu_types, "2x GPU");
    assert_eq!(
        aggregate_user_stats(&jobs, &BTreeMap::new())[0].gpu_types,
        "2x GPU"
    );
}

#[test]
fn node_jobs_expand_names_and_show_whole_job_resources() {
    let jobs = [AllUsersJob {
        node_list: "gpu[01-02]".into(),
        ..job("1", "alice", "RUNNING", "cpu=16,gres/gpu:a100=4")
    }];
    let rows = jobs_on_node(&jobs, "gpu02");
    assert_eq!(rows.len(), 1);
    assert_eq!((rows[0].cpus, rows[0].gpus), (16, 4));
    assert!(jobs_on_node(&jobs, "gpu03").is_empty());
    let resources = aggregate_account_resources(&jobs);
    assert_eq!(
        (
            resources.total_cpus,
            resources.total_gpus,
            resources.unique_nodes
        ),
        (16, 4, 2)
    );
}

fn association(
    user: &str,
    account: &str,
    factor: &str,
    share: &str,
    usage: &str,
) -> FairShareEntry {
    FairShareEntry {
        user: user.into(),
        account: account.into(),
        fair_share: factor.into(),
        norm_shares: share.into(),
        effectv_usage: usage.into(),
        ..FairShareEntry::default()
    }
}

#[test]
fn fairshare_active_rank_excludes_unused_and_deduplicates_best_association() {
    let entries = [
        association("idle", "a", "1", ".1", "0"),
        association("alice", "a", ".5", ".1", ".2"),
        association("alice", "b", ".8", ".1", ".1"),
        association("bob", "b", ".8", ".2", ".3"),
        association("carol", "c", ".1", ".1", ".8"),
        association("invalid", "a", "NaN", "0", ".2"),
    ];
    let ranked = rank_active_users(&entries);
    assert_eq!(ranked.len(), 3);
    assert_eq!(ranked[0].entry.account, "b");
    assert_eq!((ranked[0].rank, ranked[1].rank, ranked[2].rank), (1, 1, 2));
    assert_eq!(ranked[2].band, UsageBand::Heavy);
    assert_eq!(user_associations(&entries, "alice").len(), 2);
    assert!(usage_ratio(&entries[5]).is_none());
}

#[test]
fn account_ranks_use_usage_share_and_hide_root_unused_and_invalid() {
    let entries = [
        association("", "root", "", "1", "1"),
        association("", "idle", "", ".1", "0"),
        association("", "over", "", ".1", ".8"),
        association("", "under", "", ".5", ".1"),
    ];
    let ranked = rank_accounts(&entries);
    assert_eq!(
        ranked
            .iter()
            .map(|row| row.entry.account.as_str())
            .collect::<Vec<_>>(),
        ["under", "over"]
    );
    assert_eq!(account_count(&entries), 3);
    assert_eq!(ranked[0].band, UsageBand::Under);
    assert_eq!(
        recovery_time(8.0, Duration::from_secs(86_400)),
        Some(Duration::from_secs(3 * 86_400))
    );
    assert!(recovery_time(1.0, Duration::from_secs(86_400)).is_none());
    assert!(recovery_time(f64::INFINITY, Duration::from_secs(1)).is_none());
}

#[test]
fn priority_multi_partition_jobs_count_once_clusterwide_and_per_partition() {
    let entries = [
        PriorityEntry {
            job_id: "1000".into(),
            partition: "a".into(),
            priority: 10,
            ..PriorityEntry::default()
        },
        PriorityEntry {
            job_id: "999".into(),
            partition: "a".into(),
            priority: 10,
            ..PriorityEntry::default()
        },
        PriorityEntry {
            job_id: "999".into(),
            partition: "b".into(),
            priority: 9,
            ..PriorityEntry::default()
        },
        PriorityEntry {
            job_id: "1001".into(),
            partition: "b".into(),
            priority: 8,
            ..PriorityEntry::default()
        },
    ];
    let ranked = rank_pending(&entries);
    assert_eq!(ranked[0].entry.job_id, "999");
    assert_eq!(ranked[0].pos.cluster_total, 3);
    assert_eq!(ranked[2].pos.cluster, 1);
    assert_eq!(
        (ranked[2].pos.partition, ranked[2].pos.partition_total),
        (1, 2)
    );
    assert_eq!(ranked[3].pos.cluster, 3);
    assert_eq!(by_partition(&ranked)[0].entry.partition, "a");
}

#[test]
fn live_efficiency_uses_allocated_cpus_and_fresh_runtime_and_alloc_tres_memory() {
    let usage = JobUsage {
        source: "sstat".into(),
        sampled: true,
        cpu_time_sec: 120.0,
        max_rss_bytes: 2 << 30,
        disk_read_bytes: 6000,
        ..JobUsage::default()
    };
    let fields = BTreeMap::from([
        ("RunTime".into(), "00:01:00".into()),
        ("NumCPUs".into(), "4".into()),
        ("AllocTRES".into(), "cpu=4,mem=8G".into()),
    ]);
    let efficiency = derive_job_efficiency(&usage, &fields);
    assert!(efficiency.live && efficiency.cpu_known && efficiency.mem_known);
    assert_eq!(efficiency.cpu_percent, 50.0);
    assert_eq!(efficiency.cpu_avail_sec, 240.0);
    assert_eq!(efficiency.mem_percent, 25.0);
    assert_eq!(efficiency.read_bytes_per_sec, 100.0);
}

#[test]
fn mig_gpu_utilization_is_unknown_but_memory_is_measured() {
    let usage = JobUsage {
        sampled: true,
        gpu_util_per_task_percent: Some(0.0),
        gpu_mem_bytes: Some(1024),
        gpus: vec![GPUEntry {
            gpu_type: "h100_pcie_1g.10gb".into(),
            count: 1,
        }],
        ..JobUsage::default()
    };
    let efficiency = derive_job_efficiency(&usage, &BTreeMap::new());
    assert_eq!(efficiency.gpu_utilization, GpuUtilization::Mig);
    assert_eq!(efficiency.gpu_mem_bytes, Some(1024));
}

#[test]
fn sixteen_gpu_job_preserves_slurms_per_task_average() {
    let live = crate::slurm::parse_sstat_usage(
        "123",
        include_str!("../../tests/fixtures/sstat_usage_multi_gpu.txt"),
    );
    let completed = crate::slurm::parse_sacct_usage(
        "123",
        include_str!("../../tests/fixtures/sacct_usage_multi_gpu.txt"),
    );
    let fields = BTreeMap::from([("AllocTRES".into(), "gres/gpu=16".into())]);
    for (usage, fields) in [(live, fields), (completed, BTreeMap::new())] {
        let efficiency = derive_job_efficiency(&usage, &fields);
        assert_eq!(
            efficiency.gpu_utilization,
            GpuUtilization::PerTaskAverage(76.0)
        );
    }
}

#[test]
fn allocated_gpus_distinguish_missing_zero_and_multi_device_task_readings() {
    let fields = BTreeMap::from([("AllocTRES".into(), "gres/gpu=3".into())]);
    for (average, expected) in [
        ("gres/gpumem=0", GpuUtilization::NoData),
        ("gres/gpuutil=0", GpuUtilization::PerTaskAverage(0.0)),
        ("gres/gpuutil=240", GpuUtilization::PerTaskAverage(240.0)),
    ] {
        let raw = format!("123.0|||{average}|gres/gpumem=0|");
        let usage = crate::slurm::parse_sstat_usage("123", &raw);
        let efficiency = derive_job_efficiency(&usage, &fields);
        assert_eq!(efficiency.gpu_utilization, expected);
        assert_eq!(efficiency.gpu_mem_bytes, Some(0));
    }
}

#[test]
fn unsampled_cpu_and_memory_are_unknown() {
    let usage = JobUsage {
        elapsed_sec: 60.0,
        alloc_cpus: 1,
        max_rss_bytes: 1024,
        ..JobUsage::default()
    };
    let fields = BTreeMap::from([("AllocTRES".into(), "mem=1G".into())]);
    let efficiency = derive_job_efficiency(&usage, &fields);
    assert!(!efficiency.cpu_known && !efficiency.mem_known);
}

#[test]
fn timeline_uses_injected_calendar_and_surfaces_requeues() {
    let today = NaiveDate::from_ymd_opt(2026, 9, 30).unwrap();
    let submit = "2026-09-29T09:00:00";
    let start = "2026-09-30T10:00:00";
    let end = "2026-09-30T10:30:00";
    assert_eq!(
        format_compact_timeline(submit, start, end, "COMPLETED", 3, today),
        "09-29 09:00 → 10:00 → 10:30  ↻ 3"
    );
    assert_eq!(
        format_compact_timeline(submit, "Unknown", "", "PENDING", 0, today),
        "09-29 09:00 ⏳"
    );
    assert_eq!(
        format_compact_timeline("N/A", start, end, "FAILED", 3, today),
        "—"
    );
    assert_eq!(parse_restarts("-3"), 0);
}

#[test]
fn display_formats_small_shares_priority_contributions_and_state_roles() {
    assert_eq!(format_percent(".0208"), "2.08%");
    assert_eq!(format_percent(".261"), "26.1%");
    assert_eq!(format_ratio(0.81, true), "0.81×");
    assert_eq!(
        format_rank(147, 171, "active users"),
        "147 of 171 active users (bottom 15%)"
    );
    assert_eq!(format_days(Duration::from_secs(18 * 3600)), "18h");
    assert_eq!(
        format_breakdown(&PriorityFactors {
            fair_share: 100,
            age: 1,
            nice: -3,
            ..PriorityFactors::default()
        }),
        "FairShare 100 · Nice -3 · Age 1"
    );
    assert_eq!(state_role("RUNNING by 123"), "success");
    assert_eq!(state_role("CA"), "muted");
}
