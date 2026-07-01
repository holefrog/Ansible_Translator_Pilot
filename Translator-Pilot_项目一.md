# Translator-Pilot — 项目一：本地离线直播翻译引擎（总览 + 项目一定稿）

> 最后更新：2026年6月30日 下午2:55（温哥华时间）

---

## 一、整体项目背景

**业务目标**：把英文音视频实时翻译配音成中文。个人项目，单机跑（ThinkPad T14, Ubuntu 26.04），原则是**简单、易维护、不过度编程**。

### 总体四阶段路线

| 阶段 | 输入 | 输出 | 新增技术点 |
|---|---|---|---|
| 一：MP3 离线（**当前阶段**） | 3 分钟英文 MP3 | 中文配音音频 | STT→翻译→TTS 串联 + 时长对齐校验 |
| 二：本地视频 | MP4 | 中文配音 MP4 | ffmpeg 音轨剥离/混音 |
| 三：播放器实时音频 | 播放器输出流 | 实时中文跟读 | PipeWire 虚拟节点 + VAD 切片 + 滑动上下文 |
| 四：真实时推流 | 直播音视频流 | 稳定推流 | asyncio 并发、限流退避、断网容灾 |

### 全局关键设计决策

1. **provider 可插拔**：STT/翻译/TTS 三个环节统一数据契约，与具体 provider 返回格式解耦；provider 由配置项指定，免费转付费只加文件、不改主流程。
2. **共用重试/退避工具**：限流重试逻辑独立函数，被所有 provider 共用。
3. **翻译上下文**（阶段三起）：维护滑动上下文窗口，避免"句句对、连起来不通"。
4. **时长对齐**：`align_check` 作为阶段一验收标准之一。
5. **OBS 桥接独立**：作为单独可选阶段，不与阶段四异步重构混在一起验收。
6. **架构分野（重要）**：免费付费映射表里，"换更贵的同类 provider"（Deepgram/GPT/ElevenLabs）属于同架构换装，不影响现有契约；但"端到端双工模型"（Gemini Live / OpenAI Realtime，音频直接进直接出）是**完全不同的架构**，不复用 `Segment` 契约和三个抽象接口，应作为独立的"项目二"探索，不混进当前管线设计。

### 免费 → 付费映射表（同架构换装，不含端到端双工）

| 环节 | 现在（免费） | 以后可换（付费，同架构） |
|---|---|---|
| STT | Groq Whisper Large v3 Turbo | Deepgram Nova-3（约 $0.0043–0.0077/分钟）|
| 翻译 | Gemini 3.5 Flash 免费层 | 同模型付费层（约 $1.5/百万输入、$9/百万输出 token）|
| TTS | ~~edge-tts~~（已否决，见下）→ **Azure Speech F0** | OpenAI tts-1（~$15/百万字符）/ ElevenLabs（质量优先，~$0.1–0.3/千字符）|

---

## 二、项目一：Translator-Pilot 定稿设计

### 2.1 目录结构

```
translator-pilot/
  core/
    contracts.py      # Segment 定义，全项目唯一来源
    retry.py           # 共用重试/退避
    factory.py          # 配置名 -> provider 类的注册表
  stt/
    base.py             # abstract STTProvider
    groq_whisper.py      # 具体实现
  translate/
    base.py             # abstract TranslateProvider
    gemini.py
  tts/
    base.py             # abstract TTSProvider
    azure_speech.py      # 取代 edge-tts
  align_check.py         # 阶段一验收：原始时长 vs 配音时长比对
  pipeline.py            # 编排，只依赖 base.py 抽象类型
  settings.toml          # 行为配置，不进 git
  output/                # 运行时产物（中间音频、最终配音），.gitignore
```

无业务数据层（与 Stock Sentinel 模式不同），只有"配置（toml，不进 git）+ 运行时临时产物（output/，gitignore）"两层。

### 2.2 数据契约：`Segment`

