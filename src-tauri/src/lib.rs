mod app_menu;
mod backend;
mod lifecycle;
#[cfg(target_os = "macos")]
mod macos_widget_tracking;
mod tray;
mod widget;
mod windows;

use tauri::{Manager, RunEvent, WindowEvent};

use lifecycle::AppLifecycle;
use widget::{get_widget_dock_state, start_widget_dragging, toggle_widget_dock};
use windows::{
    hide_widget_window, show_main_window, show_widget_window, toggle_widget_always_on_top,
};

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Err(error) = windows::focus_main_window(app, None) {
                log::error!("failed to focus the existing main window: {error}");
            }
        }))
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_denylist(&["widget"])
                .build(),
        )
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            show_main_window,
            hide_widget_window,
            show_widget_window,
            toggle_widget_always_on_top,
            get_widget_dock_state,
            toggle_widget_dock,
            start_widget_dragging
        ])
        .setup(|app| {
            app.manage(AppLifecycle::default());
            backend::initialize(app);
            windows::normalize_restored_widget_size(app.handle());
            windows::position_widget(app.handle());
            widget::initialize(app);
            app_menu::build(app)?;
            tray::build(app)?;
            if let Some(main) = app.get_webview_window("main") {
                let _ = main.set_focus();
            }
            if !cfg!(debug_assertions) {
                backend::spawn(app.handle()).map_err(std::io::Error::other)?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Stock Opportunity Lab desktop client");

    app.run(|app, event| match event {
        RunEvent::WindowEvent {
            label,
            event: WindowEvent::CloseRequested { api, .. },
            ..
        } if !app.state::<AppLifecycle>().is_quitting() => {
            api.prevent_close();
            if let Some(window) = app.get_webview_window(&label)
                && let Err(error) = window.hide()
            {
                log::warn!("failed to hide window {label}: {error}");
            }
        }
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => {
            if let Err(error) = windows::focus_main_window(app, None) {
                log::error!("failed to reopen main window: {error}");
            }
        }
        RunEvent::ExitRequested { .. } => widget::restore_before_exit(app),
        RunEvent::Exit => backend::stop(app),
        _ => {}
    });
}
