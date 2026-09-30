use std::collections::BTreeMap;

use stoei::slurm::*;

#[test]
fn controller_fixtures_preserve_nested_values_and_array_records() {
    let fields = parse_scontrol_fields(include_str!("fixtures/scontrol_job_12345.txt"));
    assert_eq!(fields["JobId"], "12345");
    assert!(fields["TRES"].contains("cpu="));
    assert!(fields.contains_key("StdOut"));
    let records = parse_scontrol_job_records(include_str!("fixtures/scontrol_job_array.txt"));
    assert!(records.len() > 1);
    assert!(
        records
            .iter()
            .any(|record| !is_terminal_state(&record["JobState"]))
    );
    let fields = parse_scontrol_fields("JobId=1 TRES=cpu=32,mem=256G ReqB:S:C:T=0:0:*:* Empty=");
    assert_eq!(fields["TRES"], "cpu=32,mem=256G");
    assert_eq!(fields["T"], "0:0:*:*");
    assert_eq!(fields["Empty"], "");
}

#[test]
fn nodes_keep_reasons_across_blank_lines() {
    let nodes = parse_nodes(include_str!("fixtures/scontrol_nodes.txt"));
    assert!(!nodes.is_empty());
    assert!(nodes.iter().any(|node| node.cfg_tres.contains("gres/gpu")));
    let nodes = parse_nodes(include_str!("fixtures/scontrol_nodes_blank_reason.txt"));
    assert_eq!(nodes.len(), 2);
    assert!(nodes[0].reason.contains("bbusch"));
    assert_eq!(nodes[0].fields["Reason"], nodes[0].reason);
    assert!(parse_nodes("Reason=stray\n").is_empty());
}

#[test]
fn own_squeue_retains_name_delimiters_and_full_states() {
    let rows = parse_running_jobs(include_str!("fixtures/squeue_running.txt"));
    assert!(!rows.is_empty());
    let rows = parse_running_jobs(
        "header\n123| a|b | COMPLETED |01:02|1|n01|2026-09-01T00:00:00|Unknown\nbad\n",
    );
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].name, "a|b");
    assert_eq!(rows[0].state, "COMPLETED");
    assert!(parse_running_jobs("").is_empty());
    assert!(parse_running_jobs("header\n").is_empty());
}

#[test]
fn all_users_fixed_width_fixture_does_not_split_spaces() {
    let jobs = parse_all_users_jobs(include_str!("fixtures/squeue_all_users.txt"));
    assert!(!jobs.is_empty());
    assert!(
        jobs.iter()
            .all(|job| !job.id.is_empty() && !job.user.is_empty())
    );
    assert!(jobs.iter().any(|job| job.tres.contains("cpu=")));
    assert!(parse_all_users_jobs("truncated\n").is_empty());
}

#[test]
fn fair_share_and_priority_fixtures() {
    let shares = parse_fair_share(include_str!("fixtures/sshare.txt"));
    assert!(shares.iter().any(FairShareEntry::is_account));
    assert!(shares.iter().any(|entry| !entry.is_account()));
    let priorities = parse_priority(include_str!("fixtures/sprio.txt"));
    assert!(!priorities.is_empty());
    assert!(
        priorities
            .windows(2)
            .all(|rows| rows[0].priority >= rows[1].priority)
    );
    let config = parse_priority_config(include_str!("fixtures/scontrol_config.txt"));
    assert!(config.multifactor());
    assert!(config.weights.fair_share > 0);
    assert!(!config.max_age.is_zero());
    let rows = parse_priority("1|alice|a|p|q|10.5|bad|3|0|0|0|cpu=4,gres/gpu=6|0|0|-2");
    assert_eq!(rows[0].priority, 11);
    assert_eq!(rows[0].factors.tres, 10);
    assert_eq!(rows[0].factors.age, 0);
    assert_eq!(rows[0].factors.nice, -2);
}

#[test]
fn priority_contributions_include_negative_nice_and_stable_ties() {
    let mut factors = PriorityFactors {
        fair_share: 50,
        age: 20,
        nice: -30,
        ..Default::default()
    };
    let names: Vec<_> = factors
        .contributions()
        .into_iter()
        .map(|v| v.name)
        .collect();
    assert_eq!(names, ["FairShare", "Nice", "Age"]);
    factors.add(&PriorityFactors {
        age: 4,
        ..Default::default()
    });
    assert_eq!(factors.age, 24);
    assert!(PriorityFactors::default().contributions().is_empty());
}

