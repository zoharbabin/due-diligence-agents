mod secrets;
mod sidecar;

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{AppHandle, Manager, RunEvent, State, WebviewWindow};

use sidecar::Sidecar;

#[derive(Default)]
struct AppState {
    sidecar: Mutex<Option<Sidecar>>,
}

#[tauri::command]
fn get_api_token(state: State<AppState>) -> Result<String, String> {
    let guard = state.sidecar.lock().map_err(|_| "state is poisoned")?;
    guard.as_ref().map(|s| s.token.clone()).ok_or_else(|| "The local service is not running.".into())
}

#[tauri::command]
fn save_provider_env(values: HashMap<String, String>) -> Result<(), String> {
    secrets::save(values)
}

/// Where the Python runtime and the built UI are. Development uses env overrides.
fn locations(app: &AppHandle) -> Result<(PathBuf, PathBuf), String> {
    if let Ok(python) = std::env::var("DD_DESKTOP_PYTHON") {
        let ui = std::env::var("DD_DESKTOP_UI").map_err(|_| "Set DD_DESKTOP_UI with DD_DESKTOP_PYTHON.")?;
        return Ok((python.into(), ui.into()));
    }
    let res = app.path().resource_dir().map_err(|e| e.to_string())?;
    let python = if cfg!(windows) { res.join("python").join("python.exe") } else { res.join("python").join("bin").join("python3") };
    Ok((python, res.join("ui")))
}

fn show_error(window: &WebviewWindow, message: &str) {
    let text = serde_json::to_string(message).unwrap_or_else(|_| "\"error\"".into());
    let _ = window.eval(format!("window.showError({text})"));
}

fn start_backend(app: AppHandle) {
    let Some(window) = app.get_webview_window("main") else { return };
    let started = locations(&app).and_then(|(python, ui)| Sidecar::start(&python, &ui, &secrets::load()));
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
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![get_api_token, save_provider_env])
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
