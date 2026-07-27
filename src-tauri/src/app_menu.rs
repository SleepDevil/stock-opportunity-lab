use tauri::Emitter;
use tauri::menu::{MenuBuilder, SubmenuBuilder};

const CHECK_FOR_UPDATES_MENU_ID: &str = "check-for-updates";
pub(crate) const CHECK_FOR_UPDATES_EVENT: &str = "app-check-for-updates";

pub(crate) fn build(app: &tauri::App) -> tauri::Result<()> {
    let app_menu = SubmenuBuilder::new(app, "Stock Opportunity Lab")
        .about(None)
        .separator()
        .text(CHECK_FOR_UPDATES_MENU_ID, "Check for Updates…")
        .separator()
        .services()
        .separator()
        .hide()
        .hide_others()
        .show_all()
        .separator()
        .quit()
        .build()?;

    let edit_menu = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all()
        .build()?;

    let window_menu = SubmenuBuilder::new(app, "Window")
        .minimize()
        .fullscreen()
        .separator()
        .bring_all_to_front()
        .build()?;

    let menu = MenuBuilder::new(app)
        .item(&app_menu)
        .item(&edit_menu)
        .item(&window_menu)
        .build()?;
    app.set_menu(menu)?;

    app.on_menu_event(|app, event| {
        if event.id().as_ref() != CHECK_FOR_UPDATES_MENU_ID {
            return;
        }

        if let Err(error) = crate::windows::focus_main_window(app, None) {
            log::warn!("failed to focus main window before checking for updates: {error}");
        }
        if let Err(error) = app.emit_to("main", CHECK_FOR_UPDATES_EVENT, ()) {
            log::error!("failed to request an update check from the app menu: {error}");
        }
    });

    Ok(())
}
