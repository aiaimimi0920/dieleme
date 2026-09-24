# 用户脚本生成产物的门禁调整提案

状态：用户已在原会话确认单个生成安装文件例外；实现及隔离门禁已验证。
下文原始度量保留为批准前的审查依据，最新状态见文末。

`tampermonkey_scripts/fapaifang_unified.user.js` 是当前唯一超过 1500 行有效代码的
文件，1909 行有效代码、2420 行物理行。它必须作为一个 Tampermonkey 安装文件保留
metadata、grants、加载顺序和共享 IIFE；这也是源目录 README 的现行约定。
全部写接口鉴权需要修改脚本的 HTTP helper，并重新生成安装文件。
现有规则只允许这个历史文件在内容不变时保留，因此不能直接修改后宣称门禁通过。

## 本次核验依据

- 当前 checkout HEAD：`a571e41127ae2fb7093ef09467f7230c83e7f113`。
- 有效行数 baseline source commit：`a9228125623b16588f5bfda604faecb8a9c87aba`。
- baseline source tree：`a76752dc80811662401770d40693daed4391a31f`。
- 当前 policy SHA-256：`d9fb03d2de91fc87dd1d3dd488dde00ad6aea3007fb3c729641b7689452f1439`。
- 安装文件原始 bytes SHA-256：
  `c2bece5a6656e920a8dd633dd6c98bb88e66652a64f48f0cbb1a6928c5e86fc0`。
- 换行规范化后的 source SHA-256：
  `145ef726b10d4b5d91a40a73237be5c191dcb3b5209aab4022cd06cf6ba12dac`。
- `node scripts/build-userscript.mjs --check` 已通过；上述规范化 hash 同时被
  `scripts/tests/build-userscript.test.mjs` 中的原始行为检查固定。
- 当前 ratchet 扫描 1049 个源码文件，只有上述安装文件超过 700 行。
  JSON 报告的 files 字段只列超限文件；完整扫描已确认以下 12 个源文件均在门禁范围内。

源目录统一为 `tampermonkey_scripts/src/fapaifang_unified/`：

| 文件 | 有效行数 |
|---|---:|
| `00_bootstrap.js` | 111 |
| `10_sniff_collection.js` | 174 |
| `20_sniff_challenge.js` | 147 |
| `30_sniff_dashboard.js` | 189 |
| `40_fast_review_loop.js` | 235 |
| `50_fast_review_item.js` | 181 |
| `60_slow_review.js` | 93 |
| `70_detail_worker.js` | 78 |
| `80_detail_helper_context.js` | 275 |
| `90_detail_helper_panel.js` | 250 |
| `100_detail_helper_actions.js` | 141 |
| `110_dispatch_and_captcha.js` | 58 |

## 请求确认的调整范围

仅将上述一个可重复生成的安装文件作为生成产物处理，保留全部 12 个源文件的现行
有效行数检查，并将输出一致性检查和完整安装脚本的 Node 语法检查绑定到本地/CI 门禁。
手改安装文件、缺少输入、输出过期必须失败；不把整个 userscript 目录排除，也不放宽
手写产品代码、测试代码或其他历史超限文件。

如果用户同意，实施时需显式记录 policy/checker 的差异和更新后的完整生成 hash；
不得重新生成整份 baseline 来吸收其他尚未解决的技术债。原始 baseline 的源码 commit、
文件 hash 和其他超限记录继续保留可审查依据。

该提案不删除或迁移任何业务数据、Cookie、浏览器 profile、备份或 release，也不授权
提前部署。用户确认后，仍须先完成客户端及服务端鉴权迁移和负向回归。

## 批准后的实现与验证

用户在会话 `01a0c091-c79b-70b2-8bf4-4f2a71f54996` 对上述单文件提案回复确认。
后续会话 `01a0c1e9-3fe4-7702-b02e-aeaaab206410` 已实施生成门禁和鉴权脚本。
本次恢复执行后重新运行四个 Node 测试文件，51 项全部通过；ratchet 扫描 1054 个
文件通过。生成例外只适用于 `tampermonkey_scripts/fapaifang_unified.user.js`，
全部手写片段继续受原行数规则约束；缺失片段、手改/过期输出、语法错误和新增例外
均有拒绝测试。没有重新生成历史 baseline inventory。

实际文件 SHA-256：

- policy：`fefe606091b4fe9e8242ef3b4be4b6fa5ab603856b1f23c5c4090bb396a07c8a`
- checker：`c32afc9d7ef36587fde774348de876e9b2b566b93047c4ec3b6299876edde40c`
- builder：`fcfe29bac731ce6c37931008e70866a2f12fbd7b2cbac091754590436d4eba5b`
- 安装文件原始 bytes：`c0b66b6766f9bcb701e5693bdcb366147489208a7e4314601a61f08b49bf9daf`
- 安装文件规范化内容：`775624987431dbee86ba43c07d4a624327853d74496c27314ee87e72c44c45e4`

baseline source commit 仍为 `a9228125623b16588f5bfda604faecb8a9c87aba`，source tree
仍为 `a76752dc80811662401770d40693daed4391a31f`；更新的是已批准的工具完整性元数据。
这次批准不适用于测试目录放宽或其他源码例外，也不改变暂缓部署和保留全部数据的要求。
