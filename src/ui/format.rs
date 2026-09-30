use std::collections::{BTreeMap, BTreeSet};

use ratatui::style::Modifier;
use ratatui::text::{Line, Span};

use crate::store::{self, JobUsage};

use super::theme::Theme;

pub(super) fn clean(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    let mut chars = value.chars();
    while let Some(ch) = chars.next() {
        match ch {
            '\u{1b}' => match chars.next() {
                Some('[') => {
                    for ch in chars.by_ref() {
                        if ('@'..='~').contains(&ch) {
                            break;
                        }
                    }
                }
                Some(']') => {
                    let mut escape = false;
                    for ch in chars.by_ref() {
                        if ch == '\u{7}' || escape && ch == '\\' {
                            break;
                        }
                        escape = ch == '\u{1b}';
                    }
                }
                _ => {}
            },
            '\t' => out.push_str("    "),
            ch if ch.is_control() => {}
            _ => out.push(ch),
        }
    }
    out
}

pub(super) fn bytes(value: u64) -> String {
    let mut scaled = value as f64;
    let units = ["B", "K", "M", "G", "T", "P", "E"];
    let mut unit = 0;
    while scaled >= 1024.0 && unit < units.len() - 1 {
        scaled /= 1024.0;
        unit += 1;
    }
    if unit == 0 {
        format!("{value}B")
    } else {
        format!("{scaled:.1}{}", units[unit])
    }
}

pub(super) fn short_duration(seconds: f64) -> String {
    if !seconds.is_finite() || seconds <= 0.0 {
        return "0s".into();
    }
    let seconds = seconds as u64;
    if seconds >= 86400 {
        format!("{}d{}h", seconds / 86400, seconds % 86400 / 3600)
    } else if seconds >= 3600 {
        format!("{}h{}m", seconds / 3600, seconds % 3600 / 60)
    } else if seconds >= 60 {
        format!("{}m{}s", seconds / 60, seconds % 60)
    } else {
        format!("{seconds}s")
    }
}

const NODE_GROUPS: &[(&str, &[&str])] = &[
    (
        "Identity",
        &[
            "NodeName",
            "NodeAddr",
            "NodeHostName",
            "Arch",
            "OS",
            "Version",
        ],
    ),
    ("Status", &["State", "Reason", "Owner", "MCS_label"]),
    (
        "Resources",
        &[
            "CPUTot",
            "CPUAlloc",
            "CPULoad",
            "CPUEfctv",
            "RealMemory",
            "AllocMem",
            "FreeMem",
            "CfgTRES",
            "AllocTRES",
            "Gres",
            "TmpDisk",
        ],
    ),
    (
        "Hardware",
        &[
            "CoresPerSocket",
            "Sockets",
            "Boards",
            "ThreadsPerCore",
            "Weight",
            "AvailableFeatures",
            "ActiveFeatures",
        ],
    ),
    ("Partitions", &["Partitions"]),
    (
        "Timing",
        &[
            "BootTime",
            "SlurmdStartTime",
            "LastBusyTime",
            "ResumeAfterTime",
        ],
    ),
    ("Power", &["CurrentWatts", "AveWatts"]),
];

const JOB_GROUPS: &[(&str, &[&str])] = &[
    (
        "Identity",
        &["JobId", "JobName", "UserId", "GroupId", "Account", "QOS"],
    ),
    (
        "Status",
        &[
            "JobState",
            "Reason",
            "ExitCode",
            "DerivedExitCode",
            "RunTime",
            "TimeLimit",
            "Restarts",
            "Requeue",
        ],
    ),
    (
        "Resources",
        &[
            "Partition",
            "NumNodes",
            "NumCPUs",
            "NumTasks",
            "CPUs/Task",
            "TRES",
            "MinCPUsNode",
            "MinMemoryNode",
            "MinMemoryCPU",
            "ReqTRES",
            "AllocTRES",
            "Gres",
            "TresPerNode",
        ],
    ),
    (
        "Nodes",
        &[
            "NodeList",
            "BatchHost",
            "ReqNodeList",
            "ExcNodeList",
            "Features",
            "Reservation",
        ],
    ),
    (
        "Timing",
        &[
            "SubmitTime",
            "EligibleTime",
            "AccrueTime",
            "StartTime",
            "EndTime",
            "Deadline",
            "SuspendTime",
            "PreemptTime",
            "PreemptEligibleTime",
            "LastSchedEval",
        ],
    ),
    (
        "Paths",
        &[
            "WorkDir",
            "StdErr",
            "StdOut",
            "StdIn",
            "Command",
            "BatchFlag",
        ],
    ),
    (
        "Scheduling",
        &[
            "Priority",
            "Nice",
            "Contiguous",
            "Licenses",
            "Network",
            "Power",
            "NtasksPerN:B:S:C",
            "CoreSpec",
            "Shared",
            "OverSubscribe",
        ],
    ),
];

