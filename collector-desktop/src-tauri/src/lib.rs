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

fn run_hidden_powershell(script: &str, args: &[String]) -> Result<(), String> {
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

    let status = command
        .status()
        .map_err(|error| format!("failed to run script: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("script exited with status {status}"))
    }
}

fn bundled_script_path(script_name: &str) -> Option<String> {
    let current_exe = std::env::current_exe().ok()?;
    let parent = current_exe.parent()?;
    let candidate = parent.join("scripts").join(script_name);
    if candidate.exists() {
        return Some(candidate.to_string_lossy().to_string());
    }
    None
}

#[tauri::command]
fn open_auth_browser(url: String) -> Result<String, String> {
    let target_url = if url.trim().is_empty() {
        "https://login.taobao.com/member/login.jhtml".to_string()
    } else {
        url.trim().to_string()
    };
    let script = std::env::var("FAPAI_AUTH_BROWSER_SCRIPT")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| bundled_script_path("open-remote-auth-browser.ps1"))
        .unwrap_or_else(|| {
            r"\\192.168.15.200\home\project\project\fapaifang\scripts\open-remote-auth-browser.ps1"
                .to_string()
        });
    if !Path::new(&script).exists() {
        return Err(format!("auth browser script does not exist: {script}"));
    }

    spawn_hidden_powershell(
        &script,
        &[
            "-Port".to_string(),
            "9225".to_string(),
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
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| bundled_script_path("complete-pc1-inplace-auth.ps1"))
        .unwrap_or_else(|| r"\\192.168.15.200\home\project\project\fapaifang\scripts\complete-pc1-inplace-auth.ps1".to_string());

    let port = std::env::var("FAPAI_AUTH_LOCAL_CDP_PORT")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "9225".to_string());
    run_hidden_powershell(
        &script,
        &["-Port".to_string(), port],
    )?;

    Ok("当前详情页、列表请求和详情请求均已通过，浏览器未重启，认证结果可以供 PC2 worker 使用。".to_string())
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
