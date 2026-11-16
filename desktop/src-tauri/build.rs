use std::{env, fs, path::Path};

/// The bundle resources are built by `desktop/scripts/build_runtime.py` and the UI build.
/// Debug builds (`cargo test`, `cargo clippy`) do not need them, so create empty stand-ins.
/// A release build never does this: missing resources fail the build.
fn debug_placeholders() {
    if env::var("PROFILE").as_deref() != Ok("debug") {
        return;
    }
    for dir in ["resources/python", "../ui/dist"] {
        fs::create_dir_all(dir).expect("create placeholder dir");
    }
    let packages = Path::new("resources/runtime-packages.txt");
    if !packages.exists() {
        fs::write(packages, "").expect("create placeholder file");
    }
}

fn main() {
    debug_placeholders();
    // Only these commands may be called from the UI. Each gets an `allow-...` permission.
    let manifest = tauri_build::AppManifest::new().commands(&[
        "get_api_token",
        "save_provider_env",
        "check_for_update",
        "install_update",
    ]);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(manifest))
        .expect("tauri build");
}
