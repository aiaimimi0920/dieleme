from tools.test.taobao_login_health_test_context import *  # noqa: F401,F403


def test_open_page_via_cdp_brings_official_verification_page_to_front(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class FakePage:
        url = "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            events.append(f"goto:{url}:{wait_until}:{timeout}")

        def bring_to_front(self) -> None:
            events.append("bring_to_front")

    class FakeContext:
        def new_page(self) -> FakePage:
            events.append("new_page")
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self) -> None:
            events.append("browser_close")

    class FakeChromium:
        def connect_over_cdp(self, endpoint: str, timeout: int | None = None) -> FakeBrowser:
            assert timeout == taobao_login_health.DEFAULT_CDP_CONNECT_TIMEOUT_MS
            events.append(f"connect:{endpoint}")
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            events.append("playwright_close")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = lambda: FakeSyncPlaywright()
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://login.taobao.com/member/login.jhtml",
    )

    assert final_url.endswith("/_____tmd_____/punish")
    assert events[:3] == [
        "connect:http://127.0.0.1:9223",
        "new_page",
        "goto:https://login.taobao.com/member/login.jhtml:domcontentloaded:10000",
    ]
    assert "bring_to_front" in events

def test_open_page_via_cdp_reuses_existing_taobao_verification_tab(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class ExistingTaobaoPage:
        url = "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish"

        def bring_to_front(self) -> None:
            events.append("existing_bring_to_front")

    class FakeContext:
        pages = [ExistingTaobaoPage()]

        def new_page(self):
            events.append("new_page")
            raise AssertionError("should reuse existing Taobao verification tab")

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self) -> None:
            events.append("browser_close")

    class FakeChromium:
        def connect_over_cdp(self, endpoint: str, timeout: int | None = None) -> FakeBrowser:
            assert timeout == taobao_login_health.DEFAULT_CDP_CONNECT_TIMEOUT_MS
            events.append(f"connect:{endpoint}")
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            events.append("playwright_close")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = lambda: FakeSyncPlaywright()
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/list/50025969__2.htm",
    )

    assert final_url.endswith("/_____tmd_____/punish")
    assert events == [
        "connect:http://127.0.0.1:9223",
        "existing_bring_to_front",
        "playwright_close",
    ]

def test_open_page_via_cdp_reuses_existing_solver_target_tab(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class ExistingSolverPage:
        url = "https://contest.local/auth?__captcha_solver_bg=1"

        def bring_to_front(self) -> None:
            events.append("existing_solver_bring_to_front")

    class FakeContext:
        pages = [ExistingSolverPage()]

        def new_page(self):
            events.append("new_page")
            raise AssertionError("should reuse existing solver target tab")

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self) -> None:
            events.append("browser_close")

    class FakeChromium:
        def connect_over_cdp(self, endpoint: str, timeout: int | None = None) -> FakeBrowser:
            assert timeout == taobao_login_health.DEFAULT_CDP_CONNECT_TIMEOUT_MS
            events.append(f"connect:{endpoint}")
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            events.append("playwright_close")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = lambda: FakeSyncPlaywright()
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://contest.local/auth?__captcha_solver_bg=1",
    )

    assert final_url == "https://contest.local/auth?__captcha_solver_bg=1"
    assert events == [
        "connect:http://127.0.0.1:9223",
        "existing_solver_bring_to_front",
        "playwright_close",
    ]

def test_open_page_via_cdp_creates_worker_master_even_when_solver_tab_exists(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class ExistingSolverPage:
        url = "https://sf.taobao.com/list/blocked/_____tmd_____/punish?__captcha_solver_bg=1"

        def bring_to_front(self) -> None:
            events.append("existing_solver_bring_to_front")

    class NewWorkerPage:
        url = "https://sf.taobao.com/?__captcha_worker_master=1"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            events.append(f"goto:{url}:{wait_until}:{timeout}")
            self.url = url

        def bring_to_front(self) -> None:
            events.append("new_worker_bring_to_front")

    class FakeContext:
        pages = [ExistingSolverPage()]

        def new_page(self) -> NewWorkerPage:
            events.append("new_page")
            return NewWorkerPage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self) -> None:
            events.append("browser_close")

    class FakeChromium:
        def connect_over_cdp(self, endpoint: str, timeout: int | None = None) -> FakeBrowser:
            assert timeout == taobao_login_health.DEFAULT_CDP_CONNECT_TIMEOUT_MS
            events.append(f"connect:{endpoint}")
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            events.append("playwright_close")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = lambda: FakeSyncPlaywright()
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://sf.taobao.com/?__captcha_worker_master=1",
    )

    assert final_url == "https://sf.taobao.com/?__captcha_worker_master=1"
    assert "existing_solver_bring_to_front" not in events
    assert events[:3] == [
        "connect:http://127.0.0.1:9223",
        "new_page",
        "goto:https://sf.taobao.com/?__captcha_worker_master=1:domcontentloaded:10000",
    ]
    assert "new_worker_bring_to_front" in events

