use std::fs;
use std::sync::Mutex;

use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};

const DESKTOP_API_HOST: &str = "127.0.0.1";
const DESKTOP_API_PORT: u16 = 8765;

struct BackendProcess(Mutex<Option<CommandChild>>);

pub(crate) fn initialize(app: &tauri::App) {
    app.manage(BackendProcess(Mutex::new(None)));
}

pub(crate) fn spawn(app: &tauri::AppHandle) -> Result<(), String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("cannot resolve desktop data directory: {error}"))?;
    fs::create_dir_all(&data_dir)
        .map_err(|error| format!("cannot create desktop data directory: {error}"))?;

    let command = app
        .shell()
        .sidecar("stock-lab-api")
        .map_err(|error| format!("cannot create desktop API sidecar command: {error}"))?
        .env("STOCK_LAB_DATA_DIR", &data_dir)
        .env("STOCK_LAB_DATABASE_URL", "")
        .env("STOCK_LAB_DESKTOP_API_HOST", DESKTOP_API_HOST)
        .env("STOCK_LAB_DESKTOP_API_PORT", DESKTOP_API_PORT.to_string());

    let (mut events, child) = command
        .spawn()
        .map_err(|error| format!("cannot start desktop API sidecar: {error}"))?;

    let process = app.state::<BackendProcess>();
    *process
        .0
        .lock()
        .map_err(|_| "desktop API process lock is poisoned".to_string())? = Some(child);

    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    log::debug!("desktop API: {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    log::warn!("desktop API: {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Error(error) => log::error!("desktop API process error: {error}"),
                CommandEvent::Terminated(status) => {
                    log::info!("desktop API process terminated: {status:?}");
                }
                _ => {}
            }
        }
    });

    Ok(())
}

pub(crate) fn stop(app: &tauri::AppHandle) {
    let process = app.state::<BackendProcess>();
    let Ok(mut process) = process.0.lock() else {
        log::error!("desktop API process lock is poisoned during shutdown");
        return;
    };
    if let Some(mut child) = process.take()
        && let Err(error) = child.write(b"shutdown\n")
    {
        log::warn!("failed to request desktop API shutdown: {error}");
        if let Err(kill_error) = child.kill() {
            log::warn!("failed to stop desktop API sidecar: {kill_error}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{DESKTOP_API_HOST, DESKTOP_API_PORT};

    #[test]
    fn desktop_api_binding_is_loopback_only() {
        assert_eq!(DESKTOP_API_HOST, "127.0.0.1");
        assert_eq!(DESKTOP_API_PORT, 8765);
    }
}
