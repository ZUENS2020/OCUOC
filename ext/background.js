// OCUOC Browser Bridge — service worker(参考实现)
// 职责:① 维持与 OCUOC MCP 进程的本地 WebSocket;② 消息路由;③ chrome.debugger
// CDP 输入派发;④ 光标 overlay 内容脚本管理;⑤ favicon 徽章;⑥ 标签事件上报。
// 设计规格: docs/2026-10-16-ocuoc-cursor-v2-browser-subsystem-plan.md §2.3-2.5
// 红线:全部标识符为 OCUOC 自有(cuoc.* / CUOC_*),未复用任何官方扩展常量。

'use strict';

// ── 配置 ────────────────────────────────────────────────────────────────────
const RECONNECT_BASE_MS = 250;      // 重连退避基数(参考实现自定值)
const RECONNECT_MAX_MS = 5000;
const HEARTBEAT_MS = 20000;         // 保活(MV3 SW 空闲 30s 会挂起)
const CDP_VERSION = '1.3';          // chrome.debugger.attach 要求的协议版本;系统横幅显示扩展名
const INPUT_TIMEOUT_MS = 8000;

// ── 状态 ────────────────────────────────────────────────────────────────────
let ws = null;
let connected = false;
let nextId = 1;                     // 扩展→服务器请求 id(事件无需 id)
const pending = new Map();          // id → {resolve, reject, timer}
const injectedTabs = new Set();     // 已注入 content_cursor.js 的 tabId
const debuggerTabs = new Set();     // 已 attach 的 tabId

// ── WebSocket 客户端 ────────────────────────────────────────────────────────
async function loadEndpoint() {
  const { bridgeEndpoint } = await chrome.storage.local.get('bridgeEndpoint');
  return bridgeEndpoint || '';      // "ws://127.0.0.1:PORT"
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

async function request(type, data) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    send({ id, type, data });
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        reject(new Error(`bridge request timeout: ${type}`));
      }
    }, INPUT_TIMEOUT_MS);
  });
}

async function connectLoop() {
  const endpoint = await loadEndpoint();
  if (!endpoint) { setTimeout(connectLoop, 2000); return; }
  try { ws = new WebSocket(endpoint); } catch { scheduleReconnect(); return; }
  ws.onopen = async () => {
    connected = true;
    setBadge(true);
    const { bridgeToken } = await chrome.storage.local.get('bridgeToken');
    send({ type: 'hello', data: { token: bridgeToken || '', role: 'extension',
                                  ext: 'ocuoc-browser-bridge', version: chrome.runtime.getManifest().version } });
  };
  ws.onmessage = (ev) => { try { route(JSON.parse(ev.data)); } catch (e) { console.warn('bad frame', e); } };
  ws.onclose = () => { connected = false; setBadge(false); scheduleReconnect(); };
  ws.onerror = () => { try { ws.close(); } catch {} };
}

let reconnectTimer = null;
function scheduleReconnect() {
  if (reconnectTimer) return;
  let delay = RECONNECT_BASE_MS;
  reconnectTimer = setInterval(async () => {
    delay = Math.min(delay * 2, RECONNECT_MAX_MS);
    if (!connected) { clearTimeout(reconnectTimer); reconnectTimer = null; connectLoop(); }
  }, delay);
}

function setBadge(on) {
  chrome.action.setBadgeText({ text: on ? '●' : '○' });
  chrome.action.setBadgeBackgroundColor({ color: on ? '#22c55e' : '#9ca3af' });
}

setInterval(() => { if (connected) send({ type: 'ping' }); }, HEARTBEAT_MS);

// ── 服务器→扩展 请求路由 ────────────────────────────────────────────────────
async function route(msg) {
  // 事件(无 id):cursor.arrived 由内容脚本转发,tab 事件由本地监听发
  if (msg.type === 'pong' || msg.type === 'ping') { if (msg.type === 'ping') send({ type: 'pong' }); return; }
  if (msg.id === undefined) return;
  try {
    const result = await handle(msg.type, msg.data || {});
    send({ id: msg.id, ok: true, result });
  } catch (err) {
    send({ id: msg.id, ok: false, error: String(err && err.message || err) });
  }
}

