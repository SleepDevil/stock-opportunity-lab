use std::fs;
use std::io::ErrorKind;
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Emitter, LogicalSize, Manager, PhysicalPosition, PhysicalSize};

use crate::lifecycle::AppLifecycle;

pub(crate) const WIDGET_MIN_WIDTH: f64 = 320.0;
pub(crate) const WIDGET_MIN_HEIGHT: f64 = 360.0;
const WIDGET_DOCK_WIDTH: f64 = 236.0;
const WIDGET_DOCK_HEIGHT: f64 = 46.0;
// Keep the hot zone inside the widget's 18px default floating margin so a
// small adjustment at startup does not accidentally dock the window.
const WIDGET_AUTO_DOCK_DISTANCE: f64 = 16.0;
const WIDGET_DRAG_POLL_INTERVAL: Duration = Duration::from_millis(40);
const WIDGET_DRAG_SETTLE_DELAY: Duration = Duration::from_millis(180);
const WIDGET_DRAG_IDLE_TIMEOUT: Duration = Duration::from_millis(450);
const WIDGET_DRAG_WATCH_TIMEOUT: Duration = Duration::from_secs(120);
const WIDGET_DRAG_MIN_DISTANCE: f64 = 3.0;
const WIDGET_HOVER_POLL_INTERVAL: Duration = Duration::from_millis(80);
const WIDGET_COLLAPSE_DELAY: Duration = Duration::from_millis(650);
const WIDGET_DOCK_STATE_EVENT: &str = "widget-dock-state-changed";
const WIDGET_GEOMETRY_FILE: &str = "widget-geometry.json";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum WidgetDockEdge {
    Top,
    Right,
    Bottom,
    Left,
}

impl WidgetDockEdge {
    fn as_str(self) -> &'static str {
        match self {
            Self::Top => "top",
            Self::Right => "right",
            Self::Bottom => "bottom",
            Self::Left => "left",
        }
    }
}

struct WidgetDockState {
    enabled: bool,
    collapsed: bool,
    edge: Option<WidgetDockEdge>,
    expanded_position: PhysicalPosition<i32>,
    expanded_size: PhysicalSize<u32>,
    outside_since: Option<Instant>,
    dragging: bool,
    drag_generation: u64,
    suppress_expand_until_pointer_exit: bool,
}

struct WidgetDock(Mutex<WidgetDockState>);

#[derive(Clone, Copy)]
struct WidgetDockGeometry {
    current_position: PhysicalPosition<i32>,
    current_size: PhysicalSize<u32>,
    work_position: PhysicalPosition<i32>,
    work_size: PhysicalSize<u32>,
}

#[derive(serde::Deserialize, serde::Serialize)]
struct PersistedWidgetGeometry {
    width: u32,
    height: u32,
    x: i32,
    y: i32,
}

pub(crate) fn initialize(app: &tauri::App) {
    restore_expanded_geometry(app.handle());
    let initial_state = app
        .get_webview_window("widget")
        .and_then(|window| {
            Some(WidgetDockState {
                enabled: false,
                collapsed: false,
                edge: None,
                expanded_position: window.outer_position().ok()?,
                expanded_size: window.outer_size().ok()?,
                outside_since: None,
                dragging: false,
                drag_generation: 0,
                suppress_expand_until_pointer_exit: false,
            })
        })
        .unwrap_or(WidgetDockState {
            enabled: false,
            collapsed: false,
            edge: None,
            expanded_position: PhysicalPosition::new(0, 0),
            expanded_size: PhysicalSize::new(380, 520),
            outside_since: None,
            dragging: false,
            drag_generation: 0,
            suppress_expand_until_pointer_exit: false,
        });
    app.manage(WidgetDock(Mutex::new(initial_state)));
    start_hover_monitor(app.handle().clone());
}

fn expanded_size_is_valid(size: PhysicalSize<u32>, scale: f64) -> bool {
    size.width >= (WIDGET_MIN_WIDTH * scale).round() as u32
        && size.height >= (WIDGET_MIN_HEIGHT * scale).round() as u32
}

#[cfg(test)]
fn rectangles_intersect(
    first_position: PhysicalPosition<i32>,
    first_size: PhysicalSize<u32>,
    second_position: PhysicalPosition<i32>,
    second_size: PhysicalSize<u32>,
) -> bool {
    rectangle_intersection_area(first_position, first_size, second_position, second_size) > 0
}

fn rectangle_intersection_area(
    first_position: PhysicalPosition<i32>,
    first_size: PhysicalSize<u32>,
    second_position: PhysicalPosition<i32>,
    second_size: PhysicalSize<u32>,
) -> u64 {
    let first_right = first_position.x as i64 + first_size.width as i64;
    let first_bottom = first_position.y as i64 + first_size.height as i64;
    let second_right = second_position.x as i64 + second_size.width as i64;
    let second_bottom = second_position.y as i64 + second_size.height as i64;
    let left = (first_position.x as i64).max(second_position.x as i64);
    let top = (first_position.y as i64).max(second_position.y as i64);
    let right = first_right.min(second_right);
    let bottom = first_bottom.min(second_bottom);
    if right <= left || bottom <= top {
        return 0;
    }
    (right - left) as u64 * (bottom - top) as u64
}

