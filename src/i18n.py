"""中英对照文案表 —— 一个配置表，一式两份。

用法：main.py 里的界面文案照旧写中文，`t()` 会在英文模式下查这张表。
表里一行一个词条：左边是源码里写的中文，右边是英文。改文案时两列一起看即可。

规则（由 test_i18n.py 自动检查）：
  * 中文列不能重复（否则无法判断该用哪条）；
  * 英文列不能为空、不能残留中文（漏译会当场红灯）；
  * main.py 里出现的每一条中文字面量，要么在本表里，要么在 EXEMPT 里（附理由）；
  * 两个字符以上的词条同时充当「片段」：像 「已保存：xxx（窗口保持打开）」 这种拼接出来的
    句子，会按最长片段替换成英文；一个字的词条只做整串匹配（否则「中」会到处误伤）。

检查命令：
    python main.py --lang-audit      # 打印未收录的中文，并生成 i18n_review.md（左右对照）
"""
from __future__ import annotations

TEXT: list[tuple[str, str]] = [
    # ================= 1. 应用、窗口、模式 =================
    ("ReMe 助手", "ReMe Helper"),
    ("控制台说明", "Console guide"),
    ("运行与模式", "Runtime and mode"),
    ("模式", "Mode"),
    ("基线", "Baseline"),
    ("服务", "Service"),
    ("未保存改动", "Unsaved"),
    ("基础模式", "Basic"),
    ("全功能模式", "Full"),
    ("自定义模式", "Custom"),
    ("已保存配置", "Saved config"),
    ("运行中", "Running"),
    ("已停止", "Stopped"),
    ("启动中", "Starting"),
    ("停止中", "Stopping"),
    ("异常", "Error"),
    ("未安装", "Not installed"),
    ("就绪", "Ready"),
    ("未启用", "Off"),
    ("可用", "Ready"),
    ("未测试", "Untested"),
    ("缺地址/Key", "Missing URL/key"),
    ("主题", "Theme"),
    ("深色", "Dark"),
    ("浅色", "Light"),
    ("深色模式", "Dark mode"),
    ("中文", "中文"),
    ("English / 中文", "English / 中文"),
    ("前两项是固定预设：改动其中任意一项，会自动转为自定义模式（可撤销）。",
     "The first two are fixed presets: editing anything in them switches to Custom (undoable)."),
    ("不调用模型；手动写记忆，关键词检索", "No model calls; write memories by hand, keyword search"),
    ("自动整理记忆；需在【LLM 与模型】填 Key", "Consolidates memory automatically; needs a key in LLM and models"),
    ("按需挑选能力（官方默认 + 你的选择）", "Pick capabilities you need (official defaults + your choices)"),
    ("选择…", "Browse…"),
    ("扫描…", "Scan…"),
    ("确定", "OK"),
    ("取消", "Cancel"),
    ("删除", "Delete"),
    ("关闭", "Close"),
    ("开启", "On"),
    ("是", "Yes"),
    ("否", "No"),
    ("无", "None"),
    ("默认", "Default"),
    ("功能", "Feature"),
    ("效果", "Effect"),
    ("依赖", "Depends on"),
    ("（无）", "(none)"),
    ("未发现", "Not found"),
    ("无密钥", "No key"),
    ("已配置", "configured"),
    ("未配置", "not set"),
    ("停用", "Off"),
    ("（空）", "(empty)"),
    ("（新增）", "(new)"),
    ("允许内部思考", "Allow internal thinking"),
    ("每次最沉淀", "Units per run"),
    ("自定义选择", "Custom selection"),
    ("暴露的 Job", "Exposed jobs"),
    ("确定退出 ReMe 助手？", "Quit ReMe Helper?"),
    ("退出会同时停止 VM 隧道和由助手启动的 ReMe 服务。", "Quitting also stops the VM tunnels and the ReMe service that this helper started."),
    ("；留空＝不改）", "; leave blank to keep)"),
    ("（来自 .env）", "(from .env)"),
    ("（测试）", "(test)"),
    ("（时间未知）", "(time unknown)"),

    # ================= 2. 功能表：名称 / 效果 =================
    ("记忆的产生", "How memories appear"),
    ("检索与成本", "Retrieval and cost"),
    ("界面与接入", "UI and integration"),
    ("把对话整理为daily记忆卡片", "Turn conversations into daily memory cards"),
    ("从Claude Code会话生成daily记忆", "Create daily memories from Claude Code sessions"),
    ("监听resource并自动生成资料卡片", "Watch resources/ and generate material cards"),
    ("每天把变化的daily提炼、关联和纠正到digest",
     "Each day, distil, link and correct changed daily notes into digest"),
    ("读取已有的主动主题", "Read existing proactive topics"),
    ("提供ReMe内部只读Agent聊天入口", "Chat entry for ReMe's read-only internal agent"),
    ("增强近义、中英混合和改写召回", "Better recall for paraphrases, mixed CN/EN and rewrites"),
    ("大量向量时加速近邻检索", "Speeds up nearest-neighbour search at scale"),
    ("浏览、编辑、搜索和查看运行状态", "Browse, edit, search and inspect runtime status"),
    ("让Codex和其他MCP客户端使用ReMe工具", "Let Codex and other MCP clients use ReMe tools"),
    ("每批对话产生模型调用；更及时也更耗token",
     "A model call per batch of chats; more timely, more tokens"),
    ("不用Claude Code时没有价值；被调用时产生模型费用",
     "Worthless without Claude Code; model charges apply when it is called"),
    ("LLM；图像需视觉模型", "LLM; images need a vision model"),
    ("大文件或批量资料可能显著增加token、内存和处理时间",
     "Large or bulk material can add a lot of tokens, memory and processing time"),
    ("抽取一次且每个unit再调用Agent；默认最多5个unit",
     "One extraction, then one agent call per unit; 5 units per run by default"),
    ("已有兴趣主题", "Existing interest topics"),
    ("读取本身低成本；0.4.1.11默认配置不生成新主题",
     "Reading is cheap; the 0.4.1.11 default writes no new topics"),
    ("Codex/DSH已有Agent时通常不需要，会增加模型调用",
     "Usually unnecessary when Codex/DSH already has an agent; adds model calls"),
    ("Embedding模型或API", "Embedding model or API"),
    ("新增/修改和查询需要向量计算；可能产生API费用",
     "Writes and queries need vector math; may incur API charges"),
    ("增加索引内存和重建时间；小库收益有限",
     "More index memory and longer rebuilds; little gain on small stores"),
    ("少量Web服务开销，不调用LLM", "A little web-service overhead; no LLM calls"),
    ("只注册工具；实际成本由调用的Job决定",
     "Registers tools only; the real cost depends on the jobs you call"),

    # ================= 3. 整理计划 / cron =================
    ("整理计划", "Consolidation schedule"),
    ("扫描天数", "Scan days"),
    ("每次最多沉淀", "Max units per run"),
    ("下次整理：", "Next consolidation: "),
    ("下次整理：每天 ", "Next consolidation: daily "),
    ("下次整理：按自定义计划执行", "Next consolidation: runs on your custom schedule"),
    ("cron 格式不正确，将回退为每天 23:00", "Invalid cron format; falling back to daily 23:00"),
    ("每天 23:00（默认）", "Daily 23:00 (default)"),
    ("每天 03:00", "Daily 03:00"),
    ("每天 12:00", "Daily 12:00"),
    ("自定义…", "Custom…"),
    ("定时表达式，五个字段依次是 分 时 日 月 周。例如 0 23 * * * 表示每天 23:00。",
     "A cron expression: minute hour day month weekday — 0 23 * * * means daily at 23:00."),
    ("自动整理的频率、范围与上限。auto_dream 是常规操作里最贵的一环。",
     "How often consolidation runs, and how much it covers. auto_dream is the most expensive routine step."),
    ("立即整理一次（auto_dream）：调用模型把 daily 沉淀为 digest，产生 token 费用。",
     "Consolidate now (auto_dream): calls the model to distil daily notes into digest; token charges apply."),

    # ================= 4. 整理记录（从日志解析） =================
    ("刷新整理记录", "Refresh consolidation log"),
    ("还没有整理记录", "No consolidation record yet"),
    ("还没有日志目录", "No log directory yet"),
    ("还没有日志", "No log yet"),
    ("读取日志失败", "Reading the log failed"),
    ("正在安全退出：正在停止 VM 隧道和由助手启动的 ReMe…", "Exiting safely: stopping VM tunnels and ReMe started by the helper…"),
    ("应用正在退出，已取消启动 ReMe", "The app is exiting; starting ReMe was cancelled"),
    ("应用正在退出，已取消启动 ", "The app is exiting; starting "),
    (" 隧道", " tunnel was cancelled"),
    ("上次整理：", "Last consolidation: "),
    ("上次整理失败：", "Last consolidation failed: "),
    (" · 写入 ", " · wrote "),
    (" 个节点", " node(s)"),
    (" · 已整合 ", " · integrated "),
    (" 个单元", " unit(s)"),
    ("，失败 ", ", failed "),
    ("，错误 ", ", errors "),
    (" 项", " item(s)"),
    (" · 判定无新内容，直接跳过（未消耗 token）", " · no changed input, skipped (no tokens spent)"),
    ("（扫描 ", "(scanned"),
    (" 个文件、其中 ", " file(s), "),
    (" 个有变化", " changed"),
    ("，跳过 ", ", skipped "),
    (" 个单元）", "unit(s))"),
    ("（跳过 ", "(skipped"),
    ("整理中…", "Consolidating…"),
    ("立即整理一次", "Consolidate now"),
    ("重建索引", "Rebuild index"),

    # ================= 5. LLM 与模型 =================
    ("LLM 与模型", "LLM and models"),
    ("LLM 参数", "LLM settings"),
    ("地址", "Address"),
    ("模型", "Model"),
    ("思考强度", "Reasoning effort"),
    ("刷新模型", "Reload models"),
    ("允许内部思考（建议保持关闭）", "Allow internal thinking (keep off)"),
    ("不设置", "Not set"),
    ("低", "Low"),
    ("中", "Medium"),
    ("高", "High"),
    ("极高", "Very high"),
    ("最大", "Max"),
    ("极限", "Ultimate"),
    ("最小", "Minimal"),
    # ---- reasoning 能力：档位是怎么算出来的（见 main.effort_options）----
    ("该后台没有 reasoning_effort 参数，无需设置。",
     "This backend has no reasoning_effort parameter, so there is nothing to set."),
    ("端点声明该模型支持：", "The endpoint declares this model supports: "),
    ("（仅供参考；可选项以本机 ReMe 的合法集合为准）",
     " (reference only; the selectable levels follow what this machine's ReMe accepts)"),
    # ---- MCP 工具暴露：允许列表（名字与分组见 main.EXPOSE_JOB_GROUPS）----
    ("记忆读写", "Memory read / write"),
    ("检索与浏览", "Search and browse"),
    ("索引与维护", "Index and upkeep"),
    ("自动记忆", "Automatic memory"),
    ("服务信息", "Service info"),
    ("其他 Job", "Other jobs"),
    ("read（读一个记忆文件）", "read (read one memory file)"),
    ("write（新建记忆文件）", "write (create a memory file)"),
    ("edit（精确替换记忆内容）", "edit (replace exact content)"),
    ("save（整份覆盖保存）", "save (overwrite the whole file)"),
    ("load（整份载入文件）", "load (load the whole file)"),
    ("daily_write（写当天的卡片）", "daily_write (write today's card)"),
    ("read_image（读图片，需视觉模型）", "read_image (read an image; needs a vision model)"),
    ("frontmatter_read（读文件头字段）", "frontmatter_read (read header fields)"),
    ("frontmatter_update（改文件头字段）", "frontmatter_update (change header fields)"),
    ("frontmatter_delete（删文件头字段）", "frontmatter_delete (remove header fields)"),
    ("search（关键词 / 语义检索）", "search (keyword / semantic search)"),
    ("node_search（按节点检索）", "node_search (search by node)"),
    ("traverse（沿关系图遍历）", "traverse (walk the link graph)"),
    ("graph_snapshot（导出关系图快照）", "graph_snapshot (export a graph snapshot)"),
    ("list（列目录）", "list (list a directory)"),
    ("stat（看文件元信息）", "stat (file metadata)"),
    ("daily_list（列 daily 卡片）", "daily_list (list daily cards)"),
    ("reindex（重建检索索引）", "reindex (rebuild the search index)"),
    ("daily_reindex（重建 daily 索引）", "daily_reindex (rebuild the daily index)"),
    ("move（移动记忆文件）", "move (move a memory file)"),
    ("delete（删除记忆文件）", "delete (delete a memory file)"),
    ("auto_memory（把对话提炼成记忆）", "auto_memory (distill a conversation into memory)"),
    ("auto_memory_cc（从 Claude Code 会话提炼）", "auto_memory_cc (distill a Claude Code session)"),
    ("auto_dream（立刻整理成长期记忆）", "auto_dream (consolidate into long-term memory now)"),
    ("auto_resource（把资料转成卡片）", "auto_resource (turn a resource into a card)"),
    ("proactive（读当天的兴趣主题）", "proactive (read today's interest topics)"),
    ("chat（对话，仅 HTTP / SSE）", "chat (conversation; HTTP / SSE only)"),
    ("health_check（健康检查）", "health_check (health probe)"),
    ("status（服务状态）", "status (service status)"),
    ("version（版本号）", "version (version number)"),
    ("help（列出全部 Job）", "help (list every job)"),
    ("app_config（导出生效配置，密钥已脱敏）",
     "app_config (export the effective config; secrets are redacted)"),
    ("其他 Agent（Codex / VS Code）通过 HTTP 与 MCP 能主动调用的操作。"
     "这里只决定「外部能不能调」；ReMe 自己的定时任务（索引维护、做梦）不受影响。",
     "What other agents (Codex / VS Code) can call over HTTP and MCP. This only decides "
     "whether outside callers can reach a job; ReMe's own scheduled work (index upkeep, "
     "dreaming) is unaffected."),
    # ---- 允许列表：二选一 + 四级标记 + 说明（见 main.EXPOSE_JOB_INFO）----
    ("必留", "Keep"),
    ("推荐", "Recommended"),
    ("可选", "Optional"),
    ("慎开", "Risky"),
    ("官方默认：全部开放", "ReMe default: everything open"),
    ("不写 service.jobs，ReMe 的原生行为：注册进服务的每个 Job 都对外开放。"
     "普通用户保持这一项即可；它和没装这个助手时的行为完全一致。",
     "No service.jobs is written - ReMe's native behaviour: every job registered with the "
     "service stays open. Most users should keep this; it behaves exactly as if this helper "
     "were not installed."),
    ("自定义：只开放我勾选的", "Custom: only what I tick"),
    ("写 service.jobs，只把下面勾选的 Job 对外开放。"
     "适合「虚拟机里的 Agent 只该读写记忆」这类场景。"
     "没勾的 Job 外部调不到，但 ReMe 内部的定时任务照常使用它们。",
     "Writes service.jobs and opens only the ticked jobs. Meant for cases such as \"agents "
     "inside a VM should only read and write memories\". Unticked jobs are unreachable from "
     "outside, but ReMe's own scheduled work keeps using them."),
    ("什么时候用官方默认：只是自己用、外部客户端也都在本机 → 保持全开最省事。"
     "什么时候用自定义：虚拟机等外部 Agent 只该读写记忆、你不想让它们删改 → 收窄。",
     "When to keep the default: it is just you and your clients run on this machine - leaving "
     "everything open is the least fuss. When to go custom: outside agents such as a VM should "
     "only read and write memories and you do not want them to change or delete anything - "
     "narrow it down."),
    ("只勾推荐", "Recommended only"),
    ("勾上「必留」与「推荐」两组，也就是外部 Agent 读写记忆需要的那些；慎开项一律不勾。",
     "Ticks the Keep and Recommended groups - what an outside agent needs to read and write "
     "memories. Risky items stay unticked."),
    ("全选", "Select all"),
    ("32 项全勾上，风险最大，只有在确实需要时才用。",
     "Ticks all 32 jobs. The largest exposure; use it only when you really need it."),
    ("全不选", "Select none"),
    ("一项都不勾＝不写白名单＝全部开放，和不选「自定义」是一样的效果。",
     "Nothing ticked means no allowlist is written and everything stays open - the same as not "
     "choosing Custom."),
    ("有 {count} 项在当前模式或功能开关下不存在，已灰掉且不能勾：",
     "Not present under the current mode or feature switches ({count} greyed out and not "
     "selectable): "),
    ("健康检查。ReMe 助手自己的「服务」状态探测、DSH 插件的状态卡片读的就是它，"
     "不勾会让两边都显示成服务没起来。",
     "Health probe. This helper's own service check and the DSH plugin's status card read "
     "exactly this job; unticking it makes both report the service as down."),
    ("服务状态。同上：助手与 DSH 插件都靠它判断服务是否在跑。",
     "Service status. Same as above: the helper and the DSH plugin both rely on it."),
    ("读取一个记忆文件的内容。外部 Agent 回忆时的基本动作。",
     "Read one memory file. The basic move when an outside agent recalls something."),
    ("新建一个记忆文件。精确写入的前提，通常和 edit 配对使用。",
     "Create a memory file. The prerequisite for precise writes, usually paired with edit."),
    ("精确替换记忆文件里的内容。比整份覆盖安全，建议保留。",
     "Replace exact content inside a memory file. Safer than overwriting the whole file; "
     "recommended to keep."),
    ("关键词 / 语义检索。回忆的入口。", "Keyword / semantic search. The entry point for recall."),
    ("沿关系图（[[链接]]）遍历相关记忆，从一条记忆找到关联的其它记忆。",
     "Walk the link graph ([[links]]) from one memory to the memories it relates to."),
    ("列出目录内容，用来发现有哪些记忆文件。",
     "List a directory, to discover which memory files exist."),
    ("看一个文件的元信息（大小、修改时间等），不改内容。",
     "File metadata (size, modified time and so on) without changing anything."),
    ("整份覆盖保存文件。用传入内容替换整个文件，比 edit 粗放。",
     "Overwrite the whole file with the given content. Coarser than edit."),
    ("整份载入文件内容，read 的变体，一次把文件全部读出来。",
     "Load the whole file content; a variant of read."),
    ("写当天的 daily 卡片，也就是对话记忆的落地形式。",
     "Write today's daily card, the on-disk form of conversation memory."),
    ("读取图片内容。没配视觉模型时没有意义。",
     "Read an image. Pointless unless a vision model is configured."),
    ("读取文件头（--- 之间的字段，例如 tags、title）。",
     "Read the file header (the fields between ---, such as tags and title)."),
    ("修改文件头字段，不动正文。", "Change header fields without touching the body."),
    ("按节点（沉淀后的长期记忆单元）检索，比全文检索更聚焦。",
     "Search by node (a consolidated long-term memory unit); more focused than full-text search."),
    ("导出关系图快照，用于整体查看记忆之间的连接。",
     "Export a snapshot of the link graph, to see how memories connect."),
    ("列出所有 daily 卡片。", "List every daily card."),
    ("把一段对话提炼成记忆卡片。DSH 插件的后台工具会调它。",
     "Distill a conversation into memory cards. The DSH plugin's background tool calls it."),
    ("从 Claude Code 会话提炼记忆。不用 Claude Code 时没有价值。",
     "Distill memory from a Claude Code session. Worthless if you do not use Claude Code."),
    ("立刻把 daily 整理沉淀成长期记忆，相当于手动触发一次「做梦」。",
     "Consolidate today's dailies into long-term memory now - a manual \"dream\"."),
    ("把 resource 目录里的资料转成卡片。大文件会明显增加 token 与耗时。",
     "Turn files under resource into cards. Large files clearly raise token cost and time."),
    ("读当天的兴趣主题（daily/<日期>/interests.yaml）。",
     "Read today's interest topics (daily/<date>/interests.yaml)."),
    ("对话入口。只提供 HTTP / SSE 流式接口，不是 MCP 工具。",
     "Conversation entry point. HTTP / SSE only; not an MCP tool."),
    ("返回 ReMe 版本号。无副作用，排查问题时有用。",
     "Return the ReMe version. No side effects; handy when troubleshooting."),
    ("列出全部 Job 及其参数。排查与探索用。",
     "List every job and its parameters. For troubleshooting and exploration."),
    ("导出生效配置。密钥类字段会被脱敏（api_key / token 等显示成 ***）。",
     "Export the effective config. Secret fields are redacted (api_key / token show as ***)."),
    ("删除记忆文件。删掉就没了，外部 Agent 一旦被误导会真的删数据。",
     "Delete a memory file. It is gone for good; a misled outside agent will really delete data."),
    ("移动 / 重命名记忆文件，会改变引用路径。",
     "Move / rename a memory file. Changes the paths other memories refer to."),
    ("删除文件头字段，属于破坏性修改。", "Remove header fields; a destructive edit."),
    ("重建检索索引。不改内容，但会明显占用 CPU 与时间。",
     "Rebuild the search index. Does not change content, but uses noticeable CPU and time."),
    ("重建 daily 卡片索引。同上，代价明显。",
     "Rebuild the daily card index. Same story: the cost is real."),
    ("读写记忆文件本身。外部 Agent 的日常动作主要落在这里。",
     "Reading and writing the memory files themselves. Most day-to-day work by outside agents "
     "happens here."),
    ("把记忆找出来。这一组都是只读的。",
     "Finding memories again. Everything in this group is read-only."),
    ("会改动已有数据、或重建索引，默认不勾。",
     "Changes existing data or rebuilds indexes, so these stay unticked by default."),
    ("触发 ReMe 的记忆生产线（提炼、整理、资料转卡）。",
     "Triggers ReMe's memory production line (distilling, consolidating, turning resources into "
     "cards)."),
    ("服务自身的信息类 Job，无副作用；其中 health_check 与 status 是必留项。",
     "Informational jobs about the service itself, with no side effects; health_check and "
     "status are required."),
    ("官方新增、分组表里还没归档的 Job。",
     "New jobs shipped by ReMe that the grouping table does not cover yet."),
    ("已开放 {exposed}/{total}：", "Open: {exposed}/{total}"),
    # ---- ReMe 版本与更新（见 main.reme_versions / check_reme_update / reme_upgrade_prompt）----
    ("未知", "unknown"),
    ("映射端口不要复用机器上其它工具已占用的本地端口，挑一个空闲的高位端口即可，否则隧道建不起来。",
     "Do not reuse a local port that another tool on this machine already occupies; pick a free "
     "high port, otherwise the tunnel will not come up."),
    ("## 接入客户端", "## Connecting clients"),
    ("- Codex 之类的客户端在配置里加 `url = \"http://127.0.0.1:2333/mcp\"` 就能用它的记忆工具。",
     "- Clients such as Codex just add `url = \"http://127.0.0.1:2333/mcp\"` to their config to use "
     "its memory tools."),
    ("- DeepSeek Harness 另有官方 ReMe 插件（见官方文档的 typescript 一节）。装之前先卸掉别的记忆插件，",
     "- DeepSeek Harness has its own official ReMe plugin (see the typescript section of the "
     "official docs). Uninstall any other memory plugin first:"),
    ("  不要同时启用两套自动记忆，否则同一段对话会被整理两遍。",
     "  never run two automatic-memory systems at once, or the same conversation gets distilled "
     "twice."),
    ("三种模式的配置（app.yaml / app-full.yaml / app-custom.yaml）都由本工具从 ReMe 自带的",
     "All three mode configs (app.yaml / app-full.yaml / app-custom.yaml) are generated by this "
     "tool from the default.yaml that ships with ReMe:"),
    ("default.yaml 现场生成，装完就有、随时可重建，不需要手工维护。升级 ReMe 之后回到这里",
     "they exist as soon as ReMe is installed, can be rebuilt at any time, and need no manual "
     "upkeep. After upgrading ReMe, come back here"),
    ("重新保存一次，三份配置就会按新版本的 default.yaml 重建。",
     "and save once - all three are then rebuilt from the new default.yaml."),
    ("配置生成失败：", "Could not generate the config: "),
    ("官方default配置结构异常：", "The official default config has an unexpected structure: "),
    ("ReMe版本：", "ReMe version: "),
    ("（检查更新失败）", " (update check failed)"),
    ("（有新版 ", " (new version available: "),
    ("（已是最新）", " (up to date)"),
    ("检查 ReMe 更新", "Check for ReMe updates"),
    ("复制 ReMe 更新步骤（交给 AI 执行）", "Copy ReMe update steps (for an AI to run)"),
    ("更新步骤已复制，粘贴给 AI 完成更新",
     "Update steps copied - paste them into an AI to finish the upgrade"),
    ("复制失败，请稍后再试", "Copy failed, please try again"),
    ("响应里没有可用的稳定版本号", "The response contained no usable stable version"),
    ("没检测到 ReMe，先安装再检查更新", "No ReMe found; install it before checking for updates"),
    ("检查更新失败：", "Update check failed: "),
    ("（这是 GitHub 的匿名访问配额，同一网络下的其他工具也会消耗它；"
     "过几分钟再试即可，不是配置问题）",
     " (this is GitHub's anonymous rate limit, shared with other tools on the same network - "
     "wait a few minutes and retry; nothing is misconfigured)"),
    # ---- ReMe 助手自己的更新（见 main.check_helper_update / download_and_apply_helper_update）----
    ("检查 ReMe 助手更新", "Check for ReMe Helper updates"),
    ("下载并更新 ReMe 助手", "Download and update ReMe Helper"),
    ("发布页上没有可下载的 zip", "The release page has no downloadable zip"),
    ("有新版本，点「下载并更新」会自动替换并重启",
     "A new version is available; \"Download and update\" replaces it and restarts"),
    ("已是最新版本", "Up to date"),
    ("下载更新包失败：", "Could not download the update package: "),
    ("校验更新包失败：", "Could not verify the update package: "),
    ("更新包校验失败：sha256 对不上", "Update package checksum mismatch"),
    ("解压更新包失败：", "Could not extract the update package: "),
    ("更新包里没有 ", "The update package has no "),
    ("启动更新程序失败：", "Could not start the updater: "),
    ("更新已开始，本窗口会关闭；新版本会自己起来",
     "Update started; this window closes and the new version starts itself"),
    # ---- 检查/更新时的对话框（见 main.ui_dialog 与 tray_check_reme_update /
    #      tray_check_helper_update / run_helper_update）----
    ("ReMe助手版本：", "ReMe Helper version: "),
    ("好", "OK"),
    ("稍后", "Later"),
    ("立即更新", "Update now"),
    ("立即重启", "Restart now"),
    ("更新 ReMe 助手", "Update ReMe Helper"),
    ("有新版本 ", "A new version is available: "),
    ("更新 ReMe 会动配置、依赖与配套工具，所以由 AI 按步骤执行：点下面的按钮复制提示词，粘贴给 AI 即可。",
     "Updating ReMe touches its config, dependencies and companion tools, so an AI runs it step by step: "
     "copy the prompt below and paste it into your AI."),
    ("点「立即更新」会自动下载、校验，把当前版本留在 _backup，然后重启。",
     "Click \"Update now\": the package is downloaded and verified, the current build is kept in _backup, "
     "and the app restarts."),
    ("替换完成后新版本会自己启动；点「立即重启」马上开始。",
     "The new version starts itself once the swap finishes; click \"Restart now\" to begin immediately."),
    # ---- 托盘图标注册失败（见 main.warn_tray_registration_failed）----
    ("托盘图标未能注册", "The tray icon could not be registered"),
    ("程序在运行，但通知区里没有它的图标 —— 点哪里都不会有反应。",
     "The app is running, but it has no icon in the notification area, so clicking anything will "
     "do nothing."),
    ("原因是外壳（Explorer）暂时拒绝了这次注册，跟程序放在哪个目录无关；助手已经改用另一种身份继续重试。",
     "The shell (Explorer) refused this registration for now; it is not about which folder the app "
     "sits in, and the helper has switched to another identity and keeps retrying."),
    ("如果图标始终不出现：在任务管理器里重启「Windows 资源管理器」（任务栏会闪一下），"
     "然后重新启动本程序；或者注销／重启一次。每次尝试的结果都写在下面的日志里。",
     "If the icon never appears: restart \"Windows Explorer\" in Task Manager (the taskbar will "
     "flicker), then start this app again; or sign out / reboot. Every attempt is written to the "
     "log below."),
    # ---- 助手自己的更新提示词（见 main.helper_upgrade_prompt）----
    ("复制 ReMe 助手更新步骤（交给 AI 执行）", "Copy ReMe Helper update steps (for an AI to run)"),
    ("（还没查过，请自行查 GitHub Releases 的最新 tag）",
     " (not checked yet; look up the latest tag on GitHub Releases)"),
    ("请帮我更新这台机器上的 ReMe 助手（Windows 托盘工具）。",
     "Please update ReMe Helper (the Windows tray tool) on this machine."),
    ("（exe 固定叫 reme-helper.exe，名字不带版本号）",
     " (the exe is always reme-helper.exe, never versioned)"),
    ("配置与日志：", "Config and logs: "),
    ("（已不在安装目录里）", " (no longer inside the install directory)"),
    (" 的 reme-helper 值，存的是 exe 的完整路径",
     "'s reme-helper value, which stores the full path to the exe"),
    ("允许：读源码与 CHANGELOG、读配置、拉 GitHub Release 的元数据与 sha256。",
     "Allowed: read the sources and CHANGELOG, read the config, fetch the release metadata and sha256."),
    ("在我说「执行」之前：不要下载替换、不要停止服务、不要改注册表。",
     "Before I say \"execute\": do not download, replace, stop services, or touch the registry."),
    ("2. 新版有哪些变化（读 CHANGELOG.md）", "2. What changed in the new version (read CHANGELOG.md)"),
    ("3. 影响面：配置格式变没变、自启指向的 exe 路径会不会变、ReMe 与隧道要不要重启",
     "3. Impact: did the config format change, does the autostart exe path change, do ReMe and the tunnels need a restart"),
    ("4. 更新步骤：编号、简明、每一步带决策点",
     "4. Update steps: numbered, concise, each with its decision point"),
    ("6. 结论：有问题就列出来；没问题就说「没有问题」，然后停下等我回复「执行」",
     "6. Verdict: list the problems if there are any; if not, say \"no problems\" and stop until I reply \"execute\""),
    ("1. 先备份整个安装目录（更新脚本自己也会备份到 %LOCALAPPDATA%\\reme-helper\\_backup）",
     "1. Back up the whole install directory first (the updater keeps its own copy in %LOCALAPPDATA%\\reme-helper\\_backup)"),
    ("2. 退出运行中的助手：reme-helper.exe --quit",
     "2. Stop the running helper: reme-helper.exe --quit"),
    ("3. 下载 zip 与 .sha256，校验通过再解压",
     "3. Download the zip and its .sha256, verify, then extract"),
    ("4. 把解压结果铺到安装目录，重启 reme-helper.exe",
     "4. Copy the extracted files over the install directory and restart reme-helper.exe"),
    ("5. 验证：health_check 通过、托盘版本行显示新版本",
     "5. Verify: health_check passes and the tray version line shows the new version"),
    ("6. 回报新版本号", "6. Report the new version number"),
    ("- 不要改 %LOCALAPPDATA%\\reme-helper\\config.json 的内容（需要时只备份）",
     "- Do not modify %LOCALAPPDATA%\\reme-helper\\config.json (only back it up if needed)"),
    ("- 不要动 ReMe 的 workspace 与 .env", "- Do not touch ReMe's workspace or .env"),
    ("助手更新步骤已复制，粘贴给 AI 完成更新",
     "Helper update steps copied; paste them to an AI to finish the update"),
    ("（离线，或者 PyPI 被代理拦了？）", " (offline, or is PyPI blocked by a proxy?)"),
    ("ReMe 有新版本 ", "ReMe has a new version: "),
    ("（本机 ", " (this machine: "),
    ("）。右键「复制 ReMe 更新步骤（交给 AI 执行）」",
     "). Right-click \"Copy ReMe update steps (for an AI to run)\""),
    ("ReMe 已是最新版本 ", "ReMe is up to date: "),
    # ---- 升级提示词：两段式（先分析回报，等用户确认「执行」才动手）----
    ("请帮我升级这台机器上的 ReMe（本地优先的长期记忆服务）。",
     "Please upgrade ReMe (the local-first long-term memory service) on this Windows machine."),
    ("先只做分析，把方案报给我；等我说「执行」再动手。",
     "Analyse only first and report the plan back to me; wait until I say \"execute\" "
     "before touching anything."),
    ("## 现状", "## Current state"),
    ("安装根目录：", "Install root: "),
    ("（venv 在同一目录下）", " (the venv lives in the same directory)"),
    ("当前版本：", "Current version: "),
    ("，pip 安装，extra 是 [core]", ", installed with pip, extra is [core]"),
    ("目标版本：", "Target version: "),
    ("（PyPI 最新稳定版；以你自己查到的为准）",
     " (the latest stable release on PyPI; verify it yourself)"),
    ("还没查过，请自行查 PyPI 上的最新稳定版",
     " (not checked yet - look up the latest stable release on PyPI yourself)"),
    ("（待确认）", " (to be confirmed)"),
    ("，当前", ", currently "),
    ("配套工具：", "Companion tool: "),
    ("，负责生成配置、启停服务、VM 隧道",
     ", which generates the configs, starts and stops the service, and manages the VM tunnel"),
    ("## 第一阶段：只分析，不动手", "## Phase 1: analysis only, change nothing"),
    ("允许的动作：查 PyPI、把新版 wheel 下载到临时目录解包对比、读 config/ 与日志、"
     "读包的 METADATA。",
     "Allowed actions: query PyPI, download the new wheel into a temporary directory and unpack "
     "it for comparison, read config/ and the logs, read the package METADATA."),
    ("在我说「执行」之前：不要运行任何 pip 安装命令、不要停启服务、不要改任何配置文件。",
     "Until I say \"execute\": do not run any pip install command, do not start or stop the "
     "service, and do not modify any configuration file."),
    ("请按这个格式回报：", "Report back in exactly this format: "),
    ("1. 版本与来源：当前 → 目标，数据从哪来",
     "1. Version and source: current -> target, and where the data came from"),
    ("2. 会影响什么：新版 default.yaml 的 job 表差异（新增 / 删除 / 改名了哪些）；"
     "依赖变化，尤其是 agentscope 的 pin（现在是 ==2.0.7.post1）",
     "2. What this affects: how the new default.yaml job table differs (which jobs were added, "
     "removed or renamed); dependency changes, especially the agentscope pin (currently "
     "==2.0.7.post1)"),
    ("3. 需要联动 ReMe 助手的地方：升级后要用它重新生成三份配置（app.yaml / app-full.yaml / "
     "app-custom.yaml）；要重启它（它启动时才重新内省思考强度档位的合法集合）；"
     "要重新核对 MCP 工具暴露白名单（新 default.yaml 的 job 表可能变了）；助手本身不用重装",
     "3. Where the ReMe helper has to follow along: after the upgrade, use it to regenerate all "
     "three configs (app.yaml / app-full.yaml / app-custom.yaml); restart it (it re-introspects "
     "the valid reasoning-effort levels at startup); re-check the MCP tool exposure allowlist "
     "(the new default.yaml may have a different job table); the helper itself needs no "
     "reinstall"),
    ("4. 升级步骤：编号、简明、每一步带决策点",
     "4. Upgrade steps: numbered, concise, each with its decision point"),
    ("5. 风险与回滚：回滚要给出一条具体命令",
     "5. Risks and rollback: give one concrete rollback command"),
    ("6. 结论：有问题就把问题列出来；没问题就说「没有问题」，然后停下等我回复「执行」",
     "6. Conclusion: list any problems you found; if there are none, say \"no problems\" and stop "
     "until I reply \"execute\""),
    ("## 第二阶段：我说「执行」之后", "## Phase 2: after I say \"execute\""),
    ("1. 先备份：完整复制 workspace（我的记忆本体），再备份 config\\ 与 .env。"
     "备份是复制，不是移动。",
     "1. Back up first: copy the whole workspace (my memories) somewhere safe, then back up "
     "config\\ and .env. A backup is a copy, not a move."),
    ("2. 确认服务已停止（本机由 ReMe 助手的托盘菜单启停）。",
     "2. Make sure the service is stopped (the ReMe helper's tray menu starts and stops it)."),
    ("用同一个 extra 升级：", "Upgrade with the same extra: "),
    ("4. 打开 ReMe 助手控制台，逐项核对后点「验证并保存」，重新生成配置。",
     "4. Open the ReMe helper console, review each item and click \"Validate and save\" to "
     "regenerate the configs."),
    ("5. 起服务验证：health_check、Studio 页面、reme version；"
     "再用助手跑一次「测试连接」确认 LLM / Embedding 仍可用。",
     "5. Start the service and verify: health_check, the Studio page, reme version; then run the "
     "helper's \"Test connection\" once to confirm LLM / Embedding still work."),
    ("6. 回报新版本号，以及第 2 项里预判的差异是否属实。",
     "6. Report the new version, and whether the differences predicted in item 2 were accurate."),
    ("## 硬约束", "## Hard constraints"),
    ("- 不要改动 .env 与 workspace 的内容（只备份）",
     "- Do not modify the contents of .env or workspace (back them up only)"),
    ("- 不要用 --no-deps「图省事」", "- Do not use --no-deps to cut corners"),
    ("- 保持 [core] extra，否则会丢掉 agentscope 与 reme_studio",
     "- Keep the [core] extra, otherwise agentscope and reme_studio get dropped"),
    ("- 只升级 ReMe，ReMe 助手不用动",
     "- Upgrade ReMe only; the ReMe helper does not need to change"),
    ("- 任何一步失败就停下来告诉我，不要自行绕过",
     "- If any step fails, stop and tell me; do not work around it on your own"),
    ("当前没有可对外暴露的 Job：MCP 功能关掉了，或者当前模式下这些 Job 都不存在。",
     "Nothing can be exposed right now: either the MCP feature is off, or none of these jobs "
     "exists in the current mode."),
    ("下面这些 Job 全部对外开放，含会改动或删除记忆的那些——"
     "ReMe 的 HTTP 没有鉴权，能连上 2333 的进程都能调。",
     "Every job below is open to outside callers, including the ones that change or delete "
     "memories. ReMe's HTTP has no authentication, so any process that can reach port 2333 can "
     "call them."),
    ("一项都没勾＝不写白名单＝全部对外开放，和上面不勾时一样。",
     "nothing is ticked, so no allowlist is written and everything stays open - exactly the "
     "same as leaving the box above unticked."),
    ("外部只能调勾选的这些，其余的外部调不到，但 ReMe 内部的索引维护与做梦照常运行。",
     "outside callers can only use the ticked jobs. The rest are unreachable from outside, "
     "but ReMe's own index upkeep and dreaming keep running."),
    (" 注意：health_check 与 status 没勾——helper 自己的健康探测、"
     "DSH 插件的状态卡片读的就是这两个，会显示成服务没起来。",
     " Note: health_check and status are unticked. This helper's own health probe and the DSH "
     "plugin's status card read exactly those two, so both will report the service as down."),
    ("端点未提供模型能力信息，这里按本机 ReMe 的合法集合显示。",
     "The endpoint exposes no capability metadata, so this list is what this machine's ReMe accepts."),
    ("原档位不被当前后台或模型接受，已清空为不设置：",
     "The previous level is not accepted by the current backend or model and was cleared to Not set: "),
    ("（含能力信息）", " (with capability metadata)"),
    ("s，这次带了 reasoning_effort=", "s, this run carried reasoning_effort="),
    # ---- 非法档位在保存/启动前被拦下时的说明（main.validate_install）----
    ("思考强度“", "Reasoning effort \""),
    ("”不被当前后台（", "\" is not accepted by the current backend ("),
    ("）接受。\n\n", ").\n\n"),
    ("ReMe 把 reasoning_effort 交给 agentscope 校验，取值是固定集合；填错了会在",
     "ReMe validates reasoning_effort through agentscope against a fixed set; a wrong value makes the service"),
    ("启动时直接失败（连网络请求都发不出去）。\n",
     " fail at startup, before any network request is sent.\n"),
    ("当前可用：", "Available: "),
    ("（该后台不支持这一项，请选“不设置”）", "(this backend does not support it; choose \"Not set\")"),
    ("请在【LLM 与模型】里重新选择后再保存。",
     "Pick a valid level under [LLM and models], then save again."),
    ("写记忆用的模型。地址与 Key 保存在 .env，保存时写入。",
     "The model that writes memories. Address and key live in .env and are written on save."),
    ("测试连接", "Test connection"),
    ("打开 .env", "Open .env"),
    ("未启用需要模型的能力，LLM 参数暂不影响运行。",
     "No model-backed feature is enabled, so LLM settings do not affect anything yet."),
    ("负责“写与整理记忆”的模型：把对话提炼成卡片、把卡片沉淀成长期记忆。需要在【LLM 与模型】里填地址与 API Key。", "The model that writes and consolidates memory: chats become cards, cards become long-term memory. Fill the address and API key in [LLM and models]."),
    ("模型的计费单位，约等于字数。开启带模型的能力后，按实际用量计费。",
     "The model's billing unit, roughly a character count. Once a model-backed feature is on you pay by usage."),
    ("思考强度（reasoning_effort）：档位越高，模型在回答前思考得越久，也越费 token。可选档位不是照抄某个客户端：先取本机 ReMe 使用的 agentscope 模型类接受的集合，再与该模型声明的档位取交集；写出集合外的值会让服务在启动时直接失败。不确定时保持“不设置”。", "Reasoning effort: the higher the level, the longer the model thinks before answering, and the more tokens it spends. The available levels are not copied from any client: they are what the agentscope model class ReMe uses accepts, intersected with what the model itself declares. A value outside that set makes the service fail at startup. Keep \"Not set\" when unsure."),
    ("建议 ≥8192；过小会导致记忆提炼写出空内容。",
     "8192 or more is recommended; too small makes consolidation write empty content."),
    ("对应配置 thinking_enable：开启后模型先推理再输出，容易把 token 预算花在推理上，导致记忆提炼返回空内容。", "Maps to thinking_enable: the model reasons before answering, which can spend the token budget on reasoning and make consolidation return empty content."),
    ("发给模型的参数：reasoning_effort=", "Parameter sent to the model: reasoning_effort="),
    ("（不发送）", "(not sent)"),
    ("\n默认：由模型自行决定", "\nDefault: decided by the model"),
    ("需与模型输出一致，否则检索不可用。", "Must match the model's output, or retrieval will not work."),
    ("缺地址或模型名：填好后点“测试连接”。",
     "Missing base URL or model name: fill them in, then click Test connection."),
    ("请先填写 Base URL 与模型名。", "Fill in the base URL and model name first."),
    ("请先填写 Base URL", "Fill in the base URL first"),
    ("正在从端点读取模型列表…", "Reading the model list from the endpoint…"),
    ("读取到 ", "Loaded "),
    (" 个模型", " model(s)"),
    ("端点没有返回任何模型", "The endpoint returned no models"),
    ("返回结构不是 OpenAI 兼容的模型列表", "The response is not an OpenAI-compatible model list"),
    ("正在测试（最长 60s）…", "Testing (up to 60s)…"),
    ("需要 LLM_API_KEY（本地网关可填任意值，例如 sk-local）。",
     "LLM_API_KEY is required (any value works for a local gateway, e.g. sk-local)."),
    ("需要 LLM_API_KEY：未测试", "LLM_API_KEY required: not tested"),
    ("✘ 缺少地址或模型名：未测试", "✘ Missing base URL or model name: not tested"),
    ("缺少 Base URL 或模型名：未测试", "Missing base URL or model name: not tested"),
    ("已验证：对话接口可用 + 能按要求输出 JSON（", "Verified: chat endpoint works and returns the required JSON ("),
    ("接口可用，但未按要求输出 JSON（", "Endpoint works, but did not return the required JSON ("),
    ("。记忆提炼依赖结构化输出，建议换模型或提高 max_tokens。",
     ". Consolidation needs structured output — try another model or raise max_tokens."),
    ("连通但 content 为空（", "Reachable but empty content ("),
    ("连通但返回空内容（", "Reachable but returned empty content ("),
    ("调用失败（", "Call failed ("),
    ("返回结构异常（", "Unexpected response ("),
    ("s）：模型把预算花在 reasoning 上。请提高 max_tokens 或保持“允许内部思考”关闭，否则 auto_dream 会写出空内容。", "s): the model spent its budget on reasoning. Raise max_tokens or keep \"Allow internal thinking\" off, otherwise auto_dream writes empty content."),
    ("上次测试：", "Last test: "),
    ("ReMe 未运行，请先启动服务", "ReMe is not running — start the service first"),

    # ================= 6. Embedding =================
    ("Embedding（语义检索）", "Embedding (semantic search)"),
    ("启用语义检索", "Enable semantic search"),
    ("维度", "Dimensions"),
    ("测试 Embedding", "Test Embedding"),
    ("按语义检索，与 LLM 分开配置；同一份记忆可用不同服务。",
     "Semantic retrieval, configured separately from the LLM; one memory store may use different services."),
    ("负责“按意思找”的检索模型：忘了原词也能搜到（搜“打包没反应”能命中“构建卡死”）。与 LLM 分开配置，通常不是同一个服务。", "The retrieval model (search by meaning): you can find a note without the exact words (searching \"packaging does nothing\" hits \"build hangs\"). Configured separately from the LLM; usually another service."),
    ("请先填写 Embedding 的地址与模型名。", "Fill in the Embedding address and model name first."),
    ("请先填写 Embedding 的地址与模型", "Fill in the Embedding address and model first"),
    ("正在测试 Embedding（最长 45s）…", "Testing Embedding (up to 45s)…"),
    ("需要 EMBEDDING_API_KEY。", "EMBEDDING_API_KEY is required."),
    ("✘ 需要 EMBEDDING_API_KEY：未测试", "✘ EMBEDDING_API_KEY required: not tested"),
    ("已验证：embedding 接口可用 + 语义排序正常（近义 ", "Verified: embedding works and semantic ordering is correct (related"),
    (" > 无关 ", " > unrelated "),
    (" ≤ 无关 ", " ≤ unrelated "),
    (" 一致，但语义排序异常（近义 ", "matches, but semantic ordering is wrong (related"),
    ("s）：该模型可能不适合中文检索，或模型名/维度填错了。", "s): the model may be unsuited to this language, or the model name / dimensions are wrong."),
    ("），维度 ", "), dimensions"),
    ("端点返回 ", "The endpoint returned "),
    (" 维，与配置的 ", " dimensions, but "),
    (" 维不一致（", "are configured ("),
    ("s）。必须把“维度”改成一致，否则检索结果不可用（改完要重建索引）。", "s). The Dimensions field must match, or retrieval results are unusable (rebuild the index afterwards)."),
    ("；该端点不接受 dimensions 参数，按原生维度返回",
     "; this endpoint does not accept a dimensions parameter and returns its native size"),
    ("该端点不提供 embedding（HTTP 404，", "This endpoint offers no embedding (HTTP 404,"),
    ("s）。换一个端点，或改用本地模型。", "s). Use another endpoint or a local model."),
    ("今天股市大涨", "The stock market surged today"),
    ("小猫爱吃鱼", "The kitten loves fish"),
    ("猫喜欢吃鱼", "Cats like eating fish"),
    ("Embedding 尚未通过测试，启用后很可能不生效。\n\n仍要保存吗？",
     "Embedding has not passed its test yet, so it will probably not take effect.\n\nSave anyway?"),
    ("未通过测试也可保存，但不会生效", "You can save without a passing test, but it will not take effect"),

    # ================= 7. 自定义模式功能 / MCP 暴露 =================
    ("自定义模式功能", "Custom-mode features"),
    ("自定义允许列表（不勾选＝沿用 ReMe 默认）",
     "Custom allow-list (unchecked = ReMe defaults)"),
    ("逐项开关；关闭只停用入口或后台 Job，不删除已有数据。",
     "Per-feature switches; turning one off only disables its entry point or background job — data is kept."),
    ("基础模式下不存在的 Job 会被禁用。", "Jobs missing from Basic mode are disabled."),
    ("MCP 工具暴露", "MCP tools"),
    ("MCP 暴露", "MCP exposure"),
    ("其他 Agent（Codex / VS Code）可用的记忆操作。write / edit 是精确写入的前提。",
     "Memory operations other agents (Codex / VS Code) may call. write / edit enable precise writes."),
    ("search（检索）", "search (query memory)"),
    ("read（读文件）", "read (read files)"),
    ("write（新建记忆）", "write (create memory)"),
    ("edit（修改记忆）", "edit (update memory)"),
    ("traverse（关系遍历）", "traverse (walk links)"),
    ("auto_memory（手动捕获）", "auto_memory (capture now)"),
    ("auto_dream（手动整理）", "auto_dream (consolidate now)"),
    ("proactive_read（读兴趣主题）", "proactive_read (read topics)"),
    ("启用自动记忆与整理（Auto Memory + Auto Dream）",
     "Enable automatic memory and consolidation (Auto Memory + Auto Dream)"),
    ("已开启自动记忆与整理", "Automatic memory and consolidation enabled"),
    ("已关闭自动记忆与整理", "Automatic memory and consolidation disabled"),
    ("部分启用：", "Partly enabled: "),
    ("仅 Auto Memory（没有整理）", "Auto Memory only (no consolidation)"),
    ("仅 Auto Dream（没有自动记录）", "Auto Dream only (no auto capture)"),
    ("；可在下方“自定义模式功能”里逐项调整。",
     "; adjust them one by one under Custom-mode features below."),
    ("已开启：对话自动提炼为每日卡片，并按计划沉淀为长期记忆。",
     "On: chats are distilled into daily cards and consolidated into long-term memory on schedule."),
    (" ⚠ LLM 未就绪，现在还不会真正运行。", " ⚠ LLM is not ready, so nothing runs yet."),
    ("（需要【LLM 与模型】可用）", " (needs a working LLM and models setup)"),
    ("未开启：记忆只由你手动写入（BM25 与关系检索仍可用）。勾选后会自动转为自定义模式，并需要【LLM 与模型】可用。", "Off: memories are only written by hand (BM25 and link retrieval still work). Ticking it switches to Custom mode and needs a working LLM and models setup."),
    ("Auto Dream 未启用：不会自动整理，也不会产生长期节点。",
     "Auto Dream is off: nothing is consolidated and no long-term nodes are written."),
    ("当前不可用 —— ", " Not available right now — "),
    ("现在可用。", "Available now."),
    ("\n重建索引（reindex）：不调用模型、不产生费用，只需服务运行中",
     "\nRebuild index (reindex): no model calls, no charges, only needs the service running"),
    ("（当前不可用）。", " (currently unavailable)."),
    ("（现在可用）。", " (available now)."),

    # ================= 8. VM 隧道目标 =================
    ("VM 隧道目标", "VM tunnel targets"),
    ("VM目标", "VM targets"),
    ("VM隧道：", "VM tunnels: "),
    ("把 Windows 上的 ReMe 反向映射给虚拟机内的 Agent。",
     "Expose the Windows-side ReMe to agents inside your VM."),
    ("启动全部VM隧道", "Start all VM tunnels"),
    ("停止全部VM隧道", "Stop all VM tunnels"),
    ("ReMe启动后启动隧道", "Start tunnels with ReMe"),
    ("添加…", "Add…"),
    ("编辑…", "Edit…"),
    ("添加/编辑/删除作用于上表选中的那一行",
     "Add / Edit / Delete act on the row selected above"),
    ("扫描密钥…", "Scan keys…"),
    ("重新扫描本机密钥", "Rescan local keys"),
    ("添加一个 VM 目标；需要填写 SSH 用户名、主机、端口。",
     "Add a VM target; needs an SSH user, host and port."),
    ("编辑选中的 VM 目标（先在上表里选中一行）。",
     "Edit the selected VM target (select a row above first)."),
    ("删除选中的 VM 目标（不影响虚拟机本身）。",
     "Delete the selected VM target (the VM itself is untouched)."),
    ("重新扫描本机 ~/.ssh 下可用的私钥，并刷新上表“密钥”列。",
     "Rescan usable private keys in ~/.ssh and refresh the Key column above."),
    ("添加VM目标", "Add VM target"),
    ("编辑VM目标", "Edit VM target"),
    ("选择要编辑的VM目标", "Select the VM target to edit"),
    ("选择要删除的VM目标", "Select the VM target to delete"),
    ("选择ReMe安装根目录", "Choose the ReMe install folder"),
    ("选择 ReMe 安装目录", "Choose the ReMe install folder"),
    ("名称", "Name"),
    ("主机 / IP / SSH别名", "Host / IP / SSH alias"),
    ("用户名", "User"),
    ("SSH端口", "SSH port"),
    ("VM映射端口", "VM mapped port"),
    ("SSH连接", "SSH connection"),
    ("密钥", "Key"),
    ("启用", "Enabled"),
    ("私钥路径（留空使用 ~/.ssh）", "Private key path (blank = ~/.ssh)"),
    ("默认 ~/.ssh", "Default ~/.ssh"),
    ("~/.ssh（已发现）", "~/.ssh (found)"),
    ("启用（参与隧道连接与状态统计）", "Enabled (participates in tunnels and status)"),
    ("确定删除 ", "Delete "),
    ("还没有VM目标", "No VM targets yet"),
    ("请先选择一个VM目标", "Select a VM target first"),
    ("VM目标的主机 / IP不能为空", "The VM target host / IP cannot be empty"),
    ("SSH端口和VM映射端口必须是数字", "SSH port and VM mapped port must be numbers"),
    ("端口必须在1到65535之间", "Ports must be between 1 and 65535"),
    ("同一VM目标不能重复使用同一个映射端口",
     "The same mapped port cannot be used twice for one VM target"),
    ("已扫描本机SSH密钥：", "Local SSH keys scanned: "),
    ("本机 SSH 密钥扫描完成", "Local SSH key scan finished"),
    ("本机密钥：", "Local keys: "),
    ("SSH启动失败：", "SSH start failed: "),
    ("隧道已经连接", "The tunnel is already connected"),
    ("已连接", "connected"),
    ("已断开", "disconnected"),
    ("隧道已连接", "Tunnel connected"),
    ("隧道已断开", "Tunnel disconnected"),
    ("隧道连接失败，请检查SSH密钥和VM", "Tunnel failed — check the SSH key and the VM"),
    ("没有启用的VM目标", "No enabled VM targets"),
    ("全部隧道已连接", "All tunnels connected"),
    ("VM隧道已停止", "VM tunnels stopped"),
    ("状态刷新间隔", "Status refresh interval"),
    ("状态刷新间隔不受支持", "Unsupported status refresh interval"),
    ("状态刷新间隔已设为 ", "Status refresh interval set to "),
    ("20 秒", "20 seconds"),
    ("1 分钟", "1 minute"),
    ("5 分钟", "5 minutes"),
    ("10 分钟", "10 minutes"),
    ("30 分钟", "30 minutes"),
    ("1 小时", "1 hour"),
    ("已找到 ReMe：", "Found ReMe: "),

    # ================= 9. 服务与操作消息 =================
    ("启动ReMe", "Start ReMe"),
    ("停止ReMe", "Stop ReMe"),
    ("重启ReMe", "Restart ReMe"),
    ("打开ReMe Studio", "Open ReMe Studio"),
    ("打开ReMe目录", "Open ReMe folder"),
    ("打开 .env（凭据）", "Open .env (credentials)"),
    ("打开官方default配置", "Open official default config"),
    ("打开workspace", "Open workspace"),
    ("打开当前配置", "Open current config"),
    ("打开控制台说明", "Open console guide"),
    ("打开日志目录", "Open logs folder"),
    ("启动工具时启动ReMe", "Start ReMe with this tool"),
    ("开机自启", "Start with Windows"),
    ("退出", "Quit"),
    ("ReMe状态：", "ReMe status: "),
    ("当前模式：", "Current mode: "),
    ("（只读，请在 ReMe 控制台里修改）", " (read-only; change it in the ReMe console)"),
    ("正在执行另一项操作", "Another operation is already running"),
    ("成功：", "OK: "),
    ("失败：", "Failed: "),
    ("操作失败：", "Operation failed: "),
    ("ReMe已经运行", "ReMe is already running"),
    ("ReMe已经停止", "ReMe has stopped"),
    ("ReMe尚未运行", "ReMe is not running yet"),
    ("ReMe目录不存在：", "ReMe folder does not exist: "),
    ("找不到命令：", "Command not found: "),
    ("找不到ReMe虚拟环境Python：", "ReMe virtualenv Python not found: "),
    ("自定义配置生成失败：", "Generating the custom config failed: "),
    ("配置不存在：", "Configuration does not exist: "),
    ("根节点不是对象", "The root node is not an object"),
    ("配置解析失败：", "Parsing the configuration failed: "),
    ("ReMe版本校验失败：", "ReMe version check failed: "),
    ("ReMe命令校验失败：", "ReMe command check failed: "),
    ("配置有效（ReMe ", "Configuration is valid (ReMe"),
    ("官方default配置不存在：", "The official default config does not exist: "),
    ("启动失败：", "Start failed: "),
    ("启动后健康检查失败，请查看", "Health check failed after start; see "),
    ("停止失败，2333端口仍响应", "Stop failed: port 2333 still responds"),
    ("当前已经是", "Already "),
    ("失败", "failed"),
    ("新模式启动失败：", "Starting the new mode failed: "),
    ("；旧模式恢复：", "; restored the previous mode: "),
    ("路径不存在：", "Path does not exist: "),

    # ================= 10. 配置校验（保存前） =================
    ("该模式需要 LLM，但 ", "This mode needs an LLM, but "),
    (" 中以下变量未填写：", " is missing these variables: "),
    ("\n\n请点击“写入 .env”写入，或直接在【LLM 与模型】里填写。\n（本地无鉴权网关可随便填一个 Key，例如 sk-local）", "Fill them in under LLM and models, or use Open .env.\n(any key works for a local gateway without auth, e.g. sk-local)"),
    ("Embedding 已启用，但 ", "Embedding is enabled, but "),
    ("\n\n请填写后点“写入 .env”，并先用“测试 Embedding”验证。",
     "\n\nFill them in under Embedding and verify with Test Embedding first."),

    # ================= 11. 安装引导 / 目录扫描 =================
    ("未检测到 ReMe —— 复制安装提示词", "ReMe not found — copy the install prompt"),
    ("复制安装提示词", "Copy install prompt"),
    ("打开官方文档", "Open official docs"),
    ("ReMe 目录", "ReMe folder"),
    ("扫描到候选：", "Candidates found: "),
    ("（共 ", "(of"),
    (" 个）—— 点“扫描…”采用。", ") — click Scan… to use it."),
    ("已检测到 ReMe：", "ReMe detected: "),
    ("这个目录里没有可用的 ReMe（需要 venv\\Scripts\\python.exe 与 reme 包）。",
     "This folder has no usable ReMe (needs venv\\Scripts\\python.exe and the reme package)."),
    ("扫描到多个 ReMe 安装：", "Several ReMe installations found:"),
    ("已切换 ReMe 目录：", "ReMe folder switched to: "),
    ("ReMe运行中不能切换安装根目录；请先停止服务",
     "The ReMe folder cannot be changed while the service is running; stop it first."),
    ("复制一段可直接发给 DSH / Codex 的安装指令，让它替你把 ReMe 装好并启动。",
     "Copy an install prompt you can hand to DSH / Codex so it installs and starts ReMe for you."),
    ("在浏览器打开 ReMe 官方仓库。", "Open the official ReMe repository in your browser."),
    ("安装提示词已复制到剪贴板。\n\n要现在看一下内容吗？",
     "The install prompt is on your clipboard.\n\nView it now?"),
    ("安装提示词已复制，可直接粘贴给 DSH / Codex",
     "Install prompt copied — paste it into DSH / Codex"),
    ("安装提示词已复制，粘贴给 DSH / Codex 即可",
     "Install prompt copied — paste it into DSH / Codex"),
    ("复制失败，请在控制台里点“复制安装提示词”",
     "Copy failed — use Copy install prompt in the console"),

    # ================= 12. 控制台：状态条、按钮、提示 =================
    (" · 控制台", " · Console"),
    (" · 控制台说明", " · Console guide"),
    ("没有未保存的改动", "No unsaved changes"),
    ("待保存：", "Pending: "),
    ("回到基线", "Back to baseline"),
    ("↺ 回到基线", "↺ Back to baseline"),
    ("撤销修改", "Discard changes"),
    ("放弃改动", "Discard changes"),
    ("验证并保存", "Validate and save"),
    ("把 ", "Restore "),
    ("已回到基线", "restored to baseline"),
    (" 已回到基线", " restored to baseline"),
    (" 已回到基线；模式：", " restored to baseline; mode: "),
    (" 已回到基线（", "restored to baseline ("),
    ("自定义模式：已启用 ", "Custom mode: "),
    (" 项 → app-custom.yaml", " feature(s) enabled → app-custom.yaml"),
    ("；模式自动切换为", "; mode switched to "),
    ("完全一致 → 模式自动切换为", "exactly → mode switched to"),
    ("配置已与", "Configuration now matches "),
    ("已从", "Switched from "),
    ("转为自定义：只应用你刚改的这一项", " to Custom: only the item you just changed is applied"),
    ("已转为自定义模式（基线：全功能预设）；保存后生效。",
     "Switched to Custom mode (baseline: Full preset); takes effect after saving."),
    ("模式：", "Mode: "),
    ("（地址、模型、Key 等已保留；保存后生效）",
     "(address, model and key are kept; takes effect after saving)"),
    ("LLM 未就绪（地址 / 模型 / Key）", "LLM not ready (address / model / key)"),
    ("服务未运行", "Service is not running"),
    ("未检测到 ReMe 安装：请先安装（或点上方“复制安装提示词”）",
     "ReMe is not installed — install it first (or click Copy install prompt above)"),
    ("把待保存改动写入配置并重启服务（窗口不会关闭）",
     "Write the pending changes and restart the service (the window stays open)"),
    ("切换浅色 / 深色主题（会记住选择）", "Switch between light and dark theme (remembered)"),
    ("切换界面语言 / Switch interface language（会记住选择）",
     "Switch interface language (remembered)"),
    ("回到基线（", "Back to baseline ("),
    ("）？\n该操作只改草稿，保存后才生效；", ")?\nThis only edits the draft; it takes effect after saving;"),
    ("）？\n\n该操作只改草稿，保存后才生效；地址与 Key 不受影响。", ")?\n\nThis only edits the draft; it takes effect after saving. Addresses and keys are untouched."),
    ("已保存：", "Saved: "),
    ("（窗口保持打开）", " (window stays open)"),
    ("配置已保存。\n", "Configuration saved.\n"),
    ("\n\n窗口保持打开，可继续调整。", "\n\nThe window stays open for further changes."),
    ("；服务已按新配置重启", "; the service restarted with the new configuration"),
    ("（保存后会写入配置文件）", " (written to the config file on save)"),
    ("已从 .env 补全：", "Filled from .env: "),
    ("已撤销修改，回到已保存的配置", "Changes discarded — back to the saved configuration"),
    ("放弃所有未保存的改动？", "Discard all unsaved changes?"),
    ("\n\n待保存改动：", "\n\nPending changes: "),
    (" 项。继续？", ". Continue?"),
    ("\n\n会调用模型并修改 ReMe workspace（digest/ 与 interests.yaml）。",
     "\n\nIt calls the model and writes into the ReMe workspace (digest/ and interests.yaml)."),
    ("（embedding 范围会重新计算全库向量，可能产生费用）",
     "(the embedding scope recomputes vectors for the whole store; charges may apply)"),
    ("重建索引 scope=", "Rebuild index with scope="),
    ("\n扫描范围：最近 ", "\nScan range: last "),
    (" 天的 daily（当前 ", "day(s) of daily notes (currently"),
    (" 个文件 / 约 ", " file(s) / about "),
    (" 千字符）\n调用上界：1 次抽取 + 最多 ", "k characters)\nUpper bound: 1 extraction + up to"),
    (" 次整理（每个 unit 一次）\n产出：最多 ",
     " consolidation call(s) (one per unit)\nOutput: at most "),
    (" 个长期节点 → digest/personal · procedure · wiki",
     " long-term node(s) → digest/personal · procedure · wiki"),

    # ================= 13. 安装提示词（发给 DSH / Codex 的原文） =================
    ("\n\n背景：ReMe 用 Markdown 文件保存记忆，本机服务默认监听 2333 端口，供 DSH / Codex 等客户端通过 MCP 读写记忆。", "Background: ReMe stores memories as Markdown files; the local service listens on port 2333 by default so clients such as DSH / Codex can read and write memories over MCP."),
    ("\n\n请按官方方式安装（PowerShell）：\n1) 建目录与虚拟环境：mkdir \"", " \n\nInstall it the official way (PowerShell):\n1) Create the folder and virtualenv: mkdir \" "),
    ("\"；用 Python 3.11+（推荐 3.13）执行 python -m venv \"",
     "\"; with Python 3.11+ (3.13 recommended) run python -m venv \""),
    ("\\venv\"\n2) 安装：\"", "\\venv\"\n2) Install: \""),
    ("\\venv\\Scripts\\python.exe\" -m pip install -U \"reme-ai[core]\"",
     "\\venv\\Scripts\\python.exe\" -m pip install -U \"reme-ai[core]\""),
    ("\n3) 启动服务：\"", "3) Start the service: \""),
    ("\\venv\\Scripts\\reme.exe\" start service.backend=http（默认 http://127.0.0.1:2333/，Studio 也在同一个地址）",
     "\\venv\\Scripts\\reme.exe\" start service.backend=http (defaults to http://127.0.0.1:2333/, where Studio lives too)"),
    ("\n4) 验证：请求 http://127.0.0.1:2333/health_check 应返回正常；浏览器打开 http://127.0.0.1:2333/ 能看到工作区界面", " \n4) Verify: GET http://127.0.0.1:2333/health_check should return healthy; opening http://127.0.0.1:2333/ in a browser should show the workspace UI "),
    ("\n5) 如果 2333 被占用，用 service.port=<其他端口> 启动并告诉我端口号", " \n5) If port 2333 is taken, start with service.port=<another port> and tell me the port "),
    ("\n\n完成后请告诉我：① 安装根目录的绝对路径 ② 服务地址与端口 ③ 是否已配置 LLM / Embedding（记忆的自动提炼需要 LLM；语义检索需要 Embedding，可选）。", "When done, please report: (1) the absolute install path (2) the service address and port (3) whether LLM / Embedding are configured (automatic consolidation needs an LLM; semantic search needs Embedding and is optional)."),
    ("\n官方文档：https://github.com/agentscope-ai/ReMe",
     "\nOfficial docs: https://github.com/agentscope-ai/ReMe"),

    # ================= 14. 说明文档窗口 / 其它 =================
    ("Tk 解释器未能创建", "the Tk interpreter could not be created"),
    ("详见日志：", "See the log: "),
    # ================= 15. 逐条核对后补上的词条 =================
    ("记忆管道", "Memory pipeline"),
    ("VM 目标", "VM targets"),
    ("请先填写 Base URL 与模型名", "Fill in the base URL and model name first"),
    (" 返回失败（", "failed ("),
    (" 完成（", "done ("),
    ("s）：", "s):"),
    ("ReMe 已启动（", "ReMe started ("),
    ("已切换到", "Switched to "),
    ("使用这个", "Use this one"),
    ("控制台无法打开：", "Cannot open the console: "),
    ("成本/性能：", "Cost / performance: "),
    ("可以点“复制安装提示词”，把它发给 DSH / Codex，让 agent 帮你装好并启动，", "Click Copy install prompt, hand it to DSH / Codex so the agent installs and starts it, "),
    ("然后回到这里点“扫描…”确认。", "then come back here and click Scan… to confirm."),
    ("已开启自动记忆与整理 → 模式切换为", "Automatic memory and consolidation enabled → mode is now "),
    ("未检测到 ReMe。先安装（Python 3.13 建 venv → pip install \"reme-ai[core]\" → ", "ReMe not found. Install it first (Python 3.13 venv → pip install \"reme-ai[core]\" →"),
    ("reme start service.backend=http），或点“复制安装提示词”把它交给 DSH / Codex 安装。", "reme start service.backend=http), or click Copy install prompt and let DSH / Codex do it."),
    ("未通过测试", "Untested"),
    ("auto_dream 运行中（可能数分钟，期间按钮已禁用）…", "auto_dream is running (may take minutes; buttons are disabled)…"),
    ("cron 格式不正确", "Invalid cron format"),
    ("＋ 添加目标…", "＋ Add target…"),
    ("✎ 编辑目标…", "✎ Edit target…"),
    ("－ 删除目标…", "－ Remove target…"),
    ("；模式：", "; mode: "),
    ("ReMe 目录不存在：", "ReMe folder does not exist: "),
    ("重启隧道", "Restart tunnels"),
    ("等待服务就绪…", "Waiting for the service…"),
    ("（引擎）", " (engine)"),
    ("（只读）", " (read-only)"),
    ("已停止（外部启动）", "Stopped (started outside)"),
    ("启动中（等待端口）", "Starting (waiting for the port)"),
    ("请在这台 Windows 机器上安装并启动 ReMe（本地优先的长期记忆服务），完成后回报结果。\n\n背景：ReMe 用 Markdown 文件保存记忆，本机服务默认监听 2333 端口，供 DSH / Codex 等客户端通过 MCP 读写记忆。\n\n请按官方方式安装（PowerShell）：\n1) 建目录与虚拟环境：mkdir \"", "Please install and start ReMe (a local-first long-term memory service) on this Windows machine, then report the result.\n\nBackground: ReMe stores memories as Markdown files; the local service listens on port 2333 by default so clients such as DSH / Codex can read and write memories over MCP.\n\nInstall it the official way (PowerShell):\n1) Create the folder and virtualenv: mkdir \""),
    ("并重新启动", " and restarted"),
    ("开启后：对话会被自动提炼成每日记忆卡片（Auto Memory），每天再沉淀为长期记忆节点（Auto Dream）。\n两项都需要【LLM 与模型】填好地址与 Key；开启会自动转为自定义模式。", "When on: chats are distilled into daily memory cards (Auto Memory), then consolidated into long-term nodes each day (Auto Dream).\nBoth need an address and key in LLM and models; enabling switches to Custom mode."),
    ("立即整理（auto_dream）：需要 Auto Dream 已启用、LLM 已配置、服务运行中。\n会调用模型并写入 digest/，产生 token 费用。", "Consolidate now (auto_dream): needs Auto Dream enabled, an LLM configured and the service running.\nCalls the model and writes into digest/, spending tokens."),
    ("把整份草稿恢复到基线（你本次的起点）。\n基线是“已保存配置”时，请用右侧的“放弃改动”。", "Restore the whole draft to the baseline (where this session started).\nWhen the baseline is the saved configuration, use Discard changes on the right instead."),
    ("没有扫描到已安装的 ReMe。\n\n可以点“复制安装提示词”，把它发给 DSH / Codex，让 agent 帮你装好并启动，然后回到这里点“扫描…”确认。", "No existing ReMe installation was found.\n\nClick Copy install prompt, hand it to DSH / Codex so the agent installs and starts it, then come back here and click Scan… to confirm."),
    ("立即执行一次 auto_dream？\n\n会调用模型并修改 ReMe workspace（digest/ 与 interests.yaml）。", "Run auto_dream now?\n\nIt calls the model and writes into the ReMe workspace (digest/ and interests.yaml)."),
    ("保存会重启 ReMe（约 10 秒）。\n\n待保存改动：", "Saving restarts ReMe (about 10s).\n\nPending changes: "),
    ("ReMe 控制台…", "ReMe console…"),
    ("UI 线程没有在限定时间内响应", "The UI thread did not respond in time"),
    ("官方默认 2；调大≠更准，更慢更贵", "Official default 2; bigger ≠ better — slower and pricier"),
    ("官方默认 5；调大只更慢更贵", "Official default 5; bigger is only slower and pricier"),
    ("扫描范围：从今天往回数 N 个 daily 目录，ReMe 官方默认 2 天。\n先说结论：调大 ≠ 记得更准，越大越慢越贵。\n机制：内容没变的日记本来就不会被抽取（按 mtime 比对），整个窗口都没变化时这次整理直接跳过、不花钱；但窗口越大，只要其中任意一天有变化，这次抽取就要把窗口里所有变化一起读进去——输入更大、更慢更贵，还会把早已沉淀过的旧内容再提一遍。\n建议：日常保持 2；刚补录了一批旧日记、或连着几天没开机时临时调到 3–7，扫完调回 2。", "Scan window: the last N daily folders counting back from today. ReMe's official default is 2.\nBottom line: a larger window is NOT more accurate — it is slower and more expensive.\nHow it works: daily files whose content did not change are never extracted (mtime comparison), and when nothing in the window changed the whole run is skipped for free. But the wider the window, the more changed files one extraction reads in — bigger input, slower and pricier, and content that was consolidated long ago gets proposed again.\nAdvice: keep 2 day-to-day; temporarily raise it to 3–7 after importing old notes or after the machine was off for days, then set it back to 2."),
    ("一次整理最多产出几个长期节点（unit），ReMe 官方默认 5。\n先说结论：调大 ≠ 记忆更好，只是把一次运行拉长、账单变高。\n机制：每个 unit 都要单独调一次模型把它融合进 digest，所以一次整理的费用与耗时 ≈ 1 次抽取 + N 次融合（N 是实际产出的 unit 数，上限就是这里）；写得多也意味着更次要的内容会被一起沉淀进去。\n建议：日常 3–5；首次补历史可以临时调到 10，补完调回 5。", "How many long-term nodes (units) one consolidation run may write. ReMe's official default is 5.\nBottom line: a higher cap is NOT better memory — it only makes a run longer and the bill higher.\nHow it works: every unit costs its own model call to merge into digest, so one run costs about 1 extraction + N merges (N = units actually produced, capped here); writing more also means less important material gets consolidated too.\nAdvice: 3–5 day-to-day; raise to 10 temporarily when importing a backlog, then set it back to 5."),
    ("测试只读；保存时会自动把地址 / 模型 / Key 写入 .env（手工编辑：托盘右键「打开 .env（凭据）」）", "Testing is read-only; saving writes address / model / key into .env (to edit by hand: tray → Open .env (credentials))"),
    ("打开 workspace", "Open workspace"),
    ("打开指引（文件在哪）…", "Open guide (where the files live)…"),
    (" · 路径与入口", " · Paths and entry points"),
    ("这些文件在哪、点一下就能打开；平时改配置请用控制台，这里只是帮你找到它们。", "Where these files live — click to open. Change settings in the console; this window only helps you find them."),
    ("打开", "Open"),
    ("复制路径", "Copy path"),
    ("当前配置", "Current config"),
    ("官方 default 配置", "Official default config"),
    (".env（凭据）", ".env (credentials)"),
    ("日志目录", "Logs folder"),
    ("安装根目录，config / workspace / logs 都在下面", "Install root; config / workspace / logs live under it"),
    ("你的记忆文件（Markdown），可以直接翻看或备份", "Your memory files (Markdown) — read or back them up directly"),
    ("控制台保存后生效的 app*.yaml；一般不用手改", "The app*.yaml the console writes on save; normally no need to hand-edit"),
    ("ReMe 自带的默认配置，只读参考", "ReMe's bundled default config — read-only reference"),
    ("LLM / Embedding 的地址与 Key，注意别外传", "LLM / Embedding addresses and keys — do not share them"),
    ("出问题时看这里的 *.log", "Look here (*.log) when something goes wrong"),
    ("ReMe 启动与接入的 Markdown 说明（在窗口里打开）", "The Markdown guide for starting and wiring up ReMe (opens in its own window)"),
    ("密钥只放在 .env；改完配置记得回控制台保存。", "Keys live in .env only; save changes in the console afterwards."),
    ("已复制路径：", "Path copied: "),
    ("复制失败", "Copy failed"),
    ("显示", "Show"),
    ("（已配置；不动这里＝不改，输入新 Key 才覆盖）",
     "(configured; leave it alone to keep it, type a new key to replace it)"),
    ("（未配置；填写后保存）", "(not set; fill it in and save)"),
    ("已按 .env 校正：", "Corrected from .env: "),
    ("（ReMe 读的是 .env，保存后会写回配置）", " (ReMe reads .env; saving writes it back to the config)"),
    ("# ReMe 助手 · 控制台说明", "# ReMe Helper · Console guide"),
    ("ReMe 助手是一个 Windows 托盘小工具：帮你选 ReMe 的运行模式、看清每项配置的实际影响、启停服务，", "ReMe Helper is a small Windows tray tool: it picks ReMe's runtime mode, shows what each setting really does, starts and stops the service,"),
    ("以及把 Windows 上的 ReMe 反向映射给虚拟机里的客户端。它不替代 ReMe，也不修改 ReMe 安装包里的官方配置。", "and exposes the Windows-side ReMe to clients inside a VM. It does not replace ReMe and never edits the official configuration shipped with ReMe."),
    ("## 本机路径", "## Paths on this machine"),
    ("这些路径随时可以在托盘菜单的「打开指引（文件在哪）…」里查看、打开或复制。", "You can view, open or copy these paths any time from the tray menu: Open guide (where the files live)…"),
    ("## 三种模式", "## The three modes"),
    ("| 模式 | 配置文件 | 能力与前提 |", "| Mode | Config file | Capabilities and requirements |"),
    ("| 基础模式 | 基础配置 | 不调用模型：Markdown 读写、BM25 与关系检索、Studio、MCP、索引维护 |", "| Basic | base config | No model calls: Markdown read/write, BM25 and link retrieval, Studio, MCP, index upkeep |"),
    ("| 全功能模式 | 完整配置 | 官方默认全开：自动记忆与整理、资料卡片、内部 Chat；需要填好 LLM |", "| Full | full config | Everything the official default enables: automatic memory and consolidation, resource cards, internal Chat; needs a working LLM |"),
    ("| 自定义模式 | 自定义配置 | 逐项挑选，从官方默认生成；能满足依赖就能开 |", "| Custom | custom config | Pick features one by one, generated from the official default; anything whose requirements are met can be on |"),
    ("前两项是固定预设：改动其中任意一项都会自动转为自定义模式，并且只应用你改的那一项（可撤销）。", "The first two are fixed presets: editing anything in them switches to Custom and applies only that one change (undoable)."),
    ("模式是由配置内容推导出来的，不是单独存的一个开关——草稿与某个预设完全一致时会自动切回该预设。", "The mode is derived from the configuration, not stored as a separate switch — when the draft matches a preset exactly, the mode switches back to it."),
    ("「保存」会写配置、按需重启服务，并保持在窗口里，方便继续调整。", "Save writes the configuration, restarts the service when needed, and keeps the window open for further tweaks."),
    ("## 启动与停止", "## Start and stop"),
    ("- 托盘菜单或控制台按钮都可以启停；控制台会显示服务状态与健康检查结果。", "- Start and stop from the tray menu or the console buttons; the console shows service state and health."),
    ("- 服务地址默认是 http://127.0.0.1:2333/ ，健康检查在 /health_check ，Studio 就在同一个地址。", "- The service defaults to http://127.0.0.1:2333/ , health check at /health_check , and Studio lives at the same address."),
    ("- 工具只关闭「自己启动或接管」的服务；外部启动的 ReMe 不会被偷偷杀掉。", "- The tool only stops a service it started or adopted; a ReMe started elsewhere is left alone."),
    ("- 端口被占用时先看日志目录里的最新日志，再换端口或用 service.port=<端口> 启动。", "- If the port is taken, check the newest log first, then use another port or start with service.port=<port>."),
    ("## LLM 与 Embedding", "## LLM and Embedding"),
    ("- 需要 LLM 的能力：自动记忆、自动整理、内部 Chat。没有填 LLM 时这些能力会显示为未启用。", "- Features that need an LLM: automatic memory, automatic consolidation, internal Chat. Without an LLM they show as off."),
    ("- 需要 Embedding 的能力：语义检索（近义、改写、中英混搜）与近似检索加速。只用关键词检索时可以不配。", "- Features that need Embedding: semantic search (paraphrases, rewrites, mixed CN/EN) and faster nearest-neighbour search. Keyword-only setups can skip it."),
    ("- 地址、模型、Key 都可以在控制台里填；保存时会自动写入 .env，不必手工编辑。", "- Address, model and key are all editable in the console; saving writes them into .env for you."),
    ("- Key 字段按密码框处理：已经配置的会载入并显示为掩码，点「显示」才看得到明文，留空表示不改。", "- Key fields behave like password fields: an existing key loads masked, Show reveals it, and leaving it blank keeps it unchanged."),
    ("- 「测试连接」验证两件事：接口可用，以及能按要求输出结构化 JSON（自动整理依赖它）。", "- Test connection checks two things: the endpoint works, and it can return the structured JSON that consolidation depends on."),
    ("- 「测试 Embedding」验证接口可用、维度一致，以及近义句确实比无关句更接近。", "- Test Embedding checks the endpoint, the dimensions, and that related sentences really score closer than unrelated ones."),
    ("## 记忆是怎么长出来的", "## How memories grow"),
    ("- Auto Memory：把对话提炼成当天的记忆卡片（daily）。", "- Auto Memory distils conversations into that day's memory cards (daily notes)."),
    ("- Auto Dream：每天把有变化的 daily 沉淀成长期节点（digest），并维护兴趣主题。", "- Auto Dream consolidates changed daily notes into long-term nodes (digest) each day and maintains topics."),
    ("- 扫描天数决定这次整理回看几天：内容没变的日记本来就不会被抽取，整窗无变化时整次整理直接跳过；", "- Scan days decide how far back one run looks: unchanged notes are never extracted, and a run with nothing changed is skipped entirely;"),
    ("  窗口越大，只要其中任意一天有变化，这次抽取读入的内容就越多——更慢更贵，不会更准。", "  the wider the window, the more a single extraction reads whenever any day changed — slower and pricier, not more accurate."),
    ("- 每次最多沉淀决定一次能写几个长期节点：每个节点都要单独调用一次模型，调大只会更慢更贵。", "- Max units caps how many long-term nodes one run writes; each node costs its own model call, so a higher cap is only slower and pricier."),
    ("- 「立即整理一次」适合手动补一次；它需要服务在运行、LLM 可用，并会消耗 token。", "- Consolidate now is for a manual catch-up run; it needs the service running and a working LLM, and spends tokens."),
    ("- 整理结果会记在日志里，控制台下方会显示上次整理的时间与产出。", "- Results are logged, and the console shows when the last run happened and what it produced."),
    ("## 让别的客户端用上 ReMe", "## Letting other clients use ReMe"),
    ("ReMe 通过 MCP 暴露记忆工具，控制台的「MCP 工具暴露」里可以逐项开关。Codex 之类的客户端在配置里加：", "ReMe exposes its memory tools over MCP; the console's MCP tools section toggles them one by one. Clients such as Codex just need:"),
    ("只读工具（检索、读文件、关系遍历）随时可用；写入类工具（新建、修改记忆）打开后，客户端才能精确写入。", "Read-only tools (search, read files, walk links) are always available; write tools (create, edit memory) must be enabled before a client can write precisely."),
    ("多个客户端共用同一份记忆：整理交给 ReMe 自己的计划任务，客户端只负责读写，不要在客户端重复开启自动整理。", "Several clients share one memory store: leave consolidation to ReMe's own schedule, let clients only read and write, and do not enable automatic consolidation in the client as well."),
    ("## 给虚拟机里的客户端用", "## For clients inside a VM"),
    ("ReMe 只监听本机回环地址，所以用 SSH 反向转发把它映射给虚拟机。在 Windows 上执行（把占位符换成你的目标）：", "ReMe only listens on the loopback interface, so a reverse SSH forward exposes it to the VM. Run this on Windows (replace the placeholders):"),
    ("虚拟机里再把客户端指向 http://127.0.0.1:<VM端口>/mcp 即可。托盘菜单的「VM 目标」可以添加多个目标，", "Then point the client inside the VM at http://127.0.0.1:<VM port>/mcp . The tray menu's VM targets can hold several targets,"),
    ("分别配置主机、SSH 端口、私钥与映射端口，并随 ReMe 一起启停。工具只负责建立和监测隧道，", "each with its own host, SSH port, private key and mapped port, started and stopped together with ReMe. The tool only opens and watches tunnels:"),
    ("不生成密钥、不改 SSH 配置、不动防火墙。", "it never generates keys, edits SSH configuration or touches the firewall."),
    ("## 出问题时", "## When something goes wrong"),
    ("- 服务起不来：先看日志目录里最新的日志，再用 /health_check 确认端口是否有响应。", "- Service will not start: read the newest log, then check /health_check to see whether the port responds."),
    ("- 记忆不更新：确认自动记忆与整理已开启、LLM 可用、服务在运行，且当天确实有对话。", "- Memories do not update: make sure automatic memory and consolidation are on, the LLM works, the service runs, and there were conversations that day."),
    ("- 检索不到：先看是关键词检索还是语义检索；语义检索需要 Embedding 配置正确、维度与索引一致，", "- Nothing found: check whether retrieval is keyword-based or semantic; semantic search needs a correct Embedding setup with dimensions matching the index,"),
    ("  改过维度或模型后要重建一次索引。", "  and the index must be rebuilt after changing dimensions or the model."),
    ("- 界面看不清或想换语言：控制台右上角切换深色/浅色与中英，选择会被记住。", "- Hard to read or want another language: the top-right of the console switches dark/light and Chinese/English, and the choice is remembered."),
    ("## 备份与升级", "## Backup and upgrade"),
    ("需要长期备份的是记忆数据（workspace）、配置和 .env 三样；程序环境可以按官方方式重建。", "Three things are worth backing up long term: the memory data (workspace), the configuration and .env; the program environment can be rebuilt the official way."),
    ("升级前先复制一份记忆数据，用副本验证新版本，再切换正式启动方式。", "Before upgrading, copy the memory data, verify the new version against the copy, then switch the real start command."),
    ("## 官方资料", "## Official links"),
    ("内置的接入与排障说明（在窗口里打开，不依赖 ReMe 目录）", "built-in setup and troubleshooting guide (opens in a window; does not depend on the ReMe folder)"),
    ("（内置文档）", "(built-in)"),
    ("| 项目 | 本机取值 |", "| Item | Value on this machine |"),
    ("安装目录", "Install folder"),
    ("当前模式", "Current mode"),
    ("当前配置文件", "Current config file"),
    ("记忆数据", "Memory data"),
    ("凭据文件", "Credentials file"),
    ("服务地址", "Service address"),
    ("工具版本", "Tool version"),
    ("把本区可调项恢复为基线值（见顶部状态条的“基线”）。\n固定预设下，基线就是该预设的标准值。", "Restore this section to the baseline (see Baseline in the top bar).\nIn a fixed preset the baseline is that preset's standard values."),
    ("模式决定能力范围（哪些功能与后台 Job 开着）。只改能力项会转为自定义模式；地址、模型、Key 与各项参数属于公共设置，改它们不会离开预设。", "The mode decides the capability set (which features and background jobs are on). Editing a capability switches to Custom mode; addresses, models, keys and tuning values are shared settings and never move you out of a preset."),
    ("（固定预设）：下表是该预设的能力；改动能力项会转为自定义模式。", " (fixed preset): the table shows this preset's capabilities; editing a capability switches to Custom mode."),
    ("恢复到基线值（该预设的标准值）", "Restore to the baseline value (the preset's standard value)"),
    (" 恢复到基线值（该预设的标准值）", " to the baseline value (the preset's standard value)"),
    ("接入文档", "Integration doc"),
    ("接入 Agent 文档", "Agent setup guide"),
    (" · 接入 Agent 文档", " · Agent setup guide"),
    ("阅读接入文档", "Read the setup guide"),
    ("复制接入文档", "Copy the setup guide"),
    ("怎么把 Codex、Claude Code、DSH 接到 ReMe 上（可阅读，也可复制给 AI，由它探测后逐端接上）",
     "how to connect Codex, Claude Code and DSH to ReMe (read it here, or copy it to an AI that probes and wires each one)"),
    ("复制整篇接入文档（含两份捕获脚本），粘贴给 AI，它会先探测本机装了哪些客户端，再照着接上 ReMe。",
     "Copy the whole setup guide (both capture scripts included); paste it into an AI, which probes which clients are installed and wires them to ReMe."),
    ("先看这篇：怎么把 Codex、Claude Code、DSH 接到 ReMe 上。想交给 AI 去做，再用右边的「复制接入文档」。",
     "Read this first: how to connect Codex, Claude Code and DSH to ReMe. To hand the work to an AI, use Copy the setup guide on the right."),
    ("接入文档已复制：粘贴给 AI，让它先探测本机客户端，再接到 ReMe",
     "Setup guide copied: paste it into an AI to probe the local clients and connect them to ReMe"),
    ("接入文档缺失：请确认 doc 目录随工具一起分发。",
     "Setup guide is missing: make sure the doc folder ships with the tool."),
    ("ReMe 助手已在运行：请使用托盘里的那个实例（本次启动已忽略）。",
     "ReMe Helper is already running: use the instance in the tray (this launch was ignored)."),

]