pub(super) fn field_lines(
    fields: &BTreeMap<String, String>,
    node: bool,
    theme: Theme,
) -> Vec<Line<'static>> {
    let groups = if node { NODE_GROUPS } else { JOB_GROUPS };
    let mut seen = BTreeSet::new();
    let mut lines = Vec::new();
    for (title, keys) in groups {
        let members: Vec<_> = keys
            .iter()
            .filter_map(|key| fields.get(*key).map(|value| (*key, value)))
            .collect();
        if members.is_empty() {
            continue;
        }
        lines.push(Line::default());
        lines.push(Line::from(Span::styled(
            format!(" {title} "),
            theme.title(),
        )));
        for (key, value) in members {
            seen.insert(key);
            lines.push(field_line(key, value, theme));
        }
    }
    let remaining: Vec<_> = fields
        .iter()
        .filter(|(key, _)| !seen.contains(key.as_str()))
        .collect();
    if !remaining.is_empty() {
        lines.push(Line::default());
        lines.push(Line::from(Span::styled(" Other ", theme.title())));
        lines.extend(
            remaining
                .into_iter()
                .map(|(key, value)| field_line(key, value, theme)),
        );
    }
    if lines.is_empty() {
        lines.push(Line::from(Span::styled(
            if node {
                "No node information could be parsed."
            } else {
                "No job information could be parsed."
            },
            theme.subtle(),
        )));
    }
    lines
}

fn field_line(key: &str, value: &str, theme: Theme) -> Line<'static> {
    let value = clean(value);
    if value.is_empty() || ["(null)", "N/A", "None"].contains(&value.as_str()) {
        return labelled_line(key, vec![Span::styled("(not set)", theme.subtle())], theme);
    }
    let style = if key == "JobState" || key == "State" {
        let base = value.split(' ').next().unwrap_or(&value);
        theme
            .role(store::state_role(base))
            .add_modifier(Modifier::BOLD)
    } else if key.contains("ExitCode") {
        theme.role(if value == "0:0" { "success" } else { "error" })
    } else if ["WorkDir", "StdErr", "StdOut", "StdIn", "Command"].contains(&key) {
        theme.text().add_modifier(Modifier::ITALIC)
    } else if key.contains("Time") && value != "Unknown" {
        theme.role("warning")
    } else if [
        "NumNodes", "NumCPUs", "NumTasks", "Priority", "Nice", "Restarts",
    ]
    .contains(&key)
    {
        theme.text().add_modifier(Modifier::BOLD)
    } else if key.contains("TRES") || key == "Gres" {
        theme.role("success")
    } else {
        theme.text()
    };
    let value = if key.contains("ExitCode") {
        format!("{value} {}", if value == "0:0" { "✓" } else { "✗" })
    } else {
        value
    };
    labelled_line(key, vec![Span::styled(value, style)], theme)
}

fn labelled_line(label: &str, values: Vec<Span<'static>>, theme: Theme) -> Line<'static> {
    let label = clean(label);
    let width = Line::raw(&label).width();
    let label = format!("  {label}{} ", ".".repeat(24usize.saturating_sub(width)));
    let mut spans = Vec::with_capacity(values.len() + 1);
    spans.push(Span::styled(label, theme.subtle()));
    spans.extend(values);
    Line::from(spans)
}

pub(super) fn efficiency_lines(
    usage: &JobUsage,
    fields: &BTreeMap<String, String>,
    theme: Theme,
) -> Vec<Line<'static>> {
    let eff = store::derive_job_efficiency(usage, fields);
    let mut lines = vec![
        Line::default(),
        Line::from(Span::styled(
            if eff.live {
                " Efficiency (live) "
            } else {
                " Efficiency "
            },
            theme.title(),
        )),
    ];
    if !eff.sampled {
        lines.push(Line::from(Span::styled(
            if eff.live {
                "  no usage samples recorded yet"
            } else {
                "  job finished before usage was sampled"
            },
            theme.subtle(),
        )));
        return lines;
    }
    if eff.cpu_known {
        lines.push(cpu_usage_line(&eff, theme));
    }
    if eff.max_rss_bytes > 0 {
        lines.push(memory_usage_line(&eff, theme));
    }
    lines.extend(gpu_usage_lines(&eff, theme));
    lines.push(io_line(
        "Disk read",
        eff.disk_read_bytes,
        eff.read_bytes_per_sec,
        theme,
    ));
    lines.push(io_line(
        "Disk written",
        eff.disk_write_bytes,
        eff.write_bytes_per_sec,
        theme,
    ));
    lines
}