fn restore_expanded_geometry(app: &tauri::AppHandle) {
    let Ok(config_dir) = app.path().app_config_dir() else {
        return;
    };
    let path = config_dir.join(WIDGET_GEOMETRY_FILE);
    let data = match fs::read(&path) {
        Ok(data) => data,
        Err(error) if error.kind() == ErrorKind::NotFound => return,
        Err(error) => {
            log::warn!("failed to read desktop widget geometry: {error}");
            return;
        }
    };
    let geometry = match serde_json::from_slice::<PersistedWidgetGeometry>(&data) {
        Ok(geometry) => geometry,
        Err(error) => {
            log::warn!("failed to parse desktop widget geometry: {error}");
            return;
        }
    };
    let Ok(window) = window(app) else {
        return;
    };
    let Ok(scale) = window.scale_factor() else {
        return;
    };
    let size = PhysicalSize::new(geometry.width, geometry.height);
    if !expanded_size_is_valid(size, scale) {
        log::warn!("ignored compact desktop widget geometry from a previous session");
        return;
    }
    if let Err(error) = window.set_size(size) {
        log::warn!("failed to restore desktop widget size: {error}");
        return;
    }

    let saved_position = PhysicalPosition::new(geometry.x, geometry.y);
    let restored_position = window
        .available_monitors()
        .ok()
        .and_then(|monitors| {
            monitors
                .into_iter()
                .map(|monitor| {
                    let intersection = rectangle_intersection_area(
                        saved_position,
                        size,
                        *monitor.position(),
                        *monitor.size(),
                    );
                    (intersection, monitor)
                })
                .filter(|(intersection, _)| *intersection > 0)
                .max_by_key(|(intersection, _)| *intersection)
        })
        .map(|(_, monitor)| {
            let work_area = monitor.work_area();
            clamped_window_position(saved_position, size, work_area.position, work_area.size)
        });
    if let Some(position) = restored_position {
        if position != saved_position {
            log::info!("clamped restored widget position from {saved_position:?} to {position:?}");
        }
        if let Err(error) = window.set_position(position) {
            log::warn!("failed to restore desktop widget position: {error}");
        }
    }
}

fn persist_expanded_geometry(
    app: &tauri::AppHandle,
    state: &WidgetDockState,
) -> Result<(), String> {
    let config_dir = app
        .path()
        .app_config_dir()
        .map_err(|error| error.to_string())?;
    fs::create_dir_all(&config_dir).map_err(|error| error.to_string())?;
    let geometry = PersistedWidgetGeometry {
        width: state.expanded_size.width,
        height: state.expanded_size.height,
        x: state.expanded_position.x,
        y: state.expanded_position.y,
    };
    let data = serde_json::to_vec_pretty(&geometry).map_err(|error| error.to_string())?;
    fs::write(config_dir.join(WIDGET_GEOMETRY_FILE), data).map_err(|error| error.to_string())
}

fn state_value(state: &WidgetDockState) -> serde_json::Value {
    serde_json::json!({
        "enabled": state.enabled,
        "collapsed": state.collapsed,
        "edge": state.edge.map(WidgetDockEdge::as_str),
    })
}

fn emit_state(window: &tauri::WebviewWindow, state: &WidgetDockState) {
    if let Err(error) = window.emit(WIDGET_DOCK_STATE_EVENT, state_value(state)) {
        log::warn!("failed to emit widget dock state: {error}");
    }
}

fn cursor_is_inside_window(
    cursor: PhysicalPosition<f64>,
    window_position: PhysicalPosition<i32>,
    window_size: PhysicalSize<u32>,
) -> bool {
    cursor.x >= window_position.x as f64
        && cursor.x < (window_position.x + window_size.width as i32) as f64
        && cursor.y >= window_position.y as f64
        && cursor.y < (window_position.y + window_size.height as i32) as f64
}

fn edge_distances(
    window_position: PhysicalPosition<i32>,
    window_size: PhysicalSize<u32>,
    work_position: PhysicalPosition<i32>,
    work_size: PhysicalSize<u32>,
) -> [(u32, WidgetDockEdge); 4] {
    let work_right = work_position.x + work_size.width as i32;
    let work_bottom = work_position.y + work_size.height as i32;
    let window_right = window_position.x + window_size.width as i32;
    let window_bottom = window_position.y + window_size.height as i32;
    [
        (
            (window_position.y - work_position.y).max(0) as u32,
            WidgetDockEdge::Top,
        ),
        (
            (work_right - window_right).max(0) as u32,
            WidgetDockEdge::Right,
        ),
        (
            (work_bottom - window_bottom).max(0) as u32,
            WidgetDockEdge::Bottom,
        ),
        (
            (window_position.x - work_position.x).max(0) as u32,
            WidgetDockEdge::Left,
        ),
    ]
}

