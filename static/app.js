/* ═══════════════════════════════════════════════════════════
   vLLM Benchmark GUI — Alpine.js App Logic
   ═══════════════════════════════════════════════════════════ */

const API = '/api';

/* ── Helpers ─────────────────────────────────────────────── */
async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

/* Global toast queue */
const _toasts = [];

function toast(msg, type) {
  type = type || 'info';
  const t = { message: msg, type: type, show: true };
  _toasts.push(t);
  setTimeout(function () { t.show = false; }, 4000);
}

function formatTimestamp(ts) {
  if (!ts) return '—';
  try {
    var d = new Date(ts.includes('T') ? ts : ts.replace(' ', 'T'));
    return d.toLocaleString();
  } catch (e) { return ts; }
}

/* ── Theme Management ───────────────────────────────────── */
function getStoredTheme() {
  try { return localStorage.getItem('vllm_theme') || 'dark'; }
  catch { return 'dark'; }
}

function setTheme(theme) {
  const root = document.documentElement;
  root.setAttribute('data-theme', theme);
  try { localStorage.setItem('vllm_theme', theme); } catch {}

  // Apply all CSS variables for the theme
  if (theme === 'light') {
    root.style.setProperty('--bg-base', '#f8f9fc');
    root.style.setProperty('--bg-panel', '#ffffff');
    root.style.setProperty('--bg-card', '#f1f3f8');
    root.style.setProperty('--bg-hover', '#e5e8ef');
    root.style.setProperty('--border', '#d0d5e2');
    root.style.setProperty('--accent', '#ea6c00');
    root.style.setProperty('--accent-green', '#28a745');
    root.style.setProperty('--accent-red', '#dc3545');
    root.style.setProperty('--accent-blue', '#0d6efd');
    root.style.setProperty('--accent-purple', '#6f42c1');
    root.style.setProperty('--text-primary', '#212529');
    root.style.setProperty('--text-secondary', '#495057');
    root.style.setProperty('--text-muted', '#6c757d');
  } else {
    // Dark mode (defaults)
    root.style.setProperty('--bg-base', '#0f1115');
    root.style.setProperty('--bg-panel', '#161920');
    root.style.setProperty('--bg-card', '#1f232e');
    root.style.setProperty('--bg-hover', '#2a2f3c');
    root.style.setProperty('--border', '#2d3344');
    root.style.setProperty('--accent', '#f5a623');
    root.style.setProperty('--accent-green', '#4ade80');
    root.style.setProperty('--accent-red', '#f87171');
    root.style.setProperty('--accent-blue', '#60a5fa');
    root.style.setProperty('--accent-purple', '#a78bfa');
    root.style.setProperty('--text-primary', '#e8e9ec');
    root.style.setProperty('--text-secondary', '#a1a6b5');
    root.style.setProperty('--text-muted', '#73788a');
  }
}

function toggleTheme() {
  const current = getStoredTheme();
  setTheme(current === 'dark' ? 'light' : 'dark');
}

