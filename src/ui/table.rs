use std::borrow::Cow;
use std::cmp::Ordering;
use std::collections::BTreeMap;

use chrono::NaiveDate;
use ratatui::Frame;
use ratatui::layout::{Constraint, Rect};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Cell, Row, Table};

use crate::log::LogEntry;
use crate::store::{
    self, FairShareEntry, MergedJob, NodeDisplay, RankedPriority, RankedShare, UserPendingStats,
    UserStats,
};

use super::format::clean;
use super::theme::Theme;

const JOB_HEADERS: &[&str] = &[
    "Job ID",
    "Name",
    "State",
    "Time",
    "Nodes",
    "Node List",
    "Timeline",
];
const NODE_HEADERS: &[&str] = &[
    "Node",
    "State",
    "CPUs",
    "CPU%",
    "Memory",
    "Mem%",
    "GPUs",
    "GPU%",
    "GPU Types",
    "Partitions",
    "Reason",
];
const RUNNING_HEADERS: &[&str] = &[
    "User",
    "Jobs",
    "CPUs",
    "Memory (GB)",
    "GPUs",
    "GPU Types",
    "Nodes",
    "NodeList",
];
const PENDING_HEADERS: &[&str] = &[
    "User",
    "Pending Jobs",
    "CPUs Requested",
    "Memory (GB)",
    "GPUs Requested",
    "GPU Types",
    "Reasons",
];
const USER_HEADERS: &[&str] = &[
    "Rank",
    "User",
    "Account",
    "FairShare",
    "Share%",
    "Usage%",
    "Usage/Share",
    "Status",
];
const ACCOUNT_HEADERS: &[&str] = &[
    "Rank",
    "Account",
    "Share%",
    "Usage%",
    "Usage/Share",
    "Status",
    "Users",
];
const PRIORITY_HEADERS: &[&str] = &[
    "JobID",
    "Partition",
    "Queue",
    "User",
    "Account",
    "QOS",
    "Priority",
    "Cluster-wide",
    "FairShare",
    "Age",
    "JobSize",
    "PartPrio",
    "QOSPrio",
    "TRES",
    "Assoc",
    "Site",
    "Nice",
];
const MY_PRIORITY_HEADERS: &[&str] = &[
    "JobID",
    "Partition",
    "Queue",
    "QOS",
    "Priority",
    "Breakdown",
];