async function handle(type, d) {
  switch (type) {
    case 'tabs.list':        return tabsList();
    case 'tab.new':          return tabNew(d);
    case 'tab.activate':     return chrome.tabs.update(d.tabId, { active: true });
    case 'tab.close':        return chrome.tabs.remove(d.tabId);

    case 'cursor.set':       return cursorSet(d);
    case 'cursor.hide':      return cursorPublish(d.tabId, { cursor: null, isVisible: false });

    case 'input.mouse':      return inputMouse(d);
    case 'input.text':       return cdpCall(d.tabId, 'Input.insertText', { text: d.text });
    case 'input.key':        return inputKey(d);

    case 'page.screenshot':  return pageScreenshot(d);
    case 'page.axtree':      return pageAXTree(d);
    case 'page.dom':         return pageDomSnapshot(d);
    case 'page.dialog':      return cdpCall(d.tabId, 'Page.handleJavaScriptDialog',
                                        { accept: !!d.accept, promptText: d.promptText || '' });
    case 'page.eval':        return cdpCall(d.tabId, 'Runtime.evaluate',
                                        { expression: d.expression, awaitPromise: !!d.awaitPromise,
                                          returnByValue: true });
    case 'badge.set':        return badgeSet(d);
    case 'cdp.raw':          return cdpCall(d.tabId, d.method, d.params || {});
    default: throw new Error(`unknown type: ${type}`);
  }
}

// ── 标签 ────────────────────────────────────────────────────────────────────
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function waitTabReady(tabId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    let tab;
    try { tab = await chrome.tabs.get(tabId); } catch { return null; }
    if ((tab.url || '') !== '' && tab.status !== 'loading') return tab;
    await sleep(50);
  }
  try { return await chrome.tabs.get(tabId); } catch { return null; }
}

async function tabNew(d) {
  const created = await chrome.tabs.create({ url: d.url || 'about:blank', active: d.active !== false });
  return (await waitTabReady(created.id, 10000)) || created;
}

async function tabsList() {
  const tabs = await chrome.tabs.query({});
  return tabs.map(t => ({ tabId: t.id, windowId: t.windowId, index: t.index,
                          url: t.url || '', title: t.title || '', active: t.active,
                          width: t.width, height: t.height }));
}

// ── 光标 overlay(content_cursor.js) ───────────────────────────────────────
async function ensureContentScript(tabId) {
  if (injectedTabs.has(tabId)) return;
  await chrome.scripting.executeScript({ target: { tabId }, files: ['content_cursor.js'] });
  injectedTabs.add(tabId);
}

async function cursorPublish(tabId, state) {
  await ensureContentScript(tabId);
  const res = await chrome.tabs.sendMessage(tabId, { type: 'CUOC_CURSOR_STATE', state });
  return { delivered: !!(res && res.ok) };
}

async function cursorSet(d) {
  // d: {tabId, seq, x, y, visible?, animate?, viewportW?, viewportH?}
  return cursorPublish(d.tabId, {
    cursor: { x: d.x, y: d.y, visible: d.visible !== false,
              animate: d.animate !== false, seq: d.seq ?? null },
    isVisible: true,
  });
}

// ── CDP(chrome.debugger) ───────────────────────────────────────────────────
async function cdpSend(tabId, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params || {}, (result) => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message || String(err)));
      else resolve(result || {});
    });
  });
}

async function debuggerAttach(tabId) {
  if (debuggerTabs.has(tabId)) return;
  await new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, CDP_VERSION, () => {
      const err = chrome.runtime.lastError;
      if (err && !/already attached/i.test(String(err.message || ''))) {
        reject(new Error(err.message));
        return;
      }
      resolve();
    });
  });
  debuggerTabs.add(tabId);
  for (const domain of ['Page', 'Runtime', 'DOM', 'Accessibility']) {
    try { await cdpSend(tabId, domain + '.enable', {}); } catch (_e) {}
  }
}

