# Translator-Pilot — 项目一：本地离线直播翻译引擎（总览 + 项目一定稿）

> 最后更新：2026年7月1日 下午6:48（温哥华时间）

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

| 环节 | 现在（免费/低成本） | 以后可换（付费，同架构） |
|---|---|---|
| STT | Groq Whisper Large v3 Turbo | Deepgram Nova-3（约 $0.0043–0.0077/分钟）|
| 翻译 | **OpenAI gpt-4o-mini**（低成本） / NVIDIA LLM Qwen 122B（免费） / Mistral Large（免费） | 同模型付费层（约 $1.5/百万输入、$9/百万输出 token）|
| TTS | **Sherpa-ONNX 中英混合模型**（完全免费离线） / Azure Speech F0（备用） | OpenAI tts-1（~$15/百万字符）/ ElevenLabs（质量优先，~$0.1–0.3/千字符）|

---

## 二、项目一：Translator-Pilot 定稿设计

### 2.1 目录结构

```
translator-pilot/
  core/
    contracts.py      # Segment 定义，全项目唯一来源
    retry.py           # 共用重试/退避
    factory.py          # 配置名 -> provider 类的注册表
    cache.py            # 统一缓存管理器
  stt/
    base.py             # abstract STTProvider
    groq_whisper.py      # Groq Whisper STT
    gemini.py            # Gemini STT
  translate/
    base.py             # abstract TranslateProvider
    openai.py            # OpenAI 翻译
    mistral.py           # Mistral 翻译
    gemini.py            # Gemini 翻译
    groq_llm.py          # Groq LLM 翻译
    nvidia_llm.py        # NVIDIA LLM 翻译
  tts/
    base.py             # abstract TTSProvider
    sherpa_onnx.py       # Sherpa-ONNX 中英混合模型（主要）
    azure_speech.py      # Azure Speech TTS（备用）
    gemini_tts.py         # Gemini TTS
    nvidia_magpie.py      # NVIDIA Magpie TTS
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
translate = "openai"
tts = "sherpa_onnx"

[stt.groq_whisper]
api_key = ""
model = ""
timeout = 60

[stt.gemini]
api_key = ""
model = ""
timeout = 60

[translate.openai]
api_key = ""
model = "gpt-4o-mini"
system_prompt = """..."""
user_prompt = """..."""
timeout = 60
batch_size = 20
temperature = 0.3
max_tokens = 4096
enable_cache = false

[translate.mistral]
api_key = ""
model = "mistral-large-latest"
system_prompt = """..."""
user_prompt = """..."""
timeout = 60
batch_size = 20
temperature = 0.3
max_tokens = 4096
enable_cache = false

[translate.nvidia_llm]
api_key = ""
model = "qwen/qwen-122b-chat"
system_prompt = """..."""
user_prompt = """..."""
timeout = 120
batch_size = 20
temperature = 0.3
max_tokens = 4096
enable_cache = false

[translate.gemini]
api_key = ""
model = "gemini-2.0-flash-exp"
system_prompt = """..."""
user_prompt = """..."""
timeout = 60
batch_size = 20
temperature = 0.3
max_tokens = 4096
enable_cache = false

[translate.groq_llm]
api_key = ""
model = "llama-3.3-70b-versatile"
system_prompt = """..."""
user_prompt = """..."""
timeout = 60
batch_size = 20
temperature = 0.3
enable_cache = false

[tts.sherpa_onnx]
model_dir = "/path/to/matcha-icefall-zh-en"
vocoder_path = "/path/to/vocos-16khz-univ.onnx"
num_threads = 4
volume_gain = 2.0
phone_fst = "phone-zh.fst"
date_fst = "date-zh.fst"
number_fst = "number-zh.fst"
enable_cache = true

[tts.azure_speech]
api_key = ""
region = ""
voice = ""
timeout = 30
enable_cache = true

[tts.gemini_tts]
api_key = ""
model = "gemini-2.0-flash-exp"
voice = "Chirp-HD"
timeout = 30
enable_cache = true

[tts.nvidia_magpie]
api_key = ""
language = "zh-CN"
voice = "Magpie-Multilingual.ZH-CN.Aria"
sample_rate_hz = 44100
timeout = 60
enable_cache = true

[retry]
max_retries = 3
base_delay = 1.0
backoff_factor = 2.0
max_delay = 30.0

[cache]
enable_translate_cache = false
enable_tts_cache = true
```

### 2.6 缓存策略设计（重要）

**设计原则：翻译缓存默认禁用，TTS 缓存默认启用**

#### 翻译缓存策略

**默认禁用** (`enable_translate_cache = false`)

