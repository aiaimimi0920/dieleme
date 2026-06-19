"""Interactive real mouse solver - uses click to calibrate position."""
import sys, time, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import pyautogui
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyautogui", "pillow"])
    import pyautogui

from src.captcha_solver import CaptchaSolver

def solve_interactive(target_url, port=9223):
    """Interactive solver with position calibration."""

    solver = CaptchaSolver(port=port, target_url=target_url)
    if not solver.connect_tab():
        print("❌ Failed to connect to browser")
        return False

    solver._bring_to_front()
    time.sleep(2)

    # Find slider
    slider = solver._find_slider()
    if not slider:
        print("❌ Slider not found")
        return False

    track_width = solver._get_track_width()
    distance = track_width - slider["width"] - 4

    print(f"\n{'='*60}")
    print(f"滑块已找到！距离: {distance:.0f}px")
    print(f"{'='*60}")
    print("\n📍 步骤 1: 请在 5 秒内用鼠标点击滑块中心")
    print("   (这样程序可以知道滑块在屏幕上的位置)\n")

    time.sleep(5)

    # Get calibration click position
    calib_x, calib_y = pyautogui.position()
    print(f"✓ 已记录位置: ({calib_x}, {calib_y})")

    print(f"\n🎯 步骤 2: 开始自动拖动 {distance:.0f}px...")
    time.sleep(1)

    # Move to calibrated position
    pyautogui.moveTo(calib_x, calib_y, duration=0.3)
    time.sleep(0.2)

    # Drag
    pyautogui.mouseDown()
    time.sleep(random.uniform(0.15, 0.3))

    # Smooth drag with human-like movement
    steps = int(distance / 5)
    for i in range(steps):
        progress = (i + 1) / steps
        ease = 1 - (1 - progress) ** 2

        dx = (distance * ease) - (distance * ((i) / steps if i > 0 else 0))
        dy = random.uniform(-2, 2) * (1 - progress)

        pyautogui.move(dx, dy, duration=random.uniform(0.04, 0.08))

        if random.random() < 0.1:
            time.sleep(random.uniform(0.02, 0.05))

    time.sleep(random.uniform(0.4, 0.7))
    pyautogui.mouseUp()

    print("✓ 拖动完成")
    print("\n⏳ 等待验证结果...")
    time.sleep(3)

    # Check result
    result = solver._verify_success()
    solver.ws.close()

    return result


if __name__ == "__main__":
    test_url = sys.argv[1] if len(sys.argv) > 1 else "file:///" + str(Path(__file__).parent.resolve() / "test_slider_simple.html").replace('\\', '/')

    print("\n" + "="*60)
    print("真实鼠标滑块验证码求解器 (交互式)")
    print("="*60)

    result = solve_interactive(test_url)

    print("\n" + "="*60)
    if result:
        print("✅ 成功通过验证！")
    else:
        print("❌ 验证失败")
    print("="*60)

    sys.exit(0 if result else 1)
