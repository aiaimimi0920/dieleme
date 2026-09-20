use std::io::{Read, Write};
use std::process::{Command, Output, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

pub fn run(
    command: &mut Command,
    input: Vec<u8>,
    timeout: Duration,
) -> Result<Output, &'static str> {
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().map_err(|_| "helper_start_failed")?;
    let mut stdin = child.stdin.take().ok_or("helper_input_unavailable")?;
    let stdout = child.stdout.take().ok_or("helper_output_unavailable")?;
    let (sender, receiver) = mpsc::channel();
    // Neither a full input/output pipe nor a silent child may hold the UI gate.
    thread::spawn(move || {
        let _ = stdin.write_all(&input);
    });
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = stdout.take(65537).read_to_end(&mut bytes).map(|_| bytes);
        let _ = sender.send(result);
    });
    let deadline = Instant::now() + timeout;
    let result = loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                break match receiver
                    .recv_timeout(deadline.saturating_duration_since(Instant::now()))
                {
                    Ok(Ok(stdout)) if stdout.len() <= 65536 => Ok(Output {
                        status,
                        stdout,
                        stderr: Vec::new(),
                    }),
                    Ok(_) => Err("helper_output_invalid"),
                    Err(_) => Err("helper_timeout"),
                };
            }
            Err(_) => break Err("helper_wait_failed"),
            Ok(None) => {}
        }
        if Instant::now() >= deadline {
            break Err("helper_timeout");
        }
        thread::sleep(Duration::from_millis(20));
    };
    if result.is_err() {
        let _ = child.kill();
        let _ = child.wait();
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sleeper() -> Command {
        #[cfg(windows)]
        {
            let mut command = Command::new("powershell.exe");
            command.args(["-NoProfile", "-Command", "Start-Sleep -Seconds 10"]);
            command
        }
        #[cfg(not(windows))]
        {
            let mut command = Command::new("sleep");
            command.arg("10");
            command
        }
    }

    #[test]
    fn silent_helper_has_a_total_deadline() {
        let started = Instant::now();
        assert_eq!(
            run(&mut sleeper(), Vec::new(), Duration::from_millis(100)).unwrap_err(),
            "helper_timeout"
        );
        assert!(started.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn blocked_stdin_does_not_bypass_deadline() {
        assert_eq!(
            run(
                &mut sleeper(),
                vec![b'x'; 20000],
                Duration::from_millis(100)
            )
            .unwrap_err(),
            "helper_timeout"
        );
    }
}
