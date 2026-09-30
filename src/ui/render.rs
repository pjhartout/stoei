use ratatui::Frame;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::Modifier;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, BorderType, Clear, Padding, Paragraph, Wrap};

use crate::store::{self, Section, State, Store};

use super::format::{clean, efficiency_lines, field_lines};
use super::modals::{DetailView, LogView, Modal, ModifyView, SettingsView};
use super::table::Source;
use super::theme::Theme;
use super::{RuntimeStatus, Ui, source_for};

impl Ui {
    pub(super) fn render_frame(
        &mut self,
        frame: &mut Frame<'_>,
        store: &Store,
        status: &RuntimeStatus<'_>,
    ) {
        let theme = Theme::by_name(&self.config.theme);
        frame.render_widget(Block::default().style(theme.text()), frame.area());
        if frame.area().height < 5 || frame.area().width < 18 {
            frame.render_widget(
                Paragraph::new("stoei · resize terminal · q quit").style(theme.text()),
                frame.area(),
            );
            return;
        }
        let [tabs, rule, body, toast_area, footer] = Layout::vertical([
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Min(1),
            Constraint::Length(self.toasts.len().min(3) as u16),
            Constraint::Length(1),
        ])
        .areas(frame.area());
        self.render_tabs(frame, tabs, store, theme);
        frame.render_widget(
            Paragraph::new("─".repeat(usize::from(rule.width))).style(theme.subtle()),
            rule,
        );
        if let Some(error) = status.unavailable {
            render_unavailable(frame, body, error, theme);
        } else {
            let main = if body.width >= 100 {
                let lines = super::cluster::lines(store, theme);
                let width = super::cluster::sidebar_width(&lines, body.width);
                let [main, sidebar] =
                    Layout::horizontal([Constraint::Min(1), Constraint::Length(width)]).areas(body);
                super::cluster::render_sidebar(frame, sidebar, lines, theme);
                main
            } else {
                body
            };
            self.render_main(frame, main, store, theme);
        }
        let toasts: Vec<_> = self
            .toasts
            .iter()
            .rev()
            .take(3)
            .map(|toast| {
                Line::from(Span::styled(
                    format!(" {}", toast.text),
                    theme.role("warning"),
                ))
            })
            .collect();
        frame.render_widget(Paragraph::new(toasts), toast_area);
        self.render_footer(frame, footer, store, status, theme);
        if let Some(modal) = self.modals.last_mut() {
            render_modal(
                frame,
                modal,
                store,
                theme,
                &self.config.keybind_mode,
                status.version,
            );
        }
    }

    fn render_tabs(&self, frame: &mut Frame<'_>, area: Rect, store: &Store, theme: Theme) {
        let mut spans = vec![Span::styled(" stoei ", theme.selected()), Span::raw(" ")];
        for (index, label) in ["Jobs", "Nodes", "Users", "Priority", "Logs"]
            .iter()
            .enumerate()
        {
            let section = match index {
                0 => Some(Section::RunningJobs),
                1 => Some(Section::Nodes),
                2 => Some(Section::AllUsersJobs),
                3 => Some(Section::FairShare),
                _ => None,
            };
            let mark = section.map_or("", |section| match store.meta(section).state {
                State::Loading => " …",
                State::Error => " !",
                _ => "",
            });
            let label = if area.width >= 60 || index == self.active {
                format!(" {} {label}{mark} ", index + 1)
            } else {
                format!(" {}{mark} ", index + 1)
            };
            spans.push(Span::styled(
                label,
                if index == self.active {
                    theme.selected()
                } else {
                    theme.subtle()
                },
            ));
        }
        frame.render_widget(Paragraph::new(Line::from(spans)), area);
    }

    fn render_footer(
        &self,
        frame: &mut Frame<'_>,
        area: Rect,
        store: &Store,
        status: &RuntimeStatus<'_>,
        theme: Theme,
    ) {
        frame.render_widget(Block::default().style(theme.bar()), area);
        let sync = sync_label(store, status.now);
        let mut globals = if self.config.keybind_mode == "emacs" {
            vec![("C-h", "help"), ("C-r", "refresh"), ("C-q", "quit")]
        } else {
            vec![("?", "help"), ("r", "refresh"), ("q", "quit")]
        };
        if self.active == 2 && self.config.keybind_mode != "emacs" {
            globals.retain(|(_, label)| *label != "refresh");
        }
        let globals = if area.width < 40 {
            hint_line(
                &globals
                    .into_iter()
                    .rev()
                    .filter(|(_, label)| *label != "refresh")
                    .collect::<Vec<_>>(),
                theme,
            )
        } else {
            hint_line(&globals, theme)
        };
        let notice = if area.width >= 140 {
            status
                .update_available
                .map(|version| format!(" {} available · stoei update ", clean(version)))
                .unwrap_or_default()
        } else {
            String::new()
        };
        let [brand, hints, update, help, refresh] = Layout::horizontal([
            Constraint::Length(if area.width >= 72 { 7 } else { 0 }),
            Constraint::Min(0),
            Constraint::Length(Line::from(notice.as_str()).width() as u16),
            Constraint::Length(globals.width() as u16),
            Constraint::Length(if area.width >= 40 {
                Line::from(sync.as_str()).width() as u16 + 2
            } else {
                0
            }),
        ])
        .areas(area);
        frame.render_widget(Paragraph::new(" stoei ").style(theme.selected()), brand);
        frame.render_widget(Paragraph::new(self.footer_hints(hints.width, theme)), hints);
        frame.render_widget(Paragraph::new(notice).style(theme.bar_key()), update);
        frame.render_widget(Paragraph::new(globals), help);
        let color = match store.meta(Section::RunningJobs).state {
            State::Error => theme.error,
            State::Loading => theme.warning,
            _ => theme.accent_alt,
        };
        frame.render_widget(
            Paragraph::new(format!(" {sync} ")).style(theme.chip(color)),
            refresh,
        );
    }

