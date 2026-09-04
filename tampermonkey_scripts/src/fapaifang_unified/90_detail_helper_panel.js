        function createPanel() {
            let panel = document.getElementById('detail-helper-panel');
            if (!panel) {
                panel = document.createElement('div');
                panel.id = 'detail-helper-panel';
                document.body.appendChild(panel);
            }
            updatePanelStyle();
        }

        function updatePanelStyle() {
            const panel = document.getElementById('detail-helper-panel');
            if (!panel) return;

            if (isPanelMinimized) {
                panel.innerHTML = `
                    <div style="padding: 8px 12px; background: #f5f5f5; display: flex; justify-content: space-between; align-items: center;">
                        <b style="font-size: 14px;">📝 助手</b>
                        <div>
                            <button id="dh-bar-refresh" style="border:none; background:none; cursor:pointer;" title="同步">🔄</button>
                            <button id="dh-bar-expand" style="border:none; background:none; cursor:pointer;" title="展开">🔼</button>
                        </div>
                    </div>`;
                Object.assign(panel.style, {
                    position: 'fixed', top: '100px', right: '20px', width: '200px', height: 'auto',
                    background: 'white', border: '1px solid #ccc', zIndex: '999990',
                    borderRadius: '8px', boxShadow: '0 0 10px rgba(0,0,0,0.1)'
                });
                document.getElementById('dh-bar-expand').onclick = togglePanel;
                document.getElementById('dh-bar-refresh').onclick = () => refreshData();
            } else {
                Object.assign(panel.style, {
                    position: 'fixed', top: '100px', right: '20px', width: '320px', maxHeight: '80vh',
                    background: 'white', border: '1px solid #ccc', zIndex: '999990', overflowY: 'auto',
                    borderRadius: '8px', boxShadow: '0 0 20px rgba(0,0,0,0.2)'
                });
                renderPanelContent(panel);
                refreshData();
            }
        }

        function togglePanel() {
            isPanelMinimized = !isPanelMinimized;
            GM_setValue('dh_panel_minimized', isPanelMinimized);
            updatePanelStyle();
        }

        function renderPanelContent(panel) {
            panel.innerHTML = `
                <div style="padding: 12px; background: #f5f5f5; border-bottom: 1px solid #ddd; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 10;">
                    <b style="font-size: 14px;">📝 数据录入助手</b>
                    <div>
                         <button id="dh-btn-refresh" style="border:none; background:none; cursor:pointer; font-size:16px;" title="刷新">🔄</button>
                         <button id="dh-btn-min" style="border:none; background:none; cursor:pointer; font-size:16px;" title="最小化">➖</button>
                    </div>
                </div>
                <div id="dh-form-container" style="padding: 15px;"></div>
                <div style="padding: 12px; background: #f5f5f5; border-top: 1px solid #ddd; position: sticky; bottom: 0; text-align: center;">
                    <div id="dh-status" style="margin-bottom: 8px; font-size: 12px; color: #666; height: 1.5em;"></div>
                    <div style="display: flex; gap: 8px;">
                        <button id="dh-btn-infer" style="flex: 1; padding: 10px; background: #9c27b0; color: white; border: none; border-radius: 4px; cursor: pointer;">🔍 推断位置</button>
                        <button id="dh-btn-submit" style="flex: 2; padding: 10px; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">提交保存</button>
                    </div>
                </div>`;

            const container = panel.querySelector('#dh-form-container');
            FIELDS.forEach(field => {
                const row = document.createElement('div');
                row.style.marginBottom = '10px';
                const label = document.createElement('label');
                label.textContent = field.label;
                label.style.display = 'block';
                label.style.marginBottom = '4px';
                label.style.color = '#666';

                let input = document.createElement('input');
                if (field.type === 'checkbox') {
                    input.type = 'checkbox';
                    label.style.display = 'inline-block';
                    input.style.marginLeft = '8px';
                    row.appendChild(label);
                    row.appendChild(input);
                } else {
                    input.type = field.type;
                    input.style.width = '100%';
                    input.style.padding = '6px';
                    input.style.border = '1px solid #ccc';
                    input.style.borderRadius = '4px';
                    if (field.readonly) { input.readOnly = true; input.style.background = '#eee'; }
                    if (field.step) input.step = field.step;
                    row.appendChild(label);
                    row.appendChild(input);
                }
                input.id = `dh-input-${field.key}`;
                if (['建筑面积', '成交价格', '起拍价格'].includes(field.key)) {
                    input.addEventListener('input', calculateUnitPrice);
                }
                container.appendChild(row);
            });

            document.getElementById('dh-btn-min').onclick = togglePanel;
            document.getElementById('dh-btn-refresh').onclick = () => refreshData();
            document.getElementById('dh-btn-submit').onclick = submitData;
            document.getElementById('dh-btn-infer').onclick = inferLocation;
        }

        // --- Actions ---
        
        async function refreshData() {
            const data = await loadDataWithPriority();
            FIELDS.forEach(field => {
                const input = document.getElementById(`dh-input-${field.key}`);
                if (input) {
                    if (field.type === 'checkbox') input.checked = !!data[field.key];
                    else input.value = (data[field.key] !== undefined && data[field.key] !== null) ? data[field.key] : '';
                }
            });
            calculateUnitPrice();
            
            if (IS_AUTO_MODE) {
                const areaInput = document.getElementById('dh-input-建筑面积');
                if (areaInput && (!parseFloat(areaInput.value) || parseFloat(areaInput.value) === 0)) {
                    scrollAndRetryArea();
                } else {
                    checkAutoSubmit();
                }
            }
        }
        
        function calculateUnitPrice() {
             const area = parseFloat(document.getElementById('dh-input-建筑面积')?.value) || 0;
             let price = parseFloat(document.getElementById('dh-input-成交价格')?.value) || 0;
             if (price <= 0) price = parseFloat(document.getElementById('dh-input-起拍价格')?.value) || 0;
             
             const unitInput = document.getElementById('dh-input-单价');
             if (unitInput) {
                 unitInput.value = (area > 0 && price > 0) ? (price / area).toFixed(2) : 0;
             }
        }
        
        function scrollAndRetryArea() {
            updateStatus('⏳ 滚动加载详情中...');
            window.scrollTo({ top: document.body.scrollHeight * 0.75, behavior: 'smooth' });
            setTimeout(() => {
                const pageText = document.body.innerText;
                const areaPatterns = [
                    /(?<!套内)建筑面积[：:\s]*[约为]*(\d+(?:[.,]\d+)?)\s*(?:平方米|平米|㎡|m²)?/i,
                    /房屋建筑面积[：:\s]*[约为]*(\d+(?:[.,]\d+)?)/i,
                ];
                let foundArea = 0;
                for (const p of areaPatterns) {
                    const m = pageText.match(p);
                    if (m) { foundArea = parseFloat(m[1].replace(',', '.')); break; }
                }
                
                if (foundArea > 0) {
                    const el = document.getElementById('dh-input-建筑面积');
                    if(el) el.value = foundArea;
                    calculateUnitPrice();
                    updateStatus('✅ 建筑面积已补充提取');
                } else {
                    updateStatus('⚠️ 面积未找到，继续提交');
                }
                window.scrollTo({ top: 0, behavior: 'smooth' });
                checkAutoSubmit();
            }, 3000);
        }
        
        function inferLocation(callback) {
            const address = document.getElementById('dh-input-完整地址')?.value.trim() || document.getElementById('dh-input-地点')?.value.trim();
            if (!address) { updateStatus('⚠️ 需要地址', '#ff9800'); return; }
            
            updateStatus('🔍 AI推断位置中...', '#9c27b0');
            const btn = document.getElementById('dh-btn-infer');
            if(btn) btn.disabled = true;

            fetchApi('/infer_location', { address: address, title: document.title }, (result) => {
                if(btn) btn.disabled = false;
                let updated = [];
                if (result['所属小区']) {
                     const el = document.getElementById('dh-input-所属小区');
                     if(el) { el.value = result['所属小区']; updated.push('小区: '+result['所属小区']); }
                }
                if (result['最靠近商圈']) {
                     const el = document.getElementById('dh-input-最靠近商圈');
                     if(el) { el.value = result['最靠近商圈']; updated.push('商圈: '+result['最靠近商圈']); }
                }
                updateStatus(updated.length ? '✅ '+updated.join(', ') : '⚠️ AI未推断出信息', updated.length ? '#4caf50':'#ff9800');
                if (typeof callback === 'function') callback(true);
            }, () => {
                if(btn) btn.disabled = false;
                updateStatus('❌ 推断失败', '#f44336');
                if (typeof callback === 'function') callback(false);
            });
        }
        
        function collectFormData() {
            let data = {};
            const url = window.location.href;
            const itemIdMatch = url.match(/[?&]id=(\d+)/) || url.match(/\/(\d+)\.htm/);
            data.id = itemIdMatch ? itemIdMatch[1] : 'unknown';
            data.url = url;
            data.title = document.title;
            data.source_title = document.title;
            data.context = getCleanContext();
            
            FIELDS.forEach(field => {
                const input = document.getElementById(`dh-input-${field.key}`);
                if (input) {
                    if (field.type === 'checkbox') data[field.key] = input.checked;
                    else if (field.type === 'number') data[field.key] = parseFloat(input.value) || 0;
                    else data[field.key] = input.value;
                }
            });
            const fullAddress = (data['完整地址'] || data['地点'] || '').trim();
            if (fullAddress) {
                data['地点'] = fullAddress;
                data['完整地址'] = fullAddress;
                data.full_address = fullAddress;
            }
            data['出价次数'] = parseFloat(data['出价次数']) || 0;
            data['出价人数'] = parseFloat(data['出价人数']) || 0;
            data.bidCount = data['出价次数'];
            data.bid_count = data['出价次数'];
            data.bidderCount = data['出价人数'];
            data.bidder_count = data['出价人数'];
            data.deposit = parseFloat(data['保证金']) || 0;
            data.auction_start_time = data['开拍时间'];
            data.watch_count = parseFloat(data['围观人数']) || 0;
            data.reminder_count = parseFloat(data['提醒人数']) || 0;
            data.view_count = parseFloat(data['浏览次数']) || 0;
            data.gross_area_sqm = parseFloat(data['产权建筑面积']) || 0;
            data.ownership_share_ratio = parseFloat(data['产权份额比例']) || 1;
            data.court_name = data['法院名称'];
            data.case_number = data['案号'];
            return data;
        }

        function submitData() {
            calculateUnitPrice();
            const data = collectFormData();
            
            const needsInfo = (!data['所属小区'] || !data['最靠近商圈']) && data['地点'];
            if (needsInfo) {
                updateStatus('🔍 自动推断位置...', '#9c27b0');
                inferLocation(() => doSubmit());
            } else {
                doSubmit();
            }
        }
        
        function doSubmit() {
            calculateUnitPrice();
            const data = collectFormData();
            updateStatus('正在提交...', '#2196F3');
            const btn = document.getElementById('dh-btn-submit');
            if(btn) btn.disabled = true;
            
            fetchApi('/approve_area', data, (res) => {
                if(btn) btn.disabled = false;
                updateStatus('✅ 提交成功！', '#4caf50');
                // Flash Green
                const panel = document.getElementById('detail-helper-panel');
                if(panel) { panel.style.background = '#e8f5e9'; setTimeout(()=>panel.style.background='white', 500); }
                
                checkAutoSubmit(true); // Proceed to next if auto
            }, () => {
                if(btn) btn.disabled = false;
                updateStatus('❌ 提交失败', '#f44336');
            });
        }
        
        function checkAutoSubmit(forceNext = false) {
            if (!IS_AUTO_MODE) return;
            // In auto mode, logic might differ: usually we want to verify then submit
            // If called from scrollAndRetryArea, we submit result to AI queue (area_result)
            // But if called from doSubmit (Manual click or final step), we might want to fetch next.
            
            if (forceNext) {
                 setTimeout(() => {
                     updateStatus('🔄 获取下一任务...', '#2196f3');
