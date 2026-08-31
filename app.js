/**
 * Smart Money Flow Terminal Pro
 * app.js — Frontend logic
 * Connects to FastAPI WebSocket backend, renders all panels
 */

'use strict';

// ═══════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════
const CONFIG = {
  WS_URL: 'ws://localhost:8000/ws',
  RECONNECT_DELAY: 3000,
  MAX_HISTORY_POINTS: 200,
  CHART_UPDATE_INTERVAL: 1000,
  ALERT_DISPLAY_TIME: 30000,   // ms each alert stays visible
  MAX_WHALE_ALERTS: 20,
};

// Asset colors for chart lines
const ASSET_COLORS = {
  BTCUSDT:  { line: '#F7931A', label: 'BTC' },
  ETHUSDT:  { line: '#627EEA', label: 'ETH' },
  BNBUSDT:  { line: '#F3BA2F', label: 'BNB' },
  SOLUSDT:  { line: '#9945FF', label: 'SOL' },
  XRPUSDT:  { line: '#00AAE4', label: 'XRP' },
  DOGEUSDT: { line: '#C3A634', label: 'DOGE' },
  ADAUSDT:  { line: '#0033AD', label: 'ADA' },
  LINKUSDT: { line: '#2A5ADA', label: 'LINK' },
  AVAXUSDT: { line: '#E84142', label: 'AVAX' },
  TRXUSDT:  { line: '#FF0013', label: 'TRX' },
  STABLECOINS: { line: '#26A17B', label: 'STABLE' },
};

// Sectors definition
const SECTORS = {
  'Layer 1':  ['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','AVAXUSDT','ADAUSDT','TRXUSDT'],
  'AI':       ['FETUSDT','AGIXUSDT','OCEANUSDT','RNDRXUSDT'],
  'DeFi':     ['LINKUSDT','AAVEUSDT','UNIUSDT','SUSHIUSDT'],
  'Gaming':   ['AXSUSDT','SANDUSDT','MANAUSDT','ENJUSDT'],
  'Meme':     ['DOGEUSDT','SHIBUSDT','PEPEUSDT','FLOKIUSDT'],
};

// ═══════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════
const state = {
  ws: null,
  connected: false,
  reconnectTimer: null,
  latestData: {},          // symbol -> MarketData
  flowHistory: {},         // symbol -> [{time, value}]
  chartSeries: {},         // symbol -> LightweightCharts series
  chartVisible: {},        // symbol -> bool
  alerts: [],
  whaleAlerts: [],
  rankTab: 'inflow',
  totalAlertCount: 0,
  lastUpdateTime: null,
  wsConnectTime: null,
};

// ═══════════════════════════════════════════════════════
// DOM REFERENCES
// ═══════════════════════════════════════════════════════
const dom = {
  statusDot:    () => document.getElementById('statusDot'),
  statusText:   () => document.getElementById('statusText'),
  clockTime:    () => document.getElementById('clockTime'),
  regimeValue:  () => document.getElementById('regimeValue'),
  alertScroller:() => document.getElementById('alertScroller'),
  tickerStrip:  () => document.getElementById('tickerStrip'),
  rankTableBody:() => document.getElementById('rankTableBody'),
  whaleFeed:    () => document.getElementById('whaleFeed'),
  whaleBadge:   () => document.getElementById('whaleBadge'),
  sectorGrid:   () => document.getElementById('sectorGrid'),
  hotSector:    () => document.getElementById('hotSector'),
  coldSector:   () => document.getElementById('coldSector'),
  domSignal:    () => document.getElementById('domSignal'),
  fundingList:  () => document.getElementById('fundingList'),
  oiList:       () => document.getElementById('oiList'),
  chartToggles: () => document.getElementById('chartToggles'),
  fundAvg:      () => document.getElementById('fundAvg'),
  fundMax:      () => document.getElementById('fundMax'),
  fundMin:      () => document.getElementById('fundMin'),
  sbPairs:      () => document.getElementById('sbPairs'),
  sbUpdated:    () => document.getElementById('sbUpdated'),
  sbAlertCount: () => document.getElementById('sbAlertCount'),
  sbLatency:    () => document.getElementById('sbLatency'),
};

// ═══════════════════════════════════════════════════════
// CLOCK
// ═══════════════════════════════════════════════════════
function updateClock() {
  const now = new Date();
  const t = now.toUTCString().split(' ')[4];
  dom.clockTime().textContent = t;
}
setInterval(updateClock, 1000);
updateClock();

// ═══════════════════════════════════════════════════════
// CHART SETUP (TradingView Lightweight Charts)
// ═══════════════════════════════════════════════════════
let chart = null;