    fn footer_hints(&self, width: u16, theme: Theme) -> Line<'static> {
        let view = &self.tables[self.table_index()];
        if view.editing_filter {
            return hint_line(&[("Enter", "apply"), ("Esc", "clear")], theme);
        }
        let (filter, sort, settings) = if self.config.keybind_mode == "emacs" {
            ("C-s", "C-o", "C-,")
        } else {
            ("/", "o", "s")
        };
        let mut hints = match self.active {
            4 => vec![("↑↓", "scroll"), (filter, "filter")],
            _ => vec![("Enter", "inspect"), (filter, "filter"), (sort, "sort")],
        };
        if !view.filter.is_empty() {
            hints.push(("Esc", "clear"));
        }
        if self.active == 0 {
            hints.extend([("c", "cancel"), ("i", "job ID")]);
        }
        hints.extend([(settings, "settings"), ("L", "load")]);
        let mut used = 0;
        let count = hints
            .iter()
            .take_while(|(key, label)| {
                used += Line::from(format!(" {key} {label} ")).width();
                used <= usize::from(width)
            })
            .count();
        hint_line(&hints[..count], theme)
    }

    fn render_main(&mut self, frame: &mut Frame<'_>, area: Rect, store: &Store, theme: Theme) {
        let index = self.table_index();
        let heading_height = u16::from(matches!(self.active, 0 | 2 | 3));
        let gap = u16::from(heading_height > 0 && area.height > 8);
        let [heading, _, filter, mut content] = Layout::vertical([
            Constraint::Length(heading_height),
            Constraint::Length(gap),
            Constraint::Length(u16::from(
                self.tables[index].editing_filter || !self.tables[index].filter.is_empty(),
            )),
            Constraint::Min(0),
        ])
        .areas(area);
        frame.render_widget(
            Paragraph::new(self.main_heading(store, heading.width, theme)),
            heading,
        );
        if filter.height > 0 {
            let view = &self.tables[index];
            frame.render_widget(
                Paragraph::new(format!(
                    " /{}{}  · {} rows",
                    clean(&view.filter),
                    if view.editing_filter { "▏" } else { "" },
                    view.indices.len()
                ))
                .style(theme.title()),
                filter,
            );
        }
        if index == 8 {
            content = render_my_summary(frame, content, store, theme);
        }
        if self.active == 3 && matches!(self.priority_pane, 1 | 2) {
            content = render_share_note(frame, content, store, self.priority_pane == 2, theme);
        }
        let source = if index == 7 {
            Source::Logs(&self.log_snapshot)
        } else {
            source_for(index, store)
        };
        if self.tables[index].indices.is_empty() {
            let text = empty_message(
                self.active,
                index,
                store,
                !self.tables[index].filter.is_empty(),
            );
            frame.render_widget(Paragraph::new(text).style(theme.subtle()), content);
        } else {
            self.tables[index].render(frame, content, &source, self.today, theme);
        }
    }

    fn main_heading(&self, store: &Store, width: u16, theme: Theme) -> Line<'static> {
        match self.active {
            0 => usage_banner(store, theme),
            2 => subtab_line(
                "User Overview",
                &["r Running", "p Pending"],
                usize::from(self.users_pending),
                width,
                theme,
            ),
            3 => subtab_line(
                "Priority",
                &["m My Priority", "u Active Users", "a Accounts", "j Jobs"],
                self.priority_pane,
                width,
                theme,
            ),
            _ => Line::default(),
        }
    }
}

fn render_unavailable(frame: &mut Frame<'_>, area: Rect, error: &str, theme: Theme) {
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(Span::styled("Slurm is unavailable", theme.role("error"))),
            Line::default(),
            Line::from(clean(error)),
            Line::default(),
            Line::from("Run stoei on a login node with squeue and scontrol on PATH."),
            Line::from("Press r to retry, ? for help, s for settings, or q to quit."),
        ])
        .wrap(Wrap { trim: false })
        .style(theme.text()),
        area,
    );
}

fn hint_line(hints: &[(&str, &str)], theme: Theme) -> Line<'static> {
    Line::from(
        hints
            .iter()
            .flat_map(|(key, label)| {
                [
                    Span::styled(format!(" {key}"), theme.bar_key()),
                    Span::styled(format!(" {label} "), theme.bar()),
                ]
            })
            .collect::<Vec<_>>(),
    )
}

fn sync_label(store: &Store, now: std::time::Instant) -> String {
    let meta = store.meta(Section::RunningJobs);
    let Some(updated) = meta.last_success else {
        return match meta.state {
            State::Loading => "sync …",
            State::Error => "sync !",
            _ => "sync -",
        }
        .into();
    };
    let age = now.saturating_duration_since(updated).as_secs();
    if age < 60 {
        format!("sync {age}s")
    } else if age < 3600 {
        format!("sync {}m", age / 60)
    } else {
        format!("sync {}h", age / 3600)
    }
}

fn subtab_line(
    title: &str,
    labels: &[&str],
    active: usize,
    width: u16,
    theme: Theme,
) -> Line<'static> {
    let full_width = title.len() + 3 + labels.iter().map(|label| label.len() + 2).sum::<usize>();
    let compact = full_width > usize::from(width);
    if width < 28 {
        return Line::from(Span::styled(
            format!(" {} ", labels[active]),
            theme.selected(),
        ));
    }
    let mut spans = vec![Span::styled(format!(" {title}  "), theme.title())];
    spans.extend(labels.iter().enumerate().map(|(index, label)| {
        let label = if compact && index != active {
            label.split_whitespace().next().unwrap_or(label)
        } else {
            label
        };
        Span::styled(
            format!(" {label} "),
            if index == active {
                theme.selected()
            } else {
                theme.subtle()
            },
        )
    }));
    Line::from(spans)
}

