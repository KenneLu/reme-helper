"""测试共用基线：让测试脚本不依赖本机 config.json 的当前内容。

build.bat 会把源码目录的 config.json 打进新发布包，所以用户正常改一次设置之后，
源码目录那份就不再是「干净的固定预设」了。而不少断言把固定预设当作基线——
"回到基线"应当不可用、草稿与预设的折叠判定、公共参数与 PRESET_LLM /
PRESET_EMBEDDING / PRESET_PIPELINE 的比较——本机配置一旦带着改过的 llm 参数
（例如 thinking_enable=true、reasoning_effort=max），构建就会挂在门禁上。

凡是要在生成器或设置窗口上做断言的测试脚本，请在最前面调用 pin_clean_baseline()。
"""

from conftest import TOOL  # noqa: E402, F401  (puts src/ on sys.path)
import main  # noqa: E402

__all__ = ["pin_clean_baseline"]


def pin_clean_baseline() -> None:
    """把 CFG 钉成确定性基线：基础模式 + 预设公共设置。

    只动断言真正依赖的字段；reme_root、targets、ui_lang、theme 等保持本机真实值，
    所以 validate_install / 日志目录 / 托盘菜单那些测试照旧跑真实的 ReMe 安装。
    """
    main.CFG["mode"] = "minimal"
    main.CFG["custom"] = dict(main.MINIMAL_FEATURES)
    main.CFG["llm"].update(main.PRESET_LLM)
    main.CFG["embedding"].update(main.PRESET_EMBEDDING)
    main.CFG["pipeline"] = dict(main.PRESET_PIPELINE)
    # 用内置兜底名单而不是 default_expose_jobs()：测试要求确定性，不该随本机装的
    # ReMe 版本里 default.yaml 的 job 表变化。生成器写盘前本来就会按真实名单过滤。
    main.CFG["expose"] = {"custom": False, "jobs": list(main.EXPOSE_DEFAULT_FALLBACK)}