function initChart() {
  const container = document.getElementById('flowChart');
  if (!container) return;

  chart = LightweightCharts.createChart(container, {
    layout: {
      background: { type: 'solid', color: 'transparent' },
      textColor: '#7a9cc0',
    },
    grid: {
      vertLines: { color: 'rgba(26,38,64,0.6)' },
      horzLines: { color: 'rgba(26,38,64,0.6)' },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: '#00d4ff', width: 1, style: LightweightCharts.LineStyle.Dashed, labelBackgroundColor: '#0b1120' },
      horzLine: { color: '#00d4ff', width: 1, style: LightweightCharts.LineStyle.Dashed, labelBackgroundColor: '#0b1120' },
    },
    rightPriceScale: {
      borderColor: '#1a2640',
      scaleMargins: { top: 0.05, bottom: 0.05 },
    },
    timeScale: {
      borderColor: '#1a2640',
      timeVisible: true,
      secondsVisible: false,
    },
    handleScroll: true,
    handleScale: true,
  });

  // Respond to container resize
  const ro = new ResizeObserver(entries => {
    for (const e of entries) {
      chart.applyOptions({ width: e.contentRect.width, height: e.contentRect.height });
    }
  });
  ro.observe(container);

  // Create series for each asset
  initChartSeries();
}

function initChartSeries() {
  const toggleContainer = dom.chartToggles();
  toggleContainer.innerHTML = '';

  Object.entries(ASSET_COLORS).forEach(([sym, info]) => {
    if (sym === 'STABLECOINS') return; // added separately
    state.chartVisible[sym] = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'].includes(sym);

    const series = chart.addLineSeries({
      color: info.line,
      lineWidth: sym === 'BTCUSDT' || sym === 'ETHUSDT' ? 2 : 1,
      visible: state.chartVisible[sym],
      priceLineVisible: false,
      lastValueVisible: true,
      title: info.label,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 4,
    });
    state.chartSeries[sym] = series;
    state.flowHistory[sym] = [];

    // Build toggle button
    const btn = document.createElement('button');
    btn.className = `toggle-btn ${state.chartVisible[sym] ? 'active' : 'inactive'}`;
    btn.textContent = info.label;
    btn.style.borderColor = info.line;
    btn.style.color = state.chartVisible[sym] ? info.line : '#3d567a';
    btn.dataset.sym = sym;
    btn.onclick = () => toggleChartLine(sym, btn, info.line);
    toggleContainer.appendChild(btn);
  });

  // Stable coins line
  const stableSeries = chart.addLineSeries({
    color: ASSET_COLORS.STABLECOINS.line,
    lineWidth: 1,
    visible: false,
    priceLineVisible: false,
    lastValueVisible: true,
    title: 'STABLE',
  });
  state.chartSeries['STABLECOINS'] = stableSeries;
  state.chartVisible['STABLECOINS'] = false;
  state.flowHistory['STABLECOINS'] = [];

  const stableBtn = document.createElement('button');
  stableBtn.className = 'toggle-btn inactive';
  stableBtn.textContent = 'STABLE';
  stableBtn.style.borderColor = ASSET_COLORS.STABLECOINS.line;
  stableBtn.style.color = '#3d567a';
  stableBtn.dataset.sym = 'STABLECOINS';
  stableBtn.onclick = () => toggleChartLine('STABLECOINS', stableBtn, ASSET_COLORS.STABLECOINS.line);
  dom.chartToggles().appendChild(stableBtn);
}

function toggleChartLine(sym, btn, color) {
  state.chartVisible[sym] = !state.chartVisible[sym];
  const visible = state.chartVisible[sym];
  state.chartSeries[sym].applyOptions({ visible });
  btn.className = `toggle-btn ${visible ? 'active' : 'inactive'}`;
  btn.style.color = visible ? color : '#3d567a';
}

function pushFlowPoint(sym, time, value) {
  const hist = state.flowHistory[sym];
  const point = { time: Math.floor(time / 1000), value };

  if (hist.length === 0 || hist[hist.length - 1].time !== point.time) {
    hist.push(point);
    if (hist.length > CONFIG.MAX_HISTORY_POINTS) hist.shift();
  } else {
    hist[hist.length - 1].value = value;
  }

  if (state.chartSeries[sym] && hist.length > 0) {
    try {
      state.chartSeries[sym].setData([...hist]);
    } catch (e) { /* chart may not be ready */ }
  }
}

// ═══════════════════════════════════════════════════════
// WEBSOCKET CONNECTION
// ═══════════════════════════════════════════════════════
function connectWS() {
  clearTimeout(state.reconnectTimer);
  setStatus('connecting');

  try {
    state.ws = new WebSocket(CONFIG.WS_URL);
    state.wsConnectTime = Date.now();
  } catch (e) {
    setStatus('error');
    scheduleReconnect();
    return;
  }

  state.ws.onopen = () => {
    setStatus('connected');
    state.connected = true;
    console.log('[WS] Connected to Smart Money Flow backend');
  };

  state.ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      handleMessage(msg);
    } catch (e) {
      console.error('[WS] Parse error:', e);
    }
  };

  state.ws.onerror = (e) => {
    console.error('[WS] Error:', e);
    setStatus('error');
  };

  state.ws.onclose = () => {
    setStatus('disconnected');
    state.connected = false;
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  state.reconnectTimer = setTimeout(() => {
    console.log('[WS] Reconnecting…');
    connectWS();
  }, CONFIG.RECONNECT_DELAY);
}