fn usage_banner(store: &Store, theme: Theme) -> Line<'static> {
    let mut spans = vec![Span::styled(
        format!(" {} ", clean(&store.user)),
        theme.selected(),
    )];
    if let Some(usage) = store
        .running_user_stats()
        .iter()
        .find(|usage| usage.username == store.user)
    {
        let mut parts = vec![
            ("cpu", usage.total_cpus.to_string()),
            ("mem", super::cluster::compact_memory(usage.total_memory_gb)),
        ];
        if usage.total_gpus > 0 {
            let types = compact_gpu_types(&usage.gpu_types);
            parts.push((
                "gpu",
                if types.is_empty() {
                    usage.total_gpus.to_string()
                } else {
                    clean(&types)
                },
            ));
        }
        parts.extend([
            ("node", usage.total_nodes.to_string()),
            (
                "task",
                format!(
                    "{} ({}A·{}J)",
                    usage.job_count, usage.array_count, usage.plain_job_count
                ),
            ),
        ]);
        for (label, value) in parts {
            spans.extend([
                Span::styled(format!("  {label} "), theme.subtle()),
                Span::styled(value, theme.text()),
            ]);
        }
        if usage.generic_gpu_jobs > 0 {
            spans.push(Span::styled(
                format!("  {}j generic gpu", usage.generic_gpu_jobs),
                theme.subtle(),
            ));
        }
    } else {
        spans.push(Span::styled(
            if store.has_data(Section::AllUsersJobs) {
                " no running jobs"
            } else {
                " Loading usage…"
            },
            theme.subtle(),
        ));
    }
    if store.meta(Section::RunningJobs).state == State::Error
        && store.has_data(Section::RunningJobs)
    {
        spans.push(Span::styled(
            "  refresh failed · last known jobs",
            theme.role("warning"),
        ));
    }
    Line::from(spans)
}

fn compact_gpu_types(types: &str) -> String {
    types
        .split(", ")
        .filter(|part| {
            !part
                .trim_start_matches(|ch: char| ch.is_ascii_digit() || ch == 'x' || ch == ' ')
                .eq_ignore_ascii_case("gpu")
        })
        .map(|part| part.replacen("x ", "×", 1))
        .collect::<Vec<_>>()
        .join(" ")
}

fn render_share_note(
    frame: &mut Frame<'_>,
    area: Rect,
    store: &Store,
    accounts: bool,
    theme: Theme,
) -> Rect {
    if !store.has_data(Section::FairShare) {
        return area;
    }
    let (total, shown, noun) = if accounts {
        (
            store
                .fair_share
                .iter()
                .filter(|entry| entry.is_account())
                .count(),
            store.ranked_accounts().len(),
            "accounts",
        )
    } else {
        (
            store
                .fair_share
                .iter()
                .filter(|entry| !entry.user.is_empty())
                .map(|entry| entry.user.as_str())
                .collect::<std::collections::BTreeSet<_>>()
                .len(),
            store.ranked_users().len(),
            "users",
        )
    };
    let [note, body] = Layout::vertical([Constraint::Length(1), Constraint::Min(0)]).areas(area);
    frame.render_widget(
        Paragraph::new(if total > shown {
            format!(
                " {shown} active {noun} · {} without recent usage hidden",
                total - shown
            )
        } else {
            format!(" {shown} active {noun}")
        })
        .style(theme.subtle()),
        note,
    );
    body
}

fn render_my_summary(frame: &mut Frame<'_>, area: Rect, store: &Store, theme: Theme) -> Rect {
    let lines = wrap_summary(
        my_summary_lines(store, theme),
        usize::from(area.width),
        usize::from(area.height.saturating_sub(4)),
    );
    let height = (lines.len().min(usize::from(u16::MAX)) as u16).min(area.height.saturating_sub(4));
    let [summary, body] =
        Layout::vertical([Constraint::Length(height), Constraint::Min(0)]).areas(area);
    frame.render_widget(Paragraph::new(lines).style(theme.text()), summary);
    body
}

fn wrap_summary(lines: Vec<Line<'static>>, width: usize, max_rows: usize) -> Vec<Line<'static>> {
    let mut wrapped = Vec::new();
    if width == 0 {
        return wrapped;
    }
    for line in lines {
        if wrapped.len() >= max_rows {
            break;
        }
        if line.width() <= width {
            wrapped.push(line);
            continue;
        }
        let hanging = if line.spans.len() == 2 {
            line.spans[0].width()
        } else {
            1
        };
        let prefix_width = if hanging + 12 < width { hanging } else { 1 };
        let text = line
            .spans
            .iter()
            .skip(usize::from(line.spans.len() == 2))
            .map(|span| span.content.as_ref())
            .collect::<String>();
        let style = line.spans.last().map(|span| span.style).unwrap_or_default();
        let label = (line.spans.len() == 2).then(|| line.spans[0].clone());
        if prefix_width < hanging
            && let Some(label) = &label
        {
            wrapped.push(Line::from(label.clone()));
        }
        let chunks = wrap_words(
            &text,
            width.saturating_sub(prefix_width).max(1),
            max_rows.saturating_sub(wrapped.len()),
        );
        for (index, chunk) in chunks.into_iter().enumerate() {
            let prefix = if index == 0 && prefix_width == hanging {
                label.clone().unwrap_or_else(|| Span::raw(" "))
            } else {
                Span::raw(" ".repeat(prefix_width))
            };
            wrapped.push(Line::from(vec![prefix, Span::styled(chunk, style)]));
        }
    }
    wrapped
}

fn wrap_words(text: &str, width: usize, max_rows: usize) -> Vec<String> {
    let mut lines = Vec::new();
    let mut line = String::new();
    let mut used = 0;
    for mut word in text.split_whitespace() {
        if lines.len() >= max_rows {
            return lines;
        }
        let mut word_width = Span::raw(word).width();
        if !line.is_empty() && used + 1 + word_width > width {
            lines.push(std::mem::take(&mut line));
            used = 0;
        }
        while word_width > width {
            if lines.len() >= max_rows {
                return lines;
            }
            let end = fitting_prefix(word, width);
            lines.push(word[..end].to_owned());
            word_width = word_width.saturating_sub(Span::raw(&word[..end]).width());
            word = &word[end..];
        }
        if !line.is_empty() {
            line.push(' ');
            used += 1;
        }
        line.push_str(word);
        used += word_width;
    }
    if !line.is_empty() && lines.len() < max_rows {
        lines.push(line);
    }
    lines
}

fn fitting_prefix(text: &str, width: usize) -> usize {
    let mut used = 0;
    let mut end = 0;
    for (index, ch) in text.char_indices() {
        let mut bytes = [0; 4];
        let char_width = Span::raw(&*ch.encode_utf8(&mut bytes)).width();
        if used + char_width > width && end > 0 {
            break;
        }
        used += char_width;
        end = index + ch.len_utf8();
    }
    end
}

fn my_summary_lines(store: &Store, theme: Theme) -> Vec<Line<'static>> {
    let rank = store::find_ranked_user(store.ranked_users(), &store.user);
    let association = rank.map(|rank| &rank.entry).or_else(|| {
        store
            .fair_share
            .iter()
            .find(|entry| entry.user == store.user)
    });
    let who = association
        .map(|entry| format!("{} · {}", clean(&store.user), clean(&entry.account)))
        .unwrap_or_else(|| clean(&store.user));
    let mut lines = vec![Line::from(vec![
        Span::styled(" Your Priority ", theme.title()),
        Span::styled(format!("— {who}"), theme.text()),
    ])];
    my_share_lines(store, association, rank, theme, &mut lines);
    lines.push(Line::default());
    my_config_lines(store, theme, &mut lines);
    let heading = if store.has_data(Section::PendingPrio) {
        let count = store
            .ranked_pending()
            .iter()
            .filter(|row| row.entry.user == store.user)
            .count();
        format!(" Your pending jobs ({count})")
    } else {
        " Your pending jobs · Loading…".into()
    };
    lines.push(Line::from(Span::styled(heading, theme.title())));
    lines
}

