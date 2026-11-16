mod secrets;
mod sidecar;

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;

use serde::Serialize;
use tauri::{AppHandle, Manager, RunEvent, State, WebviewWindow};
use tauri_plugin_updater::UpdaterExt;

use sidecar::Sidecar;

#[derive(Default)]
struct AppState {
    sidecar: Mutex<Option<Sidecar>>,
}

#[tauri::command]
fn get_api_token(state: State<AppState>) -> Result<String, String> {
    let guard = state.sidecar.lock().map_err(|_| "state is poisoned")?;
    guard
        .as_ref()
        .map(|s| s.token.clone())
        .ok_or_else(|| "The local service is not running.".into())
}

#[tauri::command]
fn save_provider_env(values: HashMap<String, String>) -> Result<(), String> {
    secrets::save(values)
}

#[derive(Serialize)]
struct UpdateInfo {
    version: String,
    notes: Option<String>,
}

/// Ask the update endpoint for a newer signed build. Read-only: nothing is downloaded.
#[tauri::command]
async fn check_for_update(app: AppHandle) -> Result<Option<UpdateInfo>, String> {
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?;
    Ok(update.map(|u| UpdateInfo {
        version: u.version,
        notes: u.body,
    }))
}

/// Download the update, stop the local service so no file in the app is in use, install, and restart.
/// The signature is checked against the public key in `tauri.conf.json` before anything is installed.
#[tauri::command]
async fn install_update(app: AppHandle) -> Result<(), String> {
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or("You already have the latest version.")?;
    let bytes = update
        .download(|_, _| {}, || {})
        .await
        .map_err(|e| e.to_string())?;
    if let Some(mut sidecar) = app.state::<AppState>().sidecar.lock().unwrap().take() {
        sidecar.stop();
    }
    update.install(bytes).map_err(|e| e.to_string())?;
    app.restart()
}

/// Where the Python runtime and the built UI are. Development uses env overrides.
fn locations(app: &AppHandle) -> Result<(PathBuf, PathBuf), String> {
    if let Ok(python) = std::env::var("DD_DESKTOP_PYTHON") {
        let ui = std::env::var("DD_DESKTOP_UI")
            .map_err(|_| "Set DD_DESKTOP_UI with DD_DESKTOP_PYTHON.")?;
        return Ok((python.into(), ui.into()));
    }
    let res = app.path().resource_dir().map_err(|e| e.to_string())?;
    let python = if cfg!(windows) {
        res.join("python").join("python.exe")
    } else {
        res.join("python").join("bin").join("python3")
    };
    Ok((python, res.join("ui")))
}

fn show_error(window: &WebviewWindow, message: &str) {
    let text = serde_json::to_string(message).unwrap_or_else(|_| "\"error\"".into());
    let _ = window.eval(format!("window.showError({text})"));
}

fn start_backend(app: AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let log = app
        .path()
        .app_log_dir()
        .ok()
        .map(|dir| dir.join("service.log"));
    let started = locations(&app)
        .and_then(|(python, ui)| Sidecar::start(&python, &ui, &secrets::load(), log.as_deref()));
    match started {
        Ok(sidecar) => {
            let url = sidecar.url();
            *app.state::<AppState>().sidecar.lock().unwrap() = Some(sidecar);
            match url.parse() {
                Ok(parsed) => {
                    let _ = window.navigate(parsed);
                }
                Err(e) => show_error(&window, &format!("Bad service address: {e}")),
            }
        }
        Err(message) => show_error(&window, &message),
    }
}

pub fn run() {
    let app = tauri::Builder::default()
        // Registered first. A second launch shows the open window instead of starting a second service.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            get_api_token,
            save_provider_env,
            check_for_update,
            install_update
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || start_backend(handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut sidecar) = handle.state::<AppState>().sidecar.lock().unwrap().take() {
                sidecar.stop();
            }
        }
    });
}