fn nearest_edge(
    window_position: PhysicalPosition<i32>,
    window_size: PhysicalSize<u32>,
    work_position: PhysicalPosition<i32>,
    work_size: PhysicalSize<u32>,
) -> WidgetDockEdge {
    edge_distances(window_position, window_size, work_position, work_size)
        .into_iter()
        .min_by_key(|(distance, _)| *distance)
        .map(|(_, edge)| edge)
        .unwrap_or(WidgetDockEdge::Top)
}

fn edge_within_distance(
    window_position: PhysicalPosition<i32>,
    window_size: PhysicalSize<u32>,
    work_position: PhysicalPosition<i32>,
    work_size: PhysicalSize<u32>,
    maximum_distance: u32,
) -> Option<WidgetDockEdge> {
    edge_distances(window_position, window_size, work_position, work_size)
        .into_iter()
        .filter(|(distance, _)| *distance <= maximum_distance)
        .min_by_key(|(distance, _)| *distance)
        .map(|(_, edge)| edge)
}

fn point_edge_within_distance(
    point: PhysicalPosition<f64>,
    area_position: PhysicalPosition<i32>,
    area_size: PhysicalSize<u32>,
    maximum_distance: f64,
) -> Option<WidgetDockEdge> {
    let area_right = area_position.x as f64 + area_size.width as f64;
    let area_bottom = area_position.y as f64 + area_size.height as f64;
    let distances = [
        (
            (point.y - area_position.y as f64).abs(),
            WidgetDockEdge::Top,
        ),
        ((area_right - point.x).abs(), WidgetDockEdge::Right),
        ((area_bottom - point.y).abs(), WidgetDockEdge::Bottom),
        (
            (point.x - area_position.x as f64).abs(),
            WidgetDockEdge::Left,
        ),
    ];
    distances
        .into_iter()
        .filter(|(distance, _)| *distance <= maximum_distance)
        .min_by(|(first, _), (second, _)| first.total_cmp(second))
        .map(|(_, edge)| edge)
}

fn clamp_axis(value: i32, minimum: i32, maximum: i32) -> i32 {
    value.clamp(minimum, maximum.max(minimum))
}

fn clamped_window_position(
    position: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
    work_position: PhysicalPosition<i32>,
    work_size: PhysicalSize<u32>,
) -> PhysicalPosition<i32> {
    let maximum_x = work_position.x + work_size.width as i32 - size.width as i32;
    let maximum_y = work_position.y + work_size.height as i32 - size.height as i32;
    PhysicalPosition::new(
        clamp_axis(position.x, work_position.x, maximum_x),
        clamp_axis(position.y, work_position.y, maximum_y),
    )
}

fn snapped_expanded_position(
    edge: WidgetDockEdge,
    current: PhysicalPosition<i32>,
    size: PhysicalSize<u32>,
    work_position: PhysicalPosition<i32>,
    work_size: PhysicalSize<u32>,
) -> PhysicalPosition<i32> {
    let contained = clamped_window_position(current, size, work_position, work_size);
    let maximum_x = work_position.x + work_size.width as i32 - size.width as i32;
    let maximum_y = work_position.y + work_size.height as i32 - size.height as i32;
    match edge {
        WidgetDockEdge::Top => PhysicalPosition::new(contained.x, work_position.y),
        WidgetDockEdge::Right => PhysicalPosition::new(maximum_x.max(work_position.x), contained.y),
        WidgetDockEdge::Bottom => {
            PhysicalPosition::new(contained.x, maximum_y.max(work_position.y))
        }
        WidgetDockEdge::Left => PhysicalPosition::new(work_position.x, contained.y),
    }
}

fn collapsed_position(
    edge: WidgetDockEdge,
    expanded_position: PhysicalPosition<i32>,
    expanded_size: PhysicalSize<u32>,
    collapsed_size: PhysicalSize<u32>,
    work_position: PhysicalPosition<i32>,
    work_size: PhysicalSize<u32>,
) -> PhysicalPosition<i32> {
    let center_x =
        expanded_position.x + (expanded_size.width.saturating_sub(collapsed_size.width) / 2) as i32;
    let inset_y = expanded_position.y + (collapsed_size.height / 4) as i32;
    let work_right = work_position.x + work_size.width as i32;
    let work_bottom = work_position.y + work_size.height as i32;
    match edge {
        WidgetDockEdge::Top => PhysicalPosition::new(center_x, work_position.y),
        WidgetDockEdge::Right => PhysicalPosition::new(
            work_right - collapsed_size.width as i32,
            clamp_axis(
                inset_y,
                work_position.y,
                work_bottom - collapsed_size.height as i32,
            ),
        ),
        WidgetDockEdge::Bottom => {
            PhysicalPosition::new(center_x, work_bottom - collapsed_size.height as i32)
        }
        WidgetDockEdge::Left => PhysicalPosition::new(
            work_position.x,
            clamp_axis(
                inset_y,
                work_position.y,
                work_bottom - collapsed_size.height as i32,
            ),
        ),
    }
}

fn window(app: &tauri::AppHandle) -> Result<tauri::WebviewWindow, String> {
    app.get_webview_window("widget")
        .ok_or_else(|| "widget window is not available".to_string())
}

fn movement_exceeds_distance(
    start: PhysicalPosition<i32>,
    current: PhysicalPosition<i32>,
    minimum_distance: u32,
) -> bool {
    let delta_x = current.x as i64 - start.x as i64;
    let delta_y = current.y as i64 - start.y as i64;
    let minimum = minimum_distance as i64;
    delta_x * delta_x + delta_y * delta_y >= minimum * minimum
}

#[cfg(target_os = "macos")]
fn primary_mouse_button_pressed() -> Option<bool> {
    Some(objc2_app_kit::NSEvent::pressedMouseButtons() & 1 != 0)
}

#[cfg(target_os = "windows")]
fn primary_mouse_button_pressed() -> Option<bool> {
    #[link(name = "User32")]
    unsafe extern "system" {
        fn GetAsyncKeyState(virtual_key: i32) -> i16;
    }

    const VK_LBUTTON: i32 = 0x01;
    // SAFETY: GetAsyncKeyState accepts a virtual-key code and has no pointer arguments.
    let state = unsafe { GetAsyncKeyState(VK_LBUTTON) } as u16;
    Some(state & 0x8000 != 0)
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn primary_mouse_button_pressed() -> Option<bool> {
    None
}

fn dock_to_edge(
    app: &tauri::AppHandle,
    window: &tauri::WebviewWindow,
    state: &mut WidgetDockState,
    edge: WidgetDockEdge,
    geometry: WidgetDockGeometry,
) -> Result<(), String> {
    state.enabled = true;
    state.dragging = false;
    state.edge = Some(edge);
    state.expanded_size = geometry.current_size;
    state.expanded_position = snapped_expanded_position(
        edge,
        geometry.current_position,
        geometry.current_size,
        geometry.work_position,
        geometry.work_size,
    );
    state.outside_since = None;
    state.suppress_expand_until_pointer_exit = true;
    if let Err(error) = persist_expanded_geometry(app, state) {
        log::warn!("failed to persist docked widget geometry: {error}");
    }
    collapse(window, state)?;
    emit_state(window, state);
    Ok(())
}

fn finish_widget_drag(app: &tauri::AppHandle, generation: u64, moved: bool) {
    let Ok(window) = window(app) else {
        return;
    };
    let (Ok(current_position), Ok(current_size)) = (window.outer_position(), window.outer_size())
    else {
        return;
    };
    let cursor_position = app.cursor_position().ok();
    let monitor = cursor_position
        .and_then(|cursor| window.monitor_from_point(cursor.x, cursor.y).ok().flatten())
        .or_else(|| window.current_monitor().ok().flatten());
    let monitor_geometry = monitor.map(|monitor| {
        let work_area = monitor.work_area();
        (
            *monitor.position(),
            *monitor.size(),
            work_area.position,
            work_area.size,
            monitor.scale_factor(),
        )
    });

    let dock = app.state::<WidgetDock>();
    let Ok(mut state) = dock.0.lock() else {
        return;
    };
    if !state.dragging || state.drag_generation != generation {
        return;
    }
    state.dragging = false;
    state.outside_since = None;

    if !moved {
        return;
    }

    if let Some((monitor_position, monitor_size, work_position, work_size, scale)) =
        monitor_geometry
    {
        let maximum_distance = (WIDGET_AUTO_DOCK_DISTANCE * scale).round() as u32;
        let cursor_edge = cursor_position.and_then(|cursor| {
            point_edge_within_distance(
                cursor,
                monitor_position,
                monitor_size,
                maximum_distance as f64,
            )
        });
        let window_edge = edge_within_distance(
            current_position,
            current_size,
            work_position,
            work_size,
            maximum_distance,
        );
        if let Some(edge) = cursor_edge.or(window_edge) {
            if let Err(error) = dock_to_edge(
                app,
                &window,
                &mut state,
                edge,
                WidgetDockGeometry {
                    current_position,
                    current_size,
                    work_position,
                    work_size,
                },
            ) {
                log::warn!("failed to auto-dock widget after dragging: {error}");
            }
            return;
        }
    }

    let was_docked = state.enabled;
    state.enabled = false;
    state.collapsed = false;
    state.edge = None;
    state.expanded_position = current_position;
    state.expanded_size = current_size;
    state.suppress_expand_until_pointer_exit = false;
    if let Err(error) = persist_expanded_geometry(app, &state) {
        log::warn!("failed to persist dragged widget geometry: {error}");
    }
    if was_docked {
        emit_state(&window, &state);
    }
}

fn start_drag_monitor(
    app: tauri::AppHandle,
    generation: u64,
    start_position: PhysicalPosition<i32>,
    scale: f64,
) -> Result<(), String> {
    thread::Builder::new()
        .name("widget-drag-monitor".to_string())
        .spawn(move || {
            let started_at = Instant::now();
            let mut last_position = start_position;
            let mut last_moved_at = started_at;
            let mut moved = false;
            let minimum_distance = (WIDGET_DRAG_MIN_DISTANCE * scale).round().max(1.0) as u32;

            loop {
                thread::sleep(WIDGET_DRAG_POLL_INTERVAL);
                if app.state::<AppLifecycle>().is_quitting() {
                    return;
                }
                let drag_is_active = app
                    .state::<WidgetDock>()
                    .0
                    .lock()
                    .map(|state| state.dragging && state.drag_generation == generation)
                    .unwrap_or(false);
                if !drag_is_active {
                    return;
                }
                let Ok(window) = window(&app) else {
                    return;
                };
                let Ok(current_position) = window.outer_position() else {
                    continue;
                };
                let now = Instant::now();
                if current_position != last_position {
                    last_position = current_position;
                    last_moved_at = now;
                }
                moved |=
                    movement_exceeds_distance(start_position, current_position, minimum_distance);

                let should_finish = match primary_mouse_button_pressed() {
                    Some(false) => moved || started_at.elapsed() >= WIDGET_DRAG_IDLE_TIMEOUT,
                    Some(true) => false,
                    None => {
                        (moved && last_moved_at.elapsed() >= WIDGET_DRAG_SETTLE_DELAY)
                            || (!moved && started_at.elapsed() >= WIDGET_DRAG_IDLE_TIMEOUT)
                    }
                };
                if should_finish || started_at.elapsed() >= WIDGET_DRAG_WATCH_TIMEOUT {
                    finish_widget_drag(&app, generation, moved);
                    return;
                }
            }
        })
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn expand(window: &tauri::WebviewWindow, state: &mut WidgetDockState) -> Result<(), String> {
    window
        .set_min_size(Some(LogicalSize::new(WIDGET_MIN_WIDTH, WIDGET_MIN_HEIGHT)))
        .map_err(|error| error.to_string())?;
    window
        .set_size(state.expanded_size)
        .map_err(|error| error.to_string())?;
    window
        .set_position(state.expanded_position)
        .map_err(|error| error.to_string())?;
    window
        .set_resizable(true)
        .map_err(|error| error.to_string())?;
    state.collapsed = false;
    state.outside_since = None;
    state.suppress_expand_until_pointer_exit = false;
    Ok(())
}

fn collapse(window: &tauri::WebviewWindow, state: &mut WidgetDockState) -> Result<(), String> {
    let edge = state
        .edge
        .ok_or_else(|| "widget dock edge is not configured".to_string())?;
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "widget monitor is not available".to_string())?;
    let scale = monitor.scale_factor();
    let collapsed_size = PhysicalSize::new(
        (WIDGET_DOCK_WIDTH * scale).round() as u32,
        (WIDGET_DOCK_HEIGHT * scale).round() as u32,
    );
    let work_area = monitor.work_area();
    let position = collapsed_position(
        edge,
        state.expanded_position,
        state.expanded_size,
        collapsed_size,
        work_area.position,
        work_area.size,
    );
    window
        .set_min_size(None::<LogicalSize<f64>>)
        .map_err(|error| error.to_string())?;
    window
        .set_resizable(false)
        .map_err(|error| error.to_string())?;
    window
        .set_size(collapsed_size)
        .map_err(|error| error.to_string())?;
    window
        .set_position(position)
        .map_err(|error| error.to_string())?;
    state.collapsed = true;
    state.outside_since = None;
    Ok(())
}

pub(crate) fn pointer_entered(app: &tauri::AppHandle) {
    let Ok(window) = window(app) else {
        return;
    };
    let dock = app.state::<WidgetDock>();
    let Ok(mut state) = dock.0.lock() else {
        return;
    };
    if !state.enabled || state.dragging || state.suppress_expand_until_pointer_exit {
        return;
    }
    state.outside_since = None;
    if state.collapsed {
        match expand(&window, &mut state) {
            Ok(()) => emit_state(&window, &state),
            Err(error) => log::warn!("failed to expand docked widget: {error}"),
        }
    }
}

pub(crate) fn pointer_exited(app: &tauri::AppHandle) {
    let marker = Instant::now();
    {
        let dock = app.state::<WidgetDock>();
        let Ok(mut state) = dock.0.lock() else {
            return;
        };
        if !state.enabled
            || state.collapsed
            || state.dragging
            || state.suppress_expand_until_pointer_exit
        {
            return;
        }
        state.outside_since = Some(marker);
    }

    let app = app.clone();
    let _ = thread::Builder::new()
        .name("widget-collapse-delay".to_string())
        .spawn(move || {
            thread::sleep(WIDGET_COLLAPSE_DELAY);
            if app.state::<AppLifecycle>().is_quitting() {
                return;
            }
            let Ok(window) = window(&app) else {
                return;
            };
            let (Ok(cursor), Ok(position), Ok(size)) = (
                app.cursor_position(),
                window.outer_position(),
                window.outer_size(),
            ) else {
                return;
            };
            let dock = app.state::<WidgetDock>();
            let Ok(mut state) = dock.0.lock() else {
                return;
            };
            if !state.enabled
                || state.collapsed
                || state.dragging
                || state.suppress_expand_until_pointer_exit
                || state.outside_since != Some(marker)
            {
                return;
            }
            if cursor_is_inside_window(cursor, position, size) {
                state.outside_since = None;
                return;
            }
            match collapse(&window, &mut state) {
                Ok(()) => emit_state(&window, &state),
                Err(error) => log::warn!("failed to collapse docked widget: {error}"),
            }
        });
}

pub(crate) fn start_hover_polling(app: tauri::AppHandle) {
    let _ = thread::Builder::new()
        .name("widget-hover-monitor".to_string())
        .spawn(move || {
            loop {
                thread::sleep(WIDGET_HOVER_POLL_INTERVAL);
                if app.state::<AppLifecycle>().is_quitting() {
                    break;
                }
                let Ok(window) = window(&app) else {
                    continue;
                };
                if !window.is_visible().unwrap_or(false) {
                    continue;
                }
                let should_monitor = app
                    .state::<WidgetDock>()
                    .0
                    .lock()
                    .map(|state| state.enabled && !state.dragging)
                    .unwrap_or(false);
                if !should_monitor {
                    continue;
                }
                let (Ok(cursor), Ok(position), Ok(size)) = (
                    app.cursor_position(),
                    window.outer_position(),
                    window.outer_size(),
                ) else {
                    continue;
                };
                let inside = cursor_is_inside_window(cursor, position, size);
                let dock = app.state::<WidgetDock>();
                let Ok(mut state) = dock.0.lock() else {
                    continue;
                };
                if !state.enabled || state.dragging {
                    continue;
                }
                if inside {
                    if state.suppress_expand_until_pointer_exit {
                        continue;
                    }
                    drop(state);
                    pointer_entered(&app);
                    continue;
                }
                if state.suppress_expand_until_pointer_exit {
                    state.suppress_expand_until_pointer_exit = false;
                    state.outside_since = None;
                    continue;
                }
                if state.collapsed {
                    state.outside_since = None;
                    continue;
                }
                let outside_since = state.outside_since.get_or_insert_with(Instant::now);
                if outside_since.elapsed() >= WIDGET_COLLAPSE_DELAY {
                    match collapse(&window, &mut state) {
                        Ok(()) => emit_state(&window, &state),
                        Err(error) => log::warn!("failed to collapse docked widget: {error}"),
                    }
                }
            }
        });
}

#[cfg(target_os = "macos")]
fn start_hover_monitor(app: tauri::AppHandle) {
    if let Err(error) = crate::macos_widget_tracking::install(&app) {
        log::warn!("failed to install native widget tracking: {error}");
    }

    // AppKit may keep an installed NSTrackingArea while its WebView stops
    // delivering enter/exit callbacks after a resize. Keep the inexpensive
    // bounds check alive as a health fallback so a docked widget never gets
    // stranded in its collapsed state.
    start_hover_polling(app);
}

#[cfg(not(target_os = "macos"))]
fn start_hover_monitor(app: tauri::AppHandle) {
    start_hover_polling(app);
}

pub(crate) fn restore_before_exit(app: &tauri::AppHandle) {
    let Ok(window) = window(app) else {
        return;
    };
    let dock = app.state::<WidgetDock>();
    let Ok(mut state) = dock.0.lock() else {
        return;
    };
    if state.dragging || !state.enabled {
        if let Ok(position) = window.outer_position() {
            state.expanded_position = position;
        }
        if let Ok(size) = window.outer_size() {
            state.expanded_size = size;
        }
    } else if state.collapsed
        && let Err(error) = expand(&window, &mut state)
    {
        log::warn!("failed to restore widget geometry before exit: {error}");
    }
    if let Err(error) = persist_expanded_geometry(app, &state) {
        log::warn!("failed to persist desktop widget geometry: {error}");
    }
}

#[tauri::command]
pub(crate) fn get_widget_dock_state(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let dock = app.state::<WidgetDock>();
    let state = dock
        .0
        .lock()
        .map_err(|_| "widget dock state lock is poisoned".to_string())?;
    Ok(state_value(&state))
}

#[tauri::command]
pub(crate) fn toggle_widget_dock(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let window = window(&app)?;
    let dock = app.state::<WidgetDock>();
    let mut state = dock
        .0
        .lock()
        .map_err(|_| "widget dock state lock is poisoned".to_string())?;
    state.dragging = false;
    state.drag_generation = state.drag_generation.wrapping_add(1);

    if state.enabled {
        if state.collapsed {
            expand(&window, &mut state)?;
        }
        state.enabled = false;
        state.edge = None;
        state.outside_since = None;
        state.suppress_expand_until_pointer_exit = false;
        persist_expanded_geometry(&app, &state)?;
        emit_state(&window, &state);
        return Ok(state_value(&state));
    }

    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "widget monitor is not available".to_string())?;
    let work_area = monitor.work_area();
    let current_position = window.outer_position().map_err(|error| error.to_string())?;
    let current_size = window.outer_size().map_err(|error| error.to_string())?;
    let edge = nearest_edge(
        current_position,
        current_size,
        work_area.position,
        work_area.size,
    );
    dock_to_edge(
        &app,
        &window,
        &mut state,
        edge,
        WidgetDockGeometry {
            current_position,
            current_size,
            work_position: work_area.position,
            work_size: work_area.size,
        },
    )?;
    Ok(state_value(&state))
}