# ============================== 引擎 ==============================
import ast
import re
from pathlib import Path

HAN = re.compile(r"[\u4e00-\u9fff]")
FULLWIDTH = re.compile(r"[，。：；！？（）【】“”、《》]")

# 单个标点也当片段替换（中文标点在英文里本来就该换掉）
PUNCT: dict[str, str] = {
    "（": " (", "）": ")", "，": ", ", "。": ". ", "：": ": ", "；": "; ",
    "、": ", ", "！": "!", "？": "?", "【": " [", "】": "]", "“": "\"", "”": "\"",
}

# 这两个词条故意在英文里保留中文（语言开关本身要显示“中文”）
ALLOW_CJK_IN_EN: frozenset[str] = frozenset({"中文", "English / 中文"})

# 明确不翻译的中文，每条都要有理由
EXEMPT: frozenset[str] = frozenset({
    "ReMe-启动与接入说明.md",     # 磁盘上的真实文件名
    "== 未覆盖 ==",               # --lang-audit 的命令行输出，给开发者看，不进界面
    "== 表里没被用上 ==",
    "对照表已生成：",
})

_EN: dict[str, str] = {}
_DUPLICATES: list[str] = []
for _zh, _en in TEXT:
    if _zh in _EN:
        _DUPLICATES.append(_zh)
    _EN[_zh] = _en