/* ── Main Alpine Component ───────────────────────────────── */
function createApp() {
  return {
    /* ── Global state ──────────────────────────────────── */
    activeTab: 'servers',
    toasts: _toasts,
    currentTheme: getStoredTheme(),

    /* ── Servers ───────────────────────────────────────── */
    servers: [],
    showServerDialog: false,
    showDeleteConfirm: false,
    deleteTarget: null,
    serverForm: {
      editing: false,
      alias: '',
      host: '',
      port: 8000,
      description: '',
      color: '#f5a623',
      tags: '',
      testResult: '',
    },

    /* ── Benchmark ─────────────────────────────────────── */
    bench: {
      server_alias: '',
      model: '',
      models: [],
      concurrency_levels: [1, 2, 4],
      custom_concurrency: '',
      prompt_keys: ['short', 'medium', 'long', 'coding'],
      num_requests: 8,
      temperature: 0.0,
      quick_mode: false,
    },
    benchRunning: false,
    benchDone: false,
    benchProgressMap: {},   // plain object, not Map: "key" -> { pct, text, toks }
    benchResults: [],
    peakTokS: 0,
    maxConcurrencyCap: 12,
    _currentRunId: '',
    _evtSource: null,

    /* ── History ───────────────────────────────────────── */
    historyRuns: [],
    historyDetail: null,
    historyFilter: { server: '' },
    selectedHistoryRuns: [],
    selectAllHistory: false,
    _historyCharts: {},

    /* ── Compare ───────────────────────────────────────── */
    compareMode: 'two-server',
    compare: {
      serverA: '', serverB: '',
      runA: '', runB: '',
      runsA: [], runsB: [],
      metric: 'throughput_tok_s',
      prompt_key: 'medium',
    },
    compareResult: { rows: [], server_a_alias: '', server_b_alias: '' },
    _compareChart: null,

    /* ── Backup ────────────────────────────────────────── */
    backups: [],
    backupCreating: false,

    /* ── Settings ──────────────────────────────────────── */
    showSettings: false,
    settings: {
      app_port: 7842,
      request_timeout_s: 300,
      max_concurrency_cap: 12,
      backup_keep_n: 10,
    },
    maxConcurrencyCap: 12,

    /* ── Computed helpers ──────────────────────────────── */
    get recentServers() {
      return this.servers.slice(0, 3);
    },
    get canCompare() {
      if (this.compareMode === 'two-server') {
        return !!(this.compare.serverA && this.compare.runA && this.compare.serverB && this.compare.runB);
      }
      return false;
    },
    get themeIcon() {
      return this.currentTheme === 'dark' ? 'moon' : 'sun';
    },

    /* ── Tab switching (loads data on first visit) ────── */
    switchTab: function (tab) {
      this.activeTab = tab;
      if (tab === 'history' && this.historyRuns.length === 0) this.loadHistory();
      if (tab === 'backup' && this.backups.length === 0) this.loadBackups();
    },

    /* ── Progress map helpers (plain object, not Map) ─── */
    benchProgressKeys: function () {
      return Object.keys(this.benchProgressMap);
    },
    getProgress: function (key) {
      return this.benchProgressMap[key] || { pct: 0, text: 'waiting…', toks: '' };
    },

    /* ── Init ──────────────────────────────────────────── */
    init: function () {
      var self = this;
      this.loadServers();
      // Initialize theme
      this.currentTheme = getStoredTheme();
      setTheme(this.currentTheme);

      // Keyboard shortcuts
      document.addEventListener('keydown', function (e) {
        var tag = (e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
        if (e.key === 'r' || e.key === 'R') {
          if (!self.benchRunning && self.bench.server_alias && self.bench.model) {
            self.startBenchmark();
          }
        }
        if (e.key === 'Escape') {
          if (self.benchRunning) self.stopBenchmark();
        }
      });
      // Auto-ping loop
      setInterval(function () { self.autoPing(); }, 30000);
    },

    /* ════════════ Server methods ════════════ */

    loadServers: async function () {
      var self = this;
      try {
        this.servers = await api('/servers');
      } catch (e) { toast('Failed to load servers: ' + e.message, 'error'); }
    },

    openServerDialog: function (server) {
      if (server) {
        this.serverForm = {
          editing: true,
          alias: server.alias,
          host: server.host,
          port: server.port,
          description: server.description || '',
          color: server.color || '#f5a623',
          tags: server.tags || '',
          testResult: '',
        };
      } else {
        this.serverForm = {
          editing: false,
          alias: '',
          host: '',
          port: 8000,
          description: '',
          color: '#f5a623',
          tags: '',
          testResult: '',
        };
      }
      this.showServerDialog = true;
    },

    testConnection: async function () {
      this.serverForm.testResult = 'Testing…';
      try {
        var r = await api('/servers/test', {
          method: 'POST',
          body: JSON.stringify({ host: this.serverForm.host, port: this.serverForm.port }),
        });
        if (r.ok) {
          this.serverForm.testResult = '✓ Reachable · ' + r.model_count + ' models · ' + r.latency_ms + 'ms';
        } else {
          this.serverForm.testResult = '✗ ' + r.error;
        }
      } catch (e) {
        this.serverForm.testResult = '✗ ' + e.message;
      }
    },

    saveServer: async function () {
      try {
        if (this.serverForm.editing) {
          await api('/servers/' + this.serverForm.alias, {
            method: 'PUT',
            body: JSON.stringify({
              host: this.serverForm.host,
              port: this.serverForm.port,
              description: this.serverForm.description || null,
              color: this.serverForm.color || null,
              tags: this.serverForm.tags || null,
            }),
          });
          toast('Server "' + this.serverForm.alias + '" updated', 'success');
        } else {
          await api('/servers', {
            method: 'POST',
            body: JSON.stringify(this.serverForm),
          });
          toast('Server "' + this.serverForm.alias + '" created', 'success');
        }
        this.showServerDialog = false;
        await this.loadServers();
      } catch (e) { toast(e.message, 'error'); }
    },

    confirmDeleteServer: function (s) {
      this.deleteTarget = s;
      this.showDeleteConfirm = true;
    },

    deleteServer: async function () {
      try {
        await api('/servers/' + this.deleteTarget.alias, { method: 'DELETE' });
        toast('Server "' + this.deleteTarget.alias + '" deleted', 'success');
        this.showDeleteConfirm = false;
        this.deleteTarget = null;
        await this.loadServers();
      } catch (e) { toast(e.message, 'error'); }
    },

    pingServer: async function (s) {
      try {
        var r = await api('/servers/' + s.alias + '/ping');
        if (r.ok) {
          toast(s.alias + ' reachable · ' + r.model_count + ' models · ' + r.latency_ms + 'ms', 'success');
        } else {
          toast(s.alias + ' unreachable: ' + r.error, 'error');
        }
        await this.loadServers();
      } catch (e) { toast(e.message, 'error'); }
    },

    autoPing: async function () {
      for (var i = 0; i < Math.min(3, this.servers.length); i++) {
        try { await api('/servers/' + this.servers[i].alias + '/ping'); } catch (e) { /* ignore */ }
      }
      await this.loadServers();
    },

    /* ════════════ Benchmark methods ════════════ */

    addCustomConcurrency: function () {
      var c = this.bench.custom_concurrency;
      if (c && c > 0 && c <= this.maxConcurrencyCap && this.bench.concurrency_levels.indexOf(c) === -1) {
        this.bench.concurrency_levels.push(c);
        this.bench.concurrency_levels.sort(function (a, b) { return a - b; });
      }
      this.bench.custom_concurrency = '';
    },

    fetchModels: async function () {
      if (!this.bench.server_alias) return;
      try {
        var r = await api('/servers/' + this.bench.server_alias + '/models');
        this.bench.models = r.models || [];
        if (this.bench.models.length > 0 && !this.bench.model) {
          this.bench.model = this.bench.models[0];
        }
      } catch (e) { toast('Failed to fetch models: ' + e.message, 'error'); }
    },

    startBenchmark: async function () {
      if (this.benchRunning) return;
      this.benchRunning = true;
      this.benchDone = false;
      this.benchProgressMap = {};
      this.benchResults = [];
      this.peakTokS = 0;

      var levels = this.bench.concurrency_levels.slice().sort(function (a, b) { return a - b; });
      var self = this;

      // Initialize progress entries
      this.bench.prompt_keys.forEach(function (pk) {
        levels.forEach(function (c) {
          self.benchProgressMap[pk + '/c=' + c] = { pct: 0, text: 'waiting…', toks: '' };
        });
      });

      try {
        var r = await api('/benchmark/start', {
          method: 'POST',
          body: JSON.stringify({
            server_alias: self.bench.server_alias,
            model: self.bench.model,
            concurrency_levels: levels,
            prompt_keys: self.bench.prompt_keys,
            num_requests: self.bench.num_requests,
            temperature: self.bench.temperature,
            quick_mode: self.bench.quick_mode,
          }),
        });

        self._currentRunId = r.run_id;
        self._streamSSE(r.run_id);
      } catch (e) {
        toast('Failed to start: ' + e.message, 'error');
        self.benchRunning = false;
      }
    },

    _streamSSE: function (runId) {
      var self = this;
      var evtSource = new EventSource(API + '/benchmark/' + runId + '/stream');
      this._evtSource = evtSource;

      evtSource.onmessage = function (e) {
        var msg = JSON.parse(e.data);
        self._handleSSEEvent(msg);
      };
      evtSource.onerror = function () {
        evtSource.close();
        if (self.benchRunning) {
          toast('SSE connection lost', 'error');
        }
      };
    },

    _handleSSEEvent: function (msg) {
      var event = msg.event;
      var data = msg.data;
      if (event === 'progress') {
        var key = data.prompt_key + '/c=' + data.concurrency;
        var pct = data.total > 0 ? Math.round((data.done / data.total) * 100) : 0;
        var text = data.done >= data.total ? 'done' : data.done + '/' + data.total;
        var toks = data.tok_s > 0 ? Math.round(data.tok_s).toString() : '';
        this.benchProgressMap[key] = { pct: pct, text: text, toks: toks };
        // Trigger reactivity
        this.benchProgressMap = Object.assign({}, this.benchProgressMap);
      } else if (event === 'result') {
        // Update result in table
        var found = false;
        for (var i = 0; i < this.benchResults.length; i++) {
          if (this.benchResults[i].prompt_key === data.prompt_key && this.benchResults[i].concurrency === data.concurrency) {
            this.benchResults[i] = data;
            found = true;
            break;
          }
        }
        if (!found) {
          this.benchResults.push(data);
        }
        this.benchResults = this.benchResults.slice(); // trigger reactivity
      } else if (event === 'done') {
        this.peakTokS = data.peak_tok_s;
        this.benchDone = true;
        this.benchRunning = false;
        if (this._evtSource) { this._evtSource.close(); this._evtSource = null; }
        toast('Run complete — Peak: ' + data.peak_tok_s.toFixed(1) + ' tok/s', 'success');
        this.loadHistory();
      } else if (event === 'error') {
        this.benchRunning = false;
        if (this._evtSource) { this._evtSource.close(); this._evtSource = null; }
        toast('Benchmark error: ' + data.message, 'error');
      }
    },

    stopBenchmark: function () {
      if (this._currentRunId) {
        var self = this;
        api('/benchmark/' + this._currentRunId + '/stop', { method: 'POST' })
          .catch(function (e) { toast(e.message, 'error'); });
        toast('Stop requested', 'info');
      }
      this.benchRunning = false;
    },

    /* ════════════ History methods ════════════ */

    loadHistory: async function () {
      try {
        var params = 'limit=50&order=desc';
        if (this.historyFilter.server) params += '&server_alias=' + encodeURIComponent(this.historyFilter.server);
        this.historyRuns = await api('/results?' + params);
      } catch (e) { toast('Failed to load history: ' + e.message, 'error'); }
    },

    loadHistoryDetail: async function (runId) {
      try {
        this.historyDetail = await api('/results/' + runId);
        // Wait for Alpine to update DOM, then render charts
        var self = this;
        this.$nextTick(function () {
          self._renderHistoryCharts();
        });
      } catch (e) { toast('Failed to load detail: ' + e.message, 'error'); }
    },

    toggleHistoryExpand: function () { /* row click placeholder */ },

    toggleHistorySelect: function (runId) {
      var idx = this.selectedHistoryRuns.indexOf(runId);
      if (idx > -1) {
        this.selectedHistoryRuns.splice(idx, 1);
      } else {
        this.selectedHistoryRuns.push(runId);
      }
      this.selectAllHistory = this.selectedHistoryRuns.length === this.historyRuns.length && this.historyRuns.length > 0;
    },

    toggleAllHistory: function (e) {
      if (e.target.checked) {
        this.selectedHistoryRuns = this.historyRuns.map(function (r) { return r.run_id; });
      } else {
        this.selectedHistoryRuns = [];
      }
    },

    deleteSelectedHistory: async function () {
      if (this.selectedHistoryRuns.length === 0) {
        toast('No runs selected', 'info');
        return;
      }
      if (!confirm('Delete ' + this.selectedHistoryRuns.length + ' selected run(s)?')) return;

      try {
        var res = await api('/results', {
          method: 'DELETE',
          body: JSON.stringify({ run_ids: this.selectedHistoryRuns })
        });
        toast('Deleted ' + (res.deleted || []).length + ' run(s)', 'success');
        this.selectedHistoryRuns = [];
        this.selectAllHistory = false;
        await this.loadHistory();
      } catch (e) {
        toast('Delete failed: ' + e.message, 'error');
      }
    },

    _renderHistoryCharts: function () {
      // Destroy old charts
      var self = this;
      Object.keys(this._historyCharts).forEach(function (key) {
        try { self._historyCharts[key].destroy(); } catch (e) { /* ignore */ }
      });
      this._historyCharts = {};

      var results = (this.historyDetail && this.historyDetail.results) || [];
      if (results.length === 0) return;

      // Group by prompt_key
      var byPrompt = {};
      results.forEach(function (r) {
        if (!byPrompt[r.prompt_key]) byPrompt[r.prompt_key] = [];
        byPrompt[r.prompt_key].push(r);
      });

      var chartDefaults = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#e8e8e8', font: { family: 'monospace' } } } },
        scales: {
          x: { ticks: { color: '#666' }, grid: { color: '#2a2a2a' } },
          y: { ticks: { color: '#666' }, grid: { color: '#2a2a2a' } },
        },
      };

      var colors = { short: '#4ade80', medium: '#f5a623', long: '#f87171', coding: '#60a5fa', custom: '#a78bfa' };
      function colorForPrompt(pk) { return colors[pk] || '#e8e8e8'; }

      // Throughput chart
      var tpCanvas = document.getElementById('chart-throughput');
      if (tpCanvas && typeof Chart !== 'undefined') {
        var tpDatasets = Object.keys(byPrompt).map(function (pk) {
          var rows = byPrompt[pk].slice().sort(function (a, b) { return a.concurrency - b.concurrency; });
          return {
            label: pk,
            data: rows.map(function (r) { return { x: r.concurrency, y: r.throughput_tok_s || 0 }; }),
            borderColor: colorForPrompt(pk),
            backgroundColor: colorForPrompt(pk) + '33',
            tension: 0.2,
          };
        });
        this._historyCharts.tp = new Chart(tpCanvas, {
          type: 'line',
          data: { datasets: tpDatasets },
          options: Object.assign({}, chartDefaults, {
            plugins: Object.assign({}, chartDefaults.plugins, { title: { display: true, text: 'Throughput vs Concurrency', color: '#e8e8e8' } }),
          }),
        });
      }

      // Latency chart
      var latCanvas = document.getElementById('chart-latency');
      if (latCanvas && typeof Chart !== 'undefined') {
        var latDatasets = [];
        Object.keys(byPrompt).forEach(function (pk) {
          var sorted = byPrompt[pk].slice().sort(function (a, b) { return a.concurrency - b.concurrency; });
          latDatasets.push({
            label: pk + ' P50',
            data: sorted.map(function (r) { return { x: r.concurrency, y: r.p50_latency_ms || 0 }; }),
            borderColor: colorForPrompt(pk),
            borderDash: [5, 3],
            tension: 0.2,
          });
          latDatasets.push({
            label: pk + ' P95',
            data: sorted.map(function (r) { return { x: r.concurrency, y: r.p95_latency_ms || 0 }; }),
            borderColor: colorForPrompt(pk),
            tension: 0.2,
          });
        });
        this._historyCharts.lat = new Chart(latCanvas, {
          type: 'line',
          data: { datasets: latDatasets },
          options: Object.assign({}, chartDefaults, {
            plugins: Object.assign({}, chartDefaults.plugins, { title: { display: true, text: 'Latency vs Concurrency', color: '#e8e8e8' } }),
          }),
        });
      }

      // TTFT chart
      var ttftCanvas = document.getElementById('chart-ttft');
      if (ttftCanvas && typeof Chart !== 'undefined') {
        var ttftDatasets = Object.keys(byPrompt).map(function (pk) {
          var rows = byPrompt[pk].slice().sort(function (a, b) { return a.concurrency - b.concurrency; });
          return {
            label: pk,
            data: rows.map(function (r) { return { x: r.concurrency, y: r.avg_ttft_ms || 0 }; }),
            borderColor: colorForPrompt(pk),
            backgroundColor: colorForPrompt(pk) + '33',
            tension: 0.2,
          };
        });
        this._historyCharts.ttft = new Chart(ttftCanvas, {
          type: 'line',
          data: { datasets: ttftDatasets },
          options: Object.assign({}, chartDefaults, {
            plugins: Object.assign({}, chartDefaults.plugins, { title: { display: true, text: 'TTFT vs Concurrency', color: '#e8e8e8' } }),
          }),
        });
      }
    },

    exportRun: async function (runId) {
      try {
        var data = await api('/results/' + runId + '/export');
        var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = 'vllm_bench_' + runId + '.json';
        a.click(); URL.revokeObjectURL(url);
        toast('Run exported', 'success');
      } catch (e) { toast('Export failed: ' + e.message, 'error'); }
    },

    deleteRun: async function (runId) {
      if (!confirm('Delete this run?')) return;
      try {
        await api('/results/' + runId, { method: 'DELETE' });
        toast('Run deleted', 'success');
        this.historyDetail = null;
        await this.loadHistory();
      } catch (e) { toast(e.message, 'error'); }
    },

    /* ════════════ Compare methods ════════════ */

    loadCompareRuns: async function (which) {
      if (which === 'A' && this.compare.serverA) {
        try {
          var q = 'server_alias=' + encodeURIComponent(this.compare.serverA) + '&limit=50&order=desc';
          this.compare.runsA = await api('/results?' + q);
        } catch (e) { toast(e.message, 'error'); }
      }
      if (which === 'B' && this.compare.serverB) {
        try {
          var q2 = 'server_alias=' + encodeURIComponent(this.compare.serverB) + '&limit=50&order=desc';
          this.compare.runsB = await api('/results?' + q2);
        } catch (e) { toast(e.message, 'error'); }
      }
    },

    runCompare: async function () {
      try {
        var params = 'run_a_id=' + encodeURIComponent(this.compare.runA) +
                     '&run_b_id=' + encodeURIComponent(this.compare.runB) +
                     '&prompt_key=' + encodeURIComponent(this.compare.prompt_key) +
                     '&metric=' + encodeURIComponent(this.compare.metric);
        this.compareResult = await api('/results/compare?' + params);
        var self = this;
        this.$nextTick(function () {
          self._renderCompareChart();
        });
      } catch (e) { toast('Compare failed: ' + e.message, 'error'); }
    },

    _renderCompareChart: function () {
      if (this._compareChart) { try { this._compareChart.destroy(); } catch (e) { /* ignore */ } }
      var canvas = document.getElementById('chart-compare');
      if (!canvas || typeof Chart === 'undefined') return;

      var rows = this.compareResult.rows || [];
      var labels = rows.map(function (r) { return 'c=' + r.concurrency; });
      var metricLabel = this.compare.metric.replace('_tok_s', ' tok/s').replace(/_/g, ' ');

      var colorA = this._getServerColor(this.compare.serverA);
      var colorB = this._getServerColor(this.compare.serverB);

      this._compareChart = new Chart(canvas, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [
            {
              label: this.compareResult.server_a_alias,
              data: rows.map(function (r) { return r.value_a || 0; }),
              backgroundColor: colorA + 'cc',
            },
            {
              label: this.compareResult.server_b_alias,
              data: rows.map(function (r) { return r.value_b || 0; }),
              backgroundColor: colorB + 'cc',
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: '#e8e8e8' } },
            title: { display: true, text: metricLabel + ' — ' + this.compare.prompt_key, color: '#e8e8e8' },
          },
          scales: {
            x: { ticks: { color: '#666' }, grid: { color: '#2a2a2a' } },
            y: { ticks: { color: '#666' }, grid: { color: '#2a2a2a' } },
          },
        },
      });
    },

    _getServerColor: function (alias) {
      for (var i = 0; i < this.servers.length; i++) {
        if (this.servers[i].alias === alias) return this.servers[i].color || '#f5a623';
      }
      return '#f5a623';
    },

    /* ════════════ Backup methods ════════════ */

    loadBackups: async function () {
      try { this.backups = await api('/backup/list'); }
      catch (e) { toast('Failed to load backups: ' + e.message, 'error'); }
    },

    createBackup: async function () {
      this.backupCreating = true;
      try {
        var r = await api('/backup/create', { method: 'POST' });
        toast('Backup created: ' + r.filename + ' (' + Math.round(r.size_bytes / 1024) + ' KB)', 'success');
        await this.loadBackups();
      } catch (e) { toast('Backup failed: ' + e.message, 'error'); }
      finally { this.backupCreating = false; }
    },

    deleteBackup: async function (filename) {
      if (!confirm('Delete backup "' + filename + '"?')) return;
      try {
        await api('/backup/' + filename, { method: 'DELETE' });
        toast('Backup deleted', 'success');
        await this.loadBackups();
      } catch (e) { toast(e.message, 'error'); }
    },

    restoreBackup: async function () {
      var fileInput = this.$refs.restoreFile;
      if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        toast('Select a backup file first', 'error');
        return;
      }
      if (!confirm('This will replace the current database and settings. Continue?')) return;

      var formData = new FormData();
      formData.append('file', fileInput.files[0]);

      try {
        var res = await fetch(API + '/backup/restore', { method: 'POST', body: formData });
        if (!res.ok) {
          var err = await res.json();
          throw new Error(err.detail || 'Restore failed');
        }
        toast('Database restored — reloading…', 'success');
        var self = this;
        setTimeout(function () { location.reload(); }, 1500);
      } catch (e) { toast('Restore failed: ' + e.message, 'error'); }
    },

    /* ════════════ Theme methods ════════════ */

    toggleTheme: function () {
      toggleTheme();
      this.currentTheme = getStoredTheme();
      toast(`Switched to ${this.currentTheme === 'dark' ? 'Dark' : 'Light'} mode`, 'success');
    },

    /* ════════════ Settings methods ════════════ */

    saveSettings: function () {
      // Update maxConcurrencyCap from settings
      if (this.settings.max_concurrency_cap) {
        this.maxConcurrencyCap = this.settings.max_concurrency_cap;
      }
      // Stored in localStorage as the app has no settings bulk-write endpoint
      try { localStorage.setItem('vllm_settings', JSON.stringify(this.settings)); } catch (e) { /* ignore */ }
      this.showSettings = false;
      toast('Settings saved', 'success');
    },

    /* ════════════ Manual Backup methods ════════════ */

    createBackup: async function () {
      if (this.backupCreating) return;
      this.backupCreating = true;
      try {
        var r = await api('/backup/create', { method: 'POST' });
        toast('Backup created: ' + r.filename + ' (' + Math.round(r.size_bytes / 1024) + ' KB)', 'success');
        await this.loadBackups();
      } catch (e) { toast('Backup failed: ' + e.message, 'error'); }
      finally { this.backupCreating = false; }
    },
  };
}

/* ── Register with Alpine ────────────────────────────────── */
/* Alpine is loaded synchronously above, so just register directly.
   Alpine auto-starts after DOMContentLoaded, picking up our component. */
if (typeof Alpine !== 'undefined') {
  Alpine.data('app', createApp);
}