#[test]
fn journal_ids_align_tasks_with_squeue() {
    let values = [
        "12350",
        "12345",
        "3",
        "alice",
        "array job",
        "RUNNING",
        "p",
        "2026-09-01T00:00:00",
        "Unknown",
        "Unknown",
        "1:00",
        "0:0",
        "2",
        "4",
        "n01",
        "cpu=4,mem=2G",
        "",
        "/logs/%A_%3a-%j-%u-%x.txt",
    ];
    let widths = [
        30, 20, 20, 15, 50, 20, 15, 25, 25, 25, 15, 10, 10, 10, 80, 200, 256, 256,
    ];
    let raw: String = values
        .iter()
        .zip(widths)
        .map(|(value, width)| format!("{value:<width$}"))
        .collect();
    let jobs = parse_journal_jobs(&raw);
    assert_eq!(jobs.len(), 1);
    assert_eq!(jobs[0].id, "12345_3");
    assert_eq!(jobs[0].std_out, "/logs/12345_003-12350-alice-array job.txt");
    assert_eq!(jobs[0].std_err, jobs[0].std_out);
    assert_eq!(
        journal_job_id("12345_[3-20]", "12345", "3-20"),
        "12345_[3-20]"
    );
}

#[test]
fn accounting_retains_delimited_names_and_normalizes_cancelled_tasks() {
    let jobs = parse_acct_jobs(
        "123_[90%2]|alice|CANCELLED by 1|p|s|b|e|1:00|0:0|n01|4|cpu=4,mem=2G||/logs/%A_%a_%j|name|with|pipes\nbad\n",
    );
    assert_eq!(jobs.len(), 1);
    assert_eq!(jobs[0].id, "123_90");
    assert_eq!(jobs[0].state, "CANCELLED");
    assert_eq!(jobs[0].name, "name|with|pipes");
    assert_eq!(jobs[0].std_out, "/logs/123_90_%j");
    assert_eq!(jobs[0].std_err, jobs[0].std_out);
}

#[test]
fn arrays_count_tasks_independently_of_throttle() {
    for (id, count) in [
        ("123", 1),
        ("123_5", 1),
        ("123_[0-99]", 100),
        ("123_[0-99%5]", 100),
        ("123_[1,3,5,7-10]", 7),
        ("123_[99-0]", 1),
        ("bad", 1),
    ] {
        assert_eq!(parse_array_size(id), count, "{id}");
    }
    assert_eq!(normalize_array_job_id("123_[0-99%5]"), "123");
    assert_eq!(normalize_array_job_id("123_5"), "123_5");
}

#[test]
fn gpu_types_are_not_double_counted_and_mig_is_identified() {
    let entries = parse_gpu_entries("cpu=4,gres/gpu=8,gres/gpu:h200=8");
    assert_eq!(calculate_total_gpus(&entries, true), 8);
    assert_eq!(calculate_total_gpus(&entries, false), 16);
    assert_eq!(
        aggregate_gpu_counts(&entries, true),
        BTreeMap::from([("H200".into(), 8)])
    );
    let entries = parse_gpu_from_gres("gpu:a100:4(S:0-1),gpu:v100:2");
    assert_eq!(
        format_gpu_types(&aggregate_gpu_counts(&entries, true)),
        "4x A100, 2x V100"
    );
    assert!(is_mig_type("NVIDIA_A100_80GB_PCIE_1G.10GB"));
    assert_eq!(short_gpu_label("H100_PCIE_1G.10GB"), "1g.10gb");
    assert!(!is_mig_type("H100"));
    let resources = parse_tres_resources("cpu=4,mem=512M,gres/gpu:h200=2");
    assert_eq!(resources.cpus, 4);
    assert_eq!(resources.memory_gb, 0.5);
    assert_eq!(parse_tres_resources("mem=2T").memory_gb, 2048.0);
}

#[test]
fn node_lists_expand_pad_sort_and_deduplicate() {
    for (input, expected) in [
        (
            "gpu[01-02],cpu[01,03]",
            vec!["cpu01", "cpu03", "gpu01", "gpu02"],
        ),
        ("node[001-003]", vec!["node001", "node002", "node003"]),
        (
            "node[01-03],node[02-04]",
            vec!["node01", "node02", "node03", "node04"],
        ),
        ("node[8-10]", vec!["node10", "node8", "node9"]),
        ("(Resources)", vec![]),
        ("node[01-", vec![]),
    ] {
        assert_eq!(expand_node_list(input), expected, "{input}");
    }
    assert!(
        try_expand_node_list("node[1-1000000]")
            .unwrap_err()
            .contains("node[1-1000000]")
    );
}

#[test]
fn sbatch_paths_expand_known_patterns_and_preserve_unknowns() {
    assert_eq!(
        expand_std_io_path(
            "/a/%%-%j-%A-%3a-%u-%x-%N",
            "12350",
            "12345",
            "7",
            "alice",
            "job"
        ),
        "/a/%-12350-12345-007-alice-job-%N"
    );
    assert_eq!(
        expand_std_io_path("%j-%a-%99a", "12345_7", "12345", "7", "alice", "job"),
        "%j-7-%99a"
    );
    assert_eq!(
        job_std_io("/log", "(null)", "1", "", "", "a", "b"),
        ("/log".into(), "/log".into())
    );
    assert_eq!(expand_std_io_path("%é", "1", "", "", "a", "b"), "%é");
}