function setStatus(status) {
  const dot = dom.statusDot();
  const txt = dom.statusText();
  dot.className = 'status-dot';
  if (status === 'connected') {
    dot.classList.add('connected');
    txt.textContent = 'LIVE';
  } else if (status === 'connecting') {
    txt.textContent = 'CONNECTING…';
  } else if (status === 'error') {
    dot.classList.add('error');
    txt.textContent = 'ERROR';
  } else {
    txt.textContent = 'DISCONNECTED';
  }
}

// ═══════════════════════════════════════════════════════
// MESSAGE HANDLER
// ═══════════════════════════════════════════════════════
function handleMessage(msg) {
  const { type, data, timestamp } = msg;
  state.lastUpdateTime = new Date(timestamp || Date.now());

  // Calculate latency
  const latency = Date.now() - (timestamp || Date.now());
  dom.sbLatency().textContent = `Latency: ${Math.max(0, latency)}ms`;

  switch (type) {
    case 'market_update':    handleMarketUpdate(data); break;
    case 'flow_scores':      handleFlowScores(data); break;
    case 'dominance':        handleDominance(data); break;
    case 'whale_alert':      handleWhaleAlert(data); break;
    case 'funding_update':   handleFundingUpdate(data); break;
    case 'oi_update':        handleOIUpdate(data); break;
    case 'sector_update':    handleSectorUpdate(data); break;
    case 'risk_regime':      handleRiskRegime(data); break;
    case 'alert':            handleAlert(data); break;
    case 'full_snapshot':    handleFullSnapshot(data); break;
    default:
      console.warn('[WS] Unknown message type:', type);
  }

  // Update status bar
  dom.sbUpdated().textContent = `Last Update: ${state.lastUpdateTime.toLocaleTimeString()}`;
}

// ── Full Snapshot (first message) ──
function handleFullSnapshot(data) {
  if (data.market) handleMarketUpdate(data.market);
  if (data.flow_scores) handleFlowScores(data.flow_scores);
  if (data.dominance) handleDominance(data.dominance);
  if (data.funding) handleFundingUpdate(data.funding);
  if (data.oi) handleOIUpdate(data.oi);
  if (data.sectors) handleSectorUpdate(data.sectors);
  if (data.regime) handleRiskRegime(data.regime);
}

// ── Market Update ──
function handleMarketUpdate(data) {
  // data is a dict: symbol -> {price, change24h, volume, ...}
  Object.entries(data).forEach(([sym, d]) => {
    state.latestData[sym] = { ...state.latestData[sym], ...d };
  });
  updateTickerStrip();
  dom.sbPairs().textContent = `Pairs: ${Object.keys(state.latestData).length}`;
}

// ── Flow Scores ──
function handleFlowScores(data) {
  // data is a list of {symbol, score, components, signal}
  data.forEach(item => {
    if (!state.latestData[item.symbol]) state.latestData[item.symbol] = {};
    state.latestData[item.symbol].flowScore = item.score;
    state.latestData[item.symbol].signal    = item.signal;
    state.latestData[item.symbol].components = item.components;

    // Push to chart
    pushFlowPoint(item.symbol, Date.now(), item.score);
  });
  renderRankTable();
}

// ── Dominance Update ──
function handleDominance(data) {
  // data: {btc, eth, usdt, alts, signal, btcChg, ethChg, usdtChg, altsChg}
  const fmt = v => v != null ? v.toFixed(1) + '%' : '--%';
  const chgCls = v => v > 0 ? 'pct-up' : (v < 0 ? 'pct-down' : '');
  const chgFmt = v => v != null ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : '--';

  setText('domBTC',     fmt(data.btc));
  setText('domETH',     fmt(data.eth));
  setText('domUSDT',    fmt(data.usdt));
  setText('domALTS',    fmt(data.alts));
  setHtml('domBTCchg',  `<span class="${chgCls(data.btcChg)}">${chgFmt(data.btcChg)}</span>`);
  setHtml('domETHchg',  `<span class="${chgCls(data.ethChg)}">${chgFmt(data.ethChg)}</span>`);
  setHtml('domUSDTchg', `<span class="${chgCls(data.usdtChg)}">${chgFmt(data.usdtChg)}</span>`);
  setHtml('domALTSchg', `<span class="${chgCls(data.altsChg)}">${chgFmt(data.altsChg)}</span>`);

  dom.domSignal().textContent = data.signal || '—';
  setText('riDomBTC',   fmt(data.btc));

  renderDomChart(data);
}

// ── Whale Alert ──
function handleWhaleAlert(alert) {
  state.whaleAlerts.unshift(alert);
  if (state.whaleAlerts.length > CONFIG.MAX_WHALE_ALERTS) {
    state.whaleAlerts = state.whaleAlerts.slice(0, CONFIG.MAX_WHALE_ALERTS);
  }
  renderWhaleAlerts();

  // Also push to alert bar
  pushAlertBar(`🐋 ${alert.symbol} — ${alert.message}`, alert.severity === 'critical' ? 'high' : 'med');
}