**理由：**
1. **上下文依赖性**：翻译需要考虑上下文，同一个句子在不同上下文中可能有不同翻译。代词、时态、语气等都需要前后文信息。
2. **术语一致性**：专业术语的翻译需要在整个文档中保持一致，单个 segment 的缓存无法保证全局一致性。
3. **批次翻译**：当前实现采用批次翻译（batch_size=20），本身就考虑了上下文，单个 segment 缓存反而破坏了上下文连贯性。

**何时启用：**
- 处理重复性内容（如模板、固定短语）
- 调试阶段快速验证
- 确认上下文不影响翻译质量时

#### TTS 缓存策略

**默认启用** (`enable_tts_cache = true`)

**理由：**
1. **文本-语音映射稳定**：相同文本的语音输出应该一致，不需要上下文。
2. **性能提升显著**：TTS 生成耗时较长（尤其是云端 API），缓存可以大幅提升重复内容的处理速度。
3. **成本节省**：减少对云端 TTS API 的调用次数，降低费用。

**缓存 Key 设计：**
- Azure Speech: `text + voice`
- Gemini TTS: `text + voice`
- NVIDIA Magpie: `text + voice + language + sample_rate`
- Sherpa-ONNX: `text + volume_gain`

#### 缓存实现

**统一缓存管理器** (`cache.py`)：
- 支持文件缓存（TTS 音频）和 JSON 数据缓存（翻译结果）
- 缓存目录：`cache/{type}/`（type: translate, wav）
- 缓存 Key：基于稳定参数的 MD5 哈希
- 自动创建缓存目录，无需手动管理

**配置控制：**
- 全局开关：`[cache]` 配置段
- Provider 级别：每个 provider 可独立控制 `enable_cache`
- 默认值：翻译 false，TTS true

### 2.7 重试/退避策略（`retry.py`）

| 参数 | 建议值 |
|---|---|
| `max_retries` | 3，超过抛异常，跳过/中止由上层（pipeline）决定，不是 retry.py 的职责 |
| `base_delay` | 1.0 秒 |
| `backoff_factor` | 2.0（延迟 = base_delay × backoff_factor^(n-1)）|
| `max_delay` | 30 秒上限 |
| `retryable_exceptions` | 可配置；429/超时类重试，401 这类直接失败不重试 |

第一版不解析 provider 的 `Retry-After` 头，先用固定指数退避，避免过度设计；实测不够用再加。

### 2.8 验收标准（阶段一完成的定义）

1. 输入 3 分钟英文 MP3，输出中文配音音频。
2. `align_check.py` 跑通：原始片段时长（`end - start`）与配音音频实际时长比对，超阈值要有告警，不是只打印"完成"。
3. provider 全部走 `settings.toml` 配置，代码里不出现 API key 或具体模型名字符串。
4. provider 出错时 `retry.py` 按配置重试，最终失败要有清晰报错（哪个 segment、哪个环节），不能静默吞掉。
5. 缓存策略正确实现：翻译缓存默认禁用，TTS 缓存默认启用，可通过配置控制。

---

## 三、TTS 选型过程（重要决策记录）

### 3.1 否决 edge-tts 的原因

edge-tts 调用的是微软 Edge 浏览器未公开授权的逆向工程接口，社区项目本身标注"use at your own risk"，无 SLA。一旦微软修改/限流该接口，整条管线会无预警瘫痪，是隐藏的单点故障。**已否决，不用于本项目任何阶段。**

### 3.2 候选对比

| 方案 | 免费额度 | 关键说明 |
|---|---|---|
| **Sherpa-ONNX 中英混合模型（已选定）** | 完全免费、自托管、无上限 | 开源权重官方分发，非逆向；支持中英文混合；音质好、速度快；缺点：需要下载模型文件（约 1GB）|
| Azure Speech TTS F0（备用） | 每月 50 万字符，永久有效 | 官方 API；**超额直接 429 拒绝，不会自动扣费**——这是选它的核心理由 |
| Google Cloud TTS | WaveNet 每月 100 万字符免费 | 官方 API，免费额度更大，但**必须启用 billing，超额会自动扣费**，对个人项目风险更高 |

**结论：选 Sherpa-ONNX 中英混合模型**，理由：
1. **完全免费离线**：无网络依赖，无配额限制，适合个人项目
2. **中英混合支持**：`matcha-icefall-zh-en` 模型支持中英文混合内容，解决了纯中文模型无法处理英文单词的问题
3. **音质和速度**：使用 Matcha-TTS + Vocos 声码器，音质好且生成速度快
4. **可配置性**：支持 FST 文件配置（phone/date/number），灵活适应不同模型