#[test]
fn time_parser_handles_fractions_and_missing_timestamps() {
    for (input, seconds) in [
        ("3-00:07:34", 259654.0),
        ("02:51.306", 171.306),
        ("01:02:03", 3723.0),
        ("123", 123.0),
        ("bad", 0.0),
        ("-1", 0.0),
        ("NaN", 0.0),
    ] {
        assert!(
            (parse_elapsed_to_seconds(input) - seconds).abs() < 0.00001,
            "{input}"
        );
    }
    assert_eq!(
        wait_time_seconds("2026-09-01T01:00:00", "2026-09-01T01:02:00"),
        Some(120.0)
    );
    assert_eq!(wait_time_seconds("Unknown", "2026-09-01T01:00:00"), None);
    assert_eq!(
        wait_time_seconds("2026-09-01T01:00:00", "2026-09-01T00:00:00"),
        None
    );
    assert!(is_terminal_state("CANCELLED by 1001"));
    assert!(!is_terminal_state("COMPLETING"));
}

#[test]
fn cpu_usage_fixture_reads_allocation_and_step_measurements() {
    let usage = parse_sacct_usage("5834914", include_str!("fixtures/sacct_usage_cpu.txt"));
    assert_eq!(usage.elapsed_sec, 171.0);
    assert_eq!(usage.alloc_cpus, 4);
    assert!((usage.cpu_time_sec - 171.306).abs() < 0.00001);
    assert_eq!(usage.max_rss_bytes, 2502 * 1024);
    assert_eq!(usage.disk_read_bytes, 32225772153);
    assert_eq!(usage.disk_write_bytes, 1572864182);
    assert!(usage.sampled);
    assert!(!usage.gpu_util_known);
}

#[test]
fn gpu_usage_uses_peaks_but_sums_io() {
    let usage = parse_sacct_usage("5184910_0", include_str!("fixtures/sacct_usage_gpu.txt"));
    assert_eq!(usage.cpu_time_sec, 259654.0);
    assert_eq!(usage.alloc_cpus, 32);
    assert_eq!(calculate_total_gpus(&usage.gpus, true), 1);
    assert_eq!(usage.max_rss_bytes, 53418351 * 1024);
    assert_eq!(usage.disk_read_bytes, 14756614381);
    assert_eq!(usage.disk_write_bytes, 22090669340);
    assert!(usage.gpu_util_known);
    assert_eq!(usage.gpu_util_percent, 43.0);
    assert_eq!(usage.gpu_mem_bytes, 14382 << 20);
}

#[test]
fn live_usage_discards_extern_garbage_and_foreign_tasks() {
    let usage = parse_sstat_usage("5834914", include_str!("fixtures/sstat_usage.txt"));
    assert_eq!(usage.cpu_time_sec, 71.0);
    assert_eq!(usage.max_rss_bytes, 2502 * 1024);
    assert_eq!(usage.disk_read_bytes, 16176988793);
    assert_eq!(usage.disk_write_bytes, 1572864182);
    assert_eq!(usage.alloc_cpus, 0);
    let raw = "123_0|10|2|00:05:00|cpu=2,mem=1G|||||\n123_0.batch|10|2|00:05:00|cpu=2|100K|cpu=00:05:00|cpu=00:05:00||\n";
    assert!(!parse_sacct_usage("123", raw).sampled);
    assert!(!parse_sstat_usage("123", "123.extern|999999K|energy=0|energy=0||").sampled);
}

#[test]
fn sizes_are_binary_and_reject_negative_or_nonfinite_values() {
    for (input, bytes) in [
        ("1234", 1234),
        ("2502K", 2502 * 1024),
        ("20112.84M", 21089841315),
        ("1.5G", 1610612736),
        ("2T", 2 << 40),
        ("-5K", 0),
        ("NaN", 0),
        ("garbage", 0),
    ] {
        assert_eq!(parse_size_bytes(input), bytes, "{input}");
    }
}

#[test]
fn parser_expansion_budgets_count_duplicate_ranges_and_repeated_patterns() {
    assert!(
        try_expand_node_list("node[0-99999,0-99999]")
            .unwrap_err()
            .contains("node[0-99999,0-99999]")
    );
    let name = "x".repeat(1024 * 1024);
    assert!(
        try_expand_std_io_path("%x%x", "1", "", "", "alice", &name)
            .unwrap_err()
            .contains("%x%x")
    );
    assert_eq!(
        expand_std_io_path("%x%x", "1", "", "", "alice", &name),
        "%x%x"
    );
    assert!(!is_mig_type(&"1".repeat(64 * 1024)));
    assert_eq!(short_gpu_label("1g.12g.34gb"), "12g.34gb");
    assert_eq!(parse_tres_resources("CPU=4,MEM=512M").memory_gb, 0.5);
    assert_eq!(
        calculate_total_gpus(&parse_gpu_from_gres("gres:gpu:4"), true),
        4
    );
}