// ── Funding Update ──
function handleFundingUpdate(data) {
  // data: list of {symbol, rate, annualized}
  renderFundingPanel(data);
}

// ── OI Update ──
function handleOIUpdate(data) {
  // data: list of {symbol, oi, change}
  renderOIPanel(data);
}

// ── Sector Update ──
function handleSectorUpdate(data) {
  // data: {sectors: [{name, change, volume, heat}], hot, cold}
  renderSectorGrid(data);
}

// ── Risk Regime ──
function handleRiskRegime(data) {
  // data: {regime, score, bullPct, neutPct, bearPct, fear}
  const rv = dom.regimeValue();
  rv.textContent = data.regime || '—';
  rv.className = 'regime-value';
  if (data.regime === 'RISK-ON')       rv.classList.add('risk-on');
  else if (data.regime === 'RISK-OFF')  rv.classList.add('risk-off');
  else                                  rv.classList.add('neutral');

  // Update sentiment arc
  const sentScore = Math.round(data.score || 50);
  drawArc('sentimentArc', sentScore, getSentimentColor(sentScore));
  setText('sentimentValue', sentScore);
  setText('sentimentLabel', getSentimentLabel(sentScore));

  // Update risk gauge
  const riskScore = Math.round(data.riskScore || 50);
  drawGauge('riskGauge', riskScore);
  const rv2 = document.getElementById('riskValue');
  if (rv2) {
    rv2.textContent = riskScore;
    rv2.style.color = riskScore > 60 ? 'var(--accent-green)' : (riskScore < 40 ? 'var(--accent-red)' : 'var(--accent-gold)');
  }
  setText('riskLabel', data.regime || '—');

  // Sentiment bars
  const bull = data.bullPct || 33;
  const neut = data.neutPct || 34;
  const bear = data.bearPct || 33;
  setWidth('sBull', bull);
  setWidth('sNeut', neut);
  setWidth('sBear', bear);
  setText('sBullPct', Math.round(bull) + '%');
  setText('sNeutPct', Math.round(neut) + '%');
  setText('sBearPct', Math.round(bear) + '%');

  // Risk indicators
  setText('riFear',   data.fear || '--');
  setText('riAvgFund', data.avgFunding != null ? data.avgFunding.toFixed(4) + '%' : '--%');
  setText('riRegime',  data.regime || '—');
  document.getElementById('riRegime').className = 'ri-val ' + (data.regime === 'RISK-ON' ? 'pct-up' : (data.regime === 'RISK-OFF' ? 'pct-down' : ''));
}

// ── Alert (generic) ──
function handleAlert(data) {
  pushAlertBar(data.message, data.level || 'med');
  state.totalAlertCount++;
  dom.sbAlertCount().textContent = `Alerts: ${state.totalAlertCount}`;
}

// ═══════════════════════════════════════════════════════
// RENDER FUNCTIONS
// ═══════════════════════════════════════════════════════

// ── Ticker Strip ──
function updateTickerStrip() {
  const syms = ['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','AVAXUSDT'];
  const strip = dom.tickerStrip();
  strip.innerHTML = syms.map(sym => {
    const d = state.latestData[sym];
    if (!d || !d.price) return '';
    const price = formatPrice(d.price);
    const chg   = d.change24h != null ? d.change24h.toFixed(2) : '0.00';
    const up    = parseFloat(chg) >= 0;
    const label = ASSET_COLORS[sym]?.label || sym.replace('USDT','');
    return `<span class="ticker-item">
      <span class="ticker-sym">${label}</span>
      <span class="ticker-price">$${price}</span>
      <span class="ticker-chg ${up ? 'up' : 'down'}">${up ? '+' : ''}${chg}%</span>
    </span>`;
  }).join('');
}

// ── Rank Table ──
function renderRankTable() {
  const items = Object.entries(state.latestData)
    .filter(([, d]) => d.flowScore != null)
    .sort((a, b) =>
      state.rankTab === 'inflow'
        ? b[1].flowScore - a[1].flowScore
        : a[1].flowScore - b[1].flowScore
    )
    .slice(0, 10);

  const tbody = dom.rankTableBody();
  if (items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="table-loading">Awaiting flow data…</td></tr>';
    return;
  }

  const rows = items.map(([sym, d], idx) => {
    const color = ASSET_COLORS[sym]?.line || '#7a9cc0';
    const label = ASSET_COLORS[sym]?.label || sym.replace('USDT','');
    const score = d.flowScore || 0;
    const barW  = score.toFixed(1);
    const barColor = score > 65 ? 'var(--accent-green)' : (score < 35 ? 'var(--accent-red)' : 'var(--accent-gold)');
    const price = d.price ? '$' + formatPrice(d.price) : '--';
    const chg   = d.change24h != null ? d.change24h.toFixed(2) : '0.00';
    const chgCls = parseFloat(chg) >= 0 ? 'pct-up' : 'pct-down';
    const vol   = d.volume ? formatVolume(d.volume) : '--';
    const sigHtml = getSignalBadge(d.signal);

    return `<tr>
      <td class="rank-num">${idx + 1}</td>
      <td>
        <div class="rank-asset">
          <div class="asset-icon" style="background:${color}22;color:${color};border:1px solid ${color}44">${label.slice(0,3)}</div>
          ${label}
        </div>
      </td>
      <td class="flow-bar-cell">
        <div class="flow-bar-wrap">
          <div class="flow-bar-bg"><div class="flow-bar-fill" style="width:${barW}%;background:${barColor}"></div></div>
          <span class="flow-score-val" style="color:${barColor}">${score.toFixed(0)}</span>
        </div>
      </td>
      <td>${price}</td>
      <td class="${chgCls}">${parseFloat(chg)>=0?'+':''}${chg}%</td>
      <td>${vol}</td>
      <td>${sigHtml}</td>
    </tr>`;
  });

  tbody.innerHTML = rows.join('');
}