#[tauri::command]
pub(crate) fn start_widget_dragging(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let window = window(&app)?;
    let start_position = window.outer_position().map_err(|error| error.to_string())?;
    let scale = window.scale_factor().map_err(|error| error.to_string())?;
    let dock = app.state::<WidgetDock>();
    let generation = {
        let mut state = dock
            .0
            .lock()
            .map_err(|_| "widget dock state lock is poisoned".to_string())?;
        if state.collapsed {
            expand(&window, &mut state)?;
            emit_state(&window, &state);
        }
        state.dragging = true;
        state.drag_generation = state.drag_generation.wrapping_add(1);
        state.outside_since = None;
        state.suppress_expand_until_pointer_exit = false;
        state.drag_generation
    };

    if let Err(error) = window.start_dragging() {
        if let Ok(mut state) = dock.0.lock()
            && state.drag_generation == generation
        {
            state.dragging = false;
        }
        return Err(error.to_string());
    }
    if let Err(error) = start_drag_monitor(app.clone(), generation, start_position, scale) {
        if let Ok(mut state) = dock.0.lock()
            && state.drag_generation == generation
        {
            state.dragging = false;
        }
        return Err(error);
    }
    let state = dock
        .0
        .lock()
        .map_err(|_| "widget dock state lock is poisoned".to_string())?;
    Ok(state_value(&state))
}