# 片段按长度倒序：长词条优先，避免「打开」把「打开控制台说明」提前吃掉
_FRAGMENTS: list[tuple[str, str]] = sorted(
    ((zh, en) for zh, en in TEXT if len(zh) >= 2),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


def translate(text, lang: str = "en") -> str:
    """把一条界面文案翻成当前语言。

    中文模式原样返回；英文模式先整串查表，再按最长片段替换——这样
    「已保存：xxx（窗口保持打开）」这类拼接出来的句子也能整体变成英文。
    查不到的条目原样返回（宁可显示中文，也不要空白）。
    """
    value = "" if text is None else str(text)
    if lang != "en" or not value:
        return value
    exact = _EN.get(value)
    if exact is not None:
        return exact
    if not HAN.search(value) and not FULLWIDTH.search(value):
        return value                     # 纯英文/符号，不用处理
    out = value
    for zh, en in _FRAGMENTS:
        if zh in out:
            out = out.replace(zh, en)
    for zh, en in PUNCT.items():
        if zh in out:
            out = out.replace(zh, en)
    return out


def untranslated(value: str) -> bool:
    """英文模式下这条文案是否还残留中文（审查与测试用它当红灯）。"""
    if value in ALLOW_CJK_IN_EN:
        return False
    result = translate(value, "en")
    return bool(HAN.search(result) or FULLWIDTH.search(result))


# ------------------------------ 源码审查 ------------------------------
def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def _excluded_ids(tree: ast.AST) -> set[int]:
    """不参与翻译审查的字符串：docstring 与 re.compile 的模式。"""
    ids = _docstring_ids(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "compile":
            continue
        for arg in node.args:
            for child in ast.walk(arg):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    ids.add(id(child))
    return ids


def collect_literals(path) -> list[tuple[int, str]]:
    """源码里需要翻译的中文字面量：跳过 docstring、正则、以及 log(...) 里的日志文案。

    f-string 会拆成常量片段（「已保存：」这种），这样拼接句也能逐段翻译。
    返回 [(行号, 文案)]，按行号排序，同一条只保留一次。
    """
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    skip = _excluded_ids(tree)
    found: dict[str, int] = {}

    def is_log_line(lineno: int) -> bool:
        line = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ""
        stripped = line.lstrip()
        if stripped.startswith("#"):
            return False
        return bool(re.search(r"(^|[^\w.])log\(", line))

    def add(node: ast.Constant) -> None:
        value = node.value
        if not isinstance(value, str) or id(node) in skip or not HAN.search(value):
            return
        if is_log_line(node.lineno):
            return
        found.setdefault(value, node.lineno)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            add(node)
        elif isinstance(node, ast.JoinedStr):
            for piece in node.values:
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    add(piece)

    return [(lineno, value) for value, lineno in sorted(found.items(), key=lambda pair: pair[1])]


def audit(paths) -> dict:
    """审查：表里缺哪些中文（missing）、哪些词条没被用上（table_only）。"""
    used: set[str] = set()
    missing: list[tuple[str, int, str]] = []
    for path in paths:
        for lineno, value in collect_literals(path):
            used.add(value)
            if value in EXEMPT:
                continue
            if untranslated(value):
                missing.append((Path(path).name, lineno, value))
    return {
        "missing": missing,
        "table_only": [zh for zh, _ in TEXT if zh not in used],
        "duplicates": list(_DUPLICATES),
        "empty_en": [zh for zh, en in TEXT if not en.strip()],
        "cjk_en": [(zh, en) for zh, en in TEXT
                   if en not in ALLOW_CJK_IN_EN and (HAN.search(en) or FULLWIDTH.search(en))],
    }


def review_markdown() -> str:
    """生成左右对照的 Markdown，方便逐条检查中英是否得当。"""

    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", "<br>").replace("\r", "")

    rows = ["# 中英对照表（由 i18n.py 自动生成）", "",
            f"共 {len(TEXT)} 条。左列是源码里写的中文，右列是英文模式下显示的内容。", "",
            "| # | 中文 | English |", "|---|------|---------|"]
    for index, (zh, en) in enumerate(TEXT, 1):
        rows.append(f"| {index} | {cell(zh)} | {cell(en)} |")
    return "\n".join(rows) + "\n"