fn my_share_lines(
    store: &Store,
    association: Option<&store::FairShareEntry>,
    rank: Option<&store::RankedShare>,
    theme: Theme,
    lines: &mut Vec<Line<'static>>,
) {
    if !store.has_data(Section::FairShare) {
        let text = if store.meta(Section::FairShare).state == State::Error {
            " Fair-share unavailable"
        } else {
            " Loading fair-share…"
        };
        lines.push(Line::from(Span::styled(text, theme.subtle())));
        return;
    }
    let Some(entry) = association else {
        lines.push(Line::from(" No fair-share association found."));
        return;
    };
    let standing = rank
        .map(|rank| {
            format!(
                "{} · {}",
                store::format_rank(rank.rank, rank.total, "active users"),
                rank.band.label()
            )
        })
        .unwrap_or_else(|| "Unused · no recent usage".into());
    lines.push(summary_line(
        "Fair-share factor",
        format!("{}   {standing}", clean(&entry.fair_share)),
        theme,
    ));
    let ratio = store::usage_ratio(entry);
    lines.push(summary_line(
        "Usage vs share",
        format!(
            "{} · {} usage on a {} share",
            store::format_ratio(ratio.unwrap_or(0.0), ratio.is_some()),
            store::format_percent(&entry.effectv_usage),
            store::format_percent(&entry.norm_shares)
        ),
        theme,
    ));
    if store.has_data(Section::PriorityConfig)
        && let Some(recovery) = ratio
            .and_then(|ratio| store::recovery_time(ratio, store.priority_config.decay_half_life))
    {
        lines.push(summary_line(
            "Recovery",
            format!(
                "about {} without jobs to reach 1× your share",
                store::format_days(recovery)
            ),
            theme,
        ));
    }
}

fn my_config_lines(store: &Store, theme: Theme, lines: &mut Vec<Line<'static>>) {
    if !store.has_data(Section::PriorityConfig) {
        return;
    }
    let cfg = &store.priority_config;
    lines.push(Line::from(Span::styled(
        " How priority is computed here",
        theme.title(),
    )));
    if cfg.multifactor() {
        let weights = &cfg.weights;
        let parts = [
            ("FairShare", weights.fair_share),
            ("Age", weights.age),
            ("JobSize", weights.job_size),
            ("Partition", weights.partition),
            ("QOS", weights.qos),
            ("Assoc", weights.assoc),
        ]
        .into_iter()
        .filter(|(_, weight)| *weight > 0)
        .map(|(label, weight)| format!("{label} {weight}"))
        .collect::<Vec<_>>();
        lines.push(Line::from(format!(" {}", parts.join(" · "))));
        if !weights.tres.is_empty() {
            lines.push(Line::from(format!(" TRES {}", clean(&weights.tres))));
        }
    } else {
        lines.push(Line::from(format!(
            " {} · jobs start in submission order",
            clean(&cfg.priority_type)
        )));
    }
    lines.push(Line::default());
}

fn summary_line(label: &str, value: String, theme: Theme) -> Line<'static> {
    Line::from(vec![
        Span::styled(format!(" {label:<19} "), theme.subtle()),
        Span::styled(value, theme.text()),
    ])
}

fn empty_message(active: usize, index: usize, store: &Store, filtering: bool) -> String {
    if filtering {
        return " No rows match this filter.".into();
    }
    let section = match active {
        0 => Some(Section::RunningJobs),
        1 => Some(Section::Nodes),
        2 => Some(Section::AllUsersJobs),
        3 => Some(if matches!(index, 6 | 8) {
            Section::PendingPrio
        } else {
            Section::FairShare
        }),
        _ => None,
    };
    if let Some(section) = section {
        let meta = store.meta(section);
        match meta.state {
            State::Idle | State::Loading => " Loading…".into(),
            State::Error => format!(
                " {}",
                clean(meta.err.as_deref().unwrap_or("Data could not be loaded"))
            ),
            State::Loaded => " No rows to display.".into(),
        }
    } else {
        " No log entries yet.".into()
    }
}

fn render_modal(
    frame: &mut Frame<'_>,
    modal: &mut Modal,
    store: &Store,
    theme: Theme,
    key_mode: &str,
    version: &str,
) {
    let area = modal_area(frame.area(), modal);
    frame.render_widget(Clear, area);
    let block = Block::bordered()
        .border_type(BorderType::Rounded)
        .border_style(theme.text().fg(theme.border))
        .padding(Padding::new(
            u16::from(area.width >= 28) * 2,
            u16::from(area.width >= 28) * 2,
            u16::from(area.height >= 14),
            u16::from(area.height >= 14),
        ))
        .style(theme.text());
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let gap = u16::from(inner.height >= 8);
    let [title, _, body, _, footer] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(gap),
        Constraint::Min(0),
        Constraint::Length(gap),
        Constraint::Length(1),
    ])
    .areas(inner);
    frame.render_widget(
        Paragraph::new(modal_title(modal).trim().to_owned()).style(theme.title()),
        title,
    );
    render_modal_content(frame, body, modal, store, theme, key_mode, version);
    let hint = if footer.width < 45 {
        modal_short_hint(modal)
    } else {
        modal_hint(modal)
    };
    frame.render_widget(Paragraph::new(hint).style(theme.subtle()), footer);
}