#[cfg(test)]
mod tests {
    use super::{
        WIDGET_AUTO_DOCK_DISTANCE, WidgetDockEdge, clamped_window_position, collapsed_position,
        cursor_is_inside_window, edge_within_distance, expanded_size_is_valid,
        movement_exceeds_distance, nearest_edge, point_edge_within_distance, rectangles_intersect,
        snapped_expanded_position,
    };
    use tauri::{PhysicalPosition, PhysicalSize};

    #[test]
    fn widget_uses_the_nearest_screen_edge() {
        let work_position = PhysicalPosition::new(0, 24);
        let work_size = PhysicalSize::new(1440, 876);
        let window_size = PhysicalSize::new(380, 520);
        assert_eq!(
            nearest_edge(
                PhysicalPosition::new(500, 40),
                window_size,
                work_position,
                work_size,
            ),
            WidgetDockEdge::Top
        );
        assert_eq!(
            nearest_edge(
                PhysicalPosition::new(1040, 220),
                window_size,
                work_position,
                work_size,
            ),
            WidgetDockEdge::Right
        );
        assert_eq!(
            nearest_edge(
                PhysicalPosition::new(20, 220),
                window_size,
                work_position,
                work_size,
            ),
            WidgetDockEdge::Left
        );
    }

    #[test]
    fn automatic_docking_only_activates_inside_the_edge_hot_zone() {
        let work_position = PhysicalPosition::new(0, 24);
        let work_size = PhysicalSize::new(1440, 876);
        let window_size = PhysicalSize::new(380, 520);
        let maximum_distance = WIDGET_AUTO_DOCK_DISTANCE as u32;

        assert_eq!(
            edge_within_distance(
                PhysicalPosition::new(1044, 220),
                window_size,
                work_position,
                work_size,
                maximum_distance,
            ),
            Some(WidgetDockEdge::Right)
        );
        assert_eq!(
            edge_within_distance(
                PhysicalPosition::new(1043, 220),
                window_size,
                work_position,
                work_size,
                maximum_distance,
            ),
            None
        );
        assert_eq!(
            edge_within_distance(
                PhysicalPosition::new(1042, 42),
                window_size,
                work_position,
                work_size,
                maximum_distance,
            ),
            None,
            "the default 18px floating margin should stay outside the snap zone",
        );
    }

