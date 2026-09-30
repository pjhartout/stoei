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
fn stale_success_and_failure_leave_loading_data_and_health_unchanged() {
    let now = Instant::now();
    let mut store = Store::new();
    apply(
        &mut store,
        Dataset::RunningJobs(vec![running("1", "RUNNING")]),
        now,
    );
    let stale = store.begin(Section::RunningJobs);
    let current = store.begin(Section::RunningJobs);
    for result in [
        Ok(Dataset::RunningJobs(vec![running("2", "PENDING")])),
        Err("outage".into()),
    ] {
        let outcome = store.apply(
            Section::RunningJobs,
            stale,
            result,
            now + Duration::from_secs(2),
        );
        assert!(!outcome.accepted);
        assert!(outcome.notification.is_none());
        assert!(outcome.completed_ids.is_empty());
        assert_eq!(store.meta(Section::RunningJobs).state, State::Loading);
        assert_eq!(store.running_jobs[0].id, "1");
    }
    let outcome = store.apply(
        Section::RunningJobs,
        current,
        Ok(Dataset::RunningJobs(Vec::new())),
        now,
    );
    assert_eq!(outcome.completed_ids, ["1"]);
    assert!(outcome.notification.is_none());
    assert!(!store.any_loading());
}

#[test]
fn recurring_failure_keeps_data_and_notifies_only_edges() {
    let now = Instant::now();
    let mut store = Store::new();
    assert!(!store.settled(Section::RunningJobs));
    apply(
        &mut store,
        Dataset::RunningJobs(vec![running("1", "RUNNING")]),
        now,
    );
    for expected in [true, false, false] {
        let generation = store.begin(Section::RunningJobs);
        let outcome = store.apply(
            Section::RunningJobs,
            generation,
            Err("squeue unavailable".into()),
            now,
        );
        assert_eq!(outcome.notification.is_some(), expected);
        assert_eq!(store.running_jobs[0].id, "1");
        assert!(outcome.completed_ids.is_empty());
        assert_eq!(store.meta(Section::RunningJobs).state, State::Error);
    }
    assert!(store.settled(Section::RunningJobs));
    let recovery = apply(
        &mut store,
        Dataset::RunningJobs(vec![running("1", "RUNNING")]),
        now,
    );
    assert_eq!(
        recovery.notification.as_deref(),
        Some("running_jobs: data refresh recovered")
    );
    assert!(store.meta(Section::RunningJobs).err.is_none());
    assert!(
        apply(&mut store, Dataset::RunningJobs(Vec::new()), now)
            .notification
            .is_none()
    );
}

#[test]
fn first_failure_settles_and_health_sections_are_independent() {
    let now = Instant::now();
    let mut store = Store::new();
    for section in [Section::Nodes, Section::History] {
        let generation = store.begin(section);
        let outcome = store.apply(section, generation, Err("down".into()), now);
        assert!(outcome.notification.is_some());
        assert!(store.settled(section));
        assert!(!store.has_data(section));
        assert_eq!(store.meta(section).last_success, None);
    }
    let outcome = apply(&mut store, Dataset::Nodes(Vec::new()), now);
    assert!(outcome.notification.unwrap().contains("recovered"));
    assert_eq!(store.meta(Section::History).state, State::Error);
}

#[test]
fn successful_empty_snapshots_are_ready_independently() {
    let now = Instant::now();
    let mut store = Store::new();
    assert!(!store.has_data(Section::Nodes));
    assert!(!store.has_data(Section::AllUsersJobs));
    apply(&mut store, Dataset::AllUsersJobs(Vec::new()), now);
    assert!(store.has_data(Section::AllUsersJobs));
    assert!(!store.has_data(Section::Nodes));
    apply(&mut store, Dataset::Nodes(Vec::new()), now);
    assert!(store.has_data(Section::Nodes));
    assert_eq!(store.meta(Section::Nodes).last_success, Some(now));
    assert_eq!(store.meta(Section::AllUsersJobs).last_success, Some(now));
}

#[test]
fn successful_snapshot_survives_refresh_and_error_without_freshness_reset() {
    let now = Instant::now();
    let mut store = Store::new();
    let node = Node {
        name: "n01".into(),
        state: "IDLE".into(),
        ..Node::default()
    };
    apply(&mut store, Dataset::Nodes(vec![node.clone()]), now);
    let generation = store.begin(Section::Nodes);
    assert!(store.has_data(Section::Nodes));
    assert_eq!(store.meta(Section::Nodes).state, State::Loading);
    let failed_at = now + Duration::from_secs(2);
    store.apply(
        Section::Nodes,
        generation,
        Err("controller unavailable".into()),
        failed_at,
    );
    assert!(store.has_data(Section::Nodes));
    assert_eq!(store.nodes, [node]);
    assert_eq!(store.meta(Section::Nodes).state, State::Error);
    assert_eq!(store.meta(Section::Nodes).last_updated, Some(failed_at));
    assert_eq!(store.meta(Section::Nodes).last_success, Some(now));
    let recovered_at = now + Duration::from_secs(4);
    apply(&mut store, Dataset::Nodes(Vec::new()), recovered_at);
    assert!(store.has_data(Section::Nodes));
    assert_eq!(store.meta(Section::Nodes).last_success, Some(recovered_at));
}