| 字段 | 类型 | 说明 |
|---|---|---|
| `segment_id` | `str` | 唯一标识，建议 uuid4（自增整数在并发场景有竞争问题）|
| `start` | `float` | 起始时间，单位秒，浮点 |
| `end` | `float` | 结束时间，单位秒，浮点 |
| `source_text` | `str` | STT 产出的原文 |
| `target_text` | `str \| None` | 翻译产出，初始 `None` |
| `audio_path` | `str \| None` | TTS 产出的音频文件路径，初始 `None` |
| `context_window` | `list[str] \| None` | 阶段三专用（滑动上下文），阶段一不使用，先留字段 |

字段设计原则：从"翻译/TTS 消费端需要什么"倒推，而非照搬某个 STT provider 的原始返回结构，保持低耦合。

### 2.3 模块接口签名

- `STTProvider.transcribe(audio_path: str) -> list[Segment]`
- `TranslateProvider.translate(segments: list[Segment]) -> list[Segment]`（输入输出均为完整列表，内部维护滑动上下文，外部无感知）
- `TTSProvider.synthesize(segments: list[Segment]) -> list[Segment]`（填充 `audio_path`）

`pipeline.py` 只依赖这三个抽象类型，不感知具体 provider 是谁。

### 2.4 消灭硬编码

1. **Provider 选择**：`factory.py` 用字典注册表（配置名 → 类），新增 provider 只需"写新文件 + 注册一行"，不改 `pipeline.py`，不写 if/elif 链。
2. **Provider 专属参数**：API key、模型名、voice id 等一律放 `settings.toml`，按 provider 分节，代码里不出现任何具体模型名字符串。

### 2.5 `settings.toml` 结构

```toml
[provider]
stt = "groq_whisper"
translate = "gemini"
tts = "azure_speech"

[stt.groq_whisper]
api_key = ""
model = ""

[translate.gemini]
api_key = ""
model = ""

[tts.azure_speech]
api_key = ""
region = ""
voice = ""        # 中文神经语音名称，如 zh-CN-XiaoxiaoNeural

[retry]
max_retries = 3
base_delay = 1.0
backoff_factor = 2.0
max_delay = 30.0
```

### 2.6 重试/退避策略（`retry.py`）

| 参数 | 建议值 |
|---|---|
| `max_retries` | 3，超过抛异常，跳过/中止由上层（pipeline）决定，不是 retry.py 的职责 |
| `base_delay` | 1.0 秒 |
| `backoff_factor` | 2.0（延迟 = base_delay × backoff_factor^(n-1)）|
| `max_delay` | 30 秒上限 |
| `retryable_exceptions` | 可配置；429/超时类重试，401 这类直接失败不重试 |

第一版不解析 provider 的 `Retry-After` 头，先用固定指数退避，避免过度设计；实测不够用再加。

### 2.7 验收标准（阶段一完成的定义）

1. 输入 3 分钟英文 MP3，输出中文配音音频。
2. `align_check.py` 跑通：原始片段时长（`end - start`）与配音音频实际时长比对，超阈值要有告警，不是只打印"完成"。
3. provider 全部走 `settings.toml` 配置，代码里不出现 API key 或具体模型名字符串。
4. provider 出错时 `retry.py` 按配置重试，最终失败要有清晰报错（哪个 segment、哪个环节），不能静默吞掉。

---

## 三、TTS 选型过程（重要决策记录）

### 3.1 否决 edge-tts 的原因

edge-tts 调用的是微软 Edge 浏览器未公开授权的逆向工程接口，社区项目本身标注"use at your own risk"，无 SLA。一旦微软修改/限流该接口，整条管线会无预警瘫痪，是隐藏的单点故障。**已否决，不用于本项目任何阶段。**

### 3.2 候选对比

| 方案 | 免费额度 | 关键说明 |
|---|---|---|
| Sherpa-ONNX（语音助手项目同款） | 完全免费、自托管、无上限 | 开源权重官方分发，非逆向；缺点：音色单一（仅 baker 女声）、22050Hz 采样率、需编译/下载模型 |
| **Azure Speech TTS F0（已选定）** | 每月 50 万字符，永久有效 | 官方 API；**超额直接 429 拒绝，不会自动扣费**——这是选它的核心理由 |
| Google Cloud TTS | WaveNet 每月 100 万字符免费 | 官方 API，免费额度更大，但**必须启用 billing，超额会自动扣费**，对个人项目风险更高 |

