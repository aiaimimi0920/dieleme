use std::path::Path;
use std::process::{Command, Stdio};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[tauri::command]
fn default_api_base() -> String {
    std::env::var("FAPAI_COLLECTOR_API_BASE")
        .unwrap_or_else(|_| "http://127.0.0.1:8001".to_string())
}

fn spawn_hidden_powershell(script: &str, args: &[String]) -> Result<(), String> {
    if !Path::new(script).exists() {
        return Err(format!("script does not exist: {script}"));
    }

    let mut command = Command::new("powershell");
    command.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]);
    command.args(args);
    command.stdin(Stdio::null());
    command.stdout(Stdio::null());
    command.stderr(Stdio::null());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    command
        .spawn()
        .map(|_child| ())
        .map_err(|error| format!("failed to start script in background: {error}"))
}

#[tauri::command]
fn open_auth_browser(url: String) -> Result<String, String> {
    let target_url = if url.trim().is_empty() {
        "https://login.taobao.com/member/login.jhtml".to_string()
    } else {
        url.trim().to_string()
    };
    let script = std::env::var("FAPAI_AUTH_BROWSER_SCRIPT").unwrap_or_else(|_| {
        r"\\192.168.15.200\home\project\project\fapaifang\scripts\start-taobao-cdp-browser.ps1"
            .to_string()
    });
    if !Path::new(&script).exists() {
        return Err(format!("auth browser script does not exist: {script}"));
    }

    spawn_hidden_powershell(
        &script,
        &[
            "-Port".to_string(),
            "9223".to_string(),
            "-StartUrl".to_string(),
            target_url.clone(),
        ],
    )?;

    Ok(format!(
        "已在后台打开/刷新外部认证浏览器：{target_url}。如果浏览器未立即出现，请等待几秒或再次点击打开。"
    ))
}

#[tauri::command]
fn export_taobao_cookie_snapshot() -> Result<String, String> {
    let script = std::env::var("FAPAI_COOKIE_EXPORT_SCRIPT")
        .unwrap_or_else(|_| r"\\192.168.15.200\home\project\project\fapaifang\scripts\export-taobao-cookie-snapshot.ps1".to_string());

    spawn_hidden_powershell(
        &script,
        &[
            "-Port".to_string(),
            "9223".to_string(),
            "-SkipBrowserStart".to_string(),
        ],
    )?;

    Ok("已在后台刷新淘宝 cookie 快照；观察台不会等待该任务完成。".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            default_api_base,
            open_auth_browser,
            export_taobao_cookie_snapshot
        ])
        .run(tauri::generate_context!())
        .expect("error while running FapaiFang collector desktop application");
}