fn modal_title(modal: &Modal) -> String {
    match modal {
        Modal::Job(view) => format!(" Job {} ", clean(&view.id)),
        Modal::Node(view) => format!(" Node {} ", clean(&view.name)),
        Modal::Info { name, account, .. } => format!(
            " {} {} ",
            if *account { "Account" } else { "User" },
            clean(name)
        ),
        Modal::Log(view) => format!(" {} · {} ", view.label, clean(&view.path.to_string_lossy())),
        Modal::Modify(view) => format!(" Modify job {} ", clean(&view.id)),
        Modal::Cancel { id, .. } => format!(" Cancel job {}? ", clean(id)),
        Modal::Input { .. } => " Inspect job ".into(),
        Modal::Settings(_) => " Settings ".into(),
        Modal::Help { .. } => " Help ".into(),
        Modal::Load { .. } => " Cluster load ".into(),
    }
}

fn modal_hint(modal: &Modal) -> &'static str {
    match modal {
        Modal::Job(_) => "Esc close · o stdout · e stderr · m modify · r reload",
        Modal::Log(_) => "Esc close · / search · n/N match · r reload · e editor",
        Modal::Modify(view) if view.editing => "Esc back · Enter apply · C-u clear",
        Modal::Modify(_) => "Esc close · ↑↓ choose · Enter edit/apply",
        Modal::Cancel { .. } => "Esc abort · ←→/Tab choose · Enter confirm",
        Modal::Input { .. } => "Esc close · Enter inspect",
        Modal::Settings(_) => "Esc cancel · C-s save · ↑↓ field · ←→ change",
        _ => "Esc close · ↑↓ scroll · ←→ pan",
    }
}

fn modal_short_hint(modal: &Modal) -> &'static str {
    match modal {
        Modal::Settings(_) => "Esc cancel · C-s save",
        Modal::Modify(view) if view.editing => "Esc back · Enter apply",
        Modal::Modify(_) => "Esc close · Enter edit",
        Modal::Cancel { .. } => "Esc abort · Enter confirm",
        Modal::Input { .. } => "Esc close · Enter inspect",
        Modal::Log(_) => "Esc close · / search",
        _ => "Esc close · ↑↓ scroll",
    }
}

fn render_modal_content(
    frame: &mut Frame<'_>,
    area: Rect,
    modal: &mut Modal,
    store: &Store,
    theme: Theme,
    key_mode: &str,
    version: &str,
) {
    match modal {
        Modal::Job(view) => render_scrolled(
            frame,
            area,
            detail_lines(view, theme),
            &mut view.scroll,
            &mut view.horizontal,
            theme,
        ),
        Modal::Node(view) => render_node(frame, area, view, store, theme),
        Modal::Info {
            name,
            account,
            scroll,
            horizontal,
        } => render_scrolled(
            frame,
            area,
            priority_lines(store, name, *account, theme),
            scroll,
            horizontal,
            theme,
        ),
        Modal::Log(view) => render_log(frame, area, view, theme),
        Modal::Modify(view) => render_modify(frame, area, view, theme),
        Modal::Cancel { id, yes } => render_cancel(frame, area, id, *yes, theme),
        Modal::Input { text, error } => {
            render_job_input(frame, area, text, error.as_deref(), theme)
        }
        Modal::Settings(view) => render_settings(frame, area, view, theme),
        Modal::Help { scroll, horizontal } => render_scrolled(
            frame,
            area,
            help_lines(key_mode, version, theme),
            scroll,
            horizontal,
            theme,
        ),
        Modal::Load { scroll, horizontal } => render_scrolled(
            frame,
            area,
            super::cluster::lines(store, theme),
            scroll,
            horizontal,
            theme,
        ),
    }
}

fn render_node(
    frame: &mut Frame<'_>,
    area: Rect,
    view: &mut super::modals::NodeView,
    store: &Store,
    theme: Theme,
) {
    let mut lines = loading_lines(view.loading, view.error.as_deref(), theme);
    if let Some(detail) = &view.detail {
        lines.extend(field_lines(&detail.fields, true, theme));
    }
    let jobs = store::jobs_on_node(&store.all_users_jobs, &view.name);
    if !jobs.is_empty() {
        lines.push(Line::from(Span::styled(" Jobs on node ", theme.title())));
        lines.push(Line::from(
            " User          JobID         Name                    CPUs  GPUs   Time",
        ));
        for job in jobs.iter().take(30) {
            lines.push(Line::from(format!(
                " {:<13} {:<13} {:<23} {:>4}  {:>4}   {}",
                clean(&job.user),
                clean(&job.id),
                clean(&job.name),
                job.cpus,
                job.gpus,
                clean(&job.time)
            )));
        }
        if jobs.len() > 30 {
            lines.push(Line::from(format!(" … and {} more jobs", jobs.len() - 30)));
        }
    }
    render_scrolled(
        frame,
        area,
        lines,
        &mut view.scroll,
        &mut view.horizontal,
        theme,
    );
}

fn render_cancel(frame: &mut Frame<'_>, area: Rect, id: &str, yes: bool, theme: Theme) {
    let buttons = Line::from(vec![
        Span::styled("  Yes  ", if yes { theme.selected() } else { theme.text() }),
        Span::raw("   "),
        Span::styled("  No  ", if yes { theme.text() } else { theme.selected() }),
    ]);
    let lines = vec![
        Line::from(format!(" Cancel Slurm job {}?", clean(id))),
        Line::default(),
        buttons,
    ];
    frame.render_widget(Paragraph::new(lines).style(theme.text()), area);
}