    #[test]
    fn automatic_docking_activates_after_the_window_crosses_an_edge() {
        let work_position = PhysicalPosition::new(0, 24);
        let work_size = PhysicalSize::new(1440, 876);
        let window_size = PhysicalSize::new(380, 520);

        assert_eq!(
            edge_within_distance(
                PhysicalPosition::new(1100, 220),
                window_size,
                work_position,
                work_size,
                WIDGET_AUTO_DOCK_DISTANCE as u32,
            ),
            Some(WidgetDockEdge::Right),
        );
        assert_eq!(
            edge_within_distance(
                PhysicalPosition::new(-80, 220),
                window_size,
                work_position,
                work_size,
                WIDGET_AUTO_DOCK_DISTANCE as u32,
            ),
            Some(WidgetDockEdge::Left),
        );
    }

    #[test]
    fn automatic_docking_supports_negative_secondary_monitor_coordinates() {
        let work_position = PhysicalPosition::new(-1920, 24);
        let work_size = PhysicalSize::new(1920, 1056);
        let window_size = PhysicalSize::new(380, 520);

        assert_eq!(
            edge_within_distance(
                PhysicalPosition::new(-1908, 280),
                window_size,
                work_position,
                work_size,
                WIDGET_AUTO_DOCK_DISTANCE as u32,
            ),
            Some(WidgetDockEdge::Left)
        );
    }

