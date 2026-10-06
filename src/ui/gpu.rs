use crossterm::event::{KeyCode, KeyEvent};
use ratatui::text::{Line, Span};

use crate::store::{GpuDevice, GpuSnapshot};

use super::format::{bytes, clean};
use super::modals::{Modal, Response, scroll_key};
use super::render::loading_lines;
use super::theme::Theme;
use super::{Effect, Ui};

pub(super) struct GpuView {
    pub token: u64,
    pub id: String,
    pub snapshot: Option<GpuSnapshot>,
    pub loading: bool,
    pub error: Option<String>,
    pub scroll: u16,
    pub horizontal: u16,
}

impl Ui {
    pub(super) fn gpu_response(&mut self, id: &str) -> Response {
        let token = self.token();
        debug_assert!(token > 0);
        debug_assert!(self.modals.len() < 3);
        (
            true,
            vec![Effect::FetchGpu {
                token,
                job_id: id.into(),
            }],
            Some(Modal::Gpu(GpuView {
                token,
                id: id.into(),
                snapshot: None,
                loading: true,
                error: None,
                scroll: 0,
                horizontal: 0,
            })),
        )
    }

    pub(super) fn handle_gpu(&mut self, key: KeyEvent, view: &mut GpuView) -> Response {
        if key.code == KeyCode::Char('r') && !view.loading {
            view.token = self.token();
            view.loading = true;
            view.error = None;
            return (
                true,
                vec![Effect::FetchGpu {
                    token: view.token,
                    job_id: view.id.clone(),
                }],
                None,
            );
        }
        let keep = scroll_key(key, &mut view.scroll, &mut view.horizontal);
        (keep, Vec::new(), None)
    }

    pub(super) fn receive_gpu(
        &mut self,
        token: u64,
        job_id: String,
        result: Result<GpuSnapshot, String>,
    ) {
        let Some(Modal::Gpu(view)) = self.modals.iter_mut().find(
            |modal| matches!(modal, Modal::Gpu(view) if view.token == token && view.id == job_id),
        ) else {
            return;
        };
        view.loading = false;
        match result {
            Ok(snapshot) => {
                view.snapshot = Some(snapshot);
                view.error = None;
            }
            Err(error) => view.error = Some(error),
        }
    }
}

pub(super) fn gpu_lines(view: &GpuView, theme: Theme) -> Vec<Line<'static>> {
    let mut lines = loading_lines(view.loading, view.error.as_deref(), theme);
    if let Some(snapshot) = &view.snapshot {
        if view.loading || view.error.is_some() {
            lines.push(Line::from(Span::styled(
                " Showing the previous snapshot.",
                theme.subtle(),
            )));
        }
        lines.push(Line::from(Span::styled(
            " GPU readings include other processes if the device is shared.",
            theme.subtle(),
        )));
        for warning in &snapshot.warnings {
            lines.push(Line::from(Span::styled(
                format!(" {}", clean(warning)),
                theme.role("warning"),
            )));
        }
        if snapshot.devices.is_empty() {
            lines.push(Line::from(" No GPU readings available."));
        }
        for device in &snapshot.devices {
            lines.extend(device_lines(device, theme));
        }
    }
    lines
}

fn device_lines(device: &GpuDevice, theme: Theme) -> [Line<'static>; 4] {
    let utilization = device
        .utilization_percent
        .map_or_else(|| "n/a".into(), |value| format!("{value:.0}%"));
    let memory = |value: Option<u64>| value.map_or_else(|| "n/a".into(), bytes);
    [
        Line::default(),
        Line::from(Span::styled(
            format!(
                " {} · GPU {} · {}",
                clean(&device.node),
                device.index,
                clean(&device.name),
            ),
            theme.title(),
        )),
        Line::from(format!("  GPU utilization......... {utilization}")),
        Line::from(format!(
            "  VRAM used / total........ {} / {}",
            memory(device.memory_used_bytes),
            memory(device.memory_total_bytes),
        )),
    ]
}
