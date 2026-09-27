# NOT WIRED YET / 尚未接线

This folder is a byte-identical copy of the family template module (README +
`__init__.py` + `service_link.py`), staged under `src/modules/service_link/`,
but **nothing imports it**: `grep -rn "service_link" src/ tests/ scripts/`
finds only this folder. The G4.2 ADOPTED graceful-shutdown path is still pending
(复审记录.md finding #8), so the live quit flow keeps terminating the attached
service by pid.

本模块是模板正本拷贝（整文件夹已采纳），但**全仓库没有任何调用点**——G4.2 的
ADOPTED 优雅关闭分支尚未接入（REVIEW 发现 #8）。**不要把它当成活代码**；
接线完成之日删除本文件。

This file is reme-local (it has no template counterpart) and is not part of the
template comparison set; the three template files in this folder stay byte-identical
to `my-diy-tool-template/modules/service_link/`.

## D9 核查（2026-09-19）：优雅关闭 API 在服务侧不存在 ⇒ 不可接

REVIEW #8 要求 ADOPTED 停止"优先走服务的优雅关闭 API"。**实测（只读）：该 API 不存在。**

- 运行中的服务（PID 19352，`reme.exe start config=...app-custom.yaml`，服务包 `reme_ai 0.4.1.11`）
  的 OpenAPI 路由表共 **32 条，全部为 `POST /<job>`**，**无 `/shutdown`、`/stop`、`/quit`、`/exit`**。
- 服务源码 `reme/components/service/http_service.py` 只注册两类路由：每个 job 一条 `POST /{name}`
  （`:222`），以及工作区 SPA 的 `GET /{full_path}` 兜底（`:179`）——**无任何控制类端点**。
- 服务配置 `reme/config/default.yaml` 的 job 表**无** stop/shutdown/quit/exit。
- 服务 CLI `reme/reme.py:101` 的动作只有 `start` / `find_reme` / `plugins`，其余一律走
  `call_server(<job>)`——**没有 `reme stop`**。

**结论**：helper 侧无从"先走优雅关闭 API"——**不是 reme-helper 漏接，是服务端没有这条路径**。
按 §D3.2「失败方向必须不破坏」，维持既有回退：只终止规范端点的接入 pid
（`stop_service(only_attached=True)`，`src/main.py:2921`），**不做全量签名击杀**。
**卡点**：需先在 `reme` 服务包上游新增优雅关闭端点/命令（属本工具家族之外的工程），
helper 才能接线；在此之前**不得**用空回调冒充 graceful（假 API 违反 G4.2 条款 3 的意图）。