#[test]
fn stale_results_cannot_create_or_replace_a_successful_snapshot() {
    let now = Instant::now();
    let mut store = Store::new();
    let stale = store.begin(Section::Nodes);
    let current = store.begin(Section::Nodes);
    let result = store.apply(Section::Nodes, stale, Ok(Dataset::Nodes(Vec::new())), now);
    assert!(!result.accepted);
    assert!(!store.has_data(Section::Nodes));
    let succeeded_at = now + Duration::from_secs(1);
    store.apply(
        Section::Nodes,
        current,
        Ok(Dataset::Nodes(Vec::new())),
        succeeded_at,
    );
    let stale = store.begin(Section::Nodes);
    let current = store.begin(Section::Nodes);
    for result in [Ok(Dataset::Nodes(Vec::new())), Err("outage".into())] {
        let outcome = store.apply(Section::Nodes, stale, result, now + Duration::from_secs(2));
        assert!(!outcome.accepted);
        assert!(store.has_data(Section::Nodes));
        assert_eq!(store.meta(Section::Nodes).last_success, Some(succeeded_at));
        assert_eq!(store.meta(Section::Nodes).state, State::Loading);
        assert_eq!(store.generation(Section::Nodes), current);
    }
}

#[test]
fn mismatched_dataset_is_rejected_without_replacing_old_rows() {
    let now = Instant::now();
    let mut store = Store::new();
    apply(
        &mut store,
        Dataset::RunningJobs(vec![running("1", "RUNNING")]),
        now,
    );
    let generation = store.begin(Section::RunningJobs);
    store.apply(
        Section::RunningJobs,
        generation,
        Ok(Dataset::Nodes(Vec::new())),
        now,
    );
    assert_eq!(store.running_jobs[0].id, "1");
    assert_eq!(store.meta(Section::RunningJobs).state, State::Error);
    assert!(
        store
            .meta(Section::RunningJobs)
            .err
            .as_ref()
            .unwrap()
            .contains("received nodes")
    );
}

