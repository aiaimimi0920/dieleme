// ==UserScript==
// @name         法拍房全能助手 (Fapaifang Unified Tool)
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  集成了嗅探、检阅（快/慢）和详情助手功能的统一脚本
// @author       Antigravity
// @match        https://sf.taobao.com/*
// @match        https://sf-item.taobao.com/*
// @match        https://susong-item.taobao.com/*
// @match        https://paimai.taobao.com/pmp_item/*
// @match        https://login.taobao.com/*
// @match        https://sec.taobao.com/*
// @connect      127.0.0.1
// @connect      localhost
// @connect      sf.taobao.com
// @connect      sf-item.taobao.com
// @connect      susong-item.taobao.com
// @connect      detail-ext.taobao.com
// @connect      itemcdn.tmall.com
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_listValues
// @grant        GM_deleteValue
// @grant        GM_addValueChangeListener
// @grant        GM_openInTab
// @grant        GM_registerMenuCommand
// @run-at       document-idle
// ==/UserScript==

(function() {
    'use strict';

    // const API_BASE = "http://127.0.0.1:8001/api";
    // Make Port Dynamic
    const initialUrlParams = new URLSearchParams(window.location.search);
    const urlPort = initialUrlParams.get('uni_port');
    
    // Priority: URL Param > Config > Default
    const API_PORT = urlPort || GM_getValue('uni_api_port', '8001');
    const API_BASE = `http://127.0.0.1:${API_PORT}/api`;
    
    log(`[Init] Using API Port: ${API_PORT} ${urlPort ? '(from URL)' : '(from Config)'}`, 'info');


    // --- API Helper ---
    function fetchApi(endpoint, data = {}, callback = null, errorCallback = null) {
        const method = Object.keys(data).length > 0 ? "POST" : "GET";
        GM_xmlhttpRequest({
            method: method,
            url: API_BASE + endpoint,
            headers: { "Content-Type": "application/json" },
            data: method === "POST" ? JSON.stringify(data) : null,
            onload: function(response) {
                if (response.status === 200) {
                    try {
                        const json = JSON.parse(response.responseText);
                        if (callback) callback(json);
                    } catch (e) { 
                        log("API Parse Error", 'error'); 
                        if (errorCallback) errorCallback();
                    }
                } else {
                    log(`API Error: ${response.status} ${response.responseText}`, 'error');
                    if (errorCallback) errorCallback();
                }
            },
            onerror: function(err) { 
                log("API Connection Fail", 'error'); 
                if (errorCallback) errorCallback();
            }
        });
    }

    function formatLocalDateTime(input) {
        const d = new Date(input);
        if (Number.isNaN(d.getTime())) return '';
        const pad = (v) => String(v).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    }

    // ==========================================
    // MODULE 1: SNIFFING (Master Page)
    // ==========================================
    let sniffState = {
        maxSlots: 3, // Concurrency for sniffing (3 tabs)
        interval: 3000,
        running: false,
        workerMode: false,
        currSessionIdx: 0
    };

    // Use multiple sessions to maximize distribution across locations
    let sniffSessions = [];
    try {
        const stored = sessionStorage.getItem('sniff_sessions_list');
        if (stored) sniffSessions = JSON.parse(stored);
    } catch(e) {}

    if (!sniffSessions || sniffSessions.length < sniffState.maxSlots) {
        sniffSessions = [];
        for (let i = 0; i < sniffState.maxSlots; i++) {
            sniffSessions.push('sniff_s' + i + '_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5));
        }
        sessionStorage.setItem('sniff_sessions_list', JSON.stringify(sniffSessions));
    }
    
    // Auto-resume sniffing if reloading (Master only)
    if (sessionStorage.getItem("uni_is_sniffing") === "true") {
        window.addEventListener('load', () => {
             setTimeout(() => {
                 if (document.getElementById('uni-mode-select')) {
                     document.getElementById('uni-mode-select').value = 'SNIFF';
                     currentMode = 'SNIFF';
                     GM_setValue('unified_mode', 'SNIFF'); // Sync
                     toggleRunState(); // Auto-start
                 }
             }, 1000);
        });
    }

    // --- Optimization: No-Image Mode (for Sniffing/Review) ---
    function injectOptimization() {
        const style = document.createElement('style');
        style.textContent = `
            img, [style*="background-image"], .lazyload, .lazy-img, 
            .item-img, .item-pic, .image-gallery, .J_ItemPic,
            video, iframe[src*="video"], .video-container,
            #J_Map, .show-amap, iframe[src*="gaode"], iframe[src*="amap"],
            #J_SiteFooter, .tb-footer, #sf-foot-2014, .sf-foot-2014,
            .pm-main-l, #J_UlThumb, .J_HeadImageWrap,
            #J_SiteNav, .site-nav, #sf-head-2014, .sf-head-2014, .nav-con {
                visibility: hidden !important;
                height: 0 !important;
                min-height: 0 !important;
                max-height: 0 !important;
                overflow: hidden !important;
            }
        `;
        document.head.appendChild(style);

        const imgObserver = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.tagName === 'IMG') {
                        node.src = '';
                        node.srcset = '';
                        node.loading = 'lazy';
                    }
                }
            }
        });
        imgObserver.observe(document.documentElement, { childList: true, subtree: true });
        log('[Optimization] No-Image Mode Active', 'info');
    }

    // Determine current mode early
    const modeParam = initialUrlParams.get('uni_mode');
    const autoStartParam = initialUrlParams.get('uni_autostart') === '1';

    // Auto-Run Workers (Sniff Worker)
    if (modeParam === 'SNIFF_WORKER') {
        injectOptimization();
        window.addEventListener('load', () => {
            setTimeout(startSniffWorker, 1000);
        });
    }

