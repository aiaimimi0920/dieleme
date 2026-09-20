import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { mountShellIcons } from "./desktop_shell_icons";

function element<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing shell element: ${id}`);
  return node as T;
}

export function initializeShell(refresh: () => Promise<void>): void {
  mountShellIcons();
  const shell = element("appShell");
  const railToggle = element<HTMLButtonElement>("toggleSidebar");
  const settingsButton = element<HTMLButtonElement>("openSettings");
  const backButton = element<HTMLButtonElement>("closeSettings");
  const collection = element("collectionPage");
  const settings = element("settingsPage");
  const scrollArea = collection.closest("main");
  let collectionScroll = 0;
  const collectionButton = element<HTMLButtonElement>("openCollection");
  const narrow = window.matchMedia("(max-width: 820px)");
  let collapsed = false;

  const updateRail = () => {
    const compact = narrow.matches || collapsed;
    shell.classList.toggle("rail-collapsed", compact);
    railToggle.disabled = narrow.matches;
    railToggle.setAttribute("aria-expanded", String(!compact));
    railToggle.setAttribute("aria-label", compact ? "展开侧栏" : "收起侧栏");
    railToggle.title = narrow.matches ? "窄窗口使用紧凑侧栏" : railToggle.getAttribute("aria-label") || "";
  };
  railToggle.addEventListener("click", () => { collapsed = !collapsed; updateRail(); });
  narrow.addEventListener("change", updateRail);
  updateRail();

  const showSettings = (show: boolean, restoreFocus = true) => {
    if (show) {
      collectionScroll = scrollArea?.scrollTop || 0;
    }
    collection.classList.toggle("hidden", show);
    settings.classList.toggle("hidden", !show);
    backButton.classList.toggle("hidden", !show);
    settingsButton.classList.toggle("active", show);
    settingsButton.setAttribute("aria-pressed", String(show));
    collectionButton.classList.toggle("active", !show);
    collectionButton.setAttribute("aria-pressed", String(!show));
    if (show) element("settingsTitle").focus();
    else if (restoreFocus) settingsButton.focus();
    if (scrollArea) scrollArea.scrollTop = show ? 0 : collectionScroll;
  };
  settingsButton.addEventListener("click", () => {
    if (settings.classList.contains("hidden")) showSettings(true);
  });
  backButton.addEventListener("click", () => showSettings(false));
  collectionButton.addEventListener("click", () => {
    if (!settings.classList.contains("hidden")) showSettings(false, false);
  });
  settings.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); showSettings(false); }
  });

  element("windowRefresh").addEventListener("click", () => void refresh());
  if (!isTauri()) return;
  document.querySelectorAll<HTMLElement>("[data-window-command]").forEach((button) => button.classList.remove("hidden"));
  const appWindow = getCurrentWindow();
  const runWindowCommand = async (command: string) => {
    try {
      if (command === "minimize") await appWindow.minimize();
      else if (command === "maximize") await appWindow.toggleMaximize();
      else if (command === "close") await appWindow.close();
      else if (command === "drag") await appWindow.startDragging();
    } catch (error) {
      const notice = element("shellNotice");
      notice.textContent = `窗口操作失败：${error instanceof Error ? error.message : String(error)}`;
      notice.classList.remove("hidden");
    }
  };
  document.querySelectorAll<HTMLElement>("[data-window-command]").forEach((button) => {
    button.addEventListener("click", () => void runWindowCommand(button.dataset.windowCommand || ""));
  });
  document.querySelectorAll<HTMLElement>("[data-window-drag]").forEach((region) => {
    region.addEventListener("mousedown", (event) => {
      if (event.button !== 0 || (event.target instanceof Element && event.target.closest("button"))) return;
      void runWindowCommand(event.detail === 2 ? "maximize" : "drag");
    });
  });
}
