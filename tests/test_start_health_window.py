"""启动就绪判定的回归锁（1.2.26）。

1.2.25 的现场故障：ReMe 冷启动重建索引时 ``POST /health_check`` 被拖到 1.5s 边缘，
``wait_for_health`` 每轮都耗尽超时，35s 窗口一到就把**健康进程** terminate 掉
（2026-11-23 09:16 现场：ReMe 侧连续 16 条 health collection 全是 healthy:True，
helper 仍判「启动后健康检查失败」）。

本套分两层：
* 单元层——常量、探测默认值、复核三态、失败留痕、HTTP 异常兜底、线程隔离；
* 集成层——真的走 ``start_service`` / ``stop_service``（stub 掉进程、网络与日志），
  锁住「超时后复核成功 ⇒ 不杀」「复核失败 ⇒ 才杀」「退出请求 ⇒ 不报成功」以及
  探测预算的实参。集成层专门为了抓住「把复核整段回滚」这类变异。

卫生约定：所有 stub 都在 finally 还原；临时目录用 TemporaryDirectory（不留残渣）；
``main.log`` 也一并 stub，避免把假记录写进真实的助手日志。
"""
import http.client
import tempfile
import threading
from pathlib import Path

from conftest import TOOL  # noqa: E402, F401  (puts src/ on sys.path)
import main  # noqa: E402

_PATCHED = (
    "validate_install", "mode_config_path", "reme_root", "reme_exe",
    "probe_health", "terminate_process_tree", "START_HEALTH_TIMEOUT",
    "SERVICE_PROCESS", "SERVICE_LOG_HANDLE", "STATE", "log",
)


def _check(name, fn):
    fn()
    print(f"ok  {name}")


class _Proc:
    """最小 Popen 替身：只关心 poll() 的退出码。"""

    def __init__(self, code):
        self._code = code

    def poll(self):
        return self._code


class _Probe:
    """按序列返回的探测替身，同时记录每次调用的 timeout 实参。"""

    def __init__(self, results):
        self._it = iter(results)
        self._last = results[-1]
        self.calls = []

    def __call__(self, timeout=3.0):
        self.calls.append(timeout)
        try:
            return next(self._it)
        except StopIteration:
            return self._last


class _AbortProbe:
    """预检不触发退出；进入等待后的第一次探测才置 STOP_EVENT。"""

    def __init__(self):
        self.calls = []

    def __call__(self, timeout=3.0):
        self.calls.append(timeout)
        if len(self.calls) >= 2:          # 第 1 次是 Popen 之前的预检
            main.STOP_EVENT.set()
        return False


class _FakePopen:
    def __init__(self, pid=4242):
        self.pid = pid

    def poll(self):
        return None  # 进程始终"活着"


# 1) 判据：单次探测放宽、窗口不延长、停止仍快、复核更宽。
def _constants():
    assert main.START_PROBE_TIMEOUT >= 3.0, main.START_PROBE_TIMEOUT
    assert main.START_HEALTH_TIMEOUT <= 35.0, main.START_HEALTH_TIMEOUT  # 不靠拖长窗口
    assert main.STOP_PROBE_TIMEOUT <= 1.5, main.STOP_PROBE_TIMEOUT
    assert main.CONFIRM_PROBE_TIMEOUT > main.START_PROBE_TIMEOUT, main.CONFIRM_PROBE_TIMEOUT


# 2) wait_for_health 默认按 START_PROBE_TIMEOUT 探测（原来硬编码 1.5）。
def _default_probe_timeout():
    seen = []
    saved = main.probe_health
    try:
        main.probe_health = lambda timeout=3.0: (seen.append(timeout), True)[1]
        assert main.wait_for_health(True, 5) is True
    finally:
        main.probe_health = saved
    assert seen and seen[0] == main.START_PROBE_TIMEOUT, seen


