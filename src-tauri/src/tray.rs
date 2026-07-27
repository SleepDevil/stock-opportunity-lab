use tauri::Manager;
use tauri::menu::MenuBuilder;
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};

use crate::lifecycle::AppLifecycle;
use crate::{widget, windows};

pub(crate) fn build(app: &tauri::App) -> tauri::Result<()> {
    let menu = MenuBuilder::new(app)
        .text("open-main", "打开主界面")
        .text("toggle-widget", "显示 / 隐藏悬浮窗")
        .separator()
        .text("quit", "退出 Stock Opportunity Lab")
        .build()?;

    let mut tray = TrayIconBuilder::with_id("stock-opportunity-lab")
        .menu(&menu)
        .tooltip("Stock Opportunity Lab")
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open-main" => {
                if let Err(error) = windows::focus_main_window(app, None) {
                    log::error!("failed to open main window from tray: {error}");
                }
            }
            "toggle-widget" => {
                if let Err(error) = windows::toggle_widget_window(app) {
                    log::error!("failed to toggle widget from tray: {error}");
                }
            }
            "quit" => {
                app.state::<AppLifecycle>().begin_quit();
                widget::restore_before_exit(app);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if matches!(
                event,
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                }
            ) && let Err(error) = windows::toggle_widget_window(tray.app_handle())
            {
                log::error!("failed to toggle widget from tray icon: {error}");
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}
