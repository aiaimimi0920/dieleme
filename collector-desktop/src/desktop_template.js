import { defaultBrowserApiBase } from "./desktop_state.js";

export function mountTemplate() {
  const app = document.querySelector("#app");
app.innerHTML = `
  <header>
    <h1>FapaiFang 运维观察台</h1>
    <p>本机不运行采集 Worker；PC1 仅负责人工认证，链接、详情和 AI Worker 均运行在 PC2。</p>
  </header>
  <main>
    <section class="panel">
      <div class="toolbar">
        <label>API 地址 <input id="apiBase" class="api-base" value="${defaultBrowserApiBase()}" /></label>
        <button id="applyApiBase">应用地址</button>
        <span class="status-line" id="connectionStatus">读取默认 API 地址中...</span>
      </div>
    </section>
    <section class="cards" id="cards"></section>
    <section class="panel">
      <div class="toolbar">
        <div class="tabs">
          <button data-stage="links" class="active">商品链接采集</button>
          <button data-stage="details">商品详情页采集</button>
          <button data-stage="analysis">商品详情页 AI 分析</button>
        </div>
        <label>每页 <select id="limit"><option selected>10</option><option>20</option><option>50</option></select></label>
        <button id="refresh">刷新</button>
        <button id="prev">上一页</button>
        <button id="next">下一页</button>
        <span class="status-line" id="listStatus"></span>
        <span class="status-line auto-refresh-status" id="autoRefreshStatus">每 60 秒自动刷新</span>
      </div>
    </section>
    <section class="panel region-panel">
      <div class="region-header">
        <div>
          <strong>所在地</strong>
          <span class="status-line" id="regionStageHint">此地区的链接是否已经全部收集完毕</span>
        </div>
        <div class="region-actions">
          <button id="refreshRegions">刷新所在地</button>
          <button id="resetRegionLinks" class="hidden">重置本地区链接采集</button>
        </div>
      </div>
      <div class="status-line region-refresh-status" id="regionRefreshStatus">每 10 分钟自动刷新所在地状态</div>
      <div class="region-level">
        <div class="region-level-title">省份</div>
        <div class="region-tabs" id="provinceTabs"></div>
      </div>
      <div class="region-level">
        <div class="region-level-title">城市</div>
        <div class="region-tabs" id="cityTabs"></div>
      </div>
      <div class="region-level">
        <div class="region-level-title">地区</div>
        <div class="region-tabs" id="districtTabs"></div>
      </div>
    </section>
    <section class="layout detail-hidden" id="contentLayout">
      <div class="panel table-wrap">
        <table>
          <thead><tr><th>商品唯一编号</th><th>商品直达链接</th><th>商品采集地区</th><th>当前采集状态</th></tr></thead>
          <tbody id="items"></tbody>
        </table>
      </div>
      <aside class="panel detail hidden" id="detailPanel">
        <h2 id="detailTitle">已采集 HTML 文本</h2>
        <p class="status-line" id="detailHint">商品详情页采集完成后保存的 HTML/文本内容，用于后续 AI 分析。</p>
        <div class="detail-actions hidden" id="analysisActions">
          <span class="analysis-count" id="analysisAttemptCount">AI 分析次数：-</span>
          <button id="reanalysisButton">AI 再分析</button>
          <button id="editButton">手动编辑</button>
          <button id="manualUpdateButton" class="hidden">手动更新</button>
        </div>
        <div class="status-line" id="detailPath"></div>
        <pre id="detailHtmlText">点击“商品详情页采集”中的任一商品查看。</pre>
        <div class="standardized-rows hidden" id="standardizedRows"></div>
      </aside>
    </section>
  </main>
  <dialog class="auth-dialog" id="authChallengeDialog">
    <div class="auth-dialog-header">
      <div>
        <h2>认证挑战</h2>
        <p>用于处理淘宝登录、验证码或安全验证。后台会自动检测认证恢复；如果没有自动恢复，再点击“我已完成认证，开始”。</p>
      </div>
      <button id="authChallengeClose" aria-label="关闭认证框">关闭</button>
    </div>
    <div class="auth-dialog-toolbar">
      <label>挑战地址 <input id="authChallengeUrl" value="https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1" /></label>
      <button id="authChallengeReload">打开/刷新认证挑战</button>
      <button id="authChallengeQueue">提交认证任务</button>
      <button id="authChallengeResume">我已完成认证，开始</button>
    </div>
    <div class="status-line" id="authChallengeStatus">等待打开认证挑战。</div>
    <div class="auth-instructions">
      <strong>认证窗口会在外部浏览器中打开。</strong>
      <p>淘宝登录和安全挑战通常会阻止被嵌入到桌面应用内。这里不再加载内嵌页面，避免“已阻止此内容”和界面卡顿。请在弹出的浏览器窗口完成认证；后台 watcher 会自动检测恢复并让 PC2 续跑，手动按钮只作为兜底。</p>
    </div>
  </dialog>
`;
}