chrome.debugger.onDetach.addListener((source) => {
  if (source && source.tabId != null) debuggerTabs.delete(source.tabId);
});

async function cdpCall(tabId, method, params) {
  await debuggerAttach(tabId);
  return cdpSend(tabId, method, params);
}

async function pageAXTree(d) {
  await debuggerAttach(d.tabId);
  const params = {};
  if (d.depth != null) params.depth = d.depth;
  return cdpSend(d.tabId, 'Accessibility.getFullAXTree', params);
}

async function pageDomSnapshot(d) {
  await debuggerAttach(d.tabId);
  return cdpSend(d.tabId, 'DOMSnapshot.captureSnapshot', {
    computedStyles: [],
    includeDOMRects: true,
    includePaintOrder: false,
  });
}

const BUTTON_MAP = { left: 'left', right: 'right', middle: 'middle', none: 'none', back: 'back', forward: 'forward' };
const BUTTONS_BIT = { none: 0, left: 1, right: 2, middle: 4 };

async function inputMouse(d) {
  // d: {tabId, actions:[{type:'mousePressed'|'mouseReleased'|'mouseMoved', x, y, button?, clickCount?, modifiers?}]}
  const out = [];
  for (const a of d.actions) {
    const button = BUTTON_MAP[a.button || 'left'] || 'left';
    const params = {
      type: a.type, x: a.x, y: a.y, button,
      buttons: a.type === 'mouseReleased' ? 0 : (BUTTONS_BIT[button] || 0),
      clickCount: a.clickCount ?? 1, modifiers: a.modifiers ?? 0,
    };
    if (a.type === 'mouseWheel') {
      params.deltaX = a.deltaX ?? 0;
      params.deltaY = a.deltaY ?? 0;
    }
    out.push(await cdpCall(d.tabId, 'Input.dispatchMouseEvent', params));
  }
  return { count: out.length };
}

// 特殊键最小集(参考实现;完整 VK 表由使用者按需扩充)
const KEY_TABLE = {
  Enter:   { keyCode: 13,  code: 'Enter',     key: 'Enter', text: '\r' },
  Tab:     { keyCode: 9,   code: 'Tab',       key: 'Tab' },
  Escape:  { keyCode: 27,  code: 'Escape',    key: 'Escape' },
  Backspace:{ keyCode: 8,  code: 'Backspace', key: 'Backspace' },
  Delete:  { keyCode: 46,  code: 'Delete',    key: 'Delete' },
  ArrowUp: { keyCode: 38,  code: 'ArrowUp',   key: 'ArrowUp' },
  ArrowDown:{ keyCode: 40, code: 'ArrowDown', key: 'ArrowDown' },
  ArrowLeft:{ keyCode: 37, code: 'ArrowLeft', key: 'ArrowLeft' },
  ArrowRight:{ keyCode: 39,code: 'ArrowRight',key: 'ArrowRight' },
  Space:   { keyCode: 32,  code: 'Space',     key: ' ', text: ' ' },
  Home:    { keyCode: 36,  code: 'Home',      key: 'Home' },
  End:     { keyCode: 35,  code: 'End',       key: 'End' },
};

const KEY_ALIASES = {
  enter: 'Enter', return: 'Enter', tab: 'Tab', escape: 'Escape', esc: 'Escape',
  backspace: 'Backspace', delete: 'Delete', del: 'Delete', space: 'Space',
  arrowup: 'ArrowUp', up: 'ArrowUp', arrowdown: 'ArrowDown', down: 'ArrowDown',
  arrowleft: 'ArrowLeft', left: 'ArrowLeft', arrowright: 'ArrowRight', right: 'ArrowRight',
  home: 'Home', end: 'End',
};

const MOD_KEY = {
  alt:   { key: 'Alt',     code: 'AltLeft',     keyCode: 18 },
  ctrl:  { key: 'Control', code: 'ControlLeft', keyCode: 17 },
  meta:  { key: 'Meta',    code: 'MetaLeft',    keyCode: 91 },
  shift: { key: 'Shift',   code: 'ShiftLeft',   keyCode: 16 },
};

