# astrbot_plugin_ai_toggle

按群开关 AstrBot 的 AI 回复能力。管理员在群里发送文本指令即可控制，无需斜杠前缀。

## 指令

| 指令 | 说明 |
| --- | --- |
| `开启对话` | 开启当前群的 AI 回复 |
| `关闭对话` | 关闭当前群的 AI 回复 |
| `对话状态` | 查询当前群 AI 开关状态 |

- 指令大小写兼容，直接发送文本触发
- 仅限管理员操作，非管理员发送指令会被**静默忽略**
- 仅群聊有效，私聊不处理
- 开关后机器人回复确认消息（可在配置中关闭）

## 安装

1. 下载本仓库，将 `astrbot_plugin_ai_toggle/` 文件夹放入 AstrBot 的 `data/plugins/` 目录（或通过 WebUI 插件市场 → 从仓库安装）
2. 重启 AstrBot 或在 WebUI 插件管理中重载

## 配置

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `admin_ids` | list | `[]` | 允许触发开关指令的管理员用户 ID 列表；**留空则回退到 AstrBot 全局管理员配置**（WebUI 配置 → 其他配置 → 管理员 ID，即 `data/cmd_config.json` 的 `admins_id`） |
| `default_enabled` | bool | `true` | 新群（无存储记录时）的默认 AI 开关状态 |
| `reply_on_toggle` | bool | `true` | 开关切换后是否发送确认消息（`对话状态` 查询始终回复） |

## 实现说明

- **状态存储**：使用 AstrBot 插件 KV 存储（`PluginKVStoreMixin`）持久化，键为 `group_{group_id}_ai_enabled`，每个群独立，重启不丢失
- **LLM 拦截**：通过 `@filter.on_llm_request()` 钩子在 LLM 调用前检查开关，关闭状态下调用 `event.stop_event()` 终止本次请求。已对照 AstrBot 源码确认：钩子内抛出异常会被框架吞掉，无法中断管线，`stop_event()` 是唯一正确的中断方式；该钩子覆盖所有 LLM 调用路径（含群聊自动回复）
- **事件终止**：开关指令处理完后同样 `stop_event()`，避免指令文本本身再被送入 LLM

## 更新日志

### v1.0.0

- 首个版本：群级 AI 开关、管理员权限校验、状态持久化、LLM 请求拦截