fn cpu_usage_line(eff: &store::JobEfficiency, theme: Theme) -> Line<'static> {
    labelled_line(
        "CPU efficiency",
        vec![
            percentage_span(eff.cpu_percent, theme),
            Span::styled(
                format!(
                    " ({} CPU of {} across {} CPUs)",
                    short_duration(eff.cpu_time_sec),
                    short_duration(eff.cpu_avail_sec),
                    eff.alloc_cpus
                ),
                theme.subtle(),
            ),
        ],
        theme,
    )
}

fn memory_usage_line(eff: &store::JobEfficiency, theme: Theme) -> Line<'static> {
    let mut values = vec![Span::styled(
        bytes(eff.max_rss_bytes),
        theme.text().add_modifier(Modifier::BOLD),
    )];
    if eff.mem_known {
        values.push(Span::styled(
            format!(
                " ({} of {} requested)",
                percentage(eff.mem_percent),
                bytes(eff.req_mem_bytes)
            ),
            theme.subtle(),
        ));
    }
    labelled_line("Peak RAM", values, theme)
}

fn gpu_usage_lines(eff: &store::JobEfficiency, theme: Theme) -> Vec<Line<'static>> {
    let mut lines = Vec::new();
    if eff.gpu_count > 0 {
        let values = if eff.gpu_is_mig {
            vec![Span::styled(
                "n/a (MIG slice — not measurable)",
                theme.subtle(),
            )]
        } else if eff.gpu_util_known {
            vec![
                percentage_span(eff.gpu_util_percent, theme),
                Span::styled(
                    if eff.gpu_count > 1 {
                        format!(" (avg across {} GPUs)", eff.gpu_count)
                    } else {
                        " (avg)".into()
                    },
                    theme.subtle(),
                ),
            ]
        } else {
            vec![Span::styled("no data", theme.subtle())]
        };
        lines.push(labelled_line("GPU utilization", values, theme));
        if eff.gpu_mem_known {
            lines.push(labelled_line(
                "GPU memory peak",
                vec![Span::styled(
                    bytes(eff.gpu_mem_bytes),
                    theme.text().add_modifier(Modifier::BOLD),
                )],
                theme,
            ));
        }
    }
    lines
}

fn io_line(label: &str, bytes_count: u64, rate: f64, theme: Theme) -> Line<'static> {
    let mut values = vec![Span::styled(
        bytes(bytes_count),
        theme.text().add_modifier(Modifier::BOLD),
    )];
    if rate.is_finite() && rate > 0.0 {
        values.push(Span::styled(
            format!(" ({}/s avg)", bytes(rate as u64)),
            theme.subtle(),
        ));
    }
    labelled_line(label, values, theme)
}

fn percentage(value: f64) -> String {
    if value < 10.0 {
        format!("{value:.1}%")
    } else {
        format!("{value:.0}%")
    }
}