// ── Whale Alerts ──
function renderWhaleAlerts() {
  const feed = dom.whaleFeed();
  if (state.whaleAlerts.length === 0) {
    feed.innerHTML = '<div class="whale-empty">Scanning for whale activity…</div>';
    return;
  }
  feed.innerHTML = state.whaleAlerts.map(a => `
    <div class="whale-alert ${a.severity || 'medium'}">
      <span class="whale-icon">${getWhaleIcon(a.type)}</span>
      <div class="whale-body">
        <div class="whale-title">${a.symbol} — ${a.title}</div>
        <div class="whale-desc">${a.message}</div>
      </div>
      <span class="whale-time">${formatTime(a.timestamp)}</span>
    </div>
  `).join('');

  dom.whaleBadge().textContent = `${state.whaleAlerts.length} ALERTS`;
}

// ── Dominance Donut ──
function renderDomChart(data) {
  const canvas = document.getElementById('domChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const cx = canvas.width / 2, cy = canvas.height / 2, r = 70, inner = 45;

  const slices = [
    { v: data.btc  || 0, color: '#F7931A' },
    { v: data.eth  || 0, color: '#627EEA' },
    { v: data.usdt || 0, color: '#26A17B' },
    { v: data.alts || 0, color: '#8B5CF6' },
  ];
  const total = slices.reduce((s, sl) => s + sl.v, 0) || 100;

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  let angle = -Math.PI / 2;
  slices.forEach(sl => {
    const sweep = (sl.v / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, angle, angle + sweep);
    ctx.closePath();
    ctx.fillStyle = sl.color;
    ctx.fill();
    angle += sweep;
  });

  // Inner circle cutout
  ctx.beginPath();
  ctx.arc(cx, cy, inner, 0, Math.PI * 2);
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--bg-panel').trim() || '#0b1120';
  ctx.fill();

  // Center text
  ctx.fillStyle = '#e8f4ff';
  ctx.font = 'bold 13px JetBrains Mono, monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText((data.btc || 0).toFixed(1) + '%', cx, cy - 7);
  ctx.fillStyle = '#7a9cc0';
  ctx.font = '9px JetBrains Mono, monospace';
  ctx.fillText('BTC DOM', cx, cy + 8);
}

// ── OI Panel ──
function renderOIPanel(data) {
  if (!data || !data.length) return;
  const maxOI = Math.max(...data.map(d => d.oi || 0), 1);
  const list = dom.oiList();
  list.innerHTML = data.map(d => {
    const barW = ((d.oi || 0) / maxOI * 100).toFixed(1);
    const chgCls = (d.change || 0) >= 0 ? 'pct-up' : 'pct-down';
    const chg = d.change != null ? ((d.change >= 0 ? '+' : '') + d.change.toFixed(2) + '%') : '--';
    return `<div class="oi-item">
      <span class="oi-sym">${d.symbol.replace('USDT','')}</span>
      <div class="oi-bar-wrap"><div class="oi-bar-fill" style="width:${barW}%"></div></div>
      <div style="text-align:right">
        <div class="oi-val">${formatVolume(d.oi)}</div>
        <div class="oi-chg ${chgCls}">${chg}</div>
      </div>
    </div>`;
  }).join('');
}

// ── Funding Panel ──
function renderFundingPanel(data) {
  if (!data || !data.length) return;
  const list = dom.fundingList();
  list.innerHTML = data.map(d => {
    const rate = d.rate || 0;
    const ratePct = (rate * 100).toFixed(4);
    const cls = rate > 0.0001 ? 'fund-pos' : (rate < -0.0001 ? 'fund-neg' : 'fund-neu');
    // Bar centered at 50%
    const barW = Math.min(Math.abs(rate) * 100000, 50);
    const barLeft = rate >= 0 ? '50%' : (50 - barW) + '%';
    const barColor = rate > 0 ? 'var(--accent-red)' : 'var(--accent-green)';
    return `<div class="fund-item">
      <span class="fund-sym">${d.symbol.replace('USDT','')}</span>
      <div class="fund-bar-wrap">
        <div class="fund-bar-fill" style="left:${barLeft};width:${barW}%;background:${barColor}"></div>
      </div>
      <span class="fund-val ${cls}">${rate >= 0 ? '+' : ''}${ratePct}%</span>
    </div>`;
  }).join('');

  // Summary stats
  const rates = data.map(d => (d.rate || 0) * 100);
  const avg = rates.reduce((s, r) => s + r, 0) / (rates.length || 1);
  const mx  = Math.max(...rates);
  const mn  = Math.min(...rates);
  setText('fundAvg', avg.toFixed(4) + '%');
  setText('fundMax', mx.toFixed(4) + '%');
  setText('fundMin', mn.toFixed(4) + '%');

  // Update risk panel avg funding
  setText('riAvgFund', avg.toFixed(4) + '%');
}

// ── Sector Heatmap ──
function renderSectorGrid(data) {
  if (!data || !data.sectors) return;
  const grid = dom.sectorGrid();

  // Sort by change
  const sorted = [...data.sectors].sort((a, b) => b.change - a.change);

  grid.innerHTML = sorted.map(s => {
    const heat = getHeatClass(s.change);
    const chgStr = (s.change >= 0 ? '+' : '') + (s.change || 0).toFixed(2) + '%';
    const chgCls = s.change >= 0 ? 'pct-up' : 'pct-down';
    return `<div class="sector-tile ${heat}">
      <span class="sector-name">${s.name}</span>
      <span class="sector-chg ${chgCls}">${chgStr}</span>
      <span class="sector-vol">${formatVolume(s.volume || 0)}</span>
    </div>`;
  }).join('');

  setText('hotSector',  data.hot  || '—');
  setText('coldSector', data.cold || '—');
}

// ── Alert Bar ──
const alertQueue = [];
let alertAnimating = false;

function pushAlertBar(msg, level = 'med') {
  alertQueue.push({ msg, level });
  if (!alertAnimating) showNextAlert();
}

function showNextAlert() {
  if (alertQueue.length === 0) { alertAnimating = false; return; }
  alertAnimating = true;
  const { msg, level } = alertQueue.shift();
  const scroller = dom.alertScroller();
  scroller.innerHTML = `<span class="alert-item ${level}">${msg}</span>`;
  // Re-trigger animation
  const el = scroller.querySelector('.alert-item');
  el.style.animation = 'none';
  requestAnimationFrame(() => {
    el.style.animation = '';
    setTimeout(showNextAlert, CONFIG.ALERT_DISPLAY_TIME / (alertQueue.length + 1));
  });
}

// ═══════════════════════════════════════════════════════
// CANVAS DRAWING — Arc & Gauge
// ═══════════════════════════════════════════════════════
function drawArc(canvasId, value, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  const cx = w / 2, cy = h - 10, r = h - 20;

  ctx.clearRect(0, 0, w, h);

  // Background arc
  ctx.beginPath();
  ctx.arc(cx, cy, r, Math.PI, 0);
  ctx.strokeStyle = 'rgba(255,255,255,0.06)';
  ctx.lineWidth = 10;
  ctx.lineCap = 'round';
  ctx.stroke();

  // Value arc
  const sweep = (value / 100) * Math.PI;
  ctx.beginPath();
  ctx.arc(cx, cy, r, Math.PI, Math.PI + sweep);
  ctx.strokeStyle = color;
  ctx.lineWidth = 10;
  ctx.lineCap = 'round';
  ctx.shadowBlur = 12;
  ctx.shadowColor = color;
  ctx.stroke();
  ctx.shadowBlur = 0;
}

function drawGauge(canvasId, value) {
  const color = value > 60 ? '#00ff88' : (value < 40 ? '#ff3d5a' : '#ffd700');
  drawArc(canvasId, value, color);
}

function getSentimentColor(v) {
  if (v >= 70) return '#00ff88';
  if (v >= 55) return '#7dff9a';
  if (v >= 45) return '#ffd700';
  if (v >= 30) return '#ff8c00';
  return '#ff3d5a';
}

function getSentimentLabel(v) {
  if (v >= 75) return 'EXTREME GREED';
  if (v >= 60) return 'GREED';
  if (v >= 45) return 'NEUTRAL';
  if (v >= 30) return 'FEAR';
  return 'EXTREME FEAR';
}

// ═══════════════════════════════════════════════════════
// UTILITY FUNCTIONS
// ═══════════════════════════════════════════════════════
function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}
function setHtml(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}
function setWidth(id, pct) {
  const el = document.getElementById(id);
  if (el) el.style.width = pct + '%';
}