# 3) 复核：进程还在 + 此刻探测得到 -> 已就绪；预算用更宽的 CONFIRM。
def _confirm_healthy():
    probe = _Probe([True])
    saved = main.probe_health
    try:
        main.probe_health = probe
        assert main.confirm_start_after_timeout(_Proc(None)) is True
    finally:
        main.probe_health = saved
    assert probe.calls == [main.CONFIRM_PROBE_TIMEOUT], probe.calls


# 4) 复核：进程已退出 -> 失败，且不再浪费探测。
def _confirm_dead():
    probe = _Probe([True])
    saved = main.probe_health
    try:
        main.probe_health = probe
        assert main.confirm_start_after_timeout(_Proc(1)) is False
    finally:
        main.probe_health = saved
    assert probe.calls == [], probe.calls


# 5) 复核：进程活着但探不到 -> 失败（只有这一支才轮到终止）。
def _confirm_unhealthy():
    saved = main.probe_health
    try:
        main.probe_health = lambda timeout=3.0: False
        assert main.confirm_start_after_timeout(_Proc(None)) is False
    finally:
        main.probe_health = saved


# 6) 探针失败要留下判定依据。
def _probe_detail():
    saved_url = main.health_url
    try:
        main.health_url = lambda: "http://127.0.0.1:1/health_check"  # 必然连不上
        assert main.probe_health(0.5) is False
    finally:
        main.health_url = saved_url
    detail = main.last_probe_detail()
    assert detail, "失败时探测依据不能为空"
    assert "within 0.5s" in detail, detail


# 7) http.client.HTTPException 不得逃出 probe_health（会弄死没有兜底的监控线程）。
def _http_exception_contained():
    saved = main.urllib.request.urlopen

    def _boom(*_a, **_k):
        raise http.client.IncompleteRead(b"partial")  # 既非 OSError 也非 ValueError

    try:
        main.urllib.request.urlopen = _boom
        assert main.probe_health(0.5) is False
    finally:
        main.urllib.request.urlopen = saved
    assert "IncompleteRead" in main.last_probe_detail(), main.last_probe_detail()


# 8) 探测依据按线程隔离，不串台。
def _detail_is_thread_local():
    main._PROBE_LOCAL.detail = "main-thread"
    seen = {}

    def _worker():
        seen["child"] = main.last_probe_detail()

    thread = threading.Thread(target=_worker)
    thread.start()
    thread.join()
    try:
        assert seen["child"] == "", seen          # 子线程读不到主线程的依据
        assert main.last_probe_detail() == "main-thread"
    finally:
        main._PROBE_LOCAL.detail = ""


# ---------- 集成层：真的走 start_service / stop_service ----------

def _run_start(probe):
    """在 stub 环境中跑一次 start_service，返回 (ok, msg, terminated, state)。"""
    terminated = []
    saved = {}
    original_popen = main.subprocess.Popen
    with tempfile.TemporaryDirectory(prefix="reme-helper-start-") as tmp:
        root = Path(tmp)
        try:
            for name in _PATCHED:
                saved[name] = getattr(main, name)
            saved_tunnels = main.CFG.get("start_tunnels_with_reme")

            main.validate_install = lambda mode=None: (True, "")
            main.mode_config_path = lambda mode=None: root / "c.yaml"
            main.reme_root = lambda: root
            main.reme_exe = lambda: root / "reme.exe"
            main.subprocess.Popen = lambda *a, **k: _FakePopen()
            main.probe_health = probe
            main.terminate_process_tree = lambda pid: terminated.append(pid)
            main.START_HEALTH_TIMEOUT = 0.05      # 不等真的 35s
            main.SERVICE_PROCESS = None
            main.SERVICE_LOG_HANDLE = None
            main.STATE = dict(saved["STATE"])
            main.log = lambda *_a, **_k: None     # 别把假记录写进真实日志
            main.CFG["start_tunnels_with_reme"] = False
            main.STOP_EVENT.clear()

            ok, msg = main.start_service("minimal")
            return ok, msg, terminated, dict(main.STATE)
        finally:
            main.STOP_EVENT.clear()
            if main.SERVICE_LOG_HANDLE is not None:
                main.SERVICE_LOG_HANDLE.close()
            main.subprocess.Popen = original_popen
            main.CFG["start_tunnels_with_reme"] = saved_tunnels
            for name, value in saved.items():
                setattr(main, name, value)


