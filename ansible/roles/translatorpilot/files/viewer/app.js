let currentAudio = null;
    let currentBtn = null;

    const playIcon = `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
    const stopIcon = `<svg viewBox="0 0 24 24"><path d="M6 6h12v12H6z"/></svg>`;
    
    let pollInterval = null;
    let hasFinished = false;

    async function pollState() {
        if (hasFinished) return;
        try {
            // Add cache-buster to ensure we get the latest state
            const response = await fetch('pipeline_state.json?t=' + new Date().getTime());
            if (!response.ok) {
                // If it's a 404, it might just mean the pipeline hasn't created the file yet.
                // We keep polling.
                return;
            }
            const data = await response.json();
            handleState(data);
        } catch (e) {
            // Ignore fetch errors during early boot
        }
    }

    function updateStageCards(timings, engines, p, msg) {
        const dashboard = document.getElementById('dashboard');
        if (dashboard) dashboard.style.display = '';

        if (timings) {
            if (timings.stt       !== null) document.getElementById('time-stt').textContent       = timings.stt.toFixed(1) + ' 秒';
            if (timings.translate !== null) document.getElementById('time-translate').textContent = timings.translate.toFixed(1) + ' 秒';
            if (timings.tts       !== null) document.getElementById('time-tts').textContent       = timings.tts.toFixed(1) + ' 秒';
        }
        if (engines) {
            if (engines.stt)       document.getElementById('engine-stt').textContent       = engines.stt;
            if (engines.translate) document.getElementById('engine-translate').textContent = engines.translate;
            if (engines.tts)       document.getElementById('engine-tts').textContent       = engines.tts;
        }

        // Active / completed highlights on stage cards
        const cardStt   = document.getElementById('card-stt');
        const cardTrans = document.getElementById('card-translate');
        const cardTts   = document.getElementById('card-tts');
        if (!cardStt) return;

        const lmsg = (msg || '').toLowerCase();

        // STT
        if (p >= 40) {
            cardStt.className = 'stat-card stage-card completed';
        } else {
            cardStt.className = 'stat-card stage-card active';
        }
        // Translate
        if (p >= 75) {
            cardTrans.className = 'stat-card stage-card completed';
        } else if (p >= 40) {
            cardTrans.className = 'stat-card stage-card active';
        } else {
            cardTrans.className = 'stat-card stage-card';
        }
        // TTS
        if (p >= 95) {
            cardTts.className = 'stat-card stage-card completed';
        } else if (p >= 75) {
            cardTts.className = 'stat-card stage-card active';
        } else {
            cardTts.className = 'stat-card stage-card';
        }
    }

    function handleState(data) {
        if (data.status === 'error') {
            document.getElementById('status').style.display = 'block';
            document.getElementById('loader').style.display = 'none';
            document.getElementById('progress-container').style.display = 'block';
            document.getElementById('progress-bar').style.backgroundColor = '#dc2626';
            document.getElementById('progress-bar').style.width = '100%';
            document.getElementById('loading-text').innerHTML = `<span style="color:#dc2626; font-weight: bold;">⚠️ 运行出错: Pipeline Error</span>`;
            document.getElementById('progress-msg').innerHTML = `<span style="color:#dc2626;">${data.error || data.message || 'Unknown error occurred.'}</span>`;
            hasFinished = true;
            window.pipelineCompletedTriggered = true;
            clearInterval(pollInterval);
            return;
        }

        if (data.status === 'running') {
            document.getElementById('status').style.display = 'block';
            document.getElementById('loading-text').textContent = '流水线运行中...';
            document.getElementById('progress-msg').textContent = data.message || '正在处理...';
            document.getElementById('progress-container').style.display = 'block';
            const p = data.progress || 0;
            document.getElementById('progress-bar').style.width = p + '%';
            updateStageCards(data.timings, data.engines, p, data.message);
        } else if (data.status === 'completed') {
            // Hide spinner, keep progress bar visible for reference
            document.getElementById('loader').style.display = 'none';
            document.getElementById('loading-text').style.display = 'none';
            document.getElementById('progress-msg').style.display = 'none';
            document.getElementById('content').style.display = 'block';
            hasFinished = true;
            clearInterval(pollInterval);
            updateStageCards(data.timings, data.engines, 100, '');
            renderSegments(data);
        }

        // Partial real-time segment rendering while running
        if (data.segments && data.segments.length > 0 && !hasFinished && data.status !== 'error') {
            document.getElementById('content').style.display = 'block';
            renderSegments(data);
        }
    }

    function renderSegments(data) {
        // Engine names and timings are now rendered by updateStageCards; nothing extra needed here.

        if (data.has_fallback) {
            document.getElementById('fallback-alert').style.display = 'block';
        } else {
            document.getElementById('fallback-alert').style.display = 'none';
        }

        if (data.status === 'completed' && !window.pipelineCompletedTriggered) {
            window.pipelineCompletedTriggered = true;
            document.getElementById('completion-banner').style.display = 'block';
        }

        const segments = data.segments || [];
        const alignmentReport = data.alignmentReport || [];

        // Calculate stats
        document.getElementById('stat-segments').textContent = segments.length;
        
        let totalDuration = 0;
        let warnings = 0;
        
        const reportMap = {};
        alignmentReport.forEach(r => {
            reportMap[r.segment_id] = r;
            totalDuration += r.synthesized_duration;
            if (r.warning) warnings++;
        });

        document.getElementById('stat-duration').textContent = totalDuration.toFixed(1) + 's';
        document.getElementById('stat-warnings').textContent = warnings;
        
        const statWarningsEl = document.getElementById('stat-warnings');
        if (warnings > 0) {
            statWarningsEl.style.color = 'var(--warning-color)';
        } else {
            statWarningsEl.style.color = 'var(--success-color)';
        }

        const container = document.getElementById('segments-container');
        container.innerHTML = '';
        
        let maxDuration = 1;
        segments.forEach(seg => {
            const report = reportMap[seg.segment_id];
            if (report) {
                if (report.original_duration > maxDuration) maxDuration = report.original_duration;
                if (report.synthesized_duration > maxDuration) maxDuration = report.synthesized_duration;
            }
        });

        segments.forEach((seg, index) => {
            const report = reportMap[seg.segment_id] || {};
            const isWarning = report.warning;
            const ratioStr = report.ratio ? report.ratio.toFixed(2) + 'x' : 'N/A';
            const durationStr = report.synthesized_duration ? report.synthesized_duration.toFixed(2) + 's' : '0.0s';
            const originalDurationStr = report.original_duration ? report.original_duration.toFixed(2) + 's' : '0.0s';
            
            const enWidth = report.original_duration ? (report.original_duration / maxDuration) * 100 : 0;
            const cnWidth = report.synthesized_duration ? (report.synthesized_duration / maxDuration) * 100 : 0;

            const badgeClass = isWarning ? 'warning' : 'perfect';
            const badgeText = isWarning ? '超出时长' : '完美对齐';

            let audioFilename = seg.audio_path;
            if (audioFilename && audioFilename.includes('/')) {
                audioFilename = audioFilename.split('/').pop();
            }
            
            // Only show play button if we have an audio path
            const playButtonHTML = audioFilename ? `
                <button class="play-btn" onclick="toggleAudio(this, '${audioFilename}')" title="播放音频">
                    ${playIcon}
                </button>
            ` : `
                <button class="play-btn" disabled title="正在合成...">
                    ${playIcon}
                </button>
            `;

            const card = document.createElement('div');
            card.className = 'segment-card';
            card.innerHTML = `
                <div class="segment-content">
                    <div class="text-group">
                        <div class="source-text">${seg.source_text || ''}</div>
                        <div class="target-text">${seg.target_text || '翻译中...'}</div>
                    </div>
                    <div class="segment-meta">
                        <span>#${index + 1}</span>
                        ${report.ratio ? `
                        <span>&bull;</span>
                        <span class="badge ${badgeClass}">${badgeText} (${ratioStr})</span>
                        ` : ''}
                    </div>
                    ${report.ratio ? `
                    <div class="duration-bars" title="EN: ${originalDurationStr} | CN: ${durationStr}">
                        <div class="bar-container">
                            <span class="bar-label">EN</span>
                            <div class="bar-track">
                                <div class="bar-fill en-fill" style="width: ${enWidth}%;"></div>
                            </div>
                            <span class="bar-time">${originalDurationStr}</span>
                        </div>
                        <div class="bar-container">
                            <span class="bar-label">CN</span>
                            <div class="bar-track">
                                <div class="bar-fill cn-fill ${isWarning ? 'warning-fill' : ''}" style="width: ${cnWidth}%;"></div>
                            </div>
                            <span class="bar-time">${durationStr}</span>
                        </div>
                    </div>
                    ` : ''}
                </div>
                <div class="play-controls">
                    ${playButtonHTML}
                </div>
            `;
            container.appendChild(card);
        });
    }

    function renderData(data) {
        document.getElementById('status').style.display = 'none';
        document.getElementById('content').style.display = 'block';
        renderSegments(data);
    }

    function toggleAudio(btn, src) {
        if (!src || src === 'null' || src === 'undefined') {
            alert("No audio file available for this segment.");
            return;
        }

        // If clicking the same playing button, stop it
        if (currentAudio && currentBtn === btn) {
            stopCurrentAudio();
            return;
        }

        // If clicking a different button while playing, stop the old one
        if (currentAudio) {
            stopCurrentAudio();
        }

        // Play new audio
        currentBtn = btn;
        btn.classList.add('playing');
        btn.innerHTML = stopIcon;

        currentAudio = new Audio(src);
        currentAudio.play().catch(e => {
            console.error("Audio playback failed:", e);
            alert("Failed to play audio. The file might be missing or corrupted.");
            stopCurrentAudio();
        });

        currentAudio.onended = () => {
            stopCurrentAudio();
        };
    }

    function stopCurrentAudio() {
        if (currentAudio) {
            currentAudio.pause();
            currentAudio.currentTime = 0;
            currentAudio = null;
        }
        if (currentBtn) {
            currentBtn.classList.remove('playing');
            currentBtn.innerHTML = playIcon;
            currentBtn = null;
        }
    }

    // Initialize Polling
    window.addEventListener('DOMContentLoaded', () => {
        // Clear any old data
        pollState();
        pollInterval = setInterval(pollState, 1000);
    });

    window.addEventListener("pagehide", function() {
        if (window.pipelineCompletedTriggered) {
            navigator.sendBeacon("/SHUTDOWN_SERVER");
        }
    });

    function shutdownServer() {
        if(confirm("确定要关闭服务器并退出吗？页面上的音频将无法再播放。")) {
            navigator.sendBeacon("/SHUTDOWN_SERVER");
            setTimeout(() => { window.close(); }, 300);
        }
    }