function formatPrice(p) {
  if (p == null) return '--';
  if (p >= 1000) return p.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  if (p >= 1)    return p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  return p.toFixed(6);
}

function formatVolume(v) {
  if (v == null) return '--';
  if (v >= 1e9)  return (v / 1e9).toFixed(2) + 'B';
  if (v >= 1e6)  return (v / 1e6).toFixed(2) + 'M';
  if (v >= 1e3)  return (v / 1e3).toFixed(2) + 'K';
  return v.toFixed(2);
}

function formatTime(ts) {
  if (!ts) return '--';
  const d = new Date(ts);
  return d.toLocaleTimeString('en-US', { hour12: false, hour:'2-digit', minute:'2-digit', second:'2-digit' });
}

function getSignalBadge(sig) {
  if (!sig) return '<span class="signal-badge sig-neut">—</span>';
  const map = {
    'STRONG_INFLOW':  '<span class="signal-badge sig-strong-in">STRONG IN ▲</span>',
    'INFLOW':         '<span class="signal-badge sig-in">INFLOW ▲</span>',
    'NEUTRAL':        '<span class="signal-badge sig-neut">NEUTRAL</span>',
    'OUTFLOW':        '<span class="signal-badge sig-out">OUTFLOW ▼</span>',
    'STRONG_OUTFLOW': '<span class="signal-badge sig-strong-out">STRONG OUT ▼</span>',
  };
  return map[sig] || `<span class="signal-badge sig-neut">${sig}</span>`;
}