#[test]
fn oversized_dataset_fails_explicitly_and_keeps_previous_snapshot() {
    let now = Instant::now();
    let mut store = Store::new();
    apply(
        &mut store,
        Dataset::RunningJobs(vec![running("1", "RUNNING")]),
        now,
    );
    let outcome = apply(
        &mut store,
        Dataset::RunningJobs(vec![RunningJob::default(); MAX_ROWS + 1]),
        now,
    );
    assert!(outcome.notification.is_some());
    assert_eq!(store.running_jobs[0].id, "1");
    assert!(
        store
            .meta(Section::RunningJobs)
            .err
            .as_ref()
            .unwrap()
            .contains("row limit")
    );
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
    store.add_completed_job(completion.clone()).unwrap();
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
fn cluster_excludes_offline_capacity_but_retains_gpu_hardware_denominator() {
    let nodes = [
        gpu_node("a", "IDLE", "h200", 4, 0),
        gpu_node("b", "DOWN", "a100", 8, 0),
        gpu_node("c", "DOWN+DRAIN+NOT_RESPONDING", "h100", 2, 0),
    ];
    let stats = derive_cluster_stats(&nodes, &[]);
    assert_eq!(
        (
            stats.total_nodes,
            stats.free_nodes,
            stats.offline_nodes,
            stats.draining_nodes
        ),
        (1, 1, 2, 0)
    );
    assert_eq!(
        (stats.total_cpus, stats.total_memory_gb, stats.total_gpus),
        (64, 4.0, 4)
    );
    assert_eq!(stats.unavail_gpus, 10);
    assert_eq!(stats.gpu_type_free_pct("H200"), 100.0);
    assert_eq!(stats.gpu_type_free_pct("A100"), 0.0);
    assert!((stats.free_gpus_pct() - 400.0 / 14.0).abs() < 1e-9);
}

#[test]
fn draining_mig_cards_are_unavailable_and_generic_counts_do_not_duplicate() {
    let node = Node {
        state: "IDLE+DRAIN".into(),
        cfg_tres: "gres/gpu=22,gres/gpu:h100_pcie_1g.10gb=16,gres/gpu:h100_pcie_2g.20gb=6".into(),
        gres: "gpu:h100_pcie_1g.10gb:16,gpu:h100_pcie_2g.20gb:6".into(),
        ..Node::default()
    };
    let stats = derive_cluster_stats(&[node], &[]);
    assert_eq!(
        (stats.total_gpus, stats.allocated_gpus, stats.unavail_gpus),
        (0, 0, 22)
    );
    assert_eq!(stats.gpus_by_type["H100_PCIE_1G.10GB"].unavail, 16);
    assert_eq!(stats.gpus_by_type["H100_PCIE_2G.20GB"].unavail, 6);
    assert!(!stats.gpus_by_type.contains_key("GPU"));
}

#[test]
fn drained_allocations_do_not_consume_schedulable_node_cpu_or_memory_capacity() {
    for state in ["ALLOCATED+DRAIN", "MIXED+DRAIN"] {
        let nodes = [
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
        ];
        let stats = derive_cluster_stats(&nodes, &[]);
        assert_eq!(
            (stats.total_nodes, stats.free_nodes, stats.allocated_nodes),
            (1, 1, 0)
        );
        assert_eq!((stats.draining_nodes, stats.offline_nodes), (1, 0));
        assert_eq!((stats.total_cpus, stats.allocated_cpus), (64, 0));
        assert_eq!(stats.free_cpus_pct(), 100.0);
        assert_eq!(
            (stats.total_memory_gb, stats.allocated_memory_gb),
            (4.0, 0.0)
        );
        assert_eq!(stats.free_memory_pct(), 100.0);
        assert_eq!(
            (stats.total_gpus, stats.allocated_gpus, stats.unavail_gpus),
            (4, 0, 8)
        );
        assert_eq!(stats.gpus_by_type["A100"].unavail, 8);
        assert_eq!(stats.gpu_type_free_pct("H200"), 100.0);
        assert!((stats.free_gpus_pct() - 100.0 / 3.0).abs() < 1e-9);
        let rows = derive_node_displays(&nodes);
        assert_eq!(rows[1].cpus_alloc, 32);
        assert_eq!(rows[1].memory_alloc_gb, 2.0);
        assert_eq!(rows[1].gpus_alloc, 4);
    }
}

#[test]
fn generic_node_tres_uses_gres_model_and_partial_allocation() {
    let node = Node {
        name: "gpu1".into(),
        state: "MIXED".into(),
        gres: "gpu:l40s:4(S:0)".into(),
        cfg_tres: "cpu=64,gres/gpu=4".into(),
        alloc_tres: "cpu=48,gres/gpu=3".into(),
        ..Node::default()
    };
    let stats = derive_cluster_stats(std::slice::from_ref(&node), &[]);
    assert_eq!((stats.total_gpus, stats.allocated_gpus), (4, 3));
    assert_eq!(stats.gpus_by_type["L40S"].allocated, 3);
    let displays = derive_node_displays(&[node]);
    assert_eq!(displays[0].gpu_usage_pct(), 75.0);
    assert_eq!(displays[0].gpu_types, "4x L40S");
}

#[test]
fn nodes_without_tres_estimate_gpu_allocation_from_state() {
    let node = Node {
        name: "gpu1".into(),
        state: "MIXED".into(),
        gres: "gpu:a100:4".into(),
        ..Node::default()
    };
    let stats = derive_cluster_stats(std::slice::from_ref(&node), &[]);
    assert_eq!((stats.total_gpus, stats.allocated_gpus), (4, 4));
    assert_eq!(derive_node_displays(&[node])[0].gpus_alloc, 4);
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
    let stats = derive_cluster_stats(&[], &jobs);
    assert_eq!(
        (
            stats.pending_jobs_count,
            stats.pending_cpus,
            stats.pending_memory_gb,
            stats.pending_gpus
        ),
        (5, 12, 24.0, 6)
    );
    assert_eq!(stats.pending_by_partition["gpu"].jobs_count, 5);
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
        gpu_util_known: true,
        gpu_mem_known: true,
        gpu_mem_bytes: 1024,
        gpus: vec![GPUEntry {
            gpu_type: "h100_pcie_1g.10gb".into(),
            count: 1,
        }],
        ..JobUsage::default()
    };
    let efficiency = derive_job_efficiency(&usage, &BTreeMap::new());
    assert!(efficiency.gpu_is_mig);
    assert!(!efficiency.gpu_util_known);
    assert!(efficiency.gpu_mem_known);
    assert_eq!(efficiency.gpu_mem_bytes, 1024);
}

#[test]
fn multi_gpu_utilization_is_per_card_and_clamped_and_unsampled_cpu_is_unknown() {
    let mut usage = JobUsage {
        gpu_util_known: true,
        gpu_util_percent: 240.0,
        gpus: vec![GPUEntry {
            gpu_type: "a100".into(),
            count: 3,
        }],
        ..JobUsage::default()
    };
    assert_eq!(
        derive_job_efficiency(&usage, &BTreeMap::new()).gpu_util_percent,
        80.0
    );
    usage.gpu_util_percent = 400.0;
    let efficiency = derive_job_efficiency(&usage, &BTreeMap::new());
    assert_eq!(efficiency.gpu_util_percent, 100.0);
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