pub(super) enum Source<'a> {
    Jobs(&'a [MergedJob]),
    Nodes(&'a [NodeDisplay]),
    Running(&'a [UserStats]),
    Pending(&'a [UserPendingStats]),
    Shares(&'a [RankedShare], bool),
    Accounts(&'a [RankedShare], &'a [FairShareEntry]),
    Priority(&'a [RankedPriority]),
    MyPriority(&'a [RankedPriority], &'a str),
    Logs(&'a [LogEntry]),
}

impl Source<'_> {
    pub fn len(&self) -> usize {
        match self {
            Self::Jobs(rows) => rows.len(),
            Self::Nodes(rows) => rows.len(),
            Self::Running(rows) => rows.len(),
            Self::Pending(rows) => rows.len(),
            Self::Shares(rows, _) | Self::Accounts(rows, _) => rows.len(),
            Self::Priority(rows) | Self::MyPriority(rows, _) => rows.len(),
            Self::Logs(rows) => rows.len(),
        }
    }

    pub fn key(&self, index: usize) -> Cow<'_, str> {
        match self {
            Self::Jobs(rows) => Cow::Borrowed(&rows[index].id),
            Self::Nodes(rows) => Cow::Borrowed(&rows[index].name),
            Self::Running(rows) => Cow::Borrowed(&rows[index].username),
            Self::Pending(rows) => Cow::Borrowed(&rows[index].username),
            Self::Shares(rows, accounts) => {
                if *accounts {
                    Cow::Borrowed(&rows[index].entry.account)
                } else {
                    Cow::Borrowed(&rows[index].entry.user)
                }
            }
            Self::Accounts(rows, _) => Cow::Borrowed(&rows[index].entry.account),
            Self::Priority(rows) | Self::MyPriority(rows, _) => Cow::Owned(format!(
                "{}@{}",
                rows[index].entry.job_id, rows[index].entry.partition
            )),
            Self::Logs(rows) => Cow::Owned(format!(
                "{}:{}:{}",
                rows[index].timestamp, rows[index].level, rows[index].message
            )),
        }
    }

    pub fn headers(&self) -> &'static [&'static str] {
        match self {
            Self::Jobs(_) => JOB_HEADERS,
            Self::Nodes(_) => NODE_HEADERS,
            Self::Running(_) => RUNNING_HEADERS,
            Self::Pending(_) => PENDING_HEADERS,
            Self::Shares(_, false) => USER_HEADERS,
            Self::Shares(_, true) | Self::Accounts(_, _) => ACCOUNT_HEADERS,
            Self::Priority(_) => PRIORITY_HEADERS,
            Self::MyPriority(_, _) => MY_PRIORITY_HEADERS,
            Self::Logs(_) => &["Time", "Level", "Message"],
        }
    }

    fn cells(&self, index: usize, today: NaiveDate, users: &[(usize, usize)]) -> Vec<String> {
        match self {
            Self::Jobs(rows) => job_cells(&rows[index], today),
            Self::Nodes(rows) => node_cells(&rows[index]),
            Self::Running(rows) => running_cells(&rows[index]),
            Self::Pending(rows) => pending_cells(&rows[index]),
            Self::Shares(rows, false) => share_cells(&rows[index]),
            Self::Shares(rows, true) | Self::Accounts(rows, _) => {
                account_cells(&rows[index], users.get(index).copied().unwrap_or_default())
            }
            Self::Priority(rows) => priority_cells(&rows[index]),
            Self::MyPriority(rows, _) => my_priority_cells(&rows[index]),
            Self::Logs(rows) => {
                let row = &rows[index];
                vec![
                    row.timestamp.clone(),
                    log_level(&row.level),
                    row.message.clone(),
                ]
            }
        }
    }

    fn default_order(&self, indices: &mut [usize]) {
        if let Self::Priority(rows) | Self::MyPriority(rows, _) = self {
            indices.sort_by(|a, b| {
                rows[*a]
                    .entry
                    .partition
                    .cmp(&rows[*b].entry.partition)
                    .then_with(|| rows[*a].pos.partition.cmp(&rows[*b].pos.partition))
            });
        }
    }

    fn cell_role(&self, index: usize, column: usize) -> &str {
        match self {
            Self::Jobs(rows) if column == 2 => store::state_role(&rows[index].state),
            Self::Nodes(rows) if column == 1 => store::state_role(&rows[index].state),
            Self::Nodes(rows) if column == 3 => usage_role(rows[index].cpu_usage_pct()),
            Self::Nodes(rows) if column == 5 => usage_role(rows[index].memory_usage_pct()),
            Self::Nodes(rows) if column == 7 && rows[index].gpus_total > 0 => {
                usage_role(rows[index].gpu_usage_pct())
            }
            Self::Shares(rows, false) if column == 3 || column == 7 => rows[index].band.role(),
            Self::Shares(rows, true) | Self::Accounts(rows, _) if column == 5 => {
                rows[index].band.role()
            }
            Self::Logs(_) if column == 0 => "muted",
            Self::Logs(rows) if column == 1 => log_role(&rows[index].level),
            _ => "",
        }
    }

    fn includes(&self, index: usize) -> bool {
        match self {
            Self::MyPriority(rows, user) => rows[index].entry.user == *user,
            _ => true,
        }
    }
}

#[derive(Default)]
pub(super) struct TableView {
    pub indices: Vec<usize>,
    pub cursor: usize,
    pub offset: usize,
    pub horizontal: u16,
    pub filter: String,
    pub editing_filter: bool,
    pub selected_key: Option<String>,
    pub sort: Option<(usize, bool)>,
    pub height: usize,
    column_widths: Vec<Constraint>,
    account_users: Vec<(usize, usize)>,
}

impl TableView {
    pub fn rebuild(&mut self, source: &Source<'_>, today: NaiveDate) {
        let filter = Filter::parse(&self.filter, source.headers());
        self.account_users = account_users(source);
        self.indices.clear();
        if self.filter.trim().is_empty() {
            self.indices
                .extend((0..source.len()).filter(|index| source.includes(*index)));
        } else {
            self.indices.extend((0..source.len()).filter(|index| {
                source.includes(*index)
                    && filter.matches(&source.cells(*index, today, &self.account_users))
            }));
        }
        source.default_order(&mut self.indices);
        if let Some((column, descending)) = self.sort {
            let mut keys: Vec<_> = self
                .indices
                .iter()
                .map(|index| {
                    (
                        *index,
                        source
                            .cells(*index, today, &self.account_users)
                            .get(column)
                            .cloned()
                            .unwrap_or_default(),
                    )
                })
                .collect();
            keys.sort_by(|a, b| {
                let ordering = compare_cell(&a.1, &b.1);
                if descending {
                    ordering.reverse()
                } else {
                    ordering
                }
            });
            self.indices = keys.into_iter().map(|(index, _)| index).collect();
        }
        if let Some(key) = &self.selected_key
            && let Some(cursor) = self
                .indices
                .iter()
                .position(|index| source.key(*index) == key.as_str())
        {
            self.cursor = cursor;
        }
        self.cursor = self.cursor.min(self.indices.len().saturating_sub(1));
        self.remember(source);
        self.keep_visible();
        self.column_widths =
            fitted_widths(source, &self.indices, today, self.sort, &self.account_users);
        debug_assert!(self.indices.iter().all(|index| *index < source.len()));
        debug_assert!(self.indices.is_empty() || self.cursor < self.indices.len());
    }

    pub fn selected(&self) -> Option<usize> {
        self.indices.get(self.cursor).copied()
    }

    pub fn move_by(&mut self, amount: isize, source: &Source<'_>) {
        self.cursor = self
            .cursor
            .saturating_add_signed(amount)
            .min(self.indices.len().saturating_sub(1));
        self.remember(source);
        self.keep_visible();
    }

    pub fn edge(&mut self, bottom: bool, source: &Source<'_>) {
        self.cursor = if bottom {
            self.indices.len().saturating_sub(1)
        } else {
            0
        };
        self.remember(source);
        self.keep_visible();
    }

    pub fn cycle_sort(&mut self, source: &Source<'_>, today: NaiveDate) {
        let columns: Vec<_> = source
            .headers()
            .iter()
            .enumerate()
            .filter(|(_, name)| !["Timeline", "Breakdown"].contains(name))
            .map(|(column, _)| column)
            .collect();
        self.sort = match self.sort {
            None => columns.first().map(|column| (*column, false)),
            Some((column, false)) => Some((column, true)),
            Some((column, true)) => columns
                .iter()
                .position(|item| *item == column)
                .and_then(|position| columns.get(position + 1))
                .map(|column| (*column, false)),
        };
        self.rebuild(source, today);
    }

    fn remember(&mut self, source: &Source<'_>) {
        self.selected_key = self.selected().map(|index| source.key(index).into_owned());
    }

    fn keep_visible(&mut self) {
        if self.cursor < self.offset {
            self.offset = self.cursor;
        }
        let height = self.height.max(1);
        if self.cursor >= self.offset.saturating_add(height) {
            self.offset = self.cursor + 1 - height;
        }
        self.offset = self.offset.min(self.indices.len().saturating_sub(1));
    }

    pub fn render(
        &mut self,
        frame: &mut Frame<'_>,
        area: Rect,
        source: &Source<'_>,
        today: NaiveDate,
        theme: Theme,
    ) {
        let logs = matches!(source, Source::Logs(_));
        let padding = u16::from(!logs && area.width > 0);
        let area = Rect::new(area.x + padding, area.y, area.width - padding, area.height);
        self.height = usize::from(area.height.saturating_sub(u16::from(!logs)));
        self.keep_visible();
        let virtual_width = preferred_width(&self.column_widths).max(area.width);
        self.horizontal = self
            .horizontal
            .min(virtual_width.saturating_sub(area.width));
        let visible = self
            .indices
            .iter()
            .enumerate()
            .skip(self.offset)
            .take(self.height);
        let rows = visible.map(|(position, index)| {
            let selected = position == self.cursor && !logs;
            let cells = source
                .cells(*index, today, &self.account_users)
                .into_iter()
                .enumerate()
                .map(|(column, value)| {
                    Cell::from(Line::from(Span::styled(
                        clean(&value),
                        if selected {
                            theme.selection()
                        } else {
                            theme.role(source.cell_role(*index, column))
                        },
                    )))
                });
            let row = Row::new(cells);
            if selected {
                row.style(theme.selection())
            } else if logs {
                row.style(theme.text())
            } else {
                row
            }
        });
        let mut table = Table::new(rows, self.column_widths.clone()).column_spacing(1);
        if !logs {
            table = table.header(table_header(source, self.sort, theme));
        }
        render_table(frame, area, table, self.horizontal, virtual_width);
    }
}

fn table_header(source: &Source<'_>, sort: Option<(usize, bool)>, theme: Theme) -> Row<'static> {
    Row::new(source.headers().iter().enumerate().map(|(column, name)| {
        let direction = if sort == Some((column, false)) {
            " ↑"
        } else if sort == Some((column, true)) {
            " ↓"
        } else {
            ""
        };
        format!("{name}{direction}")
    }))
    .style(theme.title())
}

fn log_level(value: &str) -> String {
    let value = clean(value).trim().to_uppercase();
    let padding = 8usize.saturating_sub(Line::raw(&value).width());
    format!(
        "[{}{}{}]",
        " ".repeat(padding / 2),
        value,
        " ".repeat(padding - padding / 2)
    )
}

fn log_role(value: &str) -> &'static str {
    match clean(value).trim().to_ascii_uppercase().as_str() {
        "INFO" | "SUCCESS" => "success",
        "WARNING" => "warning",
        "ERROR" | "CRITICAL" => "error",
        "DEBUG" => "muted",
        _ => "",
    }
}

fn job_cells(row: &MergedJob, today: NaiveDate) -> Vec<String> {
    vec![
        row.id.clone(),
        row.name.clone(),
        row.state.clone(),
        row.time.clone(),
        row.nodes.clone(),
        row.node_list.clone(),
        row.timeline(today),
    ]
}

fn node_cells(row: &NodeDisplay) -> Vec<String> {
    let (gpus, gpu_percent, gpu_types) = if row.gpus_total > 0 {
        (
            format!("{}/{}", row.gpus_alloc, row.gpus_total),
            format!("{:.1}%", row.gpu_usage_pct()),
            na_if_empty(&row.gpu_types),
        )
    } else {
        ("N/A".into(), "N/A".into(), "N/A".into())
    };
    vec![
        row.name.clone(),
        row.state.clone(),
        format!("{}/{}", row.cpus_alloc, row.cpus_total),
        format!("{:.1}%", row.cpu_usage_pct()),
        format!("{:.1}/{:.1} GB", row.memory_alloc_gb, row.memory_total_gb),
        format!("{:.1}%", row.memory_usage_pct()),
        gpus,
        gpu_percent,
        gpu_types,
        row.partitions.clone(),
        row.reason.clone(),
    ]
}

fn running_cells(row: &UserStats) -> Vec<String> {
    vec![
        row.username.clone(),
        row.job_count.to_string(),
        row.total_cpus.to_string(),
        format!("{:.1}", row.total_memory_gb),
        row.total_gpus.to_string(),
        na_if_empty(&row.gpu_types),
        row.total_nodes.to_string(),
        na_if_empty(&row.node_names),
    ]
}

fn pending_cells(row: &UserPendingStats) -> Vec<String> {
    vec![
        row.username.clone(),
        row.pending_job_count.to_string(),
        row.pending_cpus.to_string(),
        format!("{:.1}", row.pending_memory_gb),
        row.pending_gpus.to_string(),
        na_if_empty(&row.pending_gpu_types),
        na_if_empty(&row.pending_reasons),
    ]
}

fn share_cells(row: &RankedShare) -> Vec<String> {
    vec![
        format!("{}/{}", row.rank, row.total),
        row.entry.user.clone(),
        row.entry.account.clone(),
        format!("{:.4}", store::fair_share_value(&row.entry)),
        store::format_percent(&row.entry.norm_shares),
        store::format_percent(&row.entry.effectv_usage),
        store::format_ratio(row.ratio, row.ratio_ok),
        row.band.label().into(),
    ]
}

fn account_cells(row: &RankedShare, users: (usize, usize)) -> Vec<String> {
    vec![
        format!("{}/{}", row.rank, row.total),
        row.entry.account.clone(),
        store::format_percent(&row.entry.norm_shares),
        store::format_percent(&row.entry.effectv_usage),
        store::format_ratio(row.ratio, row.ratio_ok),
        row.band.label().into(),
        format!("{}/{}", users.0, users.1),
    ]
}

fn account_users(source: &Source<'_>) -> Vec<(usize, usize)> {
    let Source::Accounts(rows, entries) = source else {
        return Vec::new();
    };
    let mut counts: BTreeMap<&str, (usize, usize)> = BTreeMap::new();
    for entry in entries.iter().filter(|entry| !entry.is_account()) {
        let count = counts.entry(&entry.account).or_default();
        count.1 += 1;
        count.0 += usize::from(store::usage_ratio(entry).is_some_and(|ratio| ratio > 0.0));
    }
    rows.iter()
        .map(|row| {
            counts
                .get(row.entry.account.as_str())
                .copied()
                .unwrap_or_default()
        })
        .collect()
}

fn priority_cells(row: &RankedPriority) -> Vec<String> {
    let factors = &row.entry.factors;
    vec![
        row.entry.job_id.clone(),
        row.entry.partition.clone(),
        store::format_queue(row.pos.partition, row.pos.partition_total),
        row.entry.user.clone(),
        row.entry.account.clone(),
        row.entry.qos.clone(),
        row.entry.priority.to_string(),
        store::format_queue(row.pos.cluster, row.pos.cluster_total),
        factors.fair_share.to_string(),
        factors.age.to_string(),
        factors.job_size.to_string(),
        factors.partition.to_string(),
        factors.qos.to_string(),
        factors.tres.to_string(),
        factors.assoc.to_string(),
        factors.site.to_string(),
        factors.nice.to_string(),
    ]
}

fn my_priority_cells(row: &RankedPriority) -> Vec<String> {
    vec![
        row.entry.job_id.clone(),
        row.entry.partition.clone(),
        store::format_queue(row.pos.partition, row.pos.partition_total),
        row.entry.qos.clone(),
        row.entry.priority.to_string(),
        store::format_breakdown(&row.entry.factors),
    ]
}

fn na_if_empty(value: &str) -> String {
    if value.is_empty() {
        "N/A".into()
    } else {
        value.to_owned()
    }
}

fn usage_role(percent: f64) -> &'static str {
    if percent >= 90.0 {
        "error"
    } else if percent >= 70.0 {
        "warning"
    } else {
        "success"
    }
}

fn render_table(
    frame: &mut Frame<'_>,
    area: Rect,
    table: Table<'_>,
    horizontal: u16,
    virtual_width: u16,
) {
    if horizontal == 0 && virtual_width == area.width {
        frame.render_widget(table, area);
        return;
    }
    let mut buffer = ratatui::buffer::Buffer::empty(Rect::new(0, 0, virtual_width, area.height));
    ratatui::widgets::Widget::render(table, buffer.area, &mut buffer);
    for y in 0..area.height {
        for x in 0..area.width {
            if let Some(cell) = buffer.cell((x + horizontal, y))
                && let Some(target) = frame.buffer_mut().cell_mut((area.x + x, area.y + y))
            {
                *target = cell.clone();
            }
        }
    }
}

fn preferred_width(widths: &[Constraint]) -> u16 {
    let spacing = u16::try_from(widths.len().saturating_sub(1)).unwrap_or(u16::MAX);
    widths.iter().fold(spacing, |total, constraint| {
        total.saturating_add(match constraint {
            Constraint::Length(width) | Constraint::Min(width) => *width,
            _ => 0,
        })
    })
}

fn fitted_widths(
    source: &Source<'_>,
    indices: &[usize],
    today: NaiveDate,
    sort: Option<(usize, bool)>,
    users: &[(usize, usize)],
) -> Vec<Constraint> {
    let mut widths: Vec<_> = source
        .headers()
        .iter()
        .enumerate()
        .map(|(column, header)| {
            if matches!(source, Source::Logs(_)) {
                return 0;
            }
            Line::raw(*header).width() as u16
                + if sort.is_some_and(|(sorted, _)| sorted == column) {
                    2
                } else {
                    0
                }
        })
        .collect();
    for &index in indices {
        for (column, value) in source.cells(index, today, users).iter().enumerate() {
            let width = Line::raw(clean(value))
                .width()
                .min(column_limit(source.headers()[column]));
            widths[column] = widths[column].max(width as u16);
        }
    }
    widths.into_iter().map(Constraint::Length).collect()
}

fn column_limit(header: &str) -> usize {
    match header {
        "Message" => 512,
        "Breakdown" => 160,
        "NodeList" | "Node List" => 96,
        "Reason" | "Reasons" => 64,
        "Name" | "Timeline" => 48,
        "Job ID" | "JobID" | "GPU Types" => 32,
        "User" | "Account" | "Node" | "Partition" | "Partitions" => 24,
        _ => 21,
    }
}

struct Filter {
    columns: Vec<(usize, String)>,
    text: String,
}

impl Filter {
    fn parse(query: &str, headers: &[&str]) -> Self {
        let mut columns = Vec::new();
        let mut text = Vec::new();
        for word in query.split_whitespace() {
            if let Some((column, value)) = word.split_once(':') {
                let column = normalize_column(column);
                if let Some(index) = headers
                    .iter()
                    .position(|header| matches_column(header, &column))
                    && !value.is_empty()
                {
                    columns.push((index, value.to_lowercase()));
                    continue;
                }
            }
            text.push(word);
        }
        Self {
            columns,
            text: text.join(" ").to_lowercase(),
        }
    }

    fn matches(&self, cells: &[String]) -> bool {
        if !self.columns.iter().all(|(index, needle)| {
            cells
                .get(*index)
                .is_some_and(|value| value.to_lowercase().contains(needle))
        }) {
            return false;
        }
        self.text.is_empty() || cells.join(" ").to_lowercase().contains(&self.text)
    }
}

fn normalize_column(value: &str) -> String {
    let key = value.to_lowercase().replace([' ', '_', '-', '(', ')'], "");
    match key.as_str() {
        "id" | "job" => "jobid".into(),
        "cpu" => "cpus".into(),
        "gpu" => "gpus".into(),
        "username" => "user".into(),
        "mem" | "memory" | "memorygb" => "memory".into(),
        "cpu%" | "cpupct" => "cpupct".into(),
        "mem%" | "mempct" => "mempct".into(),
        "gpu%" | "gpupct" => "gpupct".into(),
        "share%" => "share".into(),
        "usage%" => "usage".into(),
        "standing" => "status".into(),
        "cluster" | "clusterwide" => "clusterwide".into(),
        "partitionprio" => "partprio".into(),
        "nodelist" | "nodelistreason" => "nodelist".into(),
        _ => key,
    }
}

fn matches_column(header: &str, key: &str) -> bool {
    let header = normalize_column(header);
    header == key
        || matches!(
            (key, header.as_str()),
            ("jobs", "pendingjobs") | ("cpus", "cpusrequested") | ("gpus", "gpusrequested")
        )
}

fn compare_cell(a: &str, b: &str) -> Ordering {
    match (numeric_cell(a), numeric_cell(b)) {
        (Some(a), Some(b)) => a.total_cmp(&b),
        _ => a.to_lowercase().cmp(&b.to_lowercase()),
    }
}

fn numeric_cell(value: &str) -> Option<f64> {
    if value.contains(':')
        && value
            .chars()
            .all(|ch| ch.is_ascii_digit() || ch == ':' || ch == '-' || ch == '.')
    {
        return Some(store::parse_elapsed_to_seconds(value));
    }
    value
        .split('/')
        .next()?
        .trim_matches(['#', '%', '×'])
        .parse::<f64>()
        .ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::Terminal;
    use ratatui::backend::TestBackend;
    use ratatui::buffer::Buffer;

    fn render_table_view(view: &mut TableView, source: &Source<'_>) -> Buffer {
        let mut terminal = Terminal::new(TestBackend::new(80, 4)).unwrap();
        terminal
            .draw(|frame| {
                let area = frame.area();
                view.render(
                    frame,
                    area,
                    source,
                    NaiveDate::from_ymd_opt(2026, 9, 30).unwrap(),
                    Theme::by_name("nord"),
                );
            })
            .unwrap();
        terminal.backend().buffer().clone()
    }

    fn buffer_text(buffer: &Buffer) -> String {
        buffer.content.iter().map(|cell| cell.symbol()).collect()
    }

    #[test]
    fn compact_job_columns_fit_a_normal_terminal_and_sort_headers_stay_complete() {
        let jobs = [MergedJob {
            id: "12345".into(),
            name: "Pending Array".into(),
            state: "PENDING".into(),
            time: "01:00:00".into(),
            nodes: "1".into(),
            node_list: "node001".into(),
            ..Default::default()
        }];
        let source = Source::Jobs(&jobs);
        let mut view = TableView::default();
        let today = NaiveDate::from_ymd_opt(2026, 9, 30).unwrap();
        view.rebuild(&source, today);
        let initial = render_table_view(&mut view, &source);
        let text = buffer_text(&initial);
        for expected in [
            "Job ID",
            "Node List",
            "Timeline",
            "Pending Array",
            "node001",
        ] {
            assert!(text.contains(expected), "missing {expected}: {text}");
        }
        view.horizontal = 8;
        assert_eq!(render_table_view(&mut view, &source), initial);
        view.cycle_sort(&source, today);
        assert!(buffer_text(&render_table_view(&mut view, &source)).contains("Job ID ↑"));
    }

    #[test]
    fn node_resources_show_usage_percentages_units_and_gpu_less_fallbacks() {
        let nodes = [NodeDisplay {
            name: "gpu01".into(),
            state: "MIXED".into(),
            cpus_alloc: 16,
            cpus_total: 64,
            memory_alloc_gb: 128.0,
            memory_total_gb: 256.0,
            gpus_alloc: 2,
            gpus_total: 8,
            gpu_types: "8x H200".into(),
            partitions: "gpu".into(),
            ..Default::default()
        }];
        let source = Source::Nodes(&nodes);
        let mut view = TableView::default();
        view.rebuild(&source, NaiveDate::from_ymd_opt(2026, 9, 30).unwrap());
        let text = buffer_text(&render_table_view(&mut view, &source));
        for expected in [
            "CPU%",
            "Mem%",
            "GPU%",
            "16/64",
            "128.0/256.0 GB",
            "2/8",
            "25.0%",
        ] {
            assert!(text.contains(expected), "missing {expected}: {text}");
        }
        let cpu_only = node_cells(&NodeDisplay::default());
        assert_eq!(&cpu_only[6..9], ["N/A", "N/A", "N/A"]);
    }

    #[test]
    fn fair_share_ranks_lead_the_row_and_usage_uses_effective_usage() {
        let ranked = [RankedShare {
            entry: FairShareEntry {
                user: "alice".into(),
                account: "science".into(),
                fair_share: "0.12345".into(),
                norm_shares: "0.4".into(),
                norm_usage: "0.1".into(),
                effectv_usage: "0.8".into(),
                ..Default::default()
            },
            rank: 2,
            total: 3,
            ratio: 2.0,
            ratio_ok: true,
            band: store::UsageBand::Over,
        }];
        let source = Source::Shares(&ranked, false);
        let mut view = TableView::default();
        view.rebuild(&source, NaiveDate::from_ymd_opt(2026, 9, 30).unwrap());
        let text = buffer_text(&render_table_view(&mut view, &source));
        assert!(text.find("Rank").unwrap() < text.find("User").unwrap());
        for expected in [
            "Share%",
            "Usage%",
            "Status",
            "2/3",
            "0.1235",
            "80.0%",
            "Over-served",
        ] {
            assert!(text.contains(expected), "missing {expected}: {text}");
        }
    }

    #[test]
    fn accounts_show_active_and_total_associations_and_filter_by_that_count() {
        let entries = [
            FairShareEntry {
                account: "science".into(),
                user: "alice".into(),
                norm_shares: "1".into(),
                effectv_usage: "0.5".into(),
                ..Default::default()
            },
            FairShareEntry {
                account: "science".into(),
                user: "bob".into(),
                norm_shares: "1".into(),
                effectv_usage: "0".into(),
                ..Default::default()
            },
            FairShareEntry {
                account: "other".into(),
                user: "carol".into(),
                norm_shares: "1".into(),
                effectv_usage: "1".into(),
                ..Default::default()
            },
        ];
        let ranked = [RankedShare {
            entry: FairShareEntry {
                account: "science".into(),
                norm_shares: "1".into(),
                effectv_usage: "0.5".into(),
                ..Default::default()
            },
            rank: 1,
            total: 1,
            ..Default::default()
        }];
        let source = Source::Accounts(&ranked, &entries);
        let mut view = TableView {
            filter: "users:1/2".into(),
            ..Default::default()
        };
        view.rebuild(&source, NaiveDate::from_ymd_opt(2026, 9, 30).unwrap());
        let text = buffer_text(&render_table_view(&mut view, &source));
        for expected in ["Rank", "Users", "science", "1/2", "50.0%"] {
            assert!(text.contains(expected), "missing {expected}: {text}");
        }
        assert_eq!(view.selected_key.as_deref(), Some("science"));
    }

    #[test]
    fn my_priority_keeps_source_indices_and_selection_without_including_other_users() {
        let entry = |id: &str, user: &str, partition: &str| RankedPriority {
            entry: store::PriorityEntry {
                job_id: id.into(),
                user: user.into(),
                partition: partition.into(),
                qos: "normal".into(),
                priority: 100,
                factors: store::PriorityFactors {
                    age: 20,
                    fair_share: 80,
                    ..Default::default()
                },
                ..Default::default()
            },
            pos: store::QueuePosition {
                partition: 1,
                partition_total: 2,
                ..Default::default()
            },
        };
        let mut jobs = vec![entry("999", "bob", "cpu"), entry("123", "alice", "gpu")];
        let today = NaiveDate::from_ymd_opt(2026, 9, 30).unwrap();
        let mut view = TableView::default();
        view.rebuild(&Source::MyPriority(&jobs, "alice"), today);
        assert_eq!(view.selected(), Some(1));
        let text = buffer_text(&render_table_view(
            &mut view,
            &Source::MyPriority(&jobs, "alice"),
        ));
        for expected in [
            "JobID",
            "Partition",
            "Queue",
            "QOS",
            "Priority",
            "Breakdown",
            "123",
        ] {
            assert!(text.contains(expected), "missing {expected}: {text}");
        }
        assert!(!text.contains("999"));
        jobs.reverse();
        view.rebuild(&Source::MyPriority(&jobs, "alice"), today);
        assert_eq!(view.selected(), Some(0));
        assert_eq!(view.selected_key.as_deref(), Some("123@gpu"));
        let all = Source::Priority(&jobs);
        let cells = all.cells(0, today, &[]);
        assert_eq!(&cells[..3], ["123", "gpu", "#1/2"]);
        assert_eq!(&cells[8..10], ["80", "20"]);
    }

    #[test]
    fn long_log_messages_can_be_scrolled_to_their_tail_without_reflow() {
        let logs = [LogEntry {
            timestamp: "12:34:56".into(),
            level: "INFO".into(),
            message: format!("\u{1b}[31m{} END_MESSAGE\u{1b}[0m", "界".repeat(64)),
        }];
        let source = Source::Logs(&logs);
        let mut view = TableView::default();
        view.rebuild(&source, NaiveDate::from_ymd_opt(2026, 9, 30).unwrap());
        let initial = render_table_view(&mut view, &source);
        let initial_text: String = initial.content.iter().map(|cell| cell.symbol()).collect();
        assert!(initial_text.contains("12:34:56"));
        assert_eq!(initial.cell((0, 0)).unwrap().symbol(), "1");
        assert!(initial_text.contains("[  INFO  ]"));
        assert!(!initial_text.contains("END_MESSAGE"));

        view.horizontal = 512;
        let last = render_table_view(&mut view, &source);
        let last_text: String = last.content.iter().map(|cell| cell.symbol()).collect();
        assert!(last_text.contains("END_MESSAGE"));
        view.horizontal += 8;
        assert_eq!(render_table_view(&mut view, &source), last);
    }

    #[test]
    fn log_lines_fill_the_view_without_headers_or_selection_and_keep_level_colors() {
        let logs: Vec<_> = [
            ("info", "first"),
            ("SUCCESS", "second"),
            ("ERROR", "third"),
            ("CRITICAL", "fourth"),
        ]
        .into_iter()
        .enumerate()
        .map(|(index, (level, message))| LogEntry {
            timestamp: format!("12:00:0{}", index + 1),
            level: level.into(),
            message: message.into(),
        })
        .collect();
        let source = Source::Logs(&logs);
        let mut view = TableView::default();
        let today = NaiveDate::from_ymd_opt(2026, 9, 30).unwrap();
        view.rebuild(&source, today);
        let initial = render_table_view(&mut view, &source);
        let text = buffer_text(&initial);
        assert!(text.starts_with("12:00:01 [  INFO  ] first"));
        assert!(text.contains("[SUCCESS ] second"));
        assert!(text.contains("[ ERROR  ] third"));
        assert!(text.contains("12:00:04 [CRITICAL] fourth"));
        assert!(!text.contains("Message"));
        let theme = Theme::by_name("nord");
        for y in 0..4 {
            assert_eq!(initial.cell((0, y)).unwrap().fg, theme.subtle);
            assert_eq!(
                initial.cell((10, y)).unwrap().fg,
                if y < 2 { theme.success } else { theme.error }
            );
            assert_eq!(initial.cell((20, y)).unwrap().fg, theme.text);
            assert_eq!(initial.cell((79, y)).unwrap().bg, theme.background);
        }
        view.move_by(1, &source);
        assert_eq!(render_table_view(&mut view, &source), initial);
        view.filter = "level:error".into();
        view.rebuild(&source, today);
        let filtered = buffer_text(&render_table_view(&mut view, &source));
        assert!(filtered.starts_with("12:00:03 [ ERROR  ] third"));
        assert!(!filtered.contains("first"));
    }

    #[test]
    fn column_filters_are_anded_with_literal_free_text() {
        let headers = ["JobID", "Name", "State"];
        let filter = Filter::parse("state:RUN id:12 alpha beta", &headers);
        assert!(filter.matches(&["123".into(), "Alpha Beta".into(), "RUNNING".into()]));
        assert!(!filter.matches(&["123".into(), "Alpha Other Beta".into(), "RUNNING".into()]));
        assert!(!filter.matches(&["123".into(), "Alpha Beta".into(), "PENDING".into()]));
        assert!(Filter::parse("unknown:value", &headers).matches(&[
            "12".into(),
            "unknown:value".into(),
            "R".into()
        ]));
    }

    #[test]
    fn filtering_sorting_and_refresh_preserve_the_selected_row() {
        let today = NaiveDate::from_ymd_opt(2026, 9, 30).unwrap();
        let mut jobs = vec![
            MergedJob {
                id: "20".into(),
                name: "Beta".into(),
                ..Default::default()
            },
            MergedJob {
                id: "3".into(),
                name: "Alpha".into(),
                ..Default::default()
            },
        ];
        let mut view = TableView::default();
        view.rebuild(&Source::Jobs(&jobs), today);
        view.move_by(1, &Source::Jobs(&jobs));
        view.cycle_sort(&Source::Jobs(&jobs), today);
        assert_eq!(view.selected_key.as_deref(), Some("3"));
        assert_eq!(view.indices, [1, 0]);
        jobs.reverse();
        view.rebuild(&Source::Jobs(&jobs), today);
        assert_eq!(view.selected_key.as_deref(), Some("3"));
        assert_eq!(view.selected(), Some(0));
    }
}