# 9) 窗口耗尽 + 进程活 + 复核探得到 -> 报成功、不杀进程、预算按 3s/3s/5s。
def _start_slow_but_healthy():
    probe = _Probe([False, False, True])
    ok, msg, terminated, state = _run_start(probe)
    assert ok is True, (ok, msg)
    assert terminated == [], terminated
    assert probe.calls == [
        main.START_PROBE_TIMEOUT,        # 预检
        main.START_PROBE_TIMEOUT,        # 窗口内
        main.CONFIRM_PROBE_TIMEOUT,      # 复核
    ], probe.calls
    assert state.get("phase") == "running", state


# 10) 窗口耗尽 + 复核也探不到 -> 才终止进程、返回失败。
def _start_really_failed():
    probe = _Probe([False, False, False])
    ok, msg, terminated, state = _run_start(probe)
    assert ok is False, (ok, msg)
    assert "启动后健康检查失败" in msg, msg
    assert terminated == [4242], terminated
    assert state.get("phase") == "error", state


# 11) 等待期间用户退出 -> 不报成功、不走复核、收掉刚起的进程。
def _start_aborted_by_exit():
    probe = _AbortProbe()
    ok, msg, terminated, state = _run_start(probe)
    assert ok is False, (ok, msg)
    assert "取消启动" in msg, msg
    assert terminated == [4242], terminated
    assert probe.calls == [main.START_PROBE_TIMEOUT, main.START_PROBE_TIMEOUT], probe.calls
    assert state.get("phase") == "stopped", state
    assert state.get("healthy") is False, state


class _FakeProc:
    pid = 4242


# 12) 停止流程仍按 1.5s 探测（放宽启动判定不得把「停止」拖慢）。
def _stop_keeps_fast_probe():
    probe = _Probe([False, False])
    saved = {}
    try:
        for name in (
            "matching_reme_processes", "adopted_reme_pid", "terminate_process_tree",
            "probe_health", "SERVICE_PROCESS", "SERVICE_LOG_HANDLE", "STATE", "log",
        ):
            saved[name] = getattr(main, name)
        main.matching_reme_processes = lambda: [_FakeProc()]
        main.adopted_reme_pid = lambda: 4242
        main.terminate_process_tree = lambda pid: None
        main.probe_health = probe
        main.SERVICE_PROCESS = None
        main.SERVICE_LOG_HANDLE = None
        main.STATE = dict(saved["STATE"])
        main.log = lambda *_a, **_k: None
        ok, msg = main.stop_service(include_tunnels=False)
        assert ok is True, (ok, msg)
    finally:
        for name, value in saved.items():
            setattr(main, name, value)
    assert probe.calls[0] == main.STOP_PROBE_TIMEOUT, probe.calls


for _name, _fn in [
    ("判定常量：探测 3s、窗口不延长、停止仍快、复核更宽", _constants),
    ("wait_for_health 默认按 3s 探测", _default_probe_timeout),
    ("复核：活着且探得到 -> 成功（预算 5s）", _confirm_healthy),
    ("复核：进程已退出 -> 失败且不再探测", _confirm_dead),
    ("复核：活着但探不到 -> 失败", _confirm_unhealthy),
    ("探测失败留下线程内判定依据", _probe_detail),
    ("HTTPException 不逃出探测（监控线程不被打断）", _http_exception_contained),
    ("探测依据按线程隔离", _detail_is_thread_local),
    ("start_service：慢启动复核成功，不杀进程", _start_slow_but_healthy),
    ("start_service：复核失败才终止", _start_really_failed),
    ("start_service：退出请求不报成功、收掉进程", _start_aborted_by_exit),
    ("stop_service 仍按 1.5s 探测", _stop_keeps_fast_probe),
]:
    _check(_name, _fn)

print("test_start_health_window: all checks passed")
