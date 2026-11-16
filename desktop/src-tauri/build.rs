fn main() {
    // Only these commands may be called from the UI. Each gets an `allow-...` permission.
    let manifest = tauri_build::AppManifest::new().commands(&["get_api_token", "save_provider_env"]);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(manifest)).expect("tauri build");
}