fn percentage_span(value: f64, theme: Theme) -> Span<'static> {
    let role = if value >= 70.0 {
        "success"
    } else if value >= 30.0 {
        "warning"
    } else {
        "error"
    };
    Span::styled(percentage(value), theme.role(role))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn untrusted_scheduler_and_log_text_cannot_emit_terminal_controls() {
        assert_eq!(
            clean("a\u{1b}[31mRED\u{1b}[0m\u{1b}]52;c;payload\u{7}b\0\r"),
            "aREDb"
        );
        assert_eq!(clean("日本語\tGPU"), "日本語    GPU");
        assert!(!clean("\u{1b}[2Jbad").contains('\u{1b}'));
    }

    #[test]
    fn durations_and_bytes_cover_unknown_and_large_usage() {
        assert_eq!(bytes(0), "0B");
        assert_eq!(bytes(1024), "1.0K");
        assert_eq!(bytes(1 << 30), "1.0G");
        assert_eq!(short_duration(f64::NAN), "0s");
        assert_eq!(short_duration(7200.0), "2h0m");
        assert_eq!(short_duration(171.9), "2m51s");
        assert_eq!(short_duration(3.0 * 86400.0 + 3.0 * 3600.0), "3d3h");
    }

    #[test]
    fn field_values_keep_go_alignment_and_semantic_styles() {
        let theme = Theme::by_name("nord");
        let path = field_line("StdOut", "/logs/output", theme);
        assert_eq!(path.to_string(), "  StdOut.................. /logs/output");
        assert_eq!(path.spans[0].width(), 27);
        assert!(path.spans[1].style.add_modifier.contains(Modifier::ITALIC));
        let state = field_line("State", "DOWN (maintenance)", theme);
        assert_eq!(state.spans[1].style.fg, Some(theme.error));
        assert!(state.spans[1].style.add_modifier.contains(Modifier::BOLD));
        let exit = field_line("ExitCode", "0:0", theme);
        assert!(exit.to_string().ends_with("0:0 ✓"));
        assert_eq!(exit.spans[1].style.fg, Some(theme.success));
        assert!(
            field_line("DerivedExitCode", "1:0", theme)
                .to_string()
                .ends_with("1:0 ✗")
        );
        assert_eq!(
            field_line("RunTime", "00:10:00", theme).spans[1].style.fg,
            Some(theme.warning)
        );
        assert_eq!(
            field_line("AllocTRES", "cpu=4", theme).spans[1].style.fg,
            Some(theme.success)
        );
        assert_eq!(
            field_line("StdOut", "(null)", theme).spans[1].style.fg,
            Some(theme.subtle)
        );
        assert!(
            field_line("NumCPUs", "4", theme).spans[1]
                .style
                .add_modifier
                .contains(Modifier::BOLD)
        );
        let long = "ExceptionallyLongSchedulerKey";
        assert!(
            field_line(long, "value", theme)
                .to_string()
                .starts_with(&format!("  {long} value"))
        );
    }

    #[test]
    fn scheduler_fields_stay_in_the_original_detail_sections() {
        let theme = Theme::by_name("nord");
        let fields = [
            ("JobId", "123"),
            ("SuspendTime", "0"),
            ("LastSchedEval", "2026-09-30"),
            ("BatchFlag", "1"),
            ("Network", "none"),
            ("CoreSpec", "0"),
            ("ZZUnknown", "z"),
            ("AAUnknown", "a"),
        ]
        .map(|(key, value)| (key.into(), value.into()))
        .into_iter()
        .collect();
        let lines = field_lines(&fields, false, theme);
        let text: Vec<_> = lines.iter().map(ToString::to_string).collect();
        assert_eq!(text[0], "");
        let other = text.iter().position(|line| line == " Other ").unwrap();
        for key in [
            "SuspendTime",
            "LastSchedEval",
            "BatchFlag",
            "Network",
            "CoreSpec",
        ] {
            assert!(text[..other].iter().any(|line| line.contains(key)));
        }
        assert!(text[other + 1].contains("AAUnknown"));
        assert!(text[other + 2].contains("ZZUnknown"));
        let node = [
            "CPUEfctv",
            "Boards",
            "Weight",
            "MCS_label",
            "ResumeAfterTime",
        ]
        .map(|key| (key.into(), "1".into()))
        .into_iter()
        .collect();
        assert!(
            !field_lines(&node, true, theme)
                .iter()
                .any(|line| line.to_string() == " Other ")
        );
    }

    #[test]
    fn efficiency_metrics_share_the_detail_value_column() {
        let usage = JobUsage {
            source: "sstat".into(),
            sampled: true,
            elapsed_sec: 600.0,
            alloc_cpus: 4,
            cpu_time_sec: 1800.0,
            max_rss_bytes: 512 << 20,
            gpus: vec![store::GPUEntry {
                gpu_type: "a100".into(),
                count: 1,
            }],
            gpu_util_percent: 40.0,
            gpu_util_known: true,
            ..Default::default()
        };
        let fields = [("AllocTRES".into(), "cpu=4,mem=1G".into())]
            .into_iter()
            .collect();
        let theme = Theme::by_name("nord");
        let lines = efficiency_lines(&usage, &fields, theme);
        let text: Vec<_> = lines.iter().map(ToString::to_string).collect();
        assert!(text.iter().any(
            |line| line == "  CPU efficiency.......... 75% (30m0s CPU of 40m0s across 4 CPUs)"
        ));
        assert!(
            text.iter()
                .any(|line| line == "  Peak RAM................ 512.0M (50% of 1.0G requested)")
        );
        assert!(
            text.iter()
                .any(|line| line == "  GPU utilization......... 40% (avg)")
        );
        assert!(
            text.iter()
                .any(|line| line == "  Disk read............... 0B")
        );
        assert!(
            text.iter()
                .any(|line| line == "  Disk written............ 0B")
        );
        for line in lines.iter().skip(2) {
            assert_eq!(line.spans[0].width(), 27);
        }
        assert_eq!(lines[2].spans[1].style.fg, Some(theme.success));
        assert_eq!(lines[4].spans[1].style.fg, Some(theme.warning));
    }
}