fn render_job_input(
    frame: &mut Frame<'_>,
    area: Rect,
    text: &str,
    error: Option<&str>,
    theme: Theme,
) {
    let mut lines = vec![
        Line::from(" Job ID (for example 12345 or 12345_4)"),
        Line::default(),
        Line::from(Span::styled(format!(" > {}▏", clean(text)), theme.title())),
    ];
    if let Some(error) = error {
        lines.push(Line::from(Span::styled(clean(error), theme.role("error"))));
    }
    frame.render_widget(Paragraph::new(lines).style(theme.text()), area);
}

fn detail_lines(view: &DetailView, theme: Theme) -> Vec<Line<'static>> {
    let mut lines = loading_lines(view.loading, view.error.as_deref(), theme);
    if let Some(snapshot) = &view.snapshot {
        if snapshot.detail.source == "sacct" {
            lines.push(Line::from(Span::styled(
                " Controller no longer has this job — showing its accounting record.",
                theme.subtle(),
            )));
        }
        if snapshot.detail.source == "journal" {
            lines.push(Line::from(Span::styled(
                " Showing the recorded journal outcome.",
                theme.subtle(),
            )));
        }
        if let Some(usage) = &snapshot.usage {
            lines.extend(efficiency_lines(usage, &snapshot.detail.fields, theme));
        }
        if let Some(note) = &snapshot.note {
            lines.push(Line::from(Span::styled(
                format!(" {}", clean(note)),
                theme.subtle(),
            )));
            lines.push(Line::default());
        }
        lines.extend(field_lines(&snapshot.detail.fields, false, theme));
    }
    lines
}

fn loading_lines(loading: bool, error: Option<&str>, theme: Theme) -> Vec<Line<'static>> {
    let mut lines = Vec::new();
    if loading {
        lines.push(Line::from(Span::styled(" Loading…", theme.role("warning"))));
    }
    if let Some(error) = error {
        lines.push(Line::from(Span::styled(clean(error), theme.role("error"))));
    }
    lines
}

fn render_log(frame: &mut Frame<'_>, area: Rect, view: &mut LogView, theme: Theme) {
    let feedback_height = u16::from(view.loading || view.error.is_some());
    let [body, feedback, status] = Layout::vertical([
        Constraint::Min(0),
        Constraint::Length(feedback_height),
        Constraint::Length(1),
    ])
    .areas(area);
    view.height = usize::from(body.height).max(1);
    view.offset = view.offset.min(view.max_offset());
    let mut lines = loading_lines(view.loading, view.error.as_deref(), theme);
    if let Some(tail) = &view.tail {
        lines = tail
            .lines
            .iter()
            .enumerate()
            .skip(view.offset)
            .take(view.height)
            .map(|(index, line)| {
                let mut spans = Vec::new();
                if view.show_lines {
                    spans.push(Span::styled(
                        format!("{:>7} │ ", tail.first_line.saturating_add(index as u64)),
                        theme.subtle(),
                    ));
                }
                let highlighted = view.matches.binary_search(&index).is_ok();
                spans.push(Span::styled(
                    clean(line),
                    if highlighted {
                        theme.text().fg(theme.warning).add_modifier(Modifier::BOLD)
                    } else {
                        theme.text()
                    },
                ));
                Line::from(spans)
            })
            .collect();
        if tail.lines.is_empty() {
            lines.push(Line::from(" (empty file)"));
        }
    }
    frame.render_widget(
        Paragraph::new(lines)
            .scroll((0, view.horizontal))
            .style(theme.text()),
        body,
    );
    frame.render_widget(
        Paragraph::new(loading_lines(view.loading, view.error.as_deref(), theme)),
        feedback,
    );
    frame.render_widget(
        Paragraph::new(log_status(view)).style(theme.subtle()),
        status,
    );
}

fn log_status(view: &LogView) -> String {
    if view.searching {
        format!(" /{}▏  Enter search · Esc finish", clean(&view.search))
    } else if !view.search.is_empty() {
        format!(" /{} · {} matches", clean(&view.search), view.matches.len())
    } else if let Some(tail) = &view.tail {
        format!(
            " Lines {}–{} of {} · {} retained",
            tail.first_line.saturating_add(view.offset as u64),
            tail.first_line.saturating_add(
                (view.offset + view.height)
                    .min(tail.lines.len())
                    .saturating_sub(1) as u64
            ),
            tail.total_lines,
            tail.lines.len()
        )
    } else {
        String::new()
    }
}

fn render_modify(frame: &mut Frame<'_>, area: Rect, view: &ModifyView, theme: Theme) {
    let mut lines = Vec::new();
    if view.pending_id.is_some() {
        lines.push(Line::from(Span::styled(
            " Applying…",
            theme.role("warning"),
        )));
    }
    if view.editing {
        let row = &view.rows[view.selected];
        lines.push(Line::from(format!(" {} · job {}", row.key, row.target)));
        lines.push(Line::default());
        lines.push(Line::from(Span::styled(
            format!(" > {}▏", clean(&view.input)),
            theme.title(),
        )));
    } else {
        for (index, row) in view.rows.iter().enumerate() {
            let marker = if index == view.selected { "›" } else { " " };
            lines.push(Line::from(Span::styled(
                format!(" {marker} {:<20} {}", row.key, clean(&row.value)),
                if index == view.selected {
                    theme.selected()
                } else {
                    theme.text()
                },
            )));
        }
    }
    if let Some(error) = &view.error {
        lines.push(Line::default());
        lines.push(Line::from(Span::styled(clean(error), theme.role("error"))));
    }
    frame.render_widget(
        Paragraph::new(lines)
            .style(theme.text())
            .wrap(Wrap { trim: false }),
        area,
    );
}

