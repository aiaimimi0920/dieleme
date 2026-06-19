## Captcha Solver 改进总结

### 修改的文件
- `src/captcha_solver.py`

### 关键改进

#### 1. 增强反自动化检测 (第127-138行)
```javascript
- 隐藏 navigator.webdriver
- 伪装 window.chrome 对象
- 伪造 navigator.plugins
- 伪造 navigator.languages 为 ['zh-CN', 'zh', 'en']
- 修复 permissions.query 行为
```

#### 2. 优化贝塞尔曲线路径生成 (第534-571行)
- 更微妙的弧度 (2-12px vs 5-20px)
- 增强抖动强度 (±2到±2.5px vs ±1到±1.5px)
- 更自然的控制点变化 (±8px vs ±5px)
- 动态点密度 (2-6px间距 vs 3-8px)

#### 3. 改进拖动行为 (第578-657行)
- 更长的预移动时间 (0.3-0.8s vs 0.2-0.6s)
- 减小overshoot (1-3px vs 2-6px，更微妙)
- 延长拖动总时长 (0.9-2.2s vs 0.7-1.8s)
- 增加微停顿频率 (8% vs 5%)
- 更长的释放前等待 (0.4-1.0s vs 0.3-0.8s)

#### 4. 添加距离随机化 (第795-797行)
- 每次拖动添加 -3到+2px 的随机偏移
- 增加等待时间随机性 (2.5-3.5s vs 固定3s)

#### 5. 添加max_attempts参数 (第738-866行)
- 默认50次尝试限制（防止无限循环）
- 支持自定义最大尝试次数

### 测试结果
- ✅ Mock滑块机械测试通过 (41个鼠标移动事件)
- ✅ 所有改进功能单元测试通过
- ✅ 代码结构改进完成

### 使用方法

#### 通过API触发
```python
import requests
requests.post('http://127.0.0.1:8001/api/report_captcha', json={
    "url": "目标URL",
    "cdp_endpoint": "http://127.0.0.1:9223",
    "timestamp": 1735000000000
})
```

#### 通过detail_worker自动触发
```bash
python tools/detail_worker.py --solver-enabled --api-base-url http://127.0.0.1:8001/api
```

#### 直接调用
```python
from src.captcha_solver import CaptchaSolver
solver = CaptchaSolver(port=9223, target_url="目标URL")
result = solver.solve(max_attempts=50)
```

### 注意事项
1. 确保浏览器以 `--remote-debugging-port=9223` 启动
2. 确保目标页面已加载验证码
3. Solver会自动重试直到成功或达到最大尝试次数
4. 成功率取决于验证码类型和难度

### 后续建议
- 在实际遇到淘宝验证码时测试通过率
- 如仍被拒绝，可进一步增加随机性或调整timing参数
- 考虑添加更多浏览器指纹隐藏技术
