use ratatui::Frame;
use ratatui::layout::Rect;
use ratatui::style::Modifier;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, BorderType, Padding, Paragraph};

use crate::store::{self, Section, State, Store};

use super::format::clean;
use super::theme::Theme;

pub(super) fn sidebar_width(lines: &[Line<'_>], terminal_width: u16) -> u16 {
    let content = lines.iter().map(Line::width).max().unwrap_or(12);
    content
        .saturating_add(6)
        .clamp(28, usize::from(terminal_width / 2)) as u16
}

pub(super) fn render_sidebar(
    frame: &mut Frame<'_>,
    area: Rect,
    lines: Vec<Line<'static>>,
    theme: Theme,
) {
    let block = Block::bordered()
        .border_type(BorderType::Rounded)
        .border_style(theme.text().fg(theme.accent))
        .padding(Padding::new(2, 2, u16::from(area.height >= 12), 0))
        .style(theme.text());
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let [title, rule, _, body] = ratatui::layout::Layout::vertical([
        ratatui::layout::Constraint::Length(1),
        ratatui::layout::Constraint::Length(1),
        ratatui::layout::Constraint::Length(u16::from(inner.height >= 6)),
        ratatui::layout::Constraint::Min(0),
    ])
    .areas(inner);
    frame.render_widget(Paragraph::new("Cluster Load").style(theme.title()), title);
    frame.render_widget(
        Paragraph::new("─".repeat(usize::from(rule.width))).style(theme.subtle()),
        rule,
    );
    frame.render_widget(Paragraph::new(lines).style(theme.text()), body);
}

pub(super) fn lines(store: &Store, theme: Theme) -> Vec<Line<'static>> {
    let mut lines = Vec::new();
    if store.has_data(Section::Nodes) {
        node_lines(store, theme, &mut lines);
    } else {
        lines.push(section_status(store, Section::Nodes, "cluster", theme));
        lines.push(Line::default());
    }
    if store.has_data(Section::AllUsersJobs) {
        pending_lines(store, theme, &mut lines);
    } else {
        lines.push(heading("Pending:", theme));
        lines.push(section_status(store, Section::AllUsersJobs, "queue", theme));
    }
    lines
}

fn section_status(store: &Store, section: Section, name: &str, theme: Theme) -> Line<'static> {
    let meta = store.meta(section);
    let (text, style) = if meta.state == State::Error {
        (format!("{name} unavailable · r retry"), theme.role("error"))
    } else {
        (format!("Loading {name}…"), theme.subtle())
    };
    Line::from(Span::styled(text, style))
}

fn node_lines(store: &Store, theme: Theme, lines: &mut Vec<Line<'static>>) {
    let stats = &store.cluster_stats;
    match store.meta(Section::Nodes).state {
        State::Loading => lines.push(Line::from(Span::styled(
            "Refreshing cluster…",
            theme.subtle(),
        ))),
        State::Error => lines.push(Line::from(Span::styled(
            "Last known cluster · refresh failed",
            theme.role("warning"),
        ))),
        _ => {}
    }
    lines.push(heading("Nodes:", theme));
    let mut nodes = free_line(stats.free_nodes, stats.total_nodes, theme);
    if stats.draining_nodes > 0 {
        nodes.spans.push(Span::styled(
            format!(" · {} drain", stats.draining_nodes),
            theme.subtle(),
        ));
    }
    if stats.offline_nodes > 0 {
        nodes.spans.push(Span::styled(
            format!(" · {} down", stats.offline_nodes),
            theme.subtle(),
        ));
    }
    lines.extend([nodes, Line::default(), heading("CPUs:", theme)]);
    lines.push(free_line(
        stats.total_cpus.saturating_sub(stats.allocated_cpus),
        stats.total_cpus,
        theme,
    ));
    lines.extend([Line::default(), heading("Memory:", theme)]);
    let free = (stats.total_memory_gb - stats.allocated_memory_gb).max(0.0);
    let pair = if stats.total_memory_gb >= 1024.0 {
        format!(
            "{:.1}/{:.1} TB free (",
            free / 1024.0,
            stats.total_memory_gb / 1024.0
        )
    } else {
        format!("{free:.0}/{:.0} GB free (", stats.total_memory_gb)
    };
    lines.push(free_percent_line(pair, free, stats.total_memory_gb, theme));
    lines.push(Line::default());
    gpu_lines(store, theme, lines);
}

