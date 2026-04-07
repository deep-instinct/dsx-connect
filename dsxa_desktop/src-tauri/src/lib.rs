use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use reqwest::header::{HeaderMap, HeaderValue, CONTENT_TYPE};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tauri::{Emitter, Manager, State};
use tokio_util::io::ReaderStream;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use uuid::Uuid;
use walkdir::WalkDir;

#[derive(Default)]
struct RuntimeState {
    jobs: Arc<Mutex<HashMap<String, Arc<AtomicBool>>>>,
    context_menu_ids: Arc<Mutex<HashMap<String, String>>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ContextConfig {
    base_url: String,
    auth_token: String,
    protected_entity: i64,
    custom_metadata: String,
    #[serde(default)]
    verify_tls: bool,
    #[serde(default)]
    base64_mode: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SavedState {
    selected_context: String,
    contexts: HashMap<String, ContextConfig>,
    #[serde(default)]
    settings: AppSettings,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct AppSettings {
    #[serde(default = "default_max_file_size_mb")]
    max_file_size_mb: u64,
    #[serde(default)]
    connection_panel_collapsed: bool,
}

fn default_max_file_size_mb() -> u64 {
    2048
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            max_file_size_mb: default_max_file_size_mb(),
            connection_panel_collapsed: true,
        }
    }
}

impl Default for SavedState {
    fn default() -> Self {
        let mut contexts = HashMap::new();
        contexts.insert(
            "default".to_string(),
            ContextConfig {
                base_url: "http://127.0.0.1:5000".to_string(),
                auth_token: String::new(),
                protected_entity: 1,
                custom_metadata: String::new(),
                verify_tls: false,
                base64_mode: false,
            },
        );
        Self {
            selected_context: "default".to_string(),
            contexts,
            settings: AppSettings::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ScanFileRequest {
    context: ContextConfig,
    file_path: String,
    password: Option<String>,
    metadata: Option<String>,
    max_file_size_bytes: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ScanHashRequest {
    context: ContextConfig,
    file_hash: String,
    metadata: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ConnectivityRequest {
    context: ContextConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ScanEicarRequest {
    context: ContextConfig,
}

#[derive(Debug, Clone, Serialize)]
struct ConnectivityResponse {
    reachable: bool,
    status: Option<u16>,
    reason: String,
    detail: String,
}

#[derive(Debug, Clone, Serialize)]
struct FolderCountPreviewResponse {
    count: usize,
    truncated: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ScanFolderRequest {
    context: ContextConfig,
    folder_path: String,
    concurrency: Option<usize>,
    password: Option<String>,
    metadata: Option<String>,
    pattern: Option<String>,
    #[serde(default)]
    log_all_results: bool,
    log_all_results_path: Option<String>,
    #[serde(default)]
    log_malicious_csv: bool,
    log_malicious_csv_path: Option<String>,
    #[serde(default)]
    quarantine_enabled: bool,
    quarantine_dir: Option<String>,
    max_file_size_bytes: Option<u64>,
}

#[derive(Debug, Clone, Serialize)]
struct FolderStartResponse {
    job_id: String,
}

#[derive(Debug, Clone, Serialize)]
struct FolderProgressEvent {
    job_id: String,
    #[serde(rename = "type")]
    event_type: String,
    total: usize,
    scanned: usize,
    ok: usize,
    failed: usize,
    stats: Option<Value>,
    summary: Option<Value>,
    failures: Option<Vec<Value>>,
    error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SyncContextMenuRequest {
    names: Vec<String>,
    selected: String,
}

fn install_app_menu<R: tauri::Runtime>(
    app: &tauri::AppHandle<R>,
    context_names: &[String],
    selected_context: &str,
    context_menu_ids: &Arc<Mutex<HashMap<String, String>>>,
) -> tauri::Result<()> {
    use tauri::menu::{IsMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};

    let settings = MenuItem::with_id(app, "settings", "Settings...", true, None::<&str>)?;
    let file_menu = Submenu::with_items(app, "File", true, &[&settings])?;

    let context_new = MenuItem::with_id(app, "ctx-new-context", "New Profile...", true, None::<&str>)?;
    let context_delete = MenuItem::with_id(app, "ctx-delete-context", "Delete Profile(s)...", true, None::<&str>)?;
    let context_save = MenuItem::with_id(app, "ctx-save-context", "Save Current Profile", true, None::<&str>)?;

    let mut select_items = Vec::new();
    let mut select_item_map: HashMap<String, String> = HashMap::new();
    if context_names.is_empty() {
        select_items.push(MenuItem::with_id(
            app,
            "ctx-select-empty",
            "No profiles",
            false,
            None::<&str>,
        )?);
    } else {
        for (idx, name) in context_names.iter().enumerate() {
            let id = format!("ctx-select-item-{idx}");
            let title = if name == selected_context {
                format!("✓ {name}")
            } else {
                name.clone()
            };
            select_items.push(MenuItem::with_id(app, &id, title, true, None::<&str>)?);
            select_item_map.insert(id, name.clone());
        }
    }
    let select_item_refs: Vec<&dyn IsMenuItem<R>> = select_items.iter().map(|item| item as &dyn IsMenuItem<R>).collect();
    let select_context_submenu = Submenu::with_items(app, "Select Profile", true, &select_item_refs)?;
    let contexts_menu = Submenu::with_items(
        app,
        "Connection",
        true,
        &[&context_new, &select_context_submenu, &context_delete, &context_save],
    )?;

    let undo = PredefinedMenuItem::undo(app, None)?;
    let redo = PredefinedMenuItem::redo(app, None)?;
    let cut = PredefinedMenuItem::cut(app, None)?;
    let copy = PredefinedMenuItem::copy(app, None)?;
    let paste = PredefinedMenuItem::paste(app, None)?;
    let select_all = PredefinedMenuItem::select_all(app, None)?;
    let edit_menu = Submenu::with_items(app, "Edit", true, &[&undo, &redo, &cut, &copy, &paste, &select_all])?;

    let fullscreen = PredefinedMenuItem::fullscreen(app, None)?;
    let view_menu = Submenu::with_items(app, "View", true, &[&fullscreen])?;

    let minimize = PredefinedMenuItem::minimize(app, None)?;
    let maximize = PredefinedMenuItem::maximize(app, None)?;
    let close_window = PredefinedMenuItem::close_window(app, None)?;
    let window_menu = Submenu::with_items(app, "Window", true, &[&minimize, &maximize, &close_window])?;

    let about_item = MenuItem::with_id(app, "about", "About DSXA Desktop", true, None::<&str>)?;
    let help_item = MenuItem::with_id(app, "help", "DSXA Desktop and SDK", true, None::<&str>)?;
    let help_menu = Submenu::with_items(app, "Help", true, &[&about_item, &help_item])?;

    let menu = Menu::with_items(app, &[&file_menu, &contexts_menu, &edit_menu, &view_menu, &window_menu, &help_menu])?;
    app.set_menu(menu)?;
    if let Ok(mut ids) = context_menu_ids.lock() {
        *ids = select_item_map;
    }
    Ok(())
}

fn state_file(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("failed to resolve app config dir: {e}"))?;
    Ok(dir.join("contexts.json"))
}

async fn read_state(app: &tauri::AppHandle) -> Result<SavedState, String> {
    let path = state_file(app)?;
    match tokio::fs::read_to_string(path).await {
        Ok(raw) => serde_json::from_str::<SavedState>(&raw).map_err(|e| format!("invalid state json: {e}")),
        Err(_) => Ok(SavedState::default()),
    }
}

async fn write_state(app: &tauri::AppHandle, state: &SavedState) -> Result<(), String> {
    let path = state_file(app)?;
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|e| format!("failed to create state directory: {e}"))?;
    }
    let body = serde_json::to_string_pretty(state).map_err(|e| format!("failed to serialize state: {e}"))?;
    tokio::fs::write(path, body)
        .await
        .map_err(|e| format!("failed to write state file: {e}"))
}

fn base64_encode(input: &str) -> String {
    base64_encode_bytes(input.as_bytes())
}

fn base64_encode_bytes(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::new();
    let mut i = 0;
    while i < bytes.len() {
        let b0 = bytes[i] as u32;
        let b1 = if i + 1 < bytes.len() { bytes[i + 1] as u32 } else { 0 };
        let b2 = if i + 2 < bytes.len() { bytes[i + 2] as u32 } else { 0 };

        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(TABLE[((n >> 18) & 0x3f) as usize] as char);
        out.push(TABLE[((n >> 12) & 0x3f) as usize] as char);
        if i + 1 < bytes.len() {
            out.push(TABLE[((n >> 6) & 0x3f) as usize] as char);
        } else {
            out.push('=');
        }
        if i + 2 < bytes.len() {
            out.push(TABLE[(n & 0x3f) as usize] as char);
        } else {
            out.push('=');
        }

        i += 3;
    }
    out
}

fn build_http_client(ctx: &ContextConfig) -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .danger_accept_invalid_certs(!ctx.verify_tls)
        .build()
        .map_err(|e| format!("failed to build HTTP client: {e}"))
}

fn effective_max_file_size_bytes(value: Option<u64>) -> u64 {
    value.unwrap_or(2_u64 * 1024 * 1024 * 1024)
}

fn sha256_file(path: &std::path::Path) -> Result<String, String> {
    let mut file = std::fs::File::open(path)
        .map_err(|e| format!("failed to open file for hashing: {e}"))?;
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 64 * 1024];
    loop {
        let n = std::io::Read::read(&mut file, &mut buf)
            .map_err(|e| format!("failed to hash file: {e}"))?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    let digest = hasher.finalize();
    let mut out = String::with_capacity(digest.len() * 2);
    for b in digest {
        out.push_str(&format!("{:02x}", b));
    }
    Ok(out)
}

fn is_malicious_verdict(result: &Value) -> bool {
    result
        .get("verdict")
        .and_then(|v| v.as_str())
        .map(|v| v.eq_ignore_ascii_case("malicious"))
        .unwrap_or(false)
}

fn verdict_value(result: &Value) -> Option<&str> {
    result.get("verdict").and_then(|v| v.as_str())
}

fn verdict_reason_value(result: &Value) -> Option<&str> {
    result
        .get("verdict_details")
        .and_then(|v| v.get("reason"))
        .and_then(|v| v.as_str())
}

fn classify_verdict_counters(result: &Value) -> (&'static str, usize) {
    let verdict = verdict_value(result).unwrap_or("").to_ascii_lowercase();
    if verdict == "benign" {
        return ("benign", 1);
    }
    if verdict == "malicious" {
        return ("malicious", 1);
    }
    if verdict == "not scanned" {
        let reason = verdict_reason_value(result).unwrap_or("").to_ascii_lowercase();
        if reason == "encrypted file" {
            return ("encrypted", 1);
        }
        return ("other", 1);
    }
    if verdict == "non-compliant" || verdict == "non compliant" {
        return ("other", 1);
    }
    if verdict == "encrypted" {
        return ("encrypted", 1);
    }
    if verdict.is_empty() {
        return ("other", 1);
    }
    ("other", 1)
}

fn csv_escape(s: &str) -> String {
    let escaped = s.replace('"', "\"\"");
    format!("\"{}\"", escaped)
}

async fn move_to_quarantine(src: &str, quarantine_dir: &str) -> Result<String, String> {
    let src_path = std::path::PathBuf::from(src);
    let file_name = src_path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .ok_or_else(|| "invalid source file name".to_string())?;

    let dest_dir = std::path::PathBuf::from(quarantine_dir);
    tokio::fs::create_dir_all(&dest_dir)
        .await
        .map_err(|e| format!("failed to create quarantine dir: {e}"))?;
    let dest_path = dest_dir.join(file_name);

    match tokio::fs::rename(&src_path, &dest_path).await {
        Ok(_) => Ok(dest_path.to_string_lossy().to_string()),
        Err(_) => {
            tokio::fs::copy(&src_path, &dest_path)
                .await
                .map_err(|e| format!("failed to copy to quarantine: {e}"))?;
            tokio::fs::remove_file(&src_path)
                .await
                .map_err(|e| format!("failed to remove original after copy: {e}"))?;
            Ok(dest_path.to_string_lossy().to_string())
        }
    }
}

fn build_headers(ctx: &ContextConfig, metadata: Option<&str>, password: Option<&str>, json_body: bool) -> Result<HeaderMap, String> {
    let mut headers = HeaderMap::new();
    let content_type = if json_body {
        "application/json"
    } else {
        "application/octet-stream"
    };
    headers.insert(
        CONTENT_TYPE,
        HeaderValue::from_str(content_type).map_err(|e| format!("invalid content-type header: {e}"))?,
    );

    headers.insert(
        "protected_entity",
        HeaderValue::from_str(&ctx.protected_entity.to_string()).map_err(|e| format!("invalid protected_entity header: {e}"))?,
    );

    let md = metadata.unwrap_or(&ctx.custom_metadata);
    if !md.is_empty() {
        headers.insert(
            "X-Custom-Metadata",
            HeaderValue::from_str(md).map_err(|e| format!("invalid X-Custom-Metadata header: {e}"))?,
        );
    }

    if let Some(pass) = password {
        if !pass.is_empty() {
            let encoded = base64_encode(pass);
            headers.insert(
                "scan_password",
                HeaderValue::from_str(&encoded).map_err(|e| format!("invalid scan_password header: {e}"))?,
            );
        }
    }

    if !ctx.auth_token.is_empty() {
        let hv = HeaderValue::from_str(&ctx.auth_token).map_err(|e| format!("invalid auth token header: {e}"))?;
        headers.insert("AUTH", hv.clone());
        headers.insert("AUTH_TOKEN", hv);
    }

    Ok(headers)
}

fn resolve_metadata_template(
    template: &str,
    file_path: Option<&std::path::Path>,
    file_hash: Option<&str>,
) -> String {
    let mut resolved = template.to_string();

    if let Some(path) = file_path {
        let full_path = path.to_string_lossy().to_string();
        let base_name = path
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();
        resolved = resolved.replace("{file_name}", &full_path);
        resolved = resolved.replace("{file_path}", &full_path);
        resolved = resolved.replace("{base_name}", &base_name);
        resolved = resolved.replace("{file_basename}", &base_name);
    }

    if let Some(hash) = file_hash {
        resolved = resolved.replace("{file_hash}", hash);
        resolved = resolved.replace("{hash}", hash);
    }

    resolved
}

fn resolve_effective_metadata(
    ctx: &ContextConfig,
    override_template: Option<&str>,
    file_path: Option<&std::path::Path>,
    file_hash: Option<&str>,
    default_to_file_name: bool,
) -> Option<String> {
    let template = if let Some(override_value) = override_template {
        let trimmed = override_value.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    } else {
        let trimmed = ctx.custom_metadata.trim();
        if trimmed.is_empty() {
            if default_to_file_name {
                Some("{file_name}".to_string())
            } else {
                None
            }
        } else {
            Some(trimmed.to_string())
        }
    }?;

    let resolved = resolve_metadata_template(&template, file_path, file_hash);
    if resolved.trim().is_empty() {
        None
    } else {
        Some(resolved)
    }
}

async fn request_json(
    client: &reqwest::Client,
    method: reqwest::Method,
    url: String,
    headers: HeaderMap,
    body: Option<Vec<u8>>,
) -> Result<Value, String> {
    let mut req = client.request(method, &url).headers(headers);
    if let Some(payload) = body {
        req = req.body(payload);
    }

    let response = req
        .send()
        .await
        .map_err(|e| format!("request failed: {e}"))?;

    let status = response.status();
    let text = response
        .text()
        .await
        .map_err(|e| format!("failed to read response body: {e}"))?;

    let body: Value = serde_json::from_str(&text).unwrap_or_else(|_| json!({ "raw": text }));

    if !status.is_success() {
        return Err(format!("HTTP {} {}", status.as_u16(), body));
    }

    Ok(body)
}

async fn request_json_stream(
    client: &reqwest::Client,
    method: reqwest::Method,
    url: String,
    headers: HeaderMap,
    body: reqwest::Body,
) -> Result<Value, String> {
    let response = client
        .request(method, &url)
        .headers(headers)
        .body(body)
        .send()
        .await
        .map_err(|e| format!("request failed: {e}"))?;

    let status = response.status();
    let text = response
        .text()
        .await
        .map_err(|e| format!("failed to read response body: {e}"))?;

    let body: Value = serde_json::from_str(&text).unwrap_or_else(|_| json!({ "raw": text }));

    if !status.is_success() {
        return Err(format!("HTTP {} {}", status.as_u16(), body));
    }

    Ok(body)
}

#[tauri::command]
async fn get_state(app: tauri::AppHandle) -> Result<SavedState, String> {
    read_state(&app).await
}

#[tauri::command]
async fn save_state(app: tauri::AppHandle, state: SavedState) -> Result<(), String> {
    write_state(&app, &state).await
}

#[tauri::command]
async fn sync_context_menu(
    app: tauri::AppHandle,
    runtime: State<'_, RuntimeState>,
    req: SyncContextMenuRequest,
) -> Result<(), String> {
    let mut names = req.names.clone();
    names.sort();
    install_app_menu(&app, &names, &req.selected, &runtime.context_menu_ids)
        .map_err(|e| format!("failed to update app menu: {e}"))
}

#[tauri::command]
async fn scan_file(req: ScanFileRequest) -> Result<Value, String> {
    let started = Instant::now();
    let max_size = effective_max_file_size_bytes(req.max_file_size_bytes);
    let meta = tokio::fs::metadata(&req.file_path)
        .await
        .map_err(|e| format!("failed to stat file: {e}"))?;
    if meta.len() > max_size {
        return Err(format!(
            "File exceeds max file size ({} bytes > {} bytes). Use scan by path for large files.",
            meta.len(),
            max_size
        ));
    }
    let base = req.context.base_url.trim_end_matches('/');
    let endpoint = if req.context.base64_mode {
        "/scan/base64/v2"
    } else {
        "/scan/binary/v2"
    };
    let url = format!("{base}{endpoint}");
    let metadata = resolve_effective_metadata(
        &req.context,
        req.metadata.as_deref(),
        Some(std::path::Path::new(&req.file_path)),
        None,
        true,
    );
    let headers = build_headers(
        &req.context,
        metadata.as_deref(),
        req.password.as_deref(),
        false,
    )?;

    let client = build_http_client(&req.context)?;
    let result = if req.context.base64_mode {
        let raw_data = tokio::fs::read(&req.file_path)
            .await
            .map_err(|e| format!("failed to read file: {e}"))?;
        let payload = base64_encode_bytes(&raw_data).into_bytes();
        request_json(&client, reqwest::Method::POST, url, headers, Some(payload)).await?
    } else {
        let file = tokio::fs::File::open(&req.file_path)
            .await
            .map_err(|e| format!("failed to open file: {e}"))?;
        let body = reqwest::Body::wrap_stream(ReaderStream::new(file));
        request_json_stream(&client, reqwest::Method::POST, url, headers, body).await?
    };

    Ok(json!({
        "operation": "scan-file",
        "file": req.file_path,
        "elapsed_seconds": started.elapsed().as_secs_f64(),
        "result": result
    }))
}

#[tauri::command]
async fn scan_hash(req: ScanHashRequest) -> Result<Value, String> {
    let started = Instant::now();
    let base = req.context.base_url.trim_end_matches('/');
    let url = format!("{base}/scan/by_hash");
    let metadata = resolve_effective_metadata(
        &req.context,
        req.metadata.as_deref(),
        None,
        Some(&req.file_hash),
        false,
    );
    let headers = build_headers(&req.context, metadata.as_deref(), None, true)?;
    let body = serde_json::to_vec(&json!({ "hash": req.file_hash }))
        .map_err(|e| format!("failed to encode request body: {e}"))?;

    let client = build_http_client(&req.context)?;
    let result = request_json(&client, reqwest::Method::POST, url, headers, Some(body)).await?;

    Ok(json!({
        "operation": "scan-hash",
        "hash": req.file_hash,
        "elapsed_seconds": started.elapsed().as_secs_f64(),
        "result": result
    }))
}

#[tauri::command]
async fn scan_eicar_test(req: ScanEicarRequest) -> Result<Value, String> {
    let started = Instant::now();
    let base = req.context.base_url.trim_end_matches('/');
    let endpoint = "/scan/base64/v2";
    let url = format!("{base}{endpoint}");
    let eicar = r#"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"#;
    let payload = base64_encode(eicar).into_bytes();
    let headers = build_headers(&req.context, None, None, false)?;

    let client = build_http_client(&req.context)?;
    let result = request_json(&client, reqwest::Method::POST, url, headers, Some(payload)).await?;

    Ok(json!({
        "operation": "scan-eicar-test",
        "endpoint": endpoint,
        "elapsed_seconds": started.elapsed().as_secs_f64(),
        "result": result
    }))
}

#[tauri::command]
async fn check_dsxa_connectivity(req: ConnectivityRequest) -> Result<ConnectivityResponse, String> {
    let base = req.context.base_url.trim_end_matches('/').to_string();
    if base.is_empty() {
        return Ok(ConnectivityResponse {
            reachable: false,
            status: None,
            reason: "invalid_url".to_string(),
            detail: "Base URL is empty".to_string(),
        });
    }

    let probe_url = format!("{base}/scan/binary/v2");
    let client = build_http_client(&req.context)?;
    let headers = build_headers(&req.context, None, None, false)?;
    let response = client
        .post(&probe_url)
        .headers(headers)
        .body(vec![0u8])
        .send()
        .await;

    let resp = match response {
        Ok(r) => r,
        Err(err) => {
            let lower = err.to_string().to_lowercase();
            let reason = if err.is_timeout() {
                "timeout"
            } else if lower.contains("certificate")
                || lower.contains("tls")
                || lower.contains("ssl")
                || lower.contains("x509")
            {
                "tls_error"
            } else {
                "connection_error"
            };
            return Ok(ConnectivityResponse {
                reachable: false,
                status: None,
                reason: reason.to_string(),
                detail: format!("{probe_url}: {err}"),
            })
        }
    };

    let status = resp.status().as_u16();
    let body_text = resp.text().await.unwrap_or_default();
    let body_json = serde_json::from_str::<Value>(&body_text).ok();
    let body_lower = body_text.to_lowercase();

    let (reachable, reason) = if (200..300).contains(&status) {
        (true, "ready")
    } else if status == 401 || status == 403 {
        (false, "auth_failed")
    } else if status == 404 || status == 405 {
        (false, "endpoint_unavailable")
    } else if status == 400 {
        if body_lower.contains("invalid protected entity")
            || body_lower.contains("protected_entity")
            || body_lower.contains("protected entity")
        {
            (false, "invalid_entity")
        } else {
            (false, "bad_request")
        }
    } else if status >= 500 {
        (false, "server_error")
    } else if body_json.is_some() {
        (false, "not_ready")
    } else {
        (false, "unknown")
    };

    Ok(ConnectivityResponse {
        reachable,
        status: Some(status),
        reason: reason.to_string(),
        detail: if reachable {
            format!("{probe_url} accepted validation request")
        } else {
            format!("{probe_url} validation failed (status {status})")
        },
    })
}

#[tauri::command]
async fn preview_folder_file_count(folder_path: String, limit: Option<usize>) -> Result<FolderCountPreviewResponse, String> {
    let path = folder_path.clone();
    let hard_limit = limit.unwrap_or(500_000).max(1);
    let (count, truncated) = tokio::task::spawn_blocking(move || {
        let mut count: usize = 0;
        for entry in WalkDir::new(path).into_iter().flatten() {
            if entry.file_type().is_file() {
                count += 1;
                if count > hard_limit {
                    return (hard_limit, true);
                }
            }
        }
        (count, false)
    })
    .await
    .map_err(|e| format!("count task failed: {e}"))?;

    Ok(FolderCountPreviewResponse { count, truncated })
}

#[tauri::command]
async fn scan_folder_start(
    app: tauri::AppHandle,
    runtime: State<'_, RuntimeState>,
    req: ScanFolderRequest,
) -> Result<FolderStartResponse, String> {
    if req.log_all_results
        && req
            .log_all_results_path
            .as_ref()
            .map(|p| p.trim().is_empty())
            .unwrap_or(true)
    {
        return Err("log_all_results is enabled but no log_all_results_path was provided".to_string());
    }
    if req.log_malicious_csv
        && req
            .log_malicious_csv_path
            .as_ref()
            .map(|p| p.trim().is_empty())
            .unwrap_or(true)
    {
        return Err("log_malicious_csv is enabled but no log_malicious_csv_path was provided".to_string());
    }
    if req.quarantine_enabled
        && req
            .quarantine_dir
            .as_ref()
            .map(|p| p.trim().is_empty())
            .unwrap_or(true)
    {
        return Err("quarantine_enabled is true but no quarantine_dir was provided".to_string());
    }

    let job_id = Uuid::new_v4().to_string();
    let cancel_flag = Arc::new(AtomicBool::new(false));
    let jobs = runtime.jobs.clone();

    {
        let mut jobs_lock = jobs
            .lock()
            .map_err(|_| "failed to lock jobs registry".to_string())?;
        jobs_lock.insert(job_id.clone(), cancel_flag.clone());
    }

    let folder_path = req.folder_path.clone();
    let job_id_for_task = job_id.clone();
    let app_for_task = app.clone();

    tauri::async_runtime::spawn(async move {
        let run = async {
            let mut files = Vec::new();
            for entry in WalkDir::new(&folder_path).into_iter().flatten() {
                if entry.file_type().is_file() {
                    files.push(entry.path().to_path_buf());
                }
            }

            let total = files.len();
            let worker_count = req.concurrency.unwrap_or(4).max(1);
            let _ = app_for_task.emit(
                "scan-folder-progress",
                FolderProgressEvent {
                    job_id: job_id_for_task.clone(),
                    event_type: "start".to_string(),
                    total,
                    scanned: 0,
                    ok: 0,
                    failed: 0,
                    stats: Some(json!({
                        "benign": 0,
                        "malicious": 0,
                        "failed": 0,
                        "encrypted": 0,
                        "other": 0
                    })),
                    summary: None,
                    failures: None,
                    error: None,
                },
            );

            let client = build_http_client(&req.context)?;
            let started = Instant::now();
            let files = Arc::new(files);
            let next_index = Arc::new(AtomicUsize::new(0));
            let scanned = Arc::new(AtomicUsize::new(0));
            let ok = Arc::new(AtomicUsize::new(0));
            let failed = Arc::new(AtomicUsize::new(0));
            let benign = Arc::new(AtomicUsize::new(0));
            let malicious = Arc::new(AtomicUsize::new(0));
            let encrypted = Arc::new(AtomicUsize::new(0));
            let other = Arc::new(AtomicUsize::new(0));
            let scan_time_total_micros = Arc::new(AtomicU64::new(0));
            let failures: Arc<Mutex<Vec<Value>>> = Arc::new(Mutex::new(Vec::new()));

            let base = req.context.base_url.trim_end_matches('/').to_string();
            let endpoint = if req.context.base64_mode {
                "/scan/base64/v2"
            } else {
                "/scan/binary/v2"
            };
            let url = format!("{base}{endpoint}");
            let max_size = effective_max_file_size_bytes(req.max_file_size_bytes);
            let jsonl_file: Arc<Mutex<Option<std::fs::File>>> = Arc::new(Mutex::new(None));
            if req.log_all_results {
                let path = req.log_all_results_path.clone().unwrap_or_default();
                let file = OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(&path)
                    .map_err(|e| format!("failed to open JSONL log file '{path}': {e}"))?;
                if let Ok(mut slot) = jsonl_file.lock() {
                    *slot = Some(file);
                }
            }

            let csv_file: Arc<Mutex<Option<std::fs::File>>> = Arc::new(Mutex::new(None));
            if req.log_malicious_csv {
                let path = req.log_malicious_csv_path.clone().unwrap_or_default();
                let mut file = OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(&path)
                    .map_err(|e| format!("failed to open CSV log file '{path}': {e}"))?;
                let len = file
                    .metadata()
                    .map(|m| m.len())
                    .map_err(|e| format!("failed to stat CSV log file '{path}': {e}"))?;
                if len == 0 {
                    writeln!(file, "file_path,file_hash,verdict,reason,quarantine_path")
                        .map_err(|e| format!("failed to write CSV header: {e}"))?;
                }
                if let Ok(mut slot) = csv_file.lock() {
                    *slot = Some(file);
                }
            }

            let mut joins = Vec::new();
            for _ in 0..worker_count {
                let client = client.clone();
                let files = Arc::clone(&files);
                let next_index = Arc::clone(&next_index);
                let scanned = Arc::clone(&scanned);
                let ok = Arc::clone(&ok);
                let failed = Arc::clone(&failed);
                let benign = Arc::clone(&benign);
                let malicious = Arc::clone(&malicious);
                let encrypted = Arc::clone(&encrypted);
                let other = Arc::clone(&other);
                let scan_time_total_micros = Arc::clone(&scan_time_total_micros);
                let failures = Arc::clone(&failures);
                let jsonl_file = Arc::clone(&jsonl_file);
                let csv_file = Arc::clone(&csv_file);
                let cancel_flag = Arc::clone(&cancel_flag);
                let app_for_task = app_for_task.clone();
                let job_id_for_task = job_id_for_task.clone();
                let req = req.clone();
                let url = url.clone();

                joins.push(tauri::async_runtime::spawn(async move {
                    loop {
                        if cancel_flag.load(Ordering::Relaxed) {
                            break;
                        }
                        let current = next_index.fetch_add(1, Ordering::Relaxed);
                        if current >= files.len() {
                            break;
                        }
                        let path = files[current].clone();
                        let request_started = Instant::now();

                        let file_meta = match tokio::fs::metadata(&path).await {
                            Ok(m) => m,
                            Err(e) => {
                                let s = scanned.fetch_add(1, Ordering::Relaxed) + 1;
                                let f = failed.fetch_add(1, Ordering::Relaxed) + 1;
                                let o = ok.load(Ordering::Relaxed);
                                let fail_record = json!({
                                    "file": path.to_string_lossy(),
                                    "status": "failed",
                                    "error": format!("failed to stat file: {e}"),
                                    "scan_duration_in_microseconds": 0
                                });
                                if let Ok(mut list) = failures.lock() {
                                    list.push(fail_record.clone());
                                }
                                if let Ok(mut slot) = jsonl_file.lock() {
                                    if let Some(file) = slot.as_mut() {
                                        let _ = writeln!(file, "{}", fail_record);
                                    }
                                }
                                let _ = app_for_task.emit(
                                    "scan-folder-progress",
                                    FolderProgressEvent {
                                        job_id: job_id_for_task.clone(),
                                        event_type: "progress".to_string(),
                                        total,
                                        scanned: s,
                                        ok: o,
                                        failed: f,
                                        stats: Some(json!({
                                            "benign": benign.load(Ordering::Relaxed),
                                            "malicious": malicious.load(Ordering::Relaxed),
                                            "failed": f,
                                            "encrypted": encrypted.load(Ordering::Relaxed),
                                            "other": other.load(Ordering::Relaxed)
                                        })),
                                        summary: None,
                                        failures: None,
                                        error: None,
                                    },
                                );
                                continue;
                            }
                        };

                        if file_meta.len() > max_size {
                            let s = scanned.fetch_add(1, Ordering::Relaxed) + 1;
                            let f = failed.fetch_add(1, Ordering::Relaxed) + 1;
                            let o = ok.load(Ordering::Relaxed);
                            let fail_record = json!({
                                "file": path.to_string_lossy(),
                                "status": "failed",
                                "error": format!(
                                    "file too large ({} bytes > {} bytes). Use scan by path for large files.",
                                    file_meta.len(),
                                    max_size
                                ),
                                "scan_duration_in_microseconds": 0
                            });
                            if let Ok(mut list) = failures.lock() {
                                list.push(fail_record.clone());
                            }
                            if let Ok(mut slot) = jsonl_file.lock() {
                                if let Some(file) = slot.as_mut() {
                                    let _ = writeln!(file, "{}", fail_record);
                                }
                            }
                            let _ = app_for_task.emit(
                                "scan-folder-progress",
                                FolderProgressEvent {
                                    job_id: job_id_for_task.clone(),
                                    event_type: "progress".to_string(),
                                    total,
                                    scanned: s,
                                    ok: o,
                                    failed: f,
                                    stats: Some(json!({
                                        "benign": benign.load(Ordering::Relaxed),
                                        "malicious": malicious.load(Ordering::Relaxed),
                                        "failed": f,
                                        "encrypted": encrypted.load(Ordering::Relaxed),
                                        "other": other.load(Ordering::Relaxed)
                                    })),
                                    summary: None,
                                    failures: None,
                                    error: None,
                                },
                            );
                            continue;
                        }

                        let resolved_metadata = resolve_effective_metadata(
                            &req.context,
                            req.metadata.as_deref(),
                            Some(path.as_path()),
                            None,
                            true,
                        );

                        let headers = match build_headers(
                            &req.context,
                            resolved_metadata.as_deref(),
                            req.password.as_deref(),
                            false,
                        ) {
                            Ok(h) => h,
                            Err(e) => {
                                let s = scanned.fetch_add(1, Ordering::Relaxed) + 1;
                                let f = failed.fetch_add(1, Ordering::Relaxed) + 1;
                                let o = ok.load(Ordering::Relaxed);
                                let fail_record = json!({
                                    "file": path.to_string_lossy(),
                                    "status": "failed",
                                    "error": e,
                                    "scan_duration_in_microseconds": 0
                                });
                                if let Ok(mut list) = failures.lock() {
                                    list.push(fail_record.clone());
                                }
                                if let Ok(mut slot) = jsonl_file.lock() {
                                    if let Some(file) = slot.as_mut() {
                                        let _ = writeln!(file, "{}", fail_record);
                                    }
                                }
                                let _ = app_for_task.emit(
                                    "scan-folder-progress",
                                    FolderProgressEvent {
                                        job_id: job_id_for_task.clone(),
                                        event_type: "progress".to_string(),
                                        total,
                                        scanned: s,
                                        ok: o,
                                        failed: f,
                                        stats: Some(json!({
                                            "benign": benign.load(Ordering::Relaxed),
                                            "malicious": malicious.load(Ordering::Relaxed),
                                            "failed": f,
                                            "encrypted": encrypted.load(Ordering::Relaxed),
                                            "other": other.load(Ordering::Relaxed)
                                        })),
                                        summary: None,
                                        failures: None,
                                        error: None,
                                    },
                                );
                                continue;
                            }
                        };

                        let file_hash = match sha256_file(path.as_path()) {
                            Ok(hash) => hash,
                            Err(e) => {
                                let s = scanned.fetch_add(1, Ordering::Relaxed) + 1;
                                let f = failed.fetch_add(1, Ordering::Relaxed) + 1;
                                let o = ok.load(Ordering::Relaxed);
                                let fail_record = json!({
                                    "file": path.to_string_lossy(),
                                    "status": "failed",
                                    "error": e,
                                    "scan_duration_in_microseconds": 0
                                });
                                if let Ok(mut list) = failures.lock() {
                                    list.push(fail_record.clone());
                                }
                                if let Ok(mut slot) = jsonl_file.lock() {
                                    if let Some(file) = slot.as_mut() {
                                        let _ = writeln!(file, "{}", fail_record);
                                    }
                                }
                                let _ = app_for_task.emit(
                                    "scan-folder-progress",
                                    FolderProgressEvent {
                                        job_id: job_id_for_task.clone(),
                                        event_type: "progress".to_string(),
                                        total,
                                        scanned: s,
                                        ok: o,
                                        failed: f,
                                        stats: Some(json!({
                                            "benign": benign.load(Ordering::Relaxed),
                                            "malicious": malicious.load(Ordering::Relaxed),
                                            "failed": f,
                                            "encrypted": encrypted.load(Ordering::Relaxed),
                                            "other": other.load(Ordering::Relaxed)
                                        })),
                                        summary: None,
                                        failures: None,
                                        error: None,
                                    },
                                );
                                continue;
                            }
                        };

                        let request_result = if req.context.base64_mode {
                            let data = match tokio::fs::read(&path).await {
                                Ok(d) => d,
                                Err(e) => {
                                    let s = scanned.fetch_add(1, Ordering::Relaxed) + 1;
                                    let f = failed.fetch_add(1, Ordering::Relaxed) + 1;
                                    let o = ok.load(Ordering::Relaxed);
                                    let fail_record = json!({
                                        "file": path.to_string_lossy(),
                                        "status": "failed",
                                        "error": format!("failed to read file: {e}"),
                                        "scan_duration_in_microseconds": 0
                                    });
                                    if let Ok(mut list) = failures.lock() {
                                        list.push(fail_record.clone());
                                    }
                                    if let Ok(mut slot) = jsonl_file.lock() {
                                        if let Some(file) = slot.as_mut() {
                                            let _ = writeln!(file, "{}", fail_record);
                                        }
                                    }
                                    let _ = app_for_task.emit(
                                        "scan-folder-progress",
                                        FolderProgressEvent {
                                            job_id: job_id_for_task.clone(),
                                            event_type: "progress".to_string(),
                                            total,
                                            scanned: s,
                                            ok: o,
                                            failed: f,
                                            stats: Some(json!({
                                                "benign": benign.load(Ordering::Relaxed),
                                                "malicious": malicious.load(Ordering::Relaxed),
                                                "failed": f,
                                                "encrypted": encrypted.load(Ordering::Relaxed),
                                                "other": other.load(Ordering::Relaxed)
                                            })),
                                            summary: None,
                                            failures: None,
                                            error: None,
                                        },
                                    );
                                    continue;
                                }
                            };
                            let payload = base64_encode_bytes(&data).into_bytes();
                            request_json(&client, reqwest::Method::POST, url.clone(), headers, Some(payload)).await
                        } else {
                            let file = match tokio::fs::File::open(&path).await {
                                Ok(file) => file,
                                Err(e) => {
                                    let s = scanned.fetch_add(1, Ordering::Relaxed) + 1;
                                    let f = failed.fetch_add(1, Ordering::Relaxed) + 1;
                                    let o = ok.load(Ordering::Relaxed);
                                    let fail_record = json!({
                                        "file": path.to_string_lossy(),
                                        "status": "failed",
                                        "error": format!("failed to open file: {e}"),
                                        "scan_duration_in_microseconds": 0
                                    });
                                    if let Ok(mut list) = failures.lock() {
                                        list.push(fail_record.clone());
                                    }
                                    if let Ok(mut slot) = jsonl_file.lock() {
                                        if let Some(file) = slot.as_mut() {
                                            let _ = writeln!(file, "{}", fail_record);
                                        }
                                    }
                                    let _ = app_for_task.emit(
                                        "scan-folder-progress",
                                        FolderProgressEvent {
                                            job_id: job_id_for_task.clone(),
                                            event_type: "progress".to_string(),
                                            total,
                                            scanned: s,
                                            ok: o,
                                            failed: f,
                                            stats: Some(json!({
                                                "benign": benign.load(Ordering::Relaxed),
                                                "malicious": malicious.load(Ordering::Relaxed),
                                                "failed": f,
                                                "encrypted": encrypted.load(Ordering::Relaxed),
                                                "other": other.load(Ordering::Relaxed)
                                            })),
                                            summary: None,
                                            failures: None,
                                            error: None,
                                        },
                                    );
                                    continue;
                                }
                            };
                            let body = reqwest::Body::wrap_stream(ReaderStream::new(file));
                            request_json_stream(&client, reqwest::Method::POST, url.clone(), headers, body).await
                        };

                        match request_result {
                            Ok(result) => {
                                let dsxa_micros = result
                                    .get("scan_duration_in_microseconds")
                                    .and_then(|v| v.as_u64())
                                    .unwrap_or(0);
                                scan_time_total_micros.fetch_add(dsxa_micros, Ordering::Relaxed);
                                let s = scanned.fetch_add(1, Ordering::Relaxed) + 1;
                                let o = ok.fetch_add(1, Ordering::Relaxed) + 1;
                                let f = failed.load(Ordering::Relaxed);
                                let (bucket, inc) = classify_verdict_counters(&result);
                                match bucket {
                                    "benign" => {
                                        benign.fetch_add(inc, Ordering::Relaxed);
                                    }
                                    "malicious" => {
                                        malicious.fetch_add(inc, Ordering::Relaxed);
                                    }
                                    "encrypted" => {
                                        encrypted.fetch_add(inc, Ordering::Relaxed);
                                    }
                                    _ => {
                                        other.fetch_add(inc, Ordering::Relaxed);
                                    }
                                }
                                let mut quarantine_path: Option<String> = None;
                                if is_malicious_verdict(&result) && req.quarantine_enabled {
                                    if let Some(ref qdir) = req.quarantine_dir {
                                        match move_to_quarantine(&path.to_string_lossy(), qdir).await {
                                            Ok(dest) => quarantine_path = Some(dest),
                                            Err(err) => {
                                                if let Ok(mut list) = failures.lock() {
                                                    list.push(json!({
                                                        "file": path.to_string_lossy(),
                                                        "status": "quarantine-failed",
                                                        "error": err
                                                    }));
                                                }
                                            }
                                        }
                                    }
                                }
                                let result_record = json!({
                                    "file": path.to_string_lossy(),
                                    "status": "ok",
                                    "file_hash": file_hash,
                                    "quarantine_path": quarantine_path,
                                    "result": result
                                });
                                if let Ok(mut slot) = jsonl_file.lock() {
                                    if let Some(file) = slot.as_mut() {
                                        let _ = writeln!(file, "{}", result_record);
                                    }
                                }
                                if is_malicious_verdict(&result) {
                                    if let Ok(mut slot) = csv_file.lock() {
                                        if let Some(file) = slot.as_mut() {
                                            let reason = result
                                                .get("verdict_details")
                                                .and_then(|d| d.get("reason"))
                                                .and_then(|r| r.as_str())
                                                .unwrap_or("");
                                            let qpath = quarantine_path.unwrap_or_default();
                                            let _ = writeln!(
                                                file,
                                                "{},{},{},{},{}",
                                                csv_escape(&path.to_string_lossy()),
                                                csv_escape(&file_hash),
                                                csv_escape("Malicious"),
                                                csv_escape(reason),
                                                csv_escape(&qpath)
                                            );
                                        }
                                    }
                                }
                                let _ = app_for_task.emit(
                                    "scan-folder-progress",
                                    FolderProgressEvent {
                                        job_id: job_id_for_task.clone(),
                                        event_type: "progress".to_string(),
                                        total,
                                        scanned: s,
                                        ok: o,
                                        failed: f,
                                        stats: Some(json!({
                                            "benign": benign.load(Ordering::Relaxed),
                                            "malicious": malicious.load(Ordering::Relaxed),
                                            "failed": f,
                                            "encrypted": encrypted.load(Ordering::Relaxed),
                                            "other": other.load(Ordering::Relaxed)
                                        })),
                                        summary: None,
                                        failures: None,
                                        error: None,
                                    },
                                );
                            }
                            Err(err) => {
                                let s = scanned.fetch_add(1, Ordering::Relaxed) + 1;
                                let f = failed.fetch_add(1, Ordering::Relaxed) + 1;
                                let o = ok.load(Ordering::Relaxed);
                                let fail_record = json!({
                                    "file": path.to_string_lossy(),
                                    "status": "failed",
                                    "error": err,
                                    "scan_duration_in_microseconds": 0,
                                    "request_duration_in_microseconds": request_started.elapsed().as_micros()
                                });
                                if let Ok(mut list) = failures.lock() {
                                    list.push(fail_record.clone());
                                }
                                if let Ok(mut slot) = jsonl_file.lock() {
                                    if let Some(file) = slot.as_mut() {
                                        let _ = writeln!(file, "{}", fail_record);
                                    }
                                }
                                let _ = app_for_task.emit(
                                    "scan-folder-progress",
                                    FolderProgressEvent {
                                        job_id: job_id_for_task.clone(),
                                        event_type: "progress".to_string(),
                                        total,
                                        scanned: s,
                                        ok: o,
                                        failed: f,
                                        stats: Some(json!({
                                            "benign": benign.load(Ordering::Relaxed),
                                            "malicious": malicious.load(Ordering::Relaxed),
                                            "failed": f,
                                            "encrypted": encrypted.load(Ordering::Relaxed),
                                            "other": other.load(Ordering::Relaxed)
                                        })),
                                        summary: None,
                                        failures: None,
                                        error: None,
                                    },
                                );
                            }
                        }
                    }
                }));
            }

            for join in joins {
                let _ = join.await;
            }

            let scanned = scanned.load(Ordering::Relaxed);
            let ok = ok.load(Ordering::Relaxed);
            let failed = failed.load(Ordering::Relaxed);
            let benign = benign.load(Ordering::Relaxed);
            let malicious = malicious.load(Ordering::Relaxed);
            let encrypted = encrypted.load(Ordering::Relaxed);
            let other = other.load(Ordering::Relaxed);
            let scan_time_total_micros = scan_time_total_micros.load(Ordering::Relaxed);
            let canceled = cancel_flag.load(Ordering::Relaxed) && scanned < total;
            let failures = failures.lock().map(|v| v.clone()).unwrap_or_default();

            let summary = json!({
                "operation": "scan-folder-summary",
                "job_id": job_id_for_task,
                "folder": req.folder_path,
                "pattern": req.pattern.unwrap_or_else(|| "**/*".to_string()),
                "concurrency": worker_count,
                "scanned": scanned,
                "ok": ok,
                "failed": failed,
                "stats": {
                    "benign": benign,
                    "malicious": malicious,
                    "failed": failed,
                    "encrypted": encrypted,
                    "other": other
                },
                "elapsed_seconds": started.elapsed().as_secs_f64(),
                "scan_time_total_microseconds": scan_time_total_micros,
                "scan_time_total_seconds": (scan_time_total_micros as f64) / 1_000_000.0,
                "canceled": canceled
            });

            let _ = app_for_task.emit(
                "scan-folder-progress",
                FolderProgressEvent {
                    job_id: summary["job_id"].as_str().unwrap_or_default().to_string(),
                    event_type: if canceled { "canceled".to_string() } else { "done".to_string() },
                    total,
                    scanned,
                    ok,
                    failed,
                    stats: Some(json!({
                        "benign": benign,
                        "malicious": malicious,
                        "failed": failed,
                        "encrypted": encrypted,
                        "other": other
                    })),
                    summary: Some(summary),
                    failures: Some(failures),
                    error: None,
                },
            );

            Ok::<(), String>(())
        }
        .await;

        if let Ok(mut jobs_lock) = jobs.lock() {
            jobs_lock.remove(&job_id_for_task);
        }

        if let Err(err) = run {
            let _ = app_for_task.emit(
                "scan-folder-progress",
                FolderProgressEvent {
                    job_id: job_id_for_task.clone(),
                    event_type: "error".to_string(),
                    total: 0,
                    scanned: 0,
                    ok: 0,
                    failed: 0,
                    stats: Some(json!({
                        "benign": 0,
                        "malicious": 0,
                        "failed": 0,
                        "encrypted": 0,
                        "other": 0
                    })),
                    summary: None,
                    failures: None,
                    error: Some(err),
                },
            );
        }
    });

    Ok(FolderStartResponse { job_id })
}

#[tauri::command]
async fn scan_folder_stop(runtime: State<'_, RuntimeState>, job_id: String) -> Result<(), String> {
    let jobs = runtime
        .jobs
        .lock()
        .map_err(|_| "failed to lock jobs registry".to_string())?;

    let Some(flag) = jobs.get(&job_id) else {
        return Err("job not found".to_string());
    };

    flag.store(true, Ordering::Relaxed);
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let runtime_state = RuntimeState::default();
    let setup_context_menu_ids = runtime_state.context_menu_ids.clone();

    tauri::Builder::default()
        .setup(move |app| {
            let app_handle = app.handle().clone();
            let state = tauri::async_runtime::block_on(read_state(&app_handle)).unwrap_or_default();
            let mut names: Vec<String> = state.contexts.keys().cloned().collect();
            names.sort();
            install_app_menu(&app_handle, &names, &state.selected_context, &setup_context_menu_ids)?;
            Ok(())
        })
        .on_menu_event(|app, event| match event.id().as_ref() {
            "settings" => {
                let _ = app.emit("open-settings", ());
            }
            "new-context" | "ctx-new-context" => {
                let _ = app.emit("open-new-context", ());
            }
            "delete-context" | "ctx-delete-context" => {
                let _ = app.emit("open-delete-context", ());
            }
            "save-context" | "ctx-save-context" => {
                let _ = app.emit("save-context", ());
            }
            "about" => {
                let version = app.package_info().version.to_string();
                let body = format!(
                    "DSXA Desktop\nVersion {version}\n\nDesktop client for file, folder, hash, and EICAR scanning against a DSXA scanner."
                );
                app.dialog()
                    .message(body)
                    .title("About DSXA Desktop")
                    .kind(MessageDialogKind::Info)
                    .buttons(MessageDialogButtons::Ok)
                    .show(|_| {});
            }
            "help" => {
                let _ = webbrowser::open("https://deep-instinct.github.io/dsx-connect/resources/dsxa-desktop/");
            }
            menu_id if menu_id.starts_with("ctx-select-item-") => {
                if let Some(runtime) = app.try_state::<RuntimeState>() {
                    if let Ok(map) = runtime.context_menu_ids.lock() {
                        if let Some(name) = map.get(menu_id) {
                            let _ = app.emit("open-select-context-by-name", name.clone());
                        }
                    }
                }
            }
            _ => {}
        })
        .plugin(tauri_plugin_dialog::init())
        .manage(runtime_state)
        .invoke_handler(tauri::generate_handler![
            get_state,
            save_state,
            sync_context_menu,
            check_dsxa_connectivity,
            preview_folder_file_count,
            scan_file,
            scan_hash,
            scan_eicar_test,
            scan_folder_start,
            scan_folder_stop
        ])
        .run(tauri::generate_context!())
        .expect("error while running DSXA Desktop app");
}