    #[test]
    fn cursor_at_the_physical_screen_edge_activates_docking() {
        let monitor_position = PhysicalPosition::new(0, 0);
        let monitor_size = PhysicalSize::new(1440, 900);

        assert_eq!(
            point_edge_within_distance(
                PhysicalPosition::new(1439.0, 420.0),
                monitor_position,
                monitor_size,
                WIDGET_AUTO_DOCK_DISTANCE,
            ),
            Some(WidgetDockEdge::Right),
        );
        assert_eq!(
            point_edge_within_distance(
                PhysicalPosition::new(700.0, 0.0),
                monitor_position,
                monitor_size,
                WIDGET_AUTO_DOCK_DISTANCE,
            ),
            Some(WidgetDockEdge::Top),
        );
        assert_eq!(
            point_edge_within_distance(
                PhysicalPosition::new(700.0, 100.0),
                monitor_position,
                monitor_size,
                WIDGET_AUTO_DOCK_DISTANCE,
            ),
            None,
        );
    }

    #[test]
    fn a_header_click_is_not_treated_as_a_window_drag() {
        let start = PhysicalPosition::new(500, 220);
        assert!(!movement_exceeds_distance(
            start,
            PhysicalPosition::new(502, 221),
            3,
        ));
        assert!(movement_exceeds_distance(
            start,
            PhysicalPosition::new(503, 220),
            3,
        ));
    }

    #[test]
    fn dock_geometry_keeps_expanded_and_collapsed_windows_on_screen() {
        let work_position = PhysicalPosition::new(0, 24);
        let work_size = PhysicalSize::new(1440, 876);
        let expanded_size = PhysicalSize::new(380, 520);
        let expanded = snapped_expanded_position(
            WidgetDockEdge::Bottom,
            PhysicalPosition::new(1220, 760),
            expanded_size,
            work_position,
            work_size,
        );
        assert_eq!(expanded, PhysicalPosition::new(1060, 380));
        let collapsed = collapsed_position(
            WidgetDockEdge::Bottom,
            expanded,
            expanded_size,
            PhysicalSize::new(236, 46),
            work_position,
            work_size,
        );
        assert_eq!(collapsed, PhysicalPosition::new(1132, 854));
    }

    #[test]
    fn widget_cursor_hit_testing_uses_native_window_bounds() {
        let position = PhysicalPosition::new(100, 200);
        let size = PhysicalSize::new(236, 46);

        assert!(cursor_is_inside_window(
            PhysicalPosition::new(100.0, 200.0),
            position,
            size,
        ));
        assert!(cursor_is_inside_window(
            PhysicalPosition::new(335.9, 245.9),
            position,
            size,
        ));
        assert!(!cursor_is_inside_window(
            PhysicalPosition::new(336.0, 245.9),
            position,
            size,
        ));
        assert!(!cursor_is_inside_window(
            PhysicalPosition::new(99.9, 200.0),
            position,
            size,
        ));
    }

    #[test]
    fn compact_geometry_is_never_accepted_as_an_expanded_widget_size() {
        assert!(!expanded_size_is_valid(PhysicalSize::new(472, 92), 2.0));
        assert!(expanded_size_is_valid(PhysicalSize::new(760, 1040), 2.0));
    }

    #[test]
    fn persisted_widget_position_must_intersect_a_screen() {
        let screen_position = PhysicalPosition::new(0, 0);
        let screen_size = PhysicalSize::new(2880, 1800);
        assert!(rectangles_intersect(
            PhysicalPosition::new(2200, 100),
            PhysicalSize::new(760, 1040),
            screen_position,
            screen_size,
        ));
        assert!(!rectangles_intersect(
            PhysicalPosition::new(4000, 100),
            PhysicalSize::new(760, 1040),
            screen_position,
            screen_size,
        ));
    }

    #[test]
    fn restored_widget_position_is_clamped_fully_inside_the_work_area() {
        assert_eq!(
            clamped_window_position(
                PhysicalPosition::new(3180, 580),
                PhysicalSize::new(766, 1046),
                PhysicalPosition::new(0, 48),
                PhysicalSize::new(3840, 2062),
            ),
            PhysicalPosition::new(3074, 580),
        );
        assert_eq!(
            clamped_window_position(
                PhysicalPosition::new(-3550, -40),
                PhysicalSize::new(760, 1040),
                PhysicalPosition::new(-3456, 48),
                PhysicalSize::new(3456, 2138),
            ),
            PhysicalPosition::new(-3456, 48),
        );
    }
}
