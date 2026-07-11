# 架构演进建议书：从单体流水线到“AI 音频中台” (AI Audio Toolkit)

> 本文档用于总结关于系统架构“模块化与工具化封装”的建议，供您与其他 AI 团队成员进行评估和讨论。
> **最新更新**：重点补充了对于 TTS（语音合成）模块在“多角色分配、自定义音色、声音克隆”方向的扩展需求分析。

## 一、 核心起因与演进动机

**【核心驱动力】**：目前，**项目一（Translator-Pilot 实时翻译流水线）已经基本上实现了功能验证**。现在，我们需要在此基础上，增加一项全新的核心业务：**有声书自动生成功能（Audiobook-Generator）**。

有声书业务的加入，对系统的底层机制提出了更高的要求。结合前期的功能验证，我们各项基础能力现状如下：
*   **STT（语音识别）**：在原翻译项目中已较为成熟，基本无需大改。
*   **LLM / Translate（大模型推理/信息提取）**：之前已对各种大模型做过大量严格的 benchmark，其优秀的上下文理解能力完全可以平移到“有声书剧本的自动化提取与角色分类”任务中。
*   **TTS（语音合成）**：**【当前最大的突破口与技术债】**有声书系统不仅要求能发声，更要求**“多角色生动演绎”**。目前项目依赖的基础本地 TTS（如 Sherpa-ONNX）不足以支撑这种复杂场景。如果要实现高质量的小说自动转有声书，目前的 TTS 架构必须进行重大升级，补齐**自定义音色映射**与**声音克隆（Voice Cloning）**的能力。

由于“实时翻译”和“有声书生成”在底层都高度依赖大模型与 TTS 引擎，如果为有声书单独起一套代码，会导致极度严重的**代码冗余**。因此，强烈建议借着这次机会，顺势将系统重构为**“统一的底层能力库 (Core Toolkit) + 多业务线”**的中台架构。

---

## 二、 提议的系统架构 (中台化设计)

系统将严格分层：**底层只提供“能力”，顶层只负责“业务编排”。**

```mermaid
graph TD
    subgraph 基础设施层 (AI Audio Toolkit)
        Base[统一基建机制\n重试/退避/哈希缓存/并发限流]
        STT[STT 抽象工厂\n状态: 已成熟 (Whisper等)]
        LLM[LLM 抽象工厂\n状态: 已成熟 (历经Benchmark)]
        
        subgraph 核心增强区域: TTS 抽象工厂
            TTS_Standard[标准合成\nSherpa/Azure]
            TTS_Clone[声音克隆与自定义音色\nXTTS/CosyVoice/ElevenLabs]
            VoiceRouter[音色路由字典]
        end
        
        STT --> Base
        LLM --> Base
        TTS_Standard --> Base
        TTS_Clone --> Base
    end

    subgraph 业务层 1：实时翻译流水线 (Translator-Pilot)
        Pipeline1[主流程: 视音频转译]
        TimeAlign[模块: 时间轴严格对齐校验]
        
        Pipeline1 -.->|1. 调STT工具| STT
        Pipeline1 -.->|2. 调LLM工具| LLM
        Pipeline1 -.->|3. 调TTS工具| TTS_Standard
    end

    subgraph 业务层 2：有声书/多角色流水线 (Audiobook-Gen)
        Pipeline2[主流程: 小说转有声书]
        Extractor[模块: 脚本提取与角色路由]
        Assembler[模块: ffmpeg 无损拼接]
        
        Pipeline2 -.->|1. 调LLM工具| LLM
        Pipeline2 -.->|2. 调TTS克隆| TTS_Clone
    end
```

### 1. 基础设施层 (Core Toolkit) 设计原则
*   **无状态与无业务逻辑**：工具只负责单一职能，不关心顶层是直播翻译还是有声书。
*   **高度容错与统一缓存**：由基础设施层统一接管 `retry` 和 `backoff`，基于输入参数做 MD5 哈希缓存，节省算力与额度。

### 2. 【重点升级】TTS 模块的深度扩展
针对“分角色、自定义音色、声音克隆”的需求，底层的 TTS 封装必须具备以下能力：
*   **音色注册表（Voice Registry）**：支持在 `settings.toml` 中定义一个角色映射库（例如：`主角=voice_id_1`, `反派=voice_id_2`）。
*   **Zero-Shot 声音克隆接口**：支持传入一段短音频（Reference Audio）直接克隆音色（如对接本地的 CosyVoice/XTTSv2 或云端的 ElevenLabs）。
*   **富文本情绪控制**：支持解析 LLM 传来的 `emotion` 标签，并将其转化为底层 TTS 引擎能理解的 SSML 标签或 Prompt 提示词。

---

## 三、 可行性与必要性总结

### 🟢 可行性 (Feasibility)
**极高。** 现有的 `Translator-Pilot` 项目已经有了良好的 Provider 抽象。重构的工作量主要是将这些文件从具体的业务目录中抽离为公共库。由于 STT 和 LLM 已经过 benchmark 考验，我们有充足的精力专门攻坚 TTS 的改造。

### 🔴 必要性 (Necessity)
**强烈推荐。** 
1. **DRY 原则 (Don't Repeat Yourself)**：底层抽离后，任何对“声音克隆引擎”的接入和测试，都能立刻惠及所有上层业务线。
2. **极佳的扩展性**：未来开发“AI 播客对谈”或“视频配音”时，直接 `import toolkit` 即可。

---

## 四、 给其他 AI 的讨论议题建议

在评估本方案时，您可以与其他 AI 重点讨论以下三个问题：

1. **TTS 声音克隆引擎选型**：为了实现自动分角色和自定义音色，我们是打算部署强大的本地开源零样本克隆模型（如阿里的 CosyVoice、Coqui XTTS v2，需要一定显存），还是直接使用商业 API（如 ElevenLabs, OpenAI TTS）？这对底层架构的设计有决定性影响。
2. **接口泛化问题**：把能力封装成底层工具时，其入参出参如何设计，才能既满足翻译的需要（带时间戳），又满足有声书的需要（带角色情绪、甚至带 参考音频路径 进行克隆）？
3. **包管理策略**：这个 Core Toolkit 是作为一个本地目录被不同脚本相对引用，还是干脆打成一个私有的 Python 包（通过 `pip install -e .` 统一管理）？