function describeKey(name) {
  const alias = KEY_ALIASES[String(name || '').toLowerCase()];
  if (alias && KEY_TABLE[alias]) return KEY_TABLE[alias];
  if (KEY_TABLE[name]) return KEY_TABLE[name];
  const raw = String(name || '');
  if (raw.length === 1) {
    const upper = raw.toUpperCase();
    const isLetter = /^[a-zA-Z]$/.test(raw);
    const isDigit = /^[0-9]$/.test(raw);
    return {
      keyCode: upper.charCodeAt(0),
      code: isLetter ? ('Key' + upper) : (isDigit ? ('Digit' + raw) : raw),
      key: isLetter ? raw.toLowerCase() : raw,
      text: (isLetter || isDigit) ? raw.toLowerCase() : raw,
    };
  }
  return { keyCode: raw.toUpperCase().charCodeAt(0) || 0, code: raw, key: raw };
}

function parseChord(spec) {
  const parts = String(spec || '').replace(/-/g, '+').split('+').map((p) => p.trim()).filter(Boolean);
  const modNames = [];
  let key = parts[parts.length - 1] || '';
  let modifiers = 0;
  for (let i = 0; i < parts.length - 1; i++) {
    const n = parts[i].toLowerCase();
    if (n === 'alt') { modifiers |= 1; modNames.push('alt'); }
    else if (n === 'ctrl' || n === 'control') { modifiers |= 2; modNames.push('ctrl'); }
    else if (n === 'meta' || n === 'cmd' || n === 'command' || n === 'win') { modifiers |= 4; modNames.push('meta'); }
    else if (n === 'shift') { modifiers |= 8; modNames.push('shift'); }
  }
  return { key, modifiers, modNames };
}

async function dispatchKey(tabId, desc, type, modifiers) {
  const base = {
    key: desc.key, code: desc.code, windowsVirtualKeyCode: desc.keyCode,
    nativeVirtualKeyCode: desc.keyCode, modifiers,
  };
  if (type === 'char' && desc.text) base.text = desc.text;
  await cdpCall(tabId, 'Input.dispatchKeyEvent', { type, ...base });
}

async function inputKey(d) {
  // d: {tabId, keys:["ctrl+a","Enter"], chords?:[{key,modifiers,modNames}]}
  const chords = Array.isArray(d.chords) && d.chords.length
    ? d.chords
    : (d.keys || []).map(parseChord);
  for (const chord of chords) {
    const modNames = chord.modNames || [];
    const modifiers = chord.modifiers || 0;
    let down = 0;
    for (const name of modNames) {
      const mk = MOD_KEY[name];
      if (!mk) continue;
      down |= (name === 'alt' ? 1 : name === 'ctrl' ? 2 : name === 'meta' ? 4 : 8);
      await dispatchKey(d.tabId, mk, 'rawKeyDown', down);
    }
    const desc = describeKey(chord.key);
    await dispatchKey(d.tabId, desc, 'rawKeyDown', modifiers);
    if (desc.text && !(modifiers & 2) && !(modifiers & 4)) {
      await dispatchKey(d.tabId, desc, 'char', modifiers);
    }
    await dispatchKey(d.tabId, desc, 'keyUp', modifiers);
    for (const name of [...modNames].reverse()) {
      const mk = MOD_KEY[name];
      if (!mk) continue;
      down &= ~(name === 'alt' ? 1 : name === 'ctrl' ? 2 : name === 'meta' ? 4 : 8);
      await dispatchKey(d.tabId, mk, 'keyUp', down);
    }
  }
  return { ok: true, chords };
}