fn render_settings(frame: &mut Frame<'_>, area: Rect, view: &SettingsView, theme: Theme) {
    let [fields, note] = Layout::vertical([
        Constraint::Min(0),
        Constraint::Length(u16::from(area.height > 1)),
    ])
    .areas(area);
    let labels = if fields.width >= 48 {
        [
            "Theme",
            "Refresh interval",
            "History window",
            "Log viewer lines",
            "Keybindings",
        ]
    } else {
        ["Theme", "Refresh", "History", "Log lines", "Keys"]
    };
    let label_width = if fields.width >= 48 {
        18
    } else if fields.width >= 28 {
        12
    } else {
        8
    };
    let first = view
        .field
        .saturating_sub(usize::from(fields.height).saturating_sub(1));
    let lines: Vec<_> = labels
        .iter()
        .zip(view.values.iter())
        .enumerate()
        .skip(first)
        .take(usize::from(fields.height))
        .map(|(index, (label, value))| {
            settings_field(index, label, value, view.field, label_width, theme)
        })
        .collect();
    frame.render_widget(Paragraph::new(lines).style(theme.text()), fields);
    let (text, style) = if let Some(error) = &view.error {
        (clean(error), theme.role("error"))
    } else if view.saving {
        ("Saving…".into(), theme.subtle())
    } else {
        (
            match view.field {
                1 => "Refresh interval: 120–300 seconds",
                2 => "History window: 1–90 days",
                3 => "Log viewer: 500–100000 lines",
                _ => "Use ←/→ to cycle options",
            }
            .into(),
            theme.subtle(),
        )
    };
    frame.render_widget(Paragraph::new(text).style(style), note);
}

fn settings_field(
    index: usize,
    label: &str,
    value: &str,
    field: usize,
    label_width: usize,
    theme: Theme,
) -> Line<'static> {
    let selected = index == field;
    let value = if index == 0 || index == 4 {
        format!("‹ {} ›", clean(value))
    } else {
        format!("{}{}", clean(value), if selected { "▏" } else { "" })
    };
    let (label_style, value_style) = if selected {
        (theme.title(), theme.title())
    } else {
        (theme.subtle(), theme.text())
    };
    Line::from(vec![
        Span::styled(
            format!(
                "{} {label:<label_width$} ",
                if selected { "›" } else { " " }
            ),
            label_style,
        ),
        Span::styled(value, value_style),
    ])
}

fn priority_lines(store: &Store, name: &str, account: bool, theme: Theme) -> Vec<Line<'static>> {
    let dependencies = [
        Section::FairShare,
        Section::PendingPrio,
        Section::PriorityConfig,
        Section::AllUsersJobs,
    ];
    let waiting: Vec<_> = dependencies
        .iter()
        .filter(|section| !store.settled(**section))
        .map(|section| section.name())
        .collect();
    if !waiting.is_empty() {
        return vec![Line::from(format!(" Loading {}…", waiting.join(", ")))];
    }
    let mut lines = Vec::new();
    for section in dependencies {
        if let Some(error) = &store.meta(section).err {
            lines.push(Line::from(Span::styled(
                format!(" {}: {}", section.name(), clean(error)),
                theme.role("error"),
            )));
        }
    }
    lines.extend(fair_share_lines(store, name, account, theme));
    if !account
        && let Some(usage) = store
            .running_user_stats()
            .iter()
            .find(|usage| usage.username == name)
    {
        lines.push(Line::from(Span::styled(" Live resources ", theme.title())));
        lines.push(Line::from(format!(
            " {} jobs · {} CPUs · {:.1} GiB · {} GPUs · {} nodes",
            usage.job_count,
            usage.total_cpus,
            usage.total_memory_gb,
            usage.total_gpus,
            usage.total_nodes
        )));
        lines.push(Line::default());
    }
    lines.extend(priority_config_lines(&store.priority_config, theme));
    lines.extend(pending_lines(store, name, account, theme));
    lines
}

fn fair_share_lines(store: &Store, name: &str, account: bool, theme: Theme) -> Vec<Line<'static>> {
    let associations: Vec<_> = store
        .fair_share
        .iter()
        .filter(|entry| {
            if account {
                entry.is_account() && entry.account == name
            } else {
                entry.user == name
            }
        })
        .collect();
    let rank = if account {
        store::find_ranked_account(store.ranked_accounts(), name)
    } else {
        store::find_ranked_user(store.ranked_users(), name)
    };
    let mut lines = vec![Line::from(Span::styled(" Fair share ", theme.title()))];
    if associations.is_empty() {
        lines.push(Line::from(" No fair-share record is available."));
    }
    for entry in associations {
        lines.extend(share_lines(
            entry,
            rank,
            account,
            store.priority_config.decay_half_life,
            theme,
        ));
    }
    lines
}

fn share_lines(
    entry: &store::FairShareEntry,
    rank: Option<&store::RankedShare>,
    account: bool,
    half_life: std::time::Duration,
    theme: Theme,
) -> Vec<Line<'static>> {
    let ratio = store::usage_ratio(entry);
    let mut lines = vec![Line::from(format!(
        " Account: {} · fair-share factor {}",
        clean(&entry.account),
        clean(&entry.fair_share)
    ))];
    if let Some(rank) = rank {
        lines.push(Line::from(format!(
            " {}",
            store::format_rank(
                rank.rank,
                rank.total,
                if account {
                    "active accounts"
                } else {
                    "active users"
                }
            )
        )));
    }
    let band = store::classify_usage(ratio.unwrap_or(0.0), ratio.is_some());
    lines.push(Line::from(Span::styled(
        format!(
            " Usage vs share: {} · {}",
            store::format_ratio(ratio.unwrap_or(0.0), ratio.is_some()),
            band.label()
        ),
        theme.role(band.role()),
    )));
    lines.push(Line::from(format!(
        " Cluster share {} · effective usage {}",
        store::format_percent(&entry.norm_shares),
        store::format_percent(&entry.effectv_usage)
    )));
    if let Some(recovery) = ratio.and_then(|ratio| store::recovery_time(ratio, half_life)) {
        lines.push(Line::from(format!(
            " With no new usage: about {} to return to 1× your share",
            store::format_days(recovery)
        )));
    }
    lines.push(Line::default());
    lines
}

fn priority_config_lines(config: &store::PriorityConfig, theme: Theme) -> Vec<Line<'static>> {
    let mut lines = vec![
        Line::from(Span::styled(
            " How priority is computed here ",
            theme.title(),
        )),
        Line::from(format!(" {}", clean(&config.priority_type))),
    ];
    if config.multifactor() {
        let weights = &config.weights;
        lines.push(Line::from(format!(
            " FairShare {} · Age {} · JobSize {} · Partition {} · QOS {} · Assoc {}",
            weights.fair_share,
            weights.age,
            weights.job_size,
            weights.partition,
            weights.qos,
            weights.assoc
        )));
        if !weights.tres.is_empty() {
            lines.push(Line::from(format!(" TRES {}", clean(&weights.tres))));
        }
        lines.push(Line::from(format!(
            " Usage half-life {} · age reaches full weight after {}",
            store::format_days(config.decay_half_life),
            store::format_days(config.max_age)
        )));
    }
    lines.push(Line::default());
    lines
}

