"""优化版Solver - 更真实的人类行为模拟"""
import random
import time
import math

def generate_human_track(distance):
    """生成更接近人类的拖动轨迹"""
    track = []
    current = 0
    mid = distance * 4 / 5

    # 加速阶段
    while current < mid:
        if current < distance / 3:
            a = random.uniform(2, 4)
        else:
            a = random.uniform(1, 3)
        v = random.uniform(5, 10)
        move = v + 0.5 * a
        current += move
        track.append(round(move, 2))

    # 减速阶段
    while current < distance:
        a = -random.uniform(3, 5)
        v = random.uniform(2, 4)
        move = v + 0.5 * a
        move = max(0.5, move)
        current += move
        track.append(round(move, 2))

    # 回退
    for _ in range(random.randint(2, 4)):
        track.append(-random.uniform(0.5, 2))

    # 微调
    for _ in range(random.randint(1, 3)):
        track.append(random.uniform(0.3, 1.5))

    return track

def drag_with_human_behavior(page, slider, distance):
    """使用更真实的人类行为拖动"""
    box = slider.bounding_box()
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2

    # 鼠标移动到滑块前停顿
    page.mouse.move(start_x - 10, start_y + random.uniform(-5, 5))
    time.sleep(random.uniform(0.3, 0.6))

    # 移到滑块
    page.mouse.move(start_x, start_y)
    time.sleep(random.uniform(0.2, 0.4))

    # 按下
    page.mouse.down()
    time.sleep(random.uniform(0.15, 0.25))

    # 拖动
    track = generate_human_track(distance)
    current_x = start_x

    for i, move in enumerate(track):
        current_x += move
        y_offset = random.uniform(-2, 2) * math.sin(i * 0.5)
        page.mouse.move(current_x, start_y + y_offset)

        # 随机停顿
        if random.random() < 0.15:
            time.sleep(random.uniform(0.02, 0.05))
        else:
            time.sleep(random.uniform(0.008, 0.015))

    # 释放前短暂停顿
    time.sleep(random.uniform(0.1, 0.2))
    page.mouse.up()

    return True
