# 房奴炼狱 Web App

这个目录是仓库内唯一的 Vite/Vue 前端子项目。

## 常用命令

```powershell
npm install
npm run dev
```

如果当前仓库是从 UNC 路径直接打开，而你想从 repo root 稳定启动本地开发服务器，可以改用：

```powershell
python tools\dev_web_app.py
```

默认会在：

- `http://127.0.0.1:43177/`

启动 Vite dev server，并自动把工作目录切到可用的本地盘映射。

## 生产构建

### 普通本地盘路径

如果当前工作目录已经是本地盘路径，可以直接运行：

```powershell
npm run build
```

当前 `build` 脚本会先生成本地 `runtime-tailwind.css`，再执行 `vite build`，因此生产构建不会再依赖 `cdn.tailwindcss.com`。

### Windows + UNC 工作目录

如果项目是从类似下面的 UNC 路径直接打开的：

- `\\192.168.15.200\home\project\project\fapaifang\game\web-app`

那么直接执行 `npm run build` 可能会触发 Windows `CMD.EXE` 的 UNC 当前目录限制，并让 Vite 报出类似：

- `UNC paths are not supported`
- `Could not resolve entry module "index.html"`

针对这个场景，仓库根目录提供了一个构建 helper：

```powershell
python tools\build_web_app.py
```

这个 helper 会：

1. 检测当前前端目录是否位于 UNC 路径
2. 收集当前主机上所有匹配的本地盘网络映射
3. 依次尝试这些本地盘候选路径，直到找到能成功执行 `npm run build` 的构建入口

如果本机没有对应的盘符映射，helper 会明确报错，而不是停在 Vite 的误导性入口解析错误上。

## 本地预览

如果希望从仓库根目录直接起一个可供浏览器 smoke 的静态预览，可以运行：

```powershell
python tools\preview_web_app.py
```

默认会在：

- `http://127.0.0.1:43173/`

启动一个基于 `dist/` 的本地预览服务。
