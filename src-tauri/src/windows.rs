use tauri::{LogicalSize, Manager, PhysicalPosition};

use crate::widget::{WIDGET_MIN_HEIGHT, WIDGET_MIN_WIDTH};

fn valid_app_route(route: &str) -> bool {
    route.starts_with('/') && !route.starts_with("//") && !route.contains("://")
}

pub(crate) fn focus_main_window(app: &tauri::AppHandle, route: Option<&str>) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window is not available".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.unminimize().map_err(|error| error.to_string())?;
    if let Some(route) = route.filter(|route| valid_app_route(route)) {
        let route = serde_json::to_string(route).map_err(|error| error.to_string())?;
        window
            .eval(format!("window.location.assign({route});"))
            .map_err(|error| error.to_string())?;
    }
    window.set_focus().map_err(|error| error.to_string())
}

pub(crate) fn toggle_widget_window(app: &tauri::AppHandle) -> Result<bool, String> {
    let window = app
        .get_webview_window("widget")
        .ok_or_else(|| "widget window is not available".to_string())?;
    let visible = window.is_visible().map_err(|error| error.to_string())?;
    if visible {
        window.hide().map_err(|error| error.to_string())?;
        Ok(false)
    } else {
        reveal_widget_window(app)?;
        Ok(true)
    }
}

fn reveal_widget_window(app: &tauri::AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("widget")
        .ok_or_else(|| "widget window is not available".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())
}

pub(crate) fn position_widget(app: &tauri::AppHandle) {
    let Some(window) = app.get_webview_window("widget") else {
        return;
    };
    let Ok(Some(monitor)) = window.current_monitor() else {
        return;
    };
    let Ok(window_size) = window.outer_size() else {
        return;
    };
    let work_area = monitor.work_area();
    let margin = (18.0 * monitor.scale_factor()).round() as i32;
    let x = work_area.position.x + work_area.size.width as i32 - window_size.width as i32 - margin;
    let y = work_area.position.y + margin;
    if let Err(error) = window.set_position(PhysicalPosition::new(x, y)) {
        log::warn!("failed to position desktop widget: {error}");
    }
}

pub(crate) fn normalize_restored_widget_size(app: &tauri::AppHandle) {
    let Some(window) = app.get_webview_window("widget") else {
        return;
    };
    let Ok(size) = window.outer_size() else {
        return;
    };
    let Ok(scale) = window.scale_factor() else {
        return;
    };
    let minimum_width = (WIDGET_MIN_WIDTH * scale).round() as u32;
    let minimum_height = (WIDGET_MIN_HEIGHT * scale).round() as u32;
    if size.width >= minimum_width && size.height >= minimum_height {
        return;
    }
    if let Err(error) = window.set_size(LogicalSize::new(380.0, 520.0)) {
        log::warn!("failed to restore desktop widget size: {error}");
    }
}

#[tauri::command]
pub(crate) fn show_main_window(app: tauri::AppHandle, route: Option<String>) -> Result<(), String> {
    focus_main_window(&app, route.as_deref())
}

#[tauri::command]
pub(crate) fn hide_widget_window(app: tauri::AppHandle) -> Result<(), String> {
    app.get_webview_window("widget")
        .ok_or_else(|| "widget window is not available".to_string())?
        .hide()
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) fn show_widget_window(app: tauri::AppHandle) -> Result<(), String> {
    reveal_widget_window(&app)
}

#[tauri::command]
pub(crate) fn toggle_widget_always_on_top(app: tauri::AppHandle) -> Result<bool, String> {
    let window = app
        .get_webview_window("widget")
        .ok_or_else(|| "widget window is not available".to_string())?;
    let next = !window
        .is_always_on_top()
        .map_err(|error| error.to_string())?;
    window
        .set_always_on_top(next)
        .map_err(|error| error.to_string())?;
    Ok(next)
}

#[cfg(test)]
mod tests {
    use super::valid_app_route;

    #[test]
    fn desktop_navigation_accepts_only_local_routes() {
        assert!(valid_app_route("/"));
        assert!(valid_app_route("/?inspect=603678"));
        assert!(!valid_app_route("//example.com"));
        assert!(!valid_app_route("https://example.com"));
    }
}