function getWhaleIcon(type) {
  const icons = {
    'volume_spike':   '📊',
    'oi_change':      '📈',
    'funding_extreme':'💰',
    'liquidation':    '💥',
    'price_impact':   '🚀',
  };
  return icons[type] || '🐋';
}

function getHeatClass(chg) {
  if (chg >= 3)  return 'heat-5';
  if (chg >= 1)  return 'heat-4';
  if (chg >= -1) return 'heat-3';
  if (chg >= -3) return 'heat-2';
  return 'heat-1';
}

// ═══════════════════════════════════════════════════════
// TAB SWITCHER
// ═══════════════════════════════════════════════════════
function switchRankTab(tab) {
  state.rankTab = tab;
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab);
  });
  renderRankTable();
}

// ═══════════════════════════════════════════════════════
// DEMO DATA FALLBACK
// When backend is not reachable, show simulated data so
// the UI is functional standalone.
// ═══════════════════════════════════════════════════════
const SYMBOLS = ['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','LINKUSDT','AVAXUSDT','TRXUSDT'];

const BASE_PRICES = {
  BTCUSDT: 67500, ETHUSDT: 3450, BNBUSDT: 580, SOLUSDT: 155,
  XRPUSDT: 0.58,  DOGEUSDT: 0.13, ADAUSDT: 0.48, LINKUSDT: 14.5,
  AVAXUSDT: 35.5, TRXUSDT: 0.12,
};

function simulateMarketData() {
  SYMBOLS.forEach(sym => {
    if (!state.latestData[sym]) {
      state.latestData[sym] = {
        price: BASE_PRICES[sym],
        change24h: (Math.random() * 10 - 5),
        volume: Math.random() * 2e9 + 1e8,
        flowScore: Math.random() * 100,
        signal: ['STRONG_INFLOW','INFLOW','NEUTRAL','OUTFLOW','STRONG_OUTFLOW'][Math.floor(Math.random()*5)],
      };
    } else {
      // Simulate price movement
      const d = state.latestData[sym];
      const drift = (Math.random() - 0.499) * 0.002;
      d.price = Math.max(d.price * (1 + drift), 0.001);
      d.change24h += (Math.random() - 0.5) * 0.1;
      d.flowScore = Math.max(0, Math.min(100, (d.flowScore || 50) + (Math.random() - 0.5) * 3));
      d.volume += (Math.random() - 0.4) * 1e6;
    }
  });

  updateTickerStrip();
  renderRankTable();

  // Push flow score to chart
  SYMBOLS.forEach(sym => {
    const d = state.latestData[sym];
    if (d.flowScore != null) pushFlowPoint(sym, Date.now(), d.flowScore);
  });
}

function simulateDominance() {
  const btc  = 52 + (Math.random() - 0.5) * 2;
  const eth  = 17 + (Math.random() - 0.5) * 1;
  const usdt = 6  + (Math.random() - 0.5) * 0.5;
  const alts = 100 - btc - eth - usdt;
  handleDominance({
    btc, eth, usdt, alts: Math.max(0, alts),
    btcChg: (Math.random() - 0.5) * 0.4,
    ethChg: (Math.random() - 0.5) * 0.3,
    usdtChg:(Math.random() - 0.5) * 0.1,
    altsChg:(Math.random() - 0.5) * 0.5,
    signal: btc > 52 ? '🔵 Capital rotating into BTC — Altcoins under pressure' : '🟢 Capital dispersing to Altcoins — Risk-On environment',
  });
}

function simulateFunding() {
  const data = SYMBOLS.map(sym => ({
    symbol: sym,
    rate: (Math.random() - 0.48) * 0.001,
    annualized: 0,
  }));
  handleFundingUpdate(data);
}

function simulateOI() {
  const data = SYMBOLS.map(sym => ({
    symbol: sym,
    oi: Math.random() * 5e9 + 1e8,
    change: (Math.random() - 0.5) * 4,
  }));
  handleOIUpdate(data);
}