**结论：选 Azure Speech F0**，理由不是免费额度大小（三者额度对 3 分钟 MP3 场景都用不完），而是"超额后的失败模式"——Azure 是安全的硬停止（429），Google 是自动计费，个人项目没有预算监控时 Azure 更保险。

### 3.3 Azure Speech TTS 接入注意事项（坑）

1. **Key 和 Region 强绑定**：region 参数必须和创建资源时的区域完全对应，错了直接 401，报错不直观。
2. **REST 调用需先换 token**：subscription key 换取的 access token **有效期仅 10 分钟**，批量处理 segment 总耗时若超过 10 分钟会中途过期——这是认证过期，不是网络/配额问题，`retry.py` 需要单独识别并处理"过期则换新 token"，不能当普通错误重试。
3. **F0 并发限制**：免费层基本只允许单并发，segment 必须串行处理；阶段三/四如果要上 asyncio 提速，这里会是硬瓶颈，现在先记下。
4. **中文 SSML 两处必须对齐**：`<speak xml:lang="zh-CN">` 和 `<voice name="zh-CN-XiaoxiaoNeural">`（示例），两处语言/语音不匹配会读出怪腔调或报错。
5. **文本需 XML 转义**：翻译结果中如含 `&`、`<`、`>`，直接拼进 SSML 会破坏结构，必须转义，容易在"翻译结果直接喂给 TTS"的链路中被漏掉。

---

## 四、Ansible 部署设计（项目一阶段）

沿用语音助手项目（roles/voiceassistant）已验证的模式，但按项目一的实际复杂度做了简化：

- **Vault 隔离密钥**：`azure_speech_key`、`azure_speech_region` 等放入 `group_vars/all.yml`（加密），不进明文仓库，与语音助手项目 `lva_ha_token` 的做法一致。
- **`settings.toml` 走模板渲染**：`settings.toml.j2`，Ansible 把 vault 变量塞入生成最终文件，代码中不出现任何密钥字符串。
- **不需要 systemd**：项目一是一次性批处理脚本，不是常驻服务。Ansible role 任务到"建 venv + 装依赖 + 渲染 settings.toml"为止，不提前抄语音助手项目里 `lva.service` 那套常驻服务配置——那是阶段三/四才需要的复杂度。
- **目录结构**：预计 `roles/translatorpilot/{defaults,tasks,templates}/main.yml`，单一 task 文件即可，不需要拆 `setup.yml`/`service.yml` 这种多文件结构（语音助手项目拆分是因为有 lva/stt/tts 三个常驻服务，项目一没有这个复杂度）。
- **部署目标**：先部署本机（ThinkPad T14），暂不上 VPS。

---

## 五、VPS 决策（暂缓，记录结论供未来参考）

**当前结论：项目一完全不需要 VPS**，纯本机批处理任务，引入 VPS 是为不存在的问题找方案。

VPS 真正有意义的场景是**阶段四（真实时推流）**，原因：公网 IP 可达（接收 OBS 推流/对外拉流）、机房出口带宽更稳（直播对上行抖动敏感）、7×24 不占用个人电脑。但每条都有前提（是否需要被外部访问、是否真要长时间无人值守直播），且要注意：

- 语音助手项目的设计哲学是"全离线、0 隐私泄露"；本项目本来就要调云端 STT/翻译/TTS，已非纯离线，若再加一层"音频经 VPS 转发"，等于多一段公网传输路径，是否在意取决于直播内容敏感度，需自行判断。
- 已有的 yattee-server（基于 yt-dlp 的自托管视频提取服务）在现有 VPS 上跑通，证明该 VPS 的 IP 信誉和 cookies 配置已经过验证，是现成可复用的资产，但需持续跟进 yt-dlp 更新和 cookies 刷新（YouTube 反爬策略持续变化，2026 年起新增 SABR 流、JS 签名验证等机制）。

**VPS 决策推迟到阶段四启动时再做。**

---

## 六、还未决定的事项（留待后续讨论）

- 阶段三的具体 VAD 切片参数、滑动上下文窗口大小
- 阶段二 ffmpeg 音轨混音的具体参数
- OBS 桥接阶段的技术选型细节