**Azure Speech F0 作为备用**，当需要更高音质或特殊语音时使用。

### 3.3 Sherpa-ONNX 中英混合模型配置

**模型信息：**
- **模型名称**：`matcha-icefall-zh-en`
- **下载地址**：https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/matcha-icefall-zh-en.tar.bz2
- **声码器**：`vocos-16khz-univ.onnx`
- **下载地址**：https://github.com/k2-fsa/sherpa-onnx/releases/download/vocoder-models/vocos-16khz-univ.onnx
- **FST 文件**：`phone-zh.fst`, `date-zh.fst`, `number-zh.fst`（中英混合模型使用 `-zh` 后缀）

**配置项：**
```toml
[tts.sherpa_onnx]
model_dir = "/path/to/matcha-icefall-zh-en"
vocoder_path = "/path/to/vocos-16khz-univ.onnx"
num_threads = 4
volume_gain = 2.0
phone_fst = "phone-zh.fst"
date_fst = "date-zh.fst"
number_fst = "number-zh.fst"
enable_cache = true
```

**注意事项：**
1. **data_dir 配置**：中英混合模型需要 `espeak-ng-data` 目录，代码会自动检测，如果不存在则使用空字符串（纯中文模型兼容）
2. **FST 文件名**：不同模型的 FST 文件名不同，纯中文模型使用 `phone.fst`，中英混合模型使用 `phone-zh.fst`，通过配置项灵活适配
3. **volume_gain**：默认 2.0，可根据需要调整音量增益
4. **num_threads**：默认 4，可根据 CPU 核心数调整

### 3.4 Azure Speech TTS 接入注意事项（坑）

1. **Key 和 Region 强绑定**：region 参数必须和创建资源时的区域完全对应，错了直接 401，报错不直观。
2. **REST 调用需先换 token**：subscription key 换取的 access token **有效期仅 10 分钟**，批量处理 segment 总耗时若超过 10 分钟会中途过期——这是认证过期，不是网络/配额问题，`retry.py` 需要单独识别并处理"过期则换新 token"，不能当普通错误重试。
3. **F0 并发限制**：免费层基本只允许单并发，segment 必须串行处理；阶段三/四如果要上 asyncio 提速，这里会是硬瓶颈，现在先记下。
4. **中文 SSML 两处必须对齐**：`<speak xml:lang="zw-CN">` 和 `<voice name="zh-CN-XiaoxiaoNeural">`（示例），两处语言/语音不匹配会读出怪腔调或报错。
5. **文本需 XML 转义**：翻译结果中如含 `&`、`<`、`>`，直接拼进 SSML 会破坏结构，必须转义，容易在"翻译结果直接喂给 TTS"的链路中被漏掉。

---

## 四、Ansible 部署设计（项目一阶段）

沿用语音助手项目（roles/voiceassistant）已验证的模式，但按项目一的实际复杂度做了简化：

- **Vault 隔离密钥**：所有 API key（`openai_api_key`、`mistral_api_key`、`nvidia_api_key`、`gemini_api_key`、`azure_speech_key` 等）放入 `group_vars/secrets.yml`（加密），不进明文仓库，与语音助手项目 `lva_ha_token` 的做法一致。
- **`settings.toml` 走模板渲染**：`settings.toml.j2`，Ansible 把 vault 变量塞入生成最终文件，代码中不出现任何密钥字符串。
- **模型下载任务**：Ansible 自动下载 Sherpa-ONNX 模型（`matcha-icefall-zh-en` 和 `vocos-16khz-univ.onnx`），无需手动操作。
- **不需要 systemd**：项目一是一次性批处理脚本，不是常驻服务。Ansible role 任务到"建 venv + 装依赖 + 渲染 settings.toml + 下载模型"为止，不提前抄语音助手项目里 `lva.service` 那套常驻服务配置——那是阶段三/四才需要的复杂度。
- **目录结构**：`roles/translatorpilot/{defaults,tasks,templates}/main.yml`，单一 task 文件即可，不需要拆 `setup.yml`/`service.yml` 这种多文件结构（语音助手项目拆分是因为有 lva/stt/tts 三个常驻服务，项目一没有这个复杂度）。
- **部署目标**：先部署本机（ThinkPad T14），暂不上 VPS。

**当前部署配置：**
```yaml
# group_vars/all.yml
stt_provider: "groq_whisper"
translate_provider: "openai"
tts_provider: "sherpa_onnx"

# API General Settings
api_timeout: 60
api_batch_size: 20
api_temperature: 0.3
api_max_tokens: 4096

# Cache Settings
enable_translate_cache: false
enable_tts_cache: true
```

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
