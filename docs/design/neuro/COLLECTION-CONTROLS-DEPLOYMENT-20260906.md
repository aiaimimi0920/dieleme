# 采集控制界面部署记录

核验时间：2026-09-06 09:53（Asia/Shanghai）。

## 当前结论

**NAS API 和 PC1 桌面程序已更新；PC2 远程重启控制器尚未启用，不能宣称整条重启链路已完成。数据库保留检查已通过。**

| 节点 | 实际执行 | 当前结果 |
| --- | --- | --- |
| NAS | 以线上镜像为基底，仅覆盖 5 个相关后端文件；只重建 API 容器 | 新版 API 在线，构建标识和文件哈希通过核验 |
| PC1 | 原子替换原生桌面 EXE，先备份旧版 | 安装文件哈希与已验证构建一致；未主动启动窗口 |
| PC2 | 安装独立宿主机控制器和加密 API 隧道服务 | NAS 禁止 SSH 端口转发；新服务已停止并禁用，等待转发授权 |

PC1 是原生桌面程序，不是容器。此次功能不要求更换 PC2 的采集 Worker 或浏览器镜像，因此没有盲目重建它们，也没有带入工作区里其他未部署的 Worker/认证修改。

## 数据库保护与证明

部署前创建独立 PostgreSQL 自定义格式备份：

```text
/volume1/docker/fapaifang/backups/postgres/20260906-collection-controls/before.dump
```

- 大小：232,667,879 字节。
- SHA-256：`896702f1818000cda5799cf2feace10452dec0813656fa3b101d2e44b5ab164b`。
- `pg_restore -l` 和 `pg_restore --file=/dev/null` 均成功。后者验证完整归档可以解码，不等同于已恢复到独立测试数据库。
- 部署前后 15 张表的既有主键逐表对比：**缺失数全部为 0**。
- `property_listing`：283,713 → 283,713。
- `fapai_seed_item`：267,172 → 267,172。
- `fapai_seed_occurrence`：872,310 → 872,310。
- PostgreSQL 容器 ID、启动时间、数据挂载完全未变。
- schema 保持 `20260905_0011`；没有执行迁移、清表、覆盖恢复、数据卷删除或备份清理。

这里证明的是备份可解码、既有记录主键保留和数据库运行边界未变；没有将其夸大成所有业务字段逐字节不变的证明。

## NAS 上线版本与接口验收

- 镜像：`fapaifang-collector:nas-20260906-collection-controls`。
- API 构建版本：`20260906-collection-controls`。
- source digest：`88e7860d7db3106ceee8b2fd203b4205202ee635cfdbbf977199e84b70abdea3`。
- 实际部署的 5 个文件全部通过 live-container SHA-256 核对：
  - `src/server.py`
  - `src/server_collection_status.py`
  - `src/server_engine_control.py`
  - `src/collection_engine_restart.py`
  - `src/storage/repository_observer_regions.py`
- API 和数据库的所有原有持久化挂载均保留。
- 新重启邮箱使用持久化目录 `/data/datas/engine-control`；两种角色使用不同的受保护令牌文件，令牌内容未写入仓库或日志。

线上三个阶段筛选均返回 HTTP 200，并各抽查 5 条记录，状态符合所选阶段：

| 阶段 | 当前条数 | 语义 |
| --- | ---: | --- |
| 链接 | 172,038 | 有链接、详情尚未完成 |
| 详情 | 16,005 | 详情已完成、AI 归档尚未完成 |
| 分析 | 79,129 | AI 归档已完成；这是最后一个采集阶段 |

三个互斥分区合计 267,172，与唯一商品链接数一致。上述数字是本次核验快照，不是未来固定值。

## PC1 安装

安装路径：

```text
C:\Users\vmjcv\AppData\Local\FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe
```

安装后 SHA-256：

```text
224c993641abcdedfb753da383b4ab40aa659e9a8d7a2cbda4e7fd613b5e0c8c
```

旧版备份：

```text
C:\Users\vmjcv\AppData\Local\FapaiFangCollectorDesktop\backup\exe-only-20260906-094340-89bffb5d\fapaifang_collector_desktop.exe
```

本次没有修改原启动器、认证 helper、浏览器 profile 或数据目录。启动器仍连接原 NAS LAN API；尚未改成加密隧道地址，也未向桌面分发重启操作令牌。现有桌面快捷方式可以启动新版界面，但“重启”功能尚不可用。

## PC2 接入阻塞与安全停留点

安装目录：

```text
/srv/apps/fapaifang-worker/engine-control/20260906-collection-controls
```

已安装的两个 systemd 服务：

- `crow-nas-api-tunnel.service`
- `crow-engine-controller.service`

尝试使用现有受保护凭据建立仅绑定 PC2 本机 `127.0.0.1:18001` 的 SSH 隧道，没有新增 NAS SSH 公钥。SSH 登录成功，但实际通道请求返回：

```text
channel 1: open failed: administratively prohibited: open failed
```

这证明“SSH 进程 active”不代表隧道可用。控制器没有取得心跳，NAS 诚实返回 `engine_restart.available=false`。两个新服务随后都已 **disabled / inactive**，避免持续重试。没有提交真实重启请求，也没有重启现有 Worker。

后续需要用户确认，才能为现有 NAS 运维账号开放**仅到 `127.0.0.1:8001` 的受限 SSH 转发**。另一种方案是用户明确接受当前局域网 HTTP；目前没有擅自启用这一降级。

权限确认后的剩余步骤：

1. 最小化配置并验证受限转发，不开放任意目的地址。
2. 启用 PC2 隧道和控制器，验证真实 API 请求及心跳，而非只检查进程。
3. 完成 PC1 受保护连接及操作令牌交付。
4. 执行一次受控重启链路验收，核对 8 个原容器 ID、启动时间、健康状态和持久化挂载；不会以伪造回执替代执行。

### 部署前已存在的浏览器异常

PC2 的 8 个 Worker 在最后核验时均为 healthy，镜像仍是 `20260905-compat-recovery`。浏览器容器部署前已 unhealthy，部署后仍然如此：内部 CDP `127.0.0.1:9223/json/version` 超时。没有证据证明 profile 损坏，本次未清理或重建浏览器。

当前重启控制器明确只控制 8 个 Worker，不包含浏览器。因此不能承诺这个按钮能够修复上述浏览器 CDP 卡死；这一既有运行异常需单独处理。

## 验证与回滚材料

本次新鲜验证：

- 相关 Python 回归测试：114 passed。
- 前端概览 Node 测试：6 passed。
- 有效代码行检查器测试：19 passed；ratchet 通过。
- 相关路径 `git diff --check`：通过。
- PC1 安装后哈希、NAS 线上构建标识、5 文件哈希、三阶段 API 和数据库保留检查：通过。

本轮沿用的已验证构建证据：桌面原生 release 构建成功、27 项离线浏览器检查通过；本次未将这些离线结果冒充为新安装 EXE 的现场窗口或人工认证验收。

NAS 回滚镜像：`fapaifang-collector:rollback-20260906-collection-controls`。原环境及 API-only 回滚命令保存在上述 NAS 备份目录的受保护文件中。回滚不应恢复旧数据库覆盖新记录。

本地可核对的非秘密回执：

```text
.debug/collection-controls-20260906/backup-receipt.json
.debug/collection-controls-20260906/deployment-receipt.json
```

工作区原有未提交修改均保留；没有创建提交，也没有清理旧发布或数据。
