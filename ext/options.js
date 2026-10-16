// OCUOC Browser Bridge — options.js(配对页逻辑,参考实现)
'use strict';
const $ = (id) => document.getElementById(id);

async function refresh() {
  const { bridgeEndpoint, bridgeToken } = await chrome.storage.local.get(['bridgeEndpoint', 'bridgeToken']);
  $('endpoint').value = bridgeEndpoint || '';
  $('token').value = bridgeToken || '';
}
refresh();

$('save').addEventListener('click', async () => {
  const endpoint = $('endpoint').value.trim().replace(/\/+$/, '');
  const token = $('token').value.trim();
  if (!/^ws:\/\/127\.0\.0\.1:\d+$/.test(endpoint)) {
    $('status').textContent = '地址必须是 ws://127.0.0.1:<port>(仅本机回环)';
    return;
  }
  await chrome.storage.local.set({ bridgeEndpoint: endpoint, bridgeToken: token });
  $('status').textContent = '已保存。service worker 将自动重连(数秒内)。';
});

// 周期刷新连接状态(simple poll;生产可改 chrome.runtime 消息)
setInterval(async () => {
  const resp = await chrome.runtime.sendMessage({ type: 'CUOC_BRIDGE_STATUS' });
  if (resp && resp.ok) {
    $('status').textContent = resp.connected ? `已连接 ${resp.endpoint}` : '未连接(重试中…)';
  }
}, 2000);
