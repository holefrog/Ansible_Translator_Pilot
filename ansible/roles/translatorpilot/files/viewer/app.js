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

    function handleState(data) {
        if (data.status === 'error') {
            document.getElementById('status').style.display = 'block';
            document.getElementById('loader').style.display = 'none';
            document.getElementById('progress-container').style.display = 'block';
            document.getElementById('progress-bar').style.backgroundColor = '#dc2626';
            document.getElementById('progress-bar').style.width = '100%';
            document.getElementById('loading-text').innerHTML = `<span style="color:#dc2626; font-weight: bold;">⚠️ 运行出错: Pipeline Error</span>`;
            document.getElementById('progress-msg').innerHTML = `<span style="color:#dc2626;">${data.error || data.message || 'Unknown error occurred.'}</span>`;
            
            const sttEl = document.getElementById('stage-stt');
            const transEl = document.getElementById('stage-translate');
            const ttsEl = document.getElementById('stage-tts');
            if (sttEl) sttEl.className = 'stage-badge pending';
            if (transEl) transEl.className = 'stage-badge pending';
            if (ttsEl) ttsEl.className = 'stage-badge pending';
            
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

            if (data.timings) {
                if (data.timings.stt !== null) document.getElementById('time-stt').textContent = data.timings.stt.toFixed(1) + '秒';
                if (data.timings.translate !== null) document.getElementById('time-translate').textContent = data.timings.translate.toFixed(1) + '秒';
                if (data.timings.tts !== null) document.getElementById('time-tts').textContent = data.timings.tts.toFixed(1) + '秒';
            }

            // Update Pipeline Stages Status
            const sttEl = document.getElementById('stage-stt');
            const transEl = document.getElementById('stage-translate');
            const ttsEl = document.getElementById('stage-tts');
            const arr1 = document.getElementById('arrow-1');
            const arr2 = document.getElementById('arrow-2');

            if (sttEl && transEl && ttsEl) {
                const msg = (data.message || '').toLowerCase();

                if (msg.includes('transcrib') || p < 40) {
                    sttEl.className = 'stage-badge active';
                } else if (p >= 40) {
                    sttEl.className = 'stage-badge completed';
                    if (arr1) arr1.className = 'stage-arrow active';
                }

                if (msg.includes('translat') || (p >= 40 && p < 75)) {
                    transEl.className = 'stage-badge active';
                } else if (p >= 75) {
                    transEl.className = 'stage-badge completed';
                    if (arr2) arr2.className = 'stage-arrow active';
                }

                if (msg.includes('synthesiz') || p >= 75) {
                    ttsEl.className = 'stage-badge active';
                }
            }
        } else if (data.status === 'completed') {
            document.getElementById('status').style.display = 'none';
            document.getElementById('content').style.display = 'block';
            hasFinished = true;
            clearInterval(pollInterval);
            if (data.timings) {
                if (data.timings.stt !== null) document.getElementById('time-stt').textContent = data.timings.stt.toFixed(1) + '秒';
                if (data.timings.translate !== null) document.getElementById('time-translate').textContent = data.timings.translate.toFixed(1) + '秒';
                if (data.timings.tts !== null) document.getElementById('time-tts').textContent = data.timings.tts.toFixed(1) + '秒';
            }
            renderSegments(data);
        }

        // We can partially render segments even while running!
        if (data.segments && data.segments.length > 0 && !hasFinished && data.status !== 'error') {
            // Only partially render if we want to stream visually. For now, let's keep it simple: 
            // We can just show the real-time segments in the background, but UI might jump.
            // Let's actually render them so user sees real-time progress!
            document.getElementById('content').style.display = 'block';
            renderSegments(data);
        }
    }

    function renderSegments(data) {
        if (data.engines) {
            const formatEngine = (label, provider) => `<span style="color: var(--accent-color);">${label}:</span> <span style="color: var(--primary-color); font-weight: bold;">${provider}</span>`;
            document.getElementById('stat-stt').innerHTML = formatEngine('STT', data.engines.stt);
            document.getElementById('stat-translate').innerHTML = formatEngine('Translate', data.engines.translate);
            document.getElementById('stat-tts').innerHTML = formatEngine('TTS', data.engines.tts);
        }

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