function simulateSectors() {
  const sectors = Object.keys(SECTORS).map(name => ({
    name,
    change: (Math.random() - 0.5) * 8,
    volume: Math.random() * 2e9,
    heat: Math.floor(Math.random() * 5) + 1,
  }));
  const sorted = [...sectors].sort((a,b)=>b.change-a.change);
  handleSectorUpdate({
    sectors,
    hot: sorted[0].name,
    cold: sorted[sorted.length-1].name,
  });
}

function simulateRisk() {
  const score = 40 + Math.random() * 30;
  const riskScore = 30 + Math.random() * 40;
  const regime = score > 60 ? 'RISK-ON' : (score < 40 ? 'RISK-OFF' : 'NEUTRAL');
  const bull = score;
  const bear = 100 - score;
  const neut = Math.max(0, 100 - bull - bear);
  handleRiskRegime({
    regime, score, riskScore,
    bullPct: bull * 0.7,
    neutPct: neut * 0.3 + 15,
    bearPct: bear * 0.7,
    fear: Math.round(score).toString(),
    avgFunding: (Math.random() - 0.48) * 0.0008,
  });
}

function simulateWhaleAlert() {
  if (Math.random() > 0.15) return; // 15% chance each tick
  const sym = SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)];
  const types = ['volume_spike','oi_change','funding_extreme','liquidation'];
  const type = types[Math.floor(Math.random() * types.length)];
  const severities = ['low','medium','high','critical'];
  const sev = severities[Math.floor(Math.random() * 3)];
  const messages = {
    volume_spike:    `${sym}: Volume spike ${(2 + Math.random() * 5).toFixed(1)}x above 24h average. Possible institutional accumulation.`,
    oi_change:       `${sym}: Open Interest surged +${(5 + Math.random() * 15).toFixed(1)}% in last 5 minutes. Leveraged position building detected.`,
    funding_extreme: `${sym}: Funding rate hit ${(0.05 + Math.random() * 0.1).toFixed(3)}% — extreme ${Math.random()>0.5?'long':'short'} dominance.`,
    liquidation:     `${sym}: $${(Math.random()*50+5).toFixed(1)}M in ${Math.random()>0.5?'long':'short'} liquidations triggered.`,
  };
  handleWhaleAlert({
    symbol: sym.replace('USDT',''),
    type,
    severity: sev,
    title: type.replace(/_/g,' ').toUpperCase(),
    message: messages[type],
    timestamp: Date.now(),
  });
}

function simulateAlerts() {
  if (Math.random() > 0.08) return;
  const alerts = [
    { message:'⬆ BTC strong inflow signal — Flow score crossing 75', level:'green' },
    { message:'🔄 Altcoin rotation detected — capital leaving BTC', level:'med' },
    { message:'🔴 Funding rate extreme — overleveraged longs at risk', level:'high' },
    { message:'📉 Risk-off signal triggered — stablecoin dominance rising', level:'high' },
    { message:'🟢 SOL showing strongest relative inflow of the session', level:'green' },
    { message:'⚡ Sector rotation: Layer1 outperforming DeFi by 4.2%', level:'med' },
  ];
  handleAlert(alerts[Math.floor(Math.random() * alerts.length)]);
}

// ═══════════════════════════════════════════════════════
// DEMO SIMULATION LOOP (runs when WS is disconnected)
// ═══════════════════════════════════════════════════════
let demoInterval = null;
let domUpdateCount = 0;

function startDemoMode() {
  if (demoInterval) return;
  console.log('[DEMO] Starting simulation mode (backend not connected)');
  pushAlertBar('⚠ Backend not connected — running in DEMO mode with simulated data', 'med');

  // Initial data
  simulateMarketData();
  simulateDominance();
  simulateFunding();
  simulateOI();
  simulateSectors();
  simulateRisk();

  demoInterval = setInterval(() => {
    simulateMarketData();
    simulateWhaleAlert();
    simulateAlerts();

    domUpdateCount++;
    if (domUpdateCount % 5 === 0)  simulateFunding();
    if (domUpdateCount % 10 === 0) simulateOI();
    if (domUpdateCount % 15 === 0) simulateSectors();
    if (domUpdateCount % 8 === 0)  simulateDominance();
    if (domUpdateCount % 12 === 0) simulateRisk();
  }, 1000);
}

function stopDemoMode() {
  if (demoInterval) {
    clearInterval(demoInterval);
    demoInterval = null;
  }
}

// ═══════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════
function init() {
  initChart();

  // Try to connect to backend WebSocket
  connectWS();

  // Start demo mode after 3 seconds if no connection
  const demoTimer = setTimeout(() => {
    if (!state.connected) startDemoMode();
  }, 3000);

  // Stop demo when WS connects
  const origOpen = WebSocket.prototype.onopen;
  document.addEventListener('ws-connected', () => {
    clearTimeout(demoTimer);
    stopDemoMode();
  });

  // Initial arc draws (blank state)
  drawArc('sentimentArc', 50, '#ffd700');
  drawGauge('riskGauge', 50);

  console.log('[SMFT] Smart Money Flow Terminal Pro initialized');
}

document.addEventListener('DOMContentLoaded', init);