// ── 截图(视口) ─────────────────────────────────────────────────────────────
async function pageScreenshot(d) {
  const format = d.format || 'png';
  const mime = format === 'jpeg' ? 'image/jpeg' : 'image/png';
  let tab;
  try { tab = await chrome.tabs.get(d.tabId); } catch (err) {
    throw new Error(`unknown_tab: ${err && err.message || err}`);
  }
  if (tab.discarded) {
    throw new Error('tab_discarded: background tab was discarded; call browser_activate_tab to reload it');
  }
  const tryCapture = async (fromSurface) => {
    const res = await cdpCall(d.tabId, 'Page.captureScreenshot', { format, fromSurface });
    return {
      dataUrl: `data:${mime};base64,${(res && res.data) || ''}`,
      backend: 'cdp',
      activated: false,
      fromSurface,
    };
  };
  try {
    return await tryCapture(true);
  } catch (err) {
    try {
      return await tryCapture(false);
    } catch (err2) {
      if (!tab.active) {
        throw new Error(
          `screenshot_requires_visible_tab: ${err2 && err2.message || err && err.message || err2}`
        );
      }
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format });
      return { dataUrl, backend: 'captureVisibleTab', activated: false };
    }
  }
}

// ── favicon 徽章(content_cursor.js 内实现) ────────────────────────────────
async function badgeSet(d) {
  // d: {tabId, kind: "active"|"deliverable"|"handoff"|null}
  await ensureContentScript(d.tabId);
  const res = await chrome.tabs.sendMessage(d.tabId, { type: 'CUOC_BADGE_SET', kind: d.kind ?? null });
  return { ok: !!(res && res.ok) };
}

// ── 事件上报 ────────────────────────────────────────────────────────────────
// 内容脚本 → 这里 → 服务器
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || typeof msg !== 'object') return;
  if (msg.type === 'CUOC_CURSOR_ARRIVED' && sender.tab) {
    send({ type: 'cursor.arrived', data: { tabId: sender.tab.id, seq: msg.seq } });
    reply({ ok: true });
    return true;
  }
  if (msg.type === 'CUOC_CURSOR_GET' && sender.tab) {
    // 页面刷新后重取状态:此处简化为服务器无状态,返回隐藏
    reply({ ok: true, state: { cursor: null, isVisible: false } });
    return true;
  }
  if (msg.type === 'CUOC_BRIDGE_STATUS' && !sender.tab) {
    reply({ ok: true, connected, endpoint: ws ? ws.url : '' });
    return true;
  }
});

// 标签生命周期 → 服务器
function forwardTab(kind, extra) {
  return (arg) => { if (connected) send({ type: 'tab.event', data: { kind, tab: tabInfo(arg), ...extra } }); };
}
function tabInfo(t) { return { tabId: t.id, windowId: t.windowId, url: t.url || '', title: t.title || '', active: !!t.active }; }
chrome.tabs.onCreated.addListener(forwardTab('created'));
chrome.tabs.onRemoved.addListener((tabId) => {
  injectedTabs.delete(tabId); debuggerTabs.delete(tabId);
  if (connected) send({ type: 'tab.event', data: { kind: 'removed', tabId } });
});
chrome.tabs.onReplaced.addListener((added, removed) => {
  injectedTabs.delete(removed);
  if (connected) send({ type: 'tab.event', data: { kind: 'replaced', tabId: added, removedTabId: removed } });
});
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.url || info.status === 'complete') forwardTab('updated', { info })(tab);
});
chrome.debugger.onDetach.addListener((source) => {
  if (source.tabId) debuggerTabs.delete(source.tabId);
});
chrome.debugger.onEvent.addListener((source, method, params) => {
  if (!connected || !source.tabId) return;
  if (method === 'Page.javascriptDialogOpening') {
    send({ type: 'dialog.event', data: { kind: 'opening', tabId: source.tabId, ...(params || {}) } });
  } else if (method === 'Page.javascriptDialogClosed') {
    send({ type: 'dialog.event', data: { kind: 'closed', tabId: source.tabId, ...(params || {}) } });
  }
});

// 动作按钮:点击弹出检查
chrome.action.onClicked.addListener(async () => {
  const endpoint = await loadEndpoint();
  chrome.tabs.create({ url: endpoint ? `options.html#check` : 'options.html' });
});

connectLoop();