fn heading(text: &str, theme: Theme) -> Line<'static> {
    Line::from(Span::styled(
        text.to_owned(),
        theme.text().add_modifier(Modifier::BOLD),
    ))
}

fn free_line(free: u64, total: u64, theme: Theme) -> Line<'static> {
    free_percent_line(
        format!("{free}/{total} free ("),
        free as f64,
        total as f64,
        theme,
    )
}

fn free_percent_line(prefix: String, free: f64, total: f64, theme: Theme) -> Line<'static> {
    let known = total.is_finite() && total > 0.0 && free.is_finite();
    let percent = if known {
        (free / total * 100.0).clamp(0.0, 100.0)
    } else {
        0.0
    };
    let role = if !known {
        "muted"
    } else if percent >= 50.0 {
        "success"
    } else if percent >= 25.0 {
        "warning"
    } else {
        "error"
    };
    Line::from(vec![
        Span::styled(prefix, theme.text()),
        Span::styled(
            if known {
                format!("{percent:.1}%")
            } else {
                "n/a".into()
            },
            theme.role(role),
        ),
        Span::styled(")", theme.text()),
    ])
}

fn gpu_lines(store: &Store, theme: Theme, lines: &mut Vec<Line<'static>>) {
    let stats = &store.cluster_stats;
    if stats.total_gpus.saturating_add(stats.unavail_gpus) == 0 {
        return;
    }
    lines.push(heading("GPUs:", theme));
    if stats.gpus_by_type.is_empty() {
        lines.push(free_line(
            stats.total_gpus.saturating_sub(stats.allocated_gpus),
            stats.total_gpus.saturating_add(stats.unavail_gpus),
            theme,
        ));
    }
    for (name, counts) in &stats.gpus_by_type {
        let name = if name.eq_ignore_ascii_case("gpu") {
            "generic".into()
        } else if store::is_mig_type(name) {
            format!(" mig {}", clean(&store::short_gpu_label(name)))
        } else {
            clean(name)
        };
        let mut line = free_line(
            counts.total.saturating_sub(counts.allocated),
            counts.total.saturating_add(counts.unavail),
            theme,
        );
        line.spans
            .insert(0, Span::styled(format!("{name} "), theme.text()));
        if counts.unavail > 0 {
            line.spans.push(Span::styled(
                format!(" · {} unavail", counts.unavail),
                theme.subtle(),
            ));
        }
        lines.push(line);
    }
    lines.push(Line::default());
}

fn pending_lines(store: &Store, theme: Theme, lines: &mut Vec<Line<'static>>) {
    let stats = &store.cluster_stats;
    let state = store.meta(Section::AllUsersJobs).state;
    if stats.pending_jobs_count == 0 && !matches!(state, State::Loading | State::Error) {
        return;
    }
    lines.push(heading("Pending:", theme));
    if state == State::Loading {
        lines.push(Line::from(Span::styled(
            "Refreshing queue…",
            theme.subtle(),
        )));
    } else if state == State::Error {
        lines.push(Line::from(Span::styled(
            "Last known queue · refresh failed",
            theme.role("warning"),
        )));
    }
    if stats.pending_jobs_count == 0 {
        lines.push(Line::from("No pending jobs."));
    } else if stats.pending_by_partition.is_empty() {
        lines.push(Line::from(format!(
            "{} jobs · no partition breakdown",
            stats.pending_jobs_count
        )));
    }
    for (partition, pending) in &stats.pending_by_partition {
        let mut parts = vec![format!("{}j", pending.jobs_count)];
        if pending.cpus > 0 {
            parts.push(format!("{}c", pending.cpus));
        }
        if pending.memory_gb > 0.0 {
            parts.push(compact_memory(pending.memory_gb));
        }
        if pending.gpus_by_type.is_empty() && pending.gpus > 0 {
            parts.push(format!("{}×gpu", pending.gpus));
        }
        for (name, count) in &pending.gpus_by_type {
            parts.push(format!("{count}×{}", clean(&store::short_gpu_label(name))));
        }
        let name = if partition.is_empty() {
            "unknown".into()
        } else {
            clean(partition)
        };
        lines.push(Line::from(format!("{name} {}", parts.join("·"))));
    }
}

pub(super) fn compact_memory(gb: f64) -> String {
    if gb >= 1024.0 {
        format!("{:.1}T", gb / 1024.0)
    } else {
        format!("{gb:.0}G")
    }
}
