// Playwright CLI run-code --filename expects a standalone JavaScript function.
async (page) => {
  const origin = "http://127.0.0.1:1436";
  const checks = [];
  const errors = [];
  const check = (ok, name) => { if (!ok) throw new Error(name); checks.push(name); };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().route("**/*", (route) => route.request().url().startsWith(`${origin}/`) ? route.continue() : route.abort());
  await page.setViewportSize({ width: 1120, height: 760 });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto(origin);
  await page.locator("#openCollection .shell-icon").waitFor();

  const animate = (toggles = [0]) => page.evaluate(async (schedule) => {
    const selectors = ["#toggleSidebar", "#openCollection .shell-icon", "#openSettings .shell-icon"];
    const measure = () => ({
      width: document.querySelector("#appRail").getBoundingClientRect().width,
      centers: selectors.map((selector) => {
        const rect = document.querySelector(selector).getBoundingClientRect();
        return rect.x + rect.width / 2;
      }),
      overflow: document.documentElement.scrollWidth > window.innerWidth,
    });
    const samples = [measure()];
    const start = performance.now();
    let next = 0;
    await new Promise((resolve) => {
      const frame = () => {
        const elapsed = performance.now() - start;
        while (next < schedule.length && elapsed >= schedule[next]) {
          document.querySelector("#toggleSidebar").click();
          next += 1;
        }
        samples.push(measure());
        if (elapsed < schedule.at(-1) + 320) requestAnimationFrame(frame);
        else resolve();
      };
      requestAnimationFrame(frame);
    });
    return samples;
  }, toggles);

  const anchored = (samples, label) => {
    const centers = samples.flatMap((sample) => sample.centers);
    const range = [Math.min(...centers), Math.max(...centers)];
    check(range[1] - range[0] <= 0.5, `${label}: icons share a fixed axis (${range.join(" to ")} px)`);
    check(samples.every((sample) => !sample.overflow), `${label}: no horizontal page overflow`);
  };
  const closeTo = (actual, expected) => Math.abs(actual - expected) < 0.5;
  await page.screenshot({ path: "output/playwright/crow-shell-motion/expanded.png" });
  const collapse = await animate();
  anchored(collapse, "collapse");
  check(closeTo(collapse[0].width, 186) && closeTo(collapse.at(-1).width, 52), "collapse reaches the compact width");
  check(collapse.some((sample) => sample.width > 53 && sample.width < 185), "collapse interpolates instead of jumping");
  check(collapse.every((sample, index) => index === 0 || sample.width <= collapse[index - 1].width + 0.1), "collapse is monotonic");
  await page.screenshot({ path: "output/playwright/crow-shell-motion/collapsed.png" });
  check(await page.locator("#toggleSidebar").getAttribute("aria-expanded") === "false", "compact state is accessible");

  const expand = await animate();
  anchored(expand, "expand");
  check(closeTo(expand.at(-1).width, 186), "expand reaches the full width");
  check(expand.some((sample) => sample.width > 53 && sample.width < 185), "expand interpolates");
  const rapid = await animate([0, 40, 80]);
  anchored(rapid, "rapid reversals");
  check(closeTo(rapid.at(-1).width, 52), "rapid reversals settle at the last requested state");
  await page.locator("#toggleSidebar").focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(260);
  check(await page.locator("#toggleSidebar").getAttribute("aria-expanded") === "true", "keyboard toggle works");
  await page.locator("#openSettings").click();
  await page.locator("#settingsTitle").waitFor();
  await page.keyboard.press("Escape");
  check(await page.locator("#openSettings").evaluate((node) => node === document.activeElement), "settings restores focus");

  await page.emulateMedia({ reducedMotion: "reduce" });
  const reduced = await animate();
  anchored(reduced, "reduced motion");
  check(reduced.every((sample) => closeTo(sample.width, 52) || closeTo(sample.width, 186)), "reduced motion has no intermediate widths");
  await page.setViewportSize({ width: 760, height: 800 });
  await page.locator("#toggleSidebar:disabled").waitFor();
  check(await page.locator("#toggleSidebar").isDisabled(), "narrow layout keeps the compact rail");
  await page.screenshot({ path: "output/playwright/crow-shell-motion/narrow.png" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator("#toggleSidebar:enabled").waitFor();
  check(await page.locator("#toggleSidebar").isEnabled(), "wide layout restores the toggle");
  check(errors.length === 0, `no browser exceptions: ${errors.join("; ")}`);
  return { checks, iconAxis: collapse.at(-1).centers, animationFrames: [collapse.length, expand.length, rapid.length], browserErrors: errors };
}
