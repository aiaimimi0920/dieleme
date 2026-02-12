# Job Manager 架构说明

## 整体流程

```mermaid
graph TB
    subgraph 前端["🌐 油猴脚本 (taobao_fast_worker.js)"]
        SW["嗅探窗口 Session"]
    end

    subgraph 后端["🖥️ 后端服务 (server.py)"]
        API["/api/sniff_task<br>/api/report_sniff"]
        JM["JobManager"]
    end

    subgraph 存储["📁 jobs/ 目录"]
        PRI["priority.json<br>优先城市列表"]
        JF1["4401.json<br>广州各区"]
        JF2["5101.json<br>成都各区"]
        JFN["XXXX.json<br>其他城市"]
        LOC["datas/all_locations.json<br>全国区县代码"]
    end

    SW -- "GET /api/sniff_task" --> API
    API -- "get_next_job(session)" --> JM
    JM -- "读取优先级" --> PRI
    JM -- "加载/保存任务" --> JF1 & JF2 & JFN
    JM -- "发现新地区" --> LOC
    JM -- "返回任务URL" --> API
    API -- "分配URL" --> SW

    SW -- "POST /api/report_sniff" --> API
    API -- "update_progress()" --> JM
    JM -- "更新进度" --> JF1 & JF2 & JFN
```

## 任务分配优先级

```mermaid
flowchart TD
    START["get_next_job(session_id)"] --> CHECK_RESUME
    CHECK_RESUME{"该 session 有<br>正在进行的任务？"}
    CHECK_RESUME -- "是" --> RESUME["恢复该任务<br>继续下一页"]
    CHECK_RESUME -- "否" --> CHECK_PRI

    CHECK_PRI{"priority.json<br>中有未完成城市？"}
    CHECK_PRI -- "是" --> ASSIGN_PRI["分配优先城市"]
    CHECK_PRI -- "否" --> CHECK_JOB

    CHECK_JOB{"已有 job 文件中<br>有未完成任务？"}
    CHECK_JOB -- "是" --> ASSIGN_JOB["分配已有任务"]
    CHECK_JOB -- "否" --> CHECK_NEW

    CHECK_NEW{"all_locations 中<br>有未嗅探的地区？"}
    CHECK_NEW -- "是" --> ASSIGN_NEW["随机选取新地区"]
    CHECK_NEW -- "否" --> DONE["全部完成 ✅"]

    style RESUME fill:#4CAF50,color:white
    style ASSIGN_PRI fill:#FF9800,color:white
    style ASSIGN_JOB fill:#2196F3,color:white
    style ASSIGN_NEW fill:#9C27B0,color:white
    style DONE fill:#607D8B,color:white
```

## 排序参数剪枝策略

每个地区 × 类别需要嗅探多种排序方式（`st_param`），核心优化逻辑：

```mermaid
flowchart TD
    S2["先做 st_param=2<br>（按出价次数排序）"]
    S2 --> CHECK83{"完成时<br>max_page < 83？"}

    CHECK83 -- "是（数据量少）" --> PRUNE["🔪 剪枝<br>跳过其他 st_param<br>标记类别完成"]
    CHECK83 -- "否（数据量大）" --> CONTINUE["继续做 st_param<br>1 → 0 → 3 → 4 → 5"]

    ZERO{"中途检测到<br>零出价条目？"} --> PRUNE

    style PRUNE fill:#f44336,color:white
    style CONTINUE fill:#4CAF50,color:white
    style ZERO fill:#FF5722,color:white
```

## 数据文件结构

每个 job 文件以城市代码前4位命名（如 `4401.json` = 广州市），内部按区县 → 类别 → 排序方式三层嵌套：

```
4401.json
├── all_done: false              # 整个文件是否完成
├── "440106"                     # 天河区
│   ├── "50025969" (住宅用房)
│   │   ├── now_session_id       # 当前占用的 session
│   │   ├── all_done             # 该类别是否完成
│   │   ├── last_update_time     # 最后更新时间
│   │   └── st_param
│   │       ├── "2": { pages: [1,2,...32], max_page: 96, is_done: false }
│   │       ├── "1": { pages: [], max_page: -1, is_done: false }
│   │       └── ...
│   └── "200782003" (商业用房)
│       └── ...同上结构
├── "440111"                     # 白云区
│   └── ...
└── ...
```

## Session 管理

| 机制 | 说明 |
|------|------|
| **会话绑定** | 每个类别任务通过 `now_session_id` 绑定到特定嗅探窗口 |
| **超时释放** | 60秒无更新自动释放，允许其他 session 接管 |
| **手动释放** | `release_session()` 用于窗口关闭时清理占用 |
| **断点续传** | session 重连后自动恢复到上次的页码继续 |

## 文件清单

| 文件 | 用途 |
|------|------|
| `job_manager.py` | 核心管理器，提供任务分配/进度更新/剪枝 |
| `priority.json` | 优先嗅探的城市代码列表 |
| `XXXX.json` | 各城市任务进度数据（按前4位市级代码分文件） |