fn pending_lines(store: &Store, name: &str, account: bool, theme: Theme) -> Vec<Line<'static>> {
    let pending: Vec<_> = store
        .ranked_pending()
        .iter()
        .filter(|row| {
            if account {
                row.entry.account == name
            } else {
                row.entry.user == name
            }
        })
        .cloned()
        .collect();
    let mut lines = Vec::new();
    let (factors, total) = store::sum_factors(&pending);
    if total > 0 {
        lines.push(Line::from(" Your pending jobs' weighted contribution:"));
        for factor in factors.contributions() {
            lines.push(Line::from(format!(
                " {}: {} ({:.1}%)",
                factor.name,
                factor.value,
                100.0 * factor.value as f64 / total as f64
            )));
        }
        lines.push(Line::default());
    }
    lines.push(Line::from(Span::styled(
        " Pending jobs by partition ",
        theme.title(),
    )));
    if pending.is_empty() {
        lines.push(Line::from(" No pending jobs."));
    }
    for standing in store::partition_standings(&pending) {
        lines.push(Line::from(Span::styled(
            format!(
                " {} — {}",
                clean(&standing.partition),
                store::format_standing(&standing)
            ),
            theme.title(),
        )));
        for row in pending
            .iter()
            .filter(|row| row.entry.partition == standing.partition)
        {
            lines.push(Line::from(format!(
                " {}  job {}  priority {}  {}",
                store::format_queue(row.pos.partition, row.pos.partition_total),
                clean(&row.entry.job_id),
                row.entry.priority,
                store::format_breakdown(&row.entry.factors)
            )));
        }
        lines.push(Line::default());
    }
    lines
}

fn help_lines(mode: &str, version: &str, theme: Theme) -> Vec<Line<'static>> {
    let globals = if mode == "emacs" {
        " C-s filter · C-o sort · C-r refresh · C-, settings · C-h help · C-q quit"
    } else {
        " / filter · o sort · r refresh · s settings · ? help · q quit"
    };
    let mut lines = vec![
        Line::from(Span::styled(
            if version == "dev" {
                "stoei · local development build".into()
            } else {
                format!("stoei · {}", clean(version))
            },
            theme.title(),
        )),
        Line::default(),
    ];
    lines.extend([" Navigation", " 1–5 tabs · Tab/Shift+Tab next/previous · ↑↓ rows · PgUp/PgDn pages", " g/G first/last · ←→ horizontal scrolling · Enter inspect", globals, "", " Jobs", " i enter a job ID · c cancel active job (confirmation defaults to No)", " Completed jobs appear alongside your live jobs.", "", " Users", " r Running · p Pending · Enter user summary", "", " Priority", " m My Priority · u Active Users · a Accounts · j Pending Jobs", " Fair-share rank is among users with recent usage.", " Queue positions are per partition; multi-partition jobs appear in each queue.", "", " Filtering and sorting", " Filter text matches a case-insensitive literal substring.", " Combine column:value constraints (state:RUNNING name:train) with free text.", " Enter keeps the filter; Esc clears it. Sort cycles ascending, descending, then next column.", "", " Job detail", " o stdout · e stderr · m modify · r refresh detail · ↑↓ scroll", " Live usage is visible only for your own running jobs.", " CPU efficiency uses all allocated CPUs; MIG GPU utilization is unavailable.", "", " Job modification", " Array throttle · Partition · TimeLimit · QOS · Nice · JobName", " Hold/Release · Other raw Key=Value · Enter apply · Esc back", "", " Log viewer", " / literal search · n/N next/previous match · r reload", " c copy path · e external editor ($VISUAL/$EDITOR, otherwise vi)", " l toggle original line numbers · g/G top/bottom · ←→ horizontal scroll", "", " Settings", " ↑↓/Tab choose field · ←→ cycle theme/keybindings · edit numeric values", " C-s save · Enter advance/save last field · Esc cancel", "", " Cluster load", " L opens a scrollable summary; wide terminals also show the sidebar.", "", " Exit", " q closes a modal or quits the dashboard; C-c quits."].into_iter().map(|text| {
        if !text.starts_with(' ') && !text.is_empty() { Line::from(Span::styled(text.to_owned(), theme.title())) } else { Line::from(text.to_owned()) }
    }));
    lines
}

fn modal_area(area: Rect, modal: &Modal) -> Rect {
    let width = (u32::from(area.width) * 85 / 100) as u16;
    let height = (u32::from(area.height) * 85 / 100) as u16;
    let (width, height) = match modal {
        Modal::Settings(_) => (width.min(66), height.min(17)),
        Modal::Cancel { .. } => (width.min(54), height.min(11)),
        Modal::Input { .. } => (width.min(62), height.min(12)),
        Modal::Modify(_) => (width.min(80), height),
        _ => (width, height),
    };
    let width = if width < 20 { area.width } else { width };
    let height = if height < 6 { area.height } else { height };
    Rect::new(
        area.x + area.width.saturating_sub(width) / 2,
        area.y + area.height.saturating_sub(height) / 2,
        width,
        height,
    )
}

fn render_scrolled(
    frame: &mut Frame<'_>,
    area: Rect,
    lines: Vec<Line<'static>>,
    scroll: &mut u16,
    horizontal: &mut u16,
    theme: Theme,
) {
    let width = lines
        .iter()
        .map(Line::width)
        .max()
        .unwrap_or(0)
        .min(usize::from(u16::MAX)) as u16;
    *horizontal = (*horizontal).min(width.saturating_sub(area.width));
    *scroll = (*scroll).min(
        lines
            .len()
            .saturating_sub(usize::from(area.height))
            .min(usize::from(u16::MAX)) as u16,
    );
    frame.render_widget(
        Paragraph::new(lines)
            .style(theme.text())
            .scroll((*scroll, *horizontal)),
        area,
    );
}