def test_open_page_via_cdp_creates_solver_target_even_when_worker_master_exists(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class ExistingWorkerPage:
        url = "https://sf.taobao.com/?__captcha_worker_master=1"

        def bring_to_front(self) -> None:
            events.append("existing_worker_bring_to_front")

    class NewSolverPage:
        url = "https://contest.local/auth?__captcha_solver_bg=1"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            events.append(f"goto:{url}:{wait_until}:{timeout}")
            self.url = url

        def bring_to_front(self) -> None:
            events.append("new_solver_bring_to_front")

    class FakeContext:
        pages = [ExistingWorkerPage()]

        def new_page(self) -> NewSolverPage:
            events.append("new_page")
            return NewSolverPage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self) -> None:
            events.append("browser_close")

    class FakeChromium:
        def connect_over_cdp(self, endpoint: str, timeout: int | None = None) -> FakeBrowser:
            assert timeout == taobao_login_health.DEFAULT_CDP_CONNECT_TIMEOUT_MS
            events.append(f"connect:{endpoint}")
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            events.append("playwright_close")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = lambda: FakeSyncPlaywright()
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://contest.local/auth?__captcha_solver_bg=1",
    )

    assert final_url == "https://contest.local/auth?__captcha_solver_bg=1"
    assert "existing_worker_bring_to_front" not in events
    assert events[:3] == [
        "connect:http://127.0.0.1:9223",
        "new_page",
        "goto:https://contest.local/auth?__captcha_solver_bg=1:domcontentloaded:10000",
    ]
    assert "new_solver_bring_to_front" in events

def test_open_page_via_cdp_does_not_reuse_plain_sf_taobao_tab(monkeypatch) -> None:
    events: list[str] = []
    _force_playwright_open(monkeypatch)

    class ExistingPlainSfPage:
        url = "https://sf.taobao.com/list/50025969__2.htm"

        def bring_to_front(self) -> None:
            events.append("plain_bring_to_front")

    class NewVerificationPage:
        url = "https://login.taobao.com/member/login.jhtml"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            events.append(f"goto:{url}:{wait_until}:{timeout}")

        def bring_to_front(self) -> None:
            events.append("new_bring_to_front")

    class FakeContext:
        pages = [ExistingPlainSfPage()]

        def new_page(self) -> NewVerificationPage:
            events.append("new_page")
            return NewVerificationPage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self) -> None:
            events.append("browser_close")

    class FakeChromium:
        def connect_over_cdp(self, endpoint: str, timeout: int | None = None) -> FakeBrowser:
            assert timeout == taobao_login_health.DEFAULT_CDP_CONNECT_TIMEOUT_MS
            events.append(f"connect:{endpoint}")
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb) -> None:
            events.append("playwright_close")

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = lambda: FakeSyncPlaywright()
    fake_playwright = types.ModuleType("playwright")
    fake_playwright.sync_api = fake_sync_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    final_url = taobao_login_health.open_page_via_cdp(
        "http://127.0.0.1:9223",
        "https://login.taobao.com/member/login.jhtml",
    )

    assert final_url == "https://login.taobao.com/member/login.jhtml"
    assert "plain_bring_to_front" not in events
    assert events[:3] == [
        "connect:http://127.0.0.1:9223",
        "new_page",
        "goto:https://login.taobao.com/member/login.jhtml:domcontentloaded:10000",
    ]
    assert "new_bring_to_front" in events
