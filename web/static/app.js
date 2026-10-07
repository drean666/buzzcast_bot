/* buzzcast UI — vanilla JS, no dependencies, no external requests. */
'use strict';

const $  = (s, r = document) => r.querySelector(s);
const st_symbols = () => (S.state && S.state.symbols) || ['r', 'b', 'g'];
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const S = { state: null, config: null, ui: {
  stakes: { r: 0, b: 0, g: 0 }, follow: 'mine', lastBet: null, tab: 'overview',
  recordOnly: true, setupDone: false,
  sim: { source: 'fair', policy: 'bot', turns: 600, seed: 1 },
  auto: { source: 'biased', turns: 60, follow: 'bot' },
  busy: false,
} };

const COLORS = { r: '#ef4444', b: '#3b82f6', g: '#22c55e' };
const money = (v) => (v < 0 ? '-' : '') + '$' + Math.abs(Math.round(v)).toLocaleString();
const pct = (v, d = 1) => (v >= 0 ? '+' : '') + v.toFixed(d) + '%';
const cls = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : 'mut');

function toast(msg, isErr) {
  const el = document.createElement('div');
  el.className = 'toast' + (isErr ? ' err' : '');
  el.innerHTML = esc(msg);
  document.body.appendChild(el);
  setTimeout(() => el.remove(), isErr ? 6000 : 3200);
}

async function api(path, body) {
  const opt = body === undefined ? {} :
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const txt = await r.text();
  let data;
  try { data = txt ? JSON.parse(txt) : {}; } catch (e) { data = { ok: false, error: txt.slice(0, 300) }; }
  if (!r.ok || data.ok === false) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}

/* ---------------------------------------------------------------- charts */
function svgLine(series, opts) {
  const o = Object.assign({ w: 600, h: 160, fill: true, color: '#7c8aff',
                            dash: [], zero: null, pad: 6 }, opts || {});
  const all = series.filter(s => s.v.length);
  if (!all.length) return '<text x="10" y="20" fill="#6e7681" font-size="12">no data yet</text>';
  let lo = Infinity, hi = -Infinity;
  all.forEach(s => s.v.forEach(v => { lo = Math.min(lo, v); hi = Math.max(hi, v); }));
  if (o.zero !== null) { lo = Math.min(lo, o.zero); hi = Math.max(hi, o.zero); }
  if (hi === lo) { hi += 1; lo -= 1; }
  const span = hi - lo;
  const X = (i, n) => (n <= 1 ? 0 : (i / (n - 1)) * o.w);
  const Y = (v) => o.h - o.pad - ((v - lo) / span) * (o.h - 2 * o.pad);
  let out = '';
  all.forEach(s => {
    const d = s.v.map((v, i) => (i ? 'L' : 'M') + X(i, s.v.length).toFixed(1) + ' ' + Y(v).toFixed(1)).join(' ');
    if (o.fill && s.fill !== false) {
      out += `<path d="${d} L ${o.w} ${o.h} L 0 ${o.h} Z" fill="${s.color}" opacity="0.10"/>`;
    }
    out += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.6" `
         + `vector-effect="non-scaling-stroke" stroke-linejoin="round"/>`;
  });
  if (o.zero !== null && o.zero >= lo && o.zero <= hi) {
    out += `<line x1="0" y1="${Y(o.zero).toFixed(1)}" x2="${o.w}" y2="${Y(o.zero).toFixed(1)}" `
         + `stroke="#6e7681" stroke-width="1" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>`;
  }
  return out;
}
function spark(el, series, opts) {
  const node = typeof el === 'string' ? $(el) : el;
  if (!node) return;
  const o = Object.assign({ w: 600, h: 160 }, opts || {});
  node.setAttribute('viewBox', `0 0 ${o.w} ${o.h}`);
  node.setAttribute('preserveAspectRatio', 'none');
  node.innerHTML = svgLine(series, o);
}

/* ------------------------------------------------------------- rendering */
function colourOf(sym) { return (S.state && S.state.colors && S.state.colors[sym]) || COLORS[sym] || '#888'; }
function nameOf(sym) { return (S.state && S.state.names && S.state.names[sym]) || String(sym).toUpperCase(); }

function render() {
  const st = S.state;
  if (!st) return;
  const c = st.capital, pr = st.prediction;

  /* header */
  $('#capital').textContent = money(c.value);
  $('#capital').className = cls(c.net);
  $('#capital-sub').innerHTML = `start ${money(c.start)} · net <span class="${cls(c.net)}">${money(c.net)}</span>`
    + (c.deposits ? ` · deposits ${money(c.deposits)}` : '')
    + ` · ${c.turns} turns`;
  const ph = $('#phase');
  ph.textContent = st.phase === 'await_result' ? 'result pending' : 'place your bet';
  ph.className = 'pill' + (st.phase === 'await_result' ? '' : ' live');

  /* session selector */
  const sel = $('#session-select');
  sel.innerHTML = st.session.all.map(s =>
    `<option value="${esc(s.name)}"${s.active ? ' selected' : ''}>${esc(s.name)} · ${s.turns}t · ${money(s.capital)}</option>`).join('');

  /* prediction */
  $('#tier').textContent = pr.tier;
  $('#tier').className = 'badge ' + pr.tier;
  $('#probs').innerHTML = st.symbols.map(s => {
    const p = pr.probs[s];
    return `<div class="pbar${s === pr.top ? ' top' : ''}">
      <span class="lab" style="color:${colourOf(s)}">${esc(nameOf(s))}</span>
      <span class="track"><span class="fill" style="width:${(p * 100).toFixed(1)}%;background:${colourOf(s)}"></span></span>
      <span class="num">${(p * 100).toFixed(1)}%</span></div>`;
  }).join('');
  $('#pred-meta').innerHTML =
    `<span>${pr.n_obs} results learned</span><span>·</span>`
  + `<span>confidence <b>${pr.confidence.toFixed(1)}%</b> (gate ${pr.gate ? pr.gate.confidence.toFixed(0) : '—'}→38)</span><span>·</span>`
  + `<span>break-even ${pr.break_even_pct.toFixed(1)}%</span><span>·</span>`
  + `<span class="${cls(pr.roi_pct)}">paper trade ${pct(pr.roi_pct)} / unit, p=${pr.roi_p_value.toFixed(3)}</span>`
  + `<span>·</span><span class="${cls(pr.info_gain_bits)}">edge ${pr.info_gain_bits >= 0 ? '+' : ''}${pr.info_gain_bits.toFixed(4)} bits</span>`;

  $('#reasons').innerHTML =
    pr.reasons.map(r => `<li class="good">${esc(r)}</li>`).join('') +
    pr.blockers.map(b => `<li class="bad">${esc(b)}</li>`).join('');

  /* bot's proposed bet */
  const bb = pr.bet || {};
  const botParts = Object.keys(bb.stakes || {}).filter(k => bb.stakes[k] > 0)
    .map(k => `<b style="color:${colourOf(k)}">${Math.round(bb.stakes[k])} ${esc(nameOf(k))}</b>`).join(' + ');
  $('#bot-bet').innerHTML = bb.total
    ? `<div class="row between"><span>${bb.shape === 'split2' ? 'split' : 'single'}: ${botParts}</span>
        <span class="num">${money(bb.total)}</span></div>
       <div class="row between small"><span class="mut">expected value</span>
        <span class="num ${cls(bb.ev)}">${money(bb.ev)} (${pct(bb.ev_pct)})</span></div>
       <div class="row between small"><span class="mut">exposure of bankroll</span>
        <span class="num">${bb.exposure_pct.toFixed(1)}%</span></div>
       <div class="row between small"><span class="mut">Kelly fraction used</span>
        <span class="num">${(bb.kelly_fraction * 100).toFixed(1)}%</span></div>
       <div class="row" style="margin-top:8px"><button class="small" id="btn-copy-bot">copy this into my bet</button></div>`
    : `<span class="mut">${esc(bb.reason || 'no bet proposed')}</span>`;

  /* bet panel vs result panel */
  const pending = st.pending;
  $('#panel-bet').classList.toggle('hidden', !!pending);
  $('#panel-result').classList.toggle('hidden', !pending);
  $('#bust-warning').classList.toggle('hidden', !c.busted);
  if (pending) {
    const p = pending;
    $('#pending-summary').innerHTML =
      `locked in <b>${esc(p.shape)}</b> — ${Object.keys(p.played_bet).filter(k => p.played_bet[k] > 0)
        .map(k => `<b style="color:${colourOf(k)}">${Math.round(p.played_bet[k])} ${esc(nameOf(k))}</b>`).join(' + ') || 'nothing (pass)'}
       &nbsp;·&nbsp; at risk <b>${money(p.stake_total)}</b> of ${money(p.capital_before)}
       &nbsp;·&nbsp; following: ${esc(p.followed)}`;
  } else {
    renderStakes();
    renderPresets();
    renderPreview();
  }

  /* bankroll — meta.curve is a flat list of capital values, one per turn */
  const curve = (st.meta.curve || []).filter(v => typeof v === 'number');
  const capCurve = curve.length > 1 ? curve : [c.start, c.value];
  spark('#curve-cap', [{ v: capCurve, color: '#7c8aff' }], { zero: c.start, fill: true });
  const rk = st.meta.risk;
  $('#risk-kv').innerHTML = [
    ['peak', money(rk.peak)], ['max drawdown', money(rk.max_drawdown) + ' (' + rk.max_drawdown_pct.toFixed(1) + '%)'],
    ['return on start', pct(rk.return_on_start_pct)], ['turnover (stake ROI)', pct(rk.roi_pct)],
  ].map(([k, v]) => `<div>${k}</div><div class="num">${v}</div>`).join('');

  /* trust */
  const t = st.meta.trust, st2 = st.meta.streaks;
  $('#trust').innerHTML =
    `<div class="row between"><b>${esc(t.verdict)}</b>
       <span class="small mut">p(bot better) = ${t.p_bot_better.toFixed(3)}</span></div>
     <div class="small mut" style="margin:6px 0">${esc(t.why)}</div>
     <div class="grid2" style="margin:10px 0">
       <div class="stat"><div class="k">your hit rate</div><div class="v">${t.me_hit_rate_pct.toFixed(1)}%</div>
         <div class="tiny dim">${t.me_turns} picks · 95% CI ${t.me_ci[0].toFixed(0)}–${t.me_ci[1].toFixed(0)}%</div></div>
       <div class="stat"><div class="k">bot hit rate</div><div class="v">${t.bot_hit_rate_pct.toFixed(1)}%</div>
         <div class="tiny dim">${t.bot_turns} turns · 95% CI ${t.bot_ci[0].toFixed(0)}–${t.bot_ci[1].toFixed(0)}%</div></div>
     </div>
     <div class="kv small">
       <div>trust weight</div><div class="num">${(t.trust_weight * 100).toFixed(1)}%</div>
       <div>${esc(t.recommendation)}</div><div></div>
     </div>
     <div class="sep"></div>
     <div class="kv small">
       <div>if you had followed the bot</div><div class="num ${cls(st.meta.follow.bot.pnl)}">${money(st.meta.follow.bot.pnl)} on ${money(st.meta.follow.bot.stake)}</div>
       <div>if you had followed yourself</div><div class="num ${cls(st.meta.follow.mine.pnl)}">${money(st.meta.follow.mine.pnl)} on ${money(st.meta.follow.mine.stake)}</div>
       <div>current streak</div><div class="num">${st2.current} (best ${st2.best}, worst ${st2.worst})</div>
       <div>cost of tilt</div><div class="num ${cls(-st.meta.tilt.cost_of_tilt)}">${money(-st.meta.tilt.cost_of_tilt)}</div>
     </div>`;

  /* ---- overview */
  const b = st.brain;
  $('#overview-stats').innerHTML = [
    ['results learned', b.n_obs],
    ['walk-forward hit rate', b.oos_hit_rate_pct.toFixed(1) + '%'],
    ['chance', b.chance_pct.toFixed(1) + '%'],
    ['contexts tracked', b.contexts_learned],
    ['log loss', b.log_loss_bits.toFixed(3) + ' bits'],
    ['paper trade', pct(b.paper_roi_pct)],
    ['committed turns', b.committed_steps + ' / ' + b.n_obs],
    ['hedged turns', (b.provisional_steps || 0) + ' / ' + b.n_obs],
  ].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${esc(String(v))}</div></div>`).join('');

  spark('#curve-acc', [{ v: st.curves.accuracy || [], color: '#7c8aff' }], { zero: 33.333 });
  spark('#curve-ig', [{ v: st.curves.info_gain || [], color: '#22c55e' }], { zero: 0 });

  $('#weights').innerHTML = Object.keys(b.order_weights).sort((x, y) => x - y).map(k => {
    const w = b.order_weights[k], label = k === '0' ? 'base rate' : k + '-step context';
    return `<div class="pbar"><span class="lab small">${label}</span>
      <span class="track"><span class="fill" style="width:${(w * 100).toFixed(1)}%;background:#7c8aff"></span></span>
      <span class="num small">${(w * 100).toFixed(0)}%</span></div>`;
  }).join('');
  $('#latest-info').innerHTML =
    `This is the hedge learning live: weights shift toward whichever context depth is
     predicting best out-of-sample. Base rate ${b.chance_pct.toFixed(1)}% is the floor —
     anything below the dashed line is worse than guessing.`;
  $('#results-tail').innerHTML = st.results_tail.map(s => {
    const edge = (s === st.prediction.top) ? ' outline' : '';
    return `<span class="chip ${esc(s)}">${esc(nameOf(s)[0])}</span>`;
  }).join('');

  /* ---- shape lab */
  if (st.shape_lab) {
    $('#lab-table').innerHTML =
      `<thead><tr><th>bet</th><th>stake</th><th>EV</th><th>EV %</th>
        <th>chance covered</th><th>if covered</th><th>if not</th>
        <th>needs cover</th><th>streak to bust</th></tr></thead><tbody>`
      + st.shape_lab.map(r => `<tr${r.label.startsWith('BOT') ? ' style="background:rgba(124,138,255,.07)"' : ''}>
        <td>${esc(r.label)}</td><td class="num">${r.total ? money(r.total) : '—'}</td>
        <td class="num ${cls(r.ev)}">${r.ev ? money(r.ev) : '—'}</td>
        <td class="num ${cls(r.ev_pct)}">${r.ev_pct ? pct(r.ev_pct) : '—'}</td>
        <td class="num">${r.win_rate_pct ? r.win_rate_pct.toFixed(1) + '%' : '—'}</td>
        <td class="num pos">${r.best_net ? money(r.best_net) : '—'}</td>
        <td class="num neg">${r.worst_net ? money(r.worst_net) : '—'}</td>
        <td class="num${r.cover_break_even_pct > r.win_rate_pct ? ' neg' : ''}">${r.cover_break_even_pct != null ? r.cover_break_even_pct.toFixed(1) + '%' : '—'}</td>
        <td class="num tiny dim">${r.consecutive_losses_to_bust != null ? r.consecutive_losses_to_bust + ' losses' : '—'}</td>
      </tr>`).join('') + '</tbody>';
  }
  if (st.trend) renderTrends();
  renderTable();   /* the game screen draws from the same state */
  if (st.patterns) { $('#patterns-table').innerHTML = patternTable(st.patterns); }
  if (st.patterns3) { $('#patterns3-table').innerHTML = patternTable(st.patterns3); }

  /* ---- backtest */
  if (st.backtest) {
    const bt = st.backtest;
    $('#backtest-cards').innerHTML = [['The bot', bt.bot], ['You', bt.you]].map(([ttl, d]) => `
      <div><div class="stat" style="margin-bottom:8px">
        <div class="k">${ttl} — final capital</div>
        <div class="v ${cls(d.final_capital - bt.bot.curve[0])}">${money(d.final_capital)}</div>
        <div class="tiny dim">${d.bets} bets · hit ${d.win_rate_pct.toFixed(1)}% · max DD ${d.max_drawdown_pct.toFixed(1)}%</div>
      </div>
      <div class="kv small">
        <div>profit</div><div class="num ${cls(d.pnl)}">${money(d.pnl)}</div>
        <div>staked</div><div class="num">${d.staked ? money(d.staked) : '—'}</div>
        <div>return on stake</div><div class="num ${cls(d.roi_pct)}">${pct(d.roi_pct)}</div>
      </div></div>`).join('');
    if (bt.bot.curve && bt.bot.curve.length) {
      spark('#curve-bt', [
        { v: bt.bot.curve, color: '#22c55e' },
        { v: bt.you.curve, color: '#7c8aff' }], { zero: null });
    }
  }

  /* ---- history */
  $('#history-table').innerHTML =
    `<thead><tr><th>#</th><th>time</th><th>bot pick</th><th>your bet</th><th>played</th>
      <th>stake</th><th>result</th><th>P/L</th><th>capital</th><th>hit</th><th></th></tr></thead><tbody>`
    + st.recent_turns.map(t => `<tr>
        <td class="num">${t.n}${t.edited ? ' <span class="tiny mid" title="edited">✎</span>' : ''}</td>
        <td class="tiny dim">${esc((t.time || '').replace('T', ' ').slice(5, 16))}</td>
        <td><span class="chip ${esc(t.bot_top || '')}">${esc((nameOf(t.bot_top) || '—')[0])}</span>
            <span class="tiny dim">${t.bot_conf != null ? t.bot_conf.toFixed(0) + '%' : ''}${t.bot_committed ? ' ●' : ''}</span></td>
        <td>${betText(t.my_pick ? { [t.my_pick]: 1 } : null, t.played_bet, true)}</td>
        <td>${betText(null, t.played_bet)}</td>
        <td class="num">${t.stake ? Math.round(t.stake) : '—'}</td>
        <td><span class="chip ${esc(t.result || '')}">${esc(nameOf(t.result))}</span></td>
        <td class="num ${cls(t.pnl)}">${money(t.pnl)}</td>
        <td class="num dim">${money(t.capital_after)}</td>
        <td class="num">${t.hit ? '✓' : t.stake ? '✕' : '·'}</td>
        <td><button class="ghost tiny" data-fix="${t.n}" title="correct the result">fix</button></td>
      </tr>`).join('') + '</tbody>';

  /* ---- settings */
  $('#sessions-table').innerHTML =
    `<thead><tr><th>session</th><th>turns</th><th>capital</th><th>results</th><th></th></tr></thead><tbody>`
    + st.session.all.map(s => `<tr>
        <td>${esc(s.name)}${s.active ? ' <span class="tiny mut">(active)</span>' : ''}</td>
        <td class="num">${s.turns}</td><td class="num">${money(s.capital)}</td>
        <td class="num">${s.results}</td>
        <td>${s.active ? '' : `<button class="ghost tiny" data-switch="${esc(s.name)}">switch</button>`}
            ${s.active ? `<button class="ghost tiny" data-del="${esc(s.name)}">delete</button>` : ''}</td>
      </tr>`).join('') + '</tbody>';
  renderConfig();
}


/* ==================================================================
   TABLE VIEW — the game screen.

   Three giant colour tiles. What a tap does depends on the phase:
     before the round  -> stake that colour (tap again to take it off)
     after the round   -> record the colour that came up
   Same two actions as the dashboard, with targets you cannot miss.
   ================================================================== */

const MODE_KEY = 'buzzcast.view';
const WIRING = { failed: [] };   // anything that failed to start, named

function defaultStake() {
  const c = (S.config && S.config.capital) || {};
  return Number(c.default_split_stake) || 120;
}

/* hex -> rgba, so each tile can tint itself without color-mix() */
function soft(hex, a) {
  let h = String(hex || '#888').replace('#', '');
  if (h.length === 3) h = h.split('').map(x => x + x).join('');
  const n = parseInt(h, 16);
  if (isNaN(n)) return 'rgba(136,136,136,' + a + ')';
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

/* how many turns in a row that colour is currently on */
function runOf(sym) {
  const tail = (S.state && S.state.results_tail) || [];
  let n = 0;
  for (let i = tail.length - 1; i >= 0 && tail[i] === sym; i--) n++;
  return n;
}

function setMode(m) {
  document.body.classList.toggle('table-mode', m === 'table');
  try { localStorage.setItem(MODE_KEY, m); } catch (e) {}
  const b = $('#btn-mode');
  if (b) b.textContent = m === 'table' ? 'Full dashboard →' : '◀ Table view';
  renderTable();
}

function tapColour(sym) {
  if (!S.state || S.ui.busy) return;
  // In record-only mode a tile means exactly one thing, whatever phase the
  // round is in. That is the whole point of the mode: no way to stake by
  // accident while you are still collecting evidence.
  if (S.ui.recordOnly || S.state.phase === 'await_result') { recordResult(sym); return; }
  S.ui.stakes[sym] = (S.ui.stakes[sym] || 0) > 0 ? 0 : defaultStake();   // toggle
  renderTable();
}

function setRecordOnly(on) {
  S.ui.recordOnly = !!on;
  try { localStorage.setItem('buzzcast.recordOnly', on ? '1' : '0'); } catch (e) {}
  renderTable();
  toast(on ? 'record only — tap the colour that came up, nothing is staked'
           : 'staking on — tap a colour before the round to put your usual on it');
}

function nudgeColour(sym, delta) {
  if (!S.state || S.ui.busy || S.state.phase === 'await_result') return;
  const c = S.state.capital || {};
  const step = c.stake_step || 10;
  const cap = c.max_stake_per_turn || 1e9;
  S.ui.stakes[sym] = Math.max(0, Math.min((S.ui.stakes[sym] || 0) + delta * step, cap));
  renderTable();
}


/* ==================================================================
   THE READINESS LADDER

   Answers the only question that matters before the bot has proven itself:
   "should I be staking yet?" The answer is no until the bot's own PAPER TRADE
   is significant - and passing every turn still records every result AND the
   bot's own opinion, so the evidence builds at no financial risk.

   The stage is derived from what the engine already reports, so the screen can
   never disagree with the gate.
   ================================================================== */

function readiness(st) {
  const c = st.capital || {};
  const pr = st.prediction || {};
  const br = st.brain || {};
  const turns = c.turns || 0;
  const nObs = br.n_obs || pr.n_obs || 0;

  /* the engine's own warm-up figure, read out of its own blocker text so the
     two can never drift apart */
  let warm = 15;
  (pr.blockers || []).concat(pr.reasons || []).forEach(t => {
    const m = /(\d+)\s*\/\s*(\d+)\s*results seen/i.exec(t) || /(\d+)\s*\/\s*(\d+)/.exec(t);
    if (m) warm = Math.max(warm, Number(m[2]));
  });

  const paper = Number(br.paper_roi_pct || 0);
  const paperP = Number(br.paper_roi_p_value || 1);
  const provisional = Number(br.provisional_steps || 0);
  const paperN = Number(br.paper_roi_n || 0);
  const readPct = Number(br.read_hit_rate_pct || 0);
  const readN = Number(br.read_window || 0);
  const chancePct = Number(br.chance_pct || 33.33);

  if (nObs < warm) {
    return {
      stage: 1, name: 'warming up', cls: '',
      what: 'Record only. The bot cannot read anything yet.',
      why: `${nObs} of ${warm} results seen before it is allowed an opinion.`,
      paper: null, read: null, track: [nObs / Math.max(warm, 1), 0, 0, 0],
    };
  }
  if (pr.tier === 'commit') {
    return {
      stage: 4, name: 'the bot has a proven edge', cls: 'done',
      what: 'This is the signal you were waiting for.',
      why: `its paper trade is ${pct(paper)} and statistically significant ` +
           `(p=${paperP < 0.001 ? '<0.001' : paperP.toFixed(3)}).`,
      paper: { v: paper, p: paperP, n: paperN },
      read: { v: readPct, n: readN, chance: chancePct },
      track: [1, 1, 1, 1],
    };
  }
  if (pr.tier === 'provisional') {
    return {
      stage: 3, name: 'close, not proven', cls: 'mid',
      what: 'The bot is staking its own money at reduced size. Keep recording.',
      why: 'its paper trade is positive but has not cleared the significance bar.',
      paper: { v: paper, p: paperP, n: paperN },
      read: { v: readPct, n: readN, chance: chancePct },
      track: [1, 1, 1, 0.5],
    };
  }
  return {
    stage: 2, name: 'earning its trust', cls: '',
    what: 'Record only. Every round is evidence, and passing costs nothing.',
    why: 'the bot has opinions but nothing proven yet. Measured: a real edge ' +
         'first commits around turn 100-170, and by turn 500 if nothing has ' +
         'committed the game is probably fair.',
    paper: { v: paper, p: paperP, n: paperN },
    read: { v: readPct, n: readN, chance: chancePct },
    track: [1, 0.35, 0, 0],
  };
}

function renderReadiness(st) {
  const host = $('#tv-stage');
  if (!host) return;
  const r = readiness(st);
  // Its read, measured against what actually came up. On a fair game this
  // sits at chance forever, so watching it is how you find out whether there is
  // anything to predict at all - before you risk a penny.
  const read = r.read && r.read.n >= 10
    ? `<div class="paper">bot's read, last ${r.read.n} turns
         <b class="${r.read.v > r.read.chance + 3 ? 'pos' : 'mut'}">${r.read.v.toFixed(0)}%</b> right
         <div class="tiny dim">chance is ${r.read.chance.toFixed(0)}%${r.read.v > r.read.chance + 3 ? ' — better than chance' : ' — no better than chance yet'}</div>
       </div>`
    : `<div class="paper tiny dim">the bot's read<br>starts at 15 results</div>`;
  const paper = r.paper && r.paper.n
    ? `<div class="paper">bot's paper trade
         <b class="${cls(r.paper.v)}">${pct(r.paper.v)}</b> over ${r.paper.n} turns
         <div class="tiny dim">p = ${r.paper.p < 0.001 ? '<0.001' : r.paper.p.toFixed(3)}${r.paper.p > 0.0167 ? ' — not proven' : ' — significant'}</div>
       </div>`
    : `<div class="paper tiny dim">the bot's paper trade<br>builds while you record</div>`;
  host.className = 'tv-stage ' + r.cls;
  host.innerHTML = `
    <div style="min-width:200px">
      <div class="step">stage ${r.stage} of 4 · ${esc(r.name)}</div>
      <div class="tv-track">${r.track.map(t =>
        `<i class="${t >= 1 ? 'on' : ''}" style="${t > 0 && t < 1 ? 'background:linear-gradient(90deg,var(--acc) ' + Math.round(t * 100) + '%,#232b38 0)' : ''}"></i>`).join('')}</div>
    </div>
    <div>
      <div class="what">${esc(r.what)}</div>
      <div class="why">${esc(r.why)}</div>
    </div>
    ${read}
    ${paper}`;
}

function renderTable() {
  const st = S.state;
  if (!st || !$('#tv-tiles')) return;
  const res = st.phase === 'await_result';
  const c = st.capital || {};
  const pr = st.prediction || {};
  const bb = pr.bet || {};
  const pend = st.pending || {};

  /* --- the two-number setup card, only while nothing has been played --- */
  const fresh = (!c.turns && !S.ui.setupDone) || !!S.ui.forceSetup;
  $('#tv-setup').classList.toggle('hidden', !fresh);
  const note = $('#tv-setup-note');
  if (note) note.innerHTML = c.turns
    ? `you already have ${c.turns} recorded turns — starting over makes a
       <b>new</b> session and leaves them untouched`
    : '';
  if (fresh && !$('#tv-setup').dataset.seeded) {
    $('#tv-setup').dataset.seeded = '1';
    $('#tv-bankroll').value = Math.round(c.start || 1000);
    $('#tv-stake').value = Math.round(defaultStake());
  }

  renderReadiness(st);

  /* --- the bot's line, small and out of the way --- */
  const top = pr.top || st_symbols()[0];
  const botBits = Object.keys(bb.stakes || {}).filter(k => bb.stakes[k] > 0)
    .map(k => `<b style="color:${colourOf(k)}">${Math.round(bb.stakes[k])} ${esc(nameOf(k))}</b>`).join(' + ');
  const line = bb.total > 0
    ? `bot would play ${botBits} — ${money(bb.total)}`
    : `bot reads <b style="color:${colourOf(top)}">${esc(nameOf(top))}</b> ` +
      `${Math.round(pr.confidence || 0)}%, then passes on purpose`;
  $('#tv-bot').innerHTML = line;
  if (S.ui.recordOnly) {
    $('#tv-hint').innerHTML = `<b style="color:var(--acc)">▼ tap the colour that came up</b>`;
  } else {
    $('#tv-hint').innerHTML = res
      ? `<b style="color:var(--acc)">▼ tap the colour that came up</b>`
      : `tap a colour to stake your usual &middot; tap it again to take it off`;
  }

  /* --- the three tiles --- */
  const total = st_symbols().reduce((a, s) => a + (S.ui.stakes[s] || 0), 0);
  $('#tv-tiles').innerHTML = st_symbols().map(sym => {
    const col = colourOf(sym);
    const stake = S.ui.stakes[sym] || 0;
    const mined = (pend.played_bet || {})[sym] || 0;
    const pay = (st.payouts && st.payouts[sym]) || 3;
    const style = `--c:${col};--cs:${soft(col, .16)}`;
    const pend_has_this = (pend.played_bet || {})[sym] > 0;

    if (S.ui.recordOnly) {
      const r = runOf(sym);
      return `<div class="tv-tile armed${pend_has_this ? ' on' : ''}" style="${style}" data-rec="${sym}">
          <span class="tv-tapme">record</span>
          <span class="tv-name">${esc(nameOf(sym))}</span>
          <span class="tv-pay ${mined > 0 ? 'pos' : 'mut'}">${mined > 0 ? '+' + Math.round(mined * pay - (pend.stake_total || 0)) : 'record'}</span>
          <span class="tv-sub">${r >= 2 ? 'on a run of ' + r : 'tap when it lands'}</span>
        </div>`;
    }
    if (res) {
      /* after the round: this tile RECORDS. Show what the round is worth. */
      const net = Math.round(mined * pay - (pend.stake_total || 0));
      const worth = (pend.stake_total || 0) > 0
        ? `<span class="tv-pay ${cls(net)}">${net > 0 ? '+' : ''}${Math.round(net)}</span>
           <span class="tv-sub">if ${esc(nameOf(sym).toLowerCase())} comes up</span>`
        : `<span class="tv-pay mut">record</span>
           <span class="tv-sub">nothing staked this round</span>`;
      return `<div class="tv-tile armed${mined > 0 ? ' on' : ''}" style="${style}" data-rec="${sym}">
          <span class="tv-tapme">tap when it lands</span>
          <span class="tv-name">${esc(nameOf(sym))}</span>
          ${worth}
        </div>`;
    }

    /* before the round: this tile STAKES. */
    const r = runOf(sym);
    const bits = [];
    if (stake > 0) bits.push(`pays ${Math.round(stake * pay - stake)} if it wins`);
    if (r >= 2) bits.push(`on a run of ${r}`);
    return `<div class="tv-tile${stake > 0 ? ' on' : ''}" style="${style}" data-tap="${sym}">
        <span class="tv-name">${esc(nameOf(sym))}</span>
        <span class="tv-stake num">${stake > 0 ? Math.round(stake) : '—'}</span>
        <span class="tv-sub">${bits.join(' · ') || 'tap to stake'}</span>
        <span class="tv-chip">
          <button data-nudge="${sym}:-1" title="less">−</button>
          <button data-nudge="${sym}:1" title="more">+</button>
        </span>
      </div>`;
  }).join('');

  const fr = $('#tv-firstrun');
  if (fr) fr.classList.toggle('hidden', (c.turns || 0) > 0);

  /* --- action row, one big button each --- */
  const minS = c.min_stake || 1;
  if (S.ui.recordOnly) {
    $('#tv-actions').innerHTML = `
      <button id="tv-record-toggle" class="ghost">Recording only — nothing is staked
        <span class="tiny dim">(press T to start staking)</span></button>
      <button id="tv-undo" class="ghost">Undo the last recorded turn</button>`;
  } else if (res) {
    $('#tv-actions').innerHTML = `
      <button id="tv-cancel" class="ghost">Cancel this bet <span class="tiny dim">(esc — costs nothing)</span></button>
      <button id="tv-undo" class="ghost">Undo the last recorded turn</button>`;
  } else {
    const ok = total >= minS;
    $('#tv-actions').innerHTML = `
      <button id="tv-lock" class="primary" ${ok ? '' : 'disabled'}>
        ${total > 0 ? `Lock in ${money(total)}` : 'Lock in'}</button>
      <button id="tv-pass" class="ghost">Pass <span class="tiny dim">(p)</span></button>`;
  }

  /* --- the recent-results strip: the game's own ticker --- */
  const tail = (st.results_tail || []).slice(-16);
  const last = (st.recent_turns || [])[0];
  $('#tv-strip').innerHTML =
    `<span class="small mut" style="margin-right:6px">last ${tail.length}</span>` +
    tail.map(sym =>
      `<span class="tv-dot" style="background:${colourOf(sym)}">${esc(nameOf(sym)[0] || '?')}</span>`
    ).join('') +
    (last ? `<span class="small ${cls(last.pnl)}" style="margin-left:10px">
        turn ${last.n}: ${money(last.pnl)}</span>` : '');

  /* --- wire the taps (fresh elements every render) --- */
  $$('[data-tap]').forEach(el => el.onclick = () => tapColour(el.dataset.tap));
  $$('[data-rec]').forEach(el => el.onclick = () => recordResult(el.dataset.rec));
  $$('[data-nudge]').forEach(el => {
    el.onclick = (ev) => {
      ev.stopPropagation();
      const [sym, d] = el.dataset.nudge.split(':');
      nudgeColour(sym, Number(d));
    };
  });
  const rt = $('#tv-record-toggle');
  if (rt) rt.onclick = () => setRecordOnly(false);
  const lock = $('#tv-lock');
  if (lock) lock.onclick = () => lockBet();
  const pass = $('#tv-pass');
  if (pass) pass.onclick = () => act(async () => {
    await api('/api/pass', {}); await refresh();
  }, 'passed — the result still teaches the model');
  const undo = $('#tv-undo');
  if (undo) undo.onclick = () => act(async () => {
    await api('/api/undo', {}); await refresh();
  }, 'last turn undone');
  const cancel = $('#tv-cancel');
  if (cancel) cancel.onclick = () => act(async () => {
    await api('/api/cancel', {}); await refresh();
  }, 'bet cancelled — nothing lost');
}

function wireTable() {
  const b = $('#btn-mode');
  if (b) b.onclick = () => setMode(document.body.classList.contains('table-mode') ? 'dash' : 'table');

  const re = $('#tv-reopen');
  if (re) re.onclick = () => { S.ui.forceSetup = true; renderTable(); };

  const start = $('#tv-start');
  if (start) start.onclick = () => act(async () => {
    const bank = Number($('#tv-bankroll').value);
    const stake = Number($('#tv-stake').value);
    if (!(bank > 0) || !(stake > 0)) { toast('both numbers need to be above zero', true); return; }
    if (stake * 2 > bank) { toast('two colours at ' + stake + ' is more than your bankroll', true); return; }
    await api('/api/config', { patch: { capital: {
      starting: bank,
      default_split_stake: stake,
      min_stake: Math.min(10, stake),
      /* room for the two-colour bet, and never more than a fifth of the roll */
      max_stake_per_turn: Math.max(stake * 2, Math.round(bank * 0.2)),
    } } });
    await api('/api/session', { action: 'new', name: 'real', starting: bank });
    await refresh();
    $('#tv-setup').dataset.seeded = '';
    S.ui.forceSetup = false;
    S.ui.setupDone = true;   // do not ask again until they ask to change it
    toast('you are set up — tap a colour to place your first bet');
  });
}

function betText(_x, played, compact) {
  if (!played) return '<span class="dim">—</span>';
  const parts = Object.keys(played).filter(k => played[k] > 0)
    .map(k => `<b style="color:${colourOf(k)}">${Math.round(played[k])}</b>`);
  if (!parts.length) return '<span class="dim">pass</span>';
  return compact ? parts.join('/') : parts.join(' + ');
}

function patternTable(rows) {
  if (!rows.length) return '<tbody><tr><td class="mut">not enough repeated contexts yet</td></tr></tbody>';
  return `<thead><tr><th>context</th><th>n</th><th>followed by</th><th>share</th>
    <th>base rate</th><th>lift</th><th>p</th><th></th></tr></thead><tbody>`
    + rows.map(r => `<tr>
      <td><b class="num">${esc(r.label)}</b></td>
      <td class="num">${r.n}</td>
      <td><span class="chip ${esc(r.top)}">${esc(nameOf(r.top))}</span></td>
      <td class="num">${(r.share * 100).toFixed(1)}%</td>
      <td class="num dim">${(r.base * 100).toFixed(1)}%</td>
      <td class="num ${r.lift > 1 ? 'pos' : 'neg'}">${r.lift.toFixed(2)}×</td>
      <td class="num">${r.p_value.toFixed(4)}</td>
      <td>${r.significant ? '<span class="tiny pos">significant</span>' : '<span class="tiny dim">noise</span>'}</td>
    </tr>`).join('') + '</tbody>';
}

/* ------------------------------------------------------------ bet inputs */
function renderStakes() {
  const st = S.state;
  $('#stakes').innerHTML = st.symbols.map(s => `
    <div class="stake">
      <span class="chip ${s}">${esc(nameOf(s))}</span>
      <input type="number" min="0" step="${st.capital.stake_step}" data-stake="${s}"
             value="${Math.round(S.ui.stakes[s] || 0)}">
      <span class="tiny dim">×${st.payouts[s]} →${Math.round((S.ui.stakes[s] || 0) * st.payouts[s])}</span>
    </div>`).join('');
  $$('[data-stake]').forEach(inp => inp.oninput = () => {
    S.ui.stakes[inp.dataset.stake] = Math.max(0, Number(inp.value) || 0);
    renderPreview();
  });
  $$('[data-follow]').forEach(btn => {
    btn.classList.toggle('on', btn.dataset.follow === S.ui.follow);
    btn.onclick = () => { S.ui.follow = btn.dataset.follow; renderStakes();
      const id = S.ui.follow === 'bot' ? 'btn-bet' : null;
      $('#btn-bet').textContent = S.ui.follow === 'bot' ? "Follow the bot"
        : S.ui.follow === 'blend' ? "Lock in the 50/50 blend" : "Lock in the bet"; };
  });
  $('#btn-bet').textContent = S.ui.follow === 'bot' ? "Follow the bot"
    : S.ui.follow === 'blend' ? "Lock in the 50/50 blend" : "Lock in the bet";
}

function renderPresets() {
  const st = S.state;
  $('#presets').innerHTML = (st.presets || []).map((p, i) =>
    `<button class="small" data-preset="${i}">${esc(p.label)}</button>`).join('');
  $$('[data-preset]').forEach(b => b.onclick = () => {
    const p = st.presets[Number(b.dataset.preset)];
    st.symbols.forEach(s => S.ui.stakes[s] = p.stakes[s] || 0);
    renderStakes(); renderPreview();
  });
}

function renderPreview() {
  const st = S.state, pr = st.prediction, P = st.payouts;
  const stk = S.ui.stakes;
  const total = st.symbols.reduce((a, s) => a + (stk[s] || 0), 0);
  if (!total) { $('#bet-preview').innerHTML = '<span class="mut">nothing staked — this would be a pass (the result is still recorded and learned from).</span>'; return; }
  let ev = 0, best = -Infinity, worst = Infinity, covers = 0, covered = [];
  st.symbols.forEach(s => {
    const ret = P[s] * (stk[s] || 0), net = ret - total;
    ev += pr.probs[s] * net;
    best = Math.max(best, net); worst = Math.min(worst, net);
    if (net > 0) { covers++; covered.push(s); }
  });
  const cap = st.capital.value, exp = 100 * total / Math.max(cap, 1);
  const be = total ? (total / (P[st.symbols[0]])) : 0;
  const winProb = covered.reduce((a, s) => a + pr.probs[s], 0);
  $('#bet-preview').innerHTML = `
    <div class="kv small">
      <div>total at risk</div><div class="num">${money(total)} <span class="${exp > 20 ? 'mid' : 'dim'}">(${exp.toFixed(1)}% of bankroll)</span></div>
      <div>expected value</div><div class="num ${cls(ev)}">${money(ev)} <span class="dim">(${pct(100 * ev / total)})</span></div>
      <div>you win if</div><div class="num">${covered.length ? covered.map(s => esc(nameOf(s))).join(' or ') + ' <span class="dim">(' + (100 * winProb).toFixed(1) + '% likely)</span>' : '<span class="neg">nothing covers</span>'}</div>
      <div>best case</div><div class="num pos">${money(best)}</div>
      <div>worst case</div><div class="num neg">${money(worst)}</div>
    </div>
    ${exp > 20 ? '<div class="callout" style="margin-top:8px">Above the ' + '20% exposure guideline the bot uses.</div>' : ''}`;
}

/* -------------------------------------------------------------- actions */
/* Record a result immediately, the same as clicking the R/B/G button. */
async function recordResult(sym) {
  await act(async () => {
    // If nothing is on the table, sit the turn out first - so recording is ONE
    // action for the user. Two requests, but the engine still refuses to
    // resolve twice, which is what stops a double-tap logging a result twice.
    if (S.state && S.state.phase !== 'await_result') await api('/api/pass', {});
    await api('/api/resolve', { result: sym });
    await refresh();
    const t = S.state.recent_turns[0];
    if (t) toast(`settled ${nameOf(t.result)} — ${money(t.pnl)}`);
  });
}

/* Apply a preset by index, exactly as clicking it does. */
function applyPreset(i) {
  const p = (S.state.presets || [])[i];
  if (!p) return;
  st_symbols().forEach(s => S.ui.stakes[s] = p.stakes[s] || 0);
  renderStakes(); renderPreview();
}

/* One keystroke to put the previous bet on again - the fastest way to play
   a consistent strategy, which is what the trend bet is. */
async function lockBet(followOverride) {
  const follow = followOverride || S.ui.follow;
  await act(async () => {
    const snap = Object.assign({}, S.ui.stakes);
    const d = await api('/api/bet', { stakes: snap, follow });
    S.ui.lastBet = { stakes: snap, follow };
    S.state = d.state; S.state.pending = d.pending;
    const full = await api('/api/state'); S.state = full;
    render(); toast('bet locked in');
  });
}

async function repeatLastBet() {
  if (!S.ui.lastBet) { toast('no previous bet to repeat yet'); return; }
  S.ui.stakes = Object.assign({}, S.ui.lastBet.stakes);
  S.ui.follow = S.ui.lastBet.follow;
  await lockBet();
}

async function act(fn, okMsg) {
  if (S.ui.busy) return;
  S.ui.busy = true;
  try { await fn(); if (okMsg) toast(okMsg); }
  catch (e) { toast(e.message, true); }
  finally { S.ui.busy = false; }
}

async function refresh(include) {
  const q = include ? '?include=' + include.join(',') : '';
  const st = await api('/api/state' + q);
  S.state = st;
  render();
}

function wireKeys() {
  document.addEventListener('keydown', (ev) => {
    const el = document.activeElement || {};
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName || '');
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const k = (ev.key || '').toLowerCase();

    if (typing) {
      // Enter inside a stake box locks the bet in; that is the natural ending
      if (ev.key === 'Enter' && $('#panel-bet') && !$('#panel-bet').classList.contains('hidden')) {
        el.blur(); lockBet(); ev.preventDefault();
      }
      return;
    }
    if (S.ui.busy) return;

    const awaitingResult = S.state && S.state.phase === 'await_result';

    // --- THE key: one tap records the real result, in any phase.
    // Recording no longer requires passing first, so this is the whole loop.
    if ('rbg'.includes(k) && k.length === 1) { recordResult(k); ev.preventDefault(); return; }

    if (k === 't') { setRecordOnly(!S.ui.recordOnly); ev.preventDefault(); return; }

    if (awaitingResult) {
      if (k === 'escape') {
        act(async () => { await api('/api/cancel', {}); await refresh(); }, 'bet cancelled');
        ev.preventDefault(); return;
      }
      return;
    }

    // --- choosing and placing a bet (only when staking is switched on)
    if (S.ui.recordOnly) {
      if (k === 'u') { act(async () => { await api('/api/undo', {}); await refresh(); }, 'last turn undone'); ev.preventDefault(); }
      return;
    }
    if (k >= '1' && k <= '9') { applyPreset(Number(k) - 1); ev.preventDefault(); return; }
    if (ev.key === 'Enter') { lockBet(); ev.preventDefault(); return; }
    if (k === 'p') {
      act(async () => { await api('/api/pass', {}); await refresh(); },
          'passed — the result still teaches the model');
      ev.preventDefault(); return;
    }
    if (k === ' ' || k === 'a') { repeatLastBet(); ev.preventDefault(); return; }
  });
}

function wire() {
  $$('#tabs .tab').forEach(t => t.onclick = () => {
    $$('#tabs .tab').forEach(x => x.classList.toggle('on', x === t));
    $$('.tab-panel').forEach(p => p.classList.add('hidden'));
    $('#tab-' + t.dataset.tab).classList.remove('hidden');
    S.ui.tab = t.dataset.tab;
  });

  $('#btn-refresh').onclick = () => act(refresh);
  const rep = $('#btn-repeat');
  if (rep) rep.onclick = () => repeatLastBet();
  $('#btn-bet').onclick = () => act(async () => {
    const snap = Object.assign({}, S.ui.stakes);
    const d = await api('/api/bet', { stakes: snap, follow: S.ui.follow });
    S.ui.lastBet = { stakes: snap, follow: S.ui.follow };
    S.state = d.state; S.state.pending = d.pending;
    const full = await api('/api/state'); S.state = full; render();
  }, 'bet locked in — enter the real result when it lands');
  $('#btn-pass').onclick = () => act(async () => {
    await api('/api/pass', {}); await refresh();
  }, 'turn passed — the result still teaches the model');

  $$('[data-result]').forEach(b => b.onclick = () => act(async () => {
    await api('/api/resolve', { result: b.dataset.result });
    await refresh();
    const t = S.state.recent_turns[0];
    if (t) toast(`settled ${nameOf(t.result)} — ${money(t.pnl)}`);
  }));

  $('#btn-cancel-bet').onclick = () => act(async () => {
    await api('/api/cancel', {}); await refresh();
  }, 'bet cancelled — nothing was staked');

  const stakeTrend = $('#btn-stake-trend');
  if (stakeTrend) stakeTrend.onclick = () => {
    const pair = S.state.trend.current.pair || [];
    st_symbols().forEach(s => S.ui.stakes[s] = 0);
    pair.forEach(s => S.ui.stakes[s] = Number(S.state.capital.default_split_stake) || 120);
    S.ui.follow = 'mine';
    renderStakes(); renderPreview();
    toast('staked both trend colours — enter the result when it lands');
  };
  // This button is only rendered when the bot actually proposes a bet, so it is
  // absent on every new session. Without the guard the assignment below threw,
  // and because it sits inside wire() the exception aborted every wiring step
  // after it - including wireTable() - so the "Table view" button silently did
  // nothing while the page blamed the engine.
  const copyBot = $('#btn-copy-bot');
  if (copyBot) copyBot.onclick = () => {
    const bb = S.state.prediction.bet;
    Object.keys(bb.stakes).forEach(s => S.ui.stakes[s] = bb.stakes[s]);
    renderStakes(); renderPreview(); toast('copied the bot\'s stakes');
  };

  $$('[data-fix]').forEach(b => b.onclick = () => {
    const n = Number(b.dataset.fix);
    const v = prompt('Correct result for turn ' + n + ' (r/b/g):');
    if (!v || !'rbg'.includes(v.toLowerCase()[0])) return;
    act(async () => { await api('/api/edit', { turn: n, result: v.toLowerCase()[0] }); await refresh(); },
      'turn corrected and everything re-derived');
  });
  $$('[data-switch]').forEach(b => b.onclick = () => act(async () => {
    await api('/api/session', { action: 'switch', name: b.dataset.switch }); await refresh();
  }));
  $$('[data-del]').forEach(b => b.onclick = () => {
    if (!confirm('Delete session ' + b.dataset.del + '?')) return;
    act(async () => { await api('/api/session', { action: 'delete', name: b.dataset.del }); await refresh(); });
  });

  $('#btn-undo').onclick = () => act(async () => { await api('/api/undo', { n: 1 }); await refresh(); }, 'last turn removed');
  $('#btn-undo5').onclick = () => act(async () => { await api('/api/undo', { n: 5 }); await refresh(); }, 'last 5 turns removed');
  $('#btn-rebuy').onclick = () => act(async () => { await api('/api/deposit', { amount: 500 }); await refresh(); }, 'deposited 500');
  $('#btn-new-session').onclick = () => {
    const name = prompt('New session name:', 'session-' + (S.state.session.all.length + 1));
    if (!name) return;
    act(async () => { await api('/api/session', { action: 'new', name }); await refresh(); }, 'session created');
  };
  $('#session-select').onchange = (e) => act(async () => {
    await api('/api/session', { action: 'switch', name: e.target.value }); await refresh();
  });
  $('#btn-seed-archive').onclick = () => act(async () => {
    const d = await api('/api/session', { action: 'seed_archive' });
    await refresh(); toast('seeded ' + d.seeded + ' archived results');
  });
  $('#btn-clear-warm').onclick = () => act(async () => {
    const d = await api('/api/session', { action: 'new', name: 'clean-' + Date.now().toString().slice(-4) });
    await refresh(); toast('new clean session created');
  });

  $('#btn-sim').onclick = () => act(async () => {
    S.ui.sim = { source: $('#sim-source').value, policy: $('#sim-policy').value,
                 turns: Number($('#sim-turns').value), seed: Number($('#sim-seed').value) };
    $('#sim-status').innerHTML = '<span class="spin"></span> running…';
    const d = await api('/api/sim', S.ui.sim);
    renderSim(d.result);
    $('#sim-status').textContent = '';
  });
  $('#btn-grid').onclick = () => act(async () => {
    $('#sim-status').innerHTML = '<span class="spin"></span> running the whole grid (a few seconds)…';
    const d = await api('/api/grid', { turns: Number($('#sim-turns').value) });
    renderGrid(d.result);
    $('#sim-status').textContent = '';
  });
  $('#btn-auto').onclick = () => act(async () => {
    const body = { source: $('#auto-source').value, turns: Number($('#auto-turns').value),
                   follow: $('#auto-follow').value,
                   stakes: $('#auto-follow').value === 'mine' ? S.ui.stakes : undefined };
    const d = await api('/api/autoplay', body);
    S.state = d.state; render();
    toast('fast-forwarded ' + d.played + ' turns into this session');
  });

  $('#btn-save-config').onclick = () => act(async () => {
    const patch = {};
    $$('[data-cfg]').forEach(inp => {
      const path = inp.dataset.cfg.split('.');
      let node = patch;
      path.slice(0, -1).forEach(k => node = (node[k] = node[k] || {}));
      node[path[path.length - 1]] = Number(inp.value);
    });
    await api('/api/config', { patch });
    await refresh();
    toast('settings saved — model rebuilt');
  });
}

const POLICY_LABELS = { bot: 'bot (follow the button)', bot_strict: 'bot, commitments only',
  bot_loose: 'bot, ignore the gate', split_two: 'fixed split (yours)',
  always_top: 'all on the favourite', fixed_colour: 'all on one colour',
  martingale: 'Martingale', random: 'random colour', mirror_you: 'mirror your own bets',
  trend2: 'your trend bet', trend2_weighted: 'trend bet, weighted to the hotter colour' };
const SOURCE_LABELS = { fair: 'fair (no edge exists)', biased: 'biased (real base-rate edge)',
  markov: 'markov (thin, real streak)', markov_strong: 'markov_strong (big edge)',
  replay: 'replay (your results)', custom: 'custom probabilities' };

function fillSelect(sel, labels, selected) {
  const node = typeof sel === 'string' ? $(sel) : sel;
  if (!node || node.dataset.filled === '1') return;
  node.innerHTML = Object.keys(labels).map(k =>
    `<option value="${k}"${k === selected ? ' selected' : ''}>${esc(labels[k])}</option>`).join('');
  node.dataset.filled = '1';
}

function populateSimSelects() {
  fillSelect('#sim-source', SOURCE_LABELS, 'fair');
  fillSelect('#sim-policy', POLICY_LABELS, 'bot');
  fillSelect('#auto-source', SOURCE_LABELS, 'biased');
}


/* ---------------------------------------------------------------- trends */
/* Measured: 60 runs x 600 turns from 1,000 coins, 150 on each of two colours. */
const TREND_RISK = [
  ['fair (no memory)',          9,   915, 0,    52, 990,  997,  0],
  ['biased 44% (no memory)',   10,  3422, 0,    50, 32770, 38197, 0],
  ['markov (real memory)',   7530,  6488, 0,    28, 3370, 14765, 0],
  ['markov_strong (big edge)', 16120, 14099, 0, 12, 149740, 146791, 0],
];

function renderTrends() {
  const t = S.state.trend;
  if (!t) { $('#trend-current').innerHTML = '<span class="mut">no data yet</span>'; return; }
  const cur = t.current, o = t.overall;
  const chips = (cur.covered || []).map(s =>
    `<span class="chip ${esc(s)}">${esc(nameOf(s))}</span>`).join(' ');
  $('#trend-current').innerHTML = `
    <div class="row between">
      <div><span class="small mut">current run</span>
        <div style="font-size:20px;font-weight:600;margin-top:2px">${cur.run} turn${cur.run === 1 ? '' : 's'} ${chips}</div></div>
      <div style="text-align:right"><span class="small mut">pair held</span>
        <div class="v num" style="font-size:20px">${o.continued_pct.toFixed(1)}%</div>
        <div class="tiny dim">need ${o.break_even_pct}%</div></div>
    </div>
    <div class="small mut" style="margin-top:8px">${esc(cur.message)}</div>
    ${cur.pair && cur.pair.length ? `<div class="row" style="margin-top:10px">
      <button class="small" id="btn-stake-trend">stake ${S.state.trend.stake_hint || 120} on each of ${cur.pair.map(x => esc(nameOf(x))).join(' + ')}</button>
    </div>` : ''}`;

  $('#trend-table').innerHTML = t.rows.length ? `
    <div class="small mut" style="margin-bottom:8px">
      ${o.n} trend turns measured. Does a longer run predict better?
    </div>
    <table><thead><tr><th>run length</th><th>turns</th><th>pair held</th>
      <th>vs 66.7% needed</th><th>p</th><th></th></tr></thead><tbody>
    ${t.rows.map(r => `<tr>
      <td>${r.run === t.rows[t.rows.length - 1].run ? r.run + '+' : r.run}</td>
      <td class="num">${r.n}</td>
      <td class="num">${r.continued_pct.toFixed(1)}%</td>
      <td class="num ${cls(r.edge_pct)}">${r.edge_pct >= 0 ? '+' : ''}${r.edge_pct.toFixed(1)}%</td>
      <td class="num">${r.p_value.toFixed(4)}</td>
      <td>${r.significant ? '<span class="tiny pos">significant</span>' : '<span class="tiny dim">noise</span>'}</td>
    </tr>`).join('')}</tbody></table>` :
    '<span class="mut">not enough results yet</span>';

  const real = o.p_value <= 0.05 && o.continued_pct > 66.67;
  const bad = o.p_value <= 0.05 && o.continued_pct < 66.67;
  $('#trend-verdict').innerHTML = `<div class="callout${real ? '' : ' info'}">
    <b>${real ? 'Your trend bet is working here' : bad ? 'Runs are breaking early here' : 'No memory detected'}</b><br>
    ${esc(t.verdict)}</div>`;

  $('#trend-risk-table').innerHTML =
    `<thead><tr><th>source</th><th>trend bet: median</th><th>trend mean</th>
      <th>trend ruined</th><th>bot: median</th><th>bot mean</th><th>bot ruined</th></tr></thead><tbody>`
    + TREND_RISK.map(r => `<tr>
        <td>${esc(r[0])}</td>
        <td class="num neg"><b>${money(r[1])}</b></td><td class="num">${money(r[2])}</td>
        <td class="num ${r[4] > 20 ? 'neg' : 'mut'}">${r[4]}%</td>
        <td class="num pos"><b>${money(r[5])}</b></td><td class="num">${money(r[6])}</td>
        <td class="num pos">${r[7]}%</td>
      </tr>`).join('') + '</tbody>'
    + `<tfoot><tr><td colspan="7" class="small mut" style="text-align:left;padding-top:10px">
        On a fair game the trend bet's <b>median</b> outcome is ${money(9)} out of ${money(1000)},
        because 300 per turn on a 1,000 bankroll is 30% exposure: the odds are exactly fair, but
        the <i>size</i> is fatal. The bot's refusal to bet is worth more than any trend.
        On games with real memory the same strategy does work — so the question is never
        "is there a trend?", it is "does this game have memory?" — which is what the test above answers.
      </td></tr></tfoot>`;
}

function renderSim(r) {
  const ok = r.ruined ? 'neg' : r.roi_pct > 0 ? 'pos' : 'mut';
  $('#sim-result').innerHTML = `
    <div class="grid4">
      ${[['final capital', money(r.final_capital), ok],
         ['return', pct(r.roi_pct), cls(r.roi_pct)],
         ['bets placed', r.bets + ' / ' + r.turns_played, ''],
         ['win rate', r.win_rate_pct.toFixed(1) + '%', ''],
         ['max drawdown', r.max_drawdown_pct.toFixed(1) + '%', 'neg'],
         ['busted', r.ruined ? 'yes' + (r.ruined_at_turn != null ? ' @ ' + r.ruined_at_turn : '') : 'no', r.ruined ? 'neg' : 'pos'],
         ['engine hit rate', r.engine_hit_rate_pct.toFixed(1) + '%', ''],
         ['engine edge', r.engine_edge_bits.toFixed(4) + ' bits', r.engine_edge_bits > 0 ? 'pos' : 'mut'],
        ].map(([k, v, c]) => `<div class="stat"><div class="k">${k}</div><div class="v ${c}">${esc(String(v))}</div></div>`).join('')}
    </div>
    <svg class="spark" id="curve-sim" style="height:150px;margin-top:12px"></svg>
    <div class="legend"><span><i style="background:var(--acc)"></i>bankroll over ${r.turns_played} turns
      (${esc(r.source)} / ${esc(r.policy)} / seed ${r.seed})</span></div>`;
  spark('#curve-sim', [{ v: r.curve || [], color: '#7c8aff' }],
    { zero: 1000, fill: true });
}

function renderGrid(out) {
  const stores = [...new Set(out.summary.map(r => r.source))];
  let html = '';
  stores.forEach(src => {
    const rows = out.summary.filter(r => r.source === src);
    html += `<div class="small" style="margin-top:14px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)">${esc(src)}</div>`;
    html += `<table><thead><tr><th>strategy</th><th>median final</th><th>mean ROI</th>
      <th>worst</th><th>best</th><th>ruin rate</th><th>max DD</th><th>turnover</th></tr></thead><tbody>`
      + rows.map(r => `<tr${r.policy === 'bot' ? ' style="background:rgba(124,138,255,.09)"' : ''}>
        <td>${esc(r.policy)}</td>
        <td class="num">${money(r.median_final)}</td>
        <td class="num ${cls(r.mean_roi_pct)}">${pct(r.mean_roi_pct)}</td>
        <td class="num neg">${pct(r.worst_roi_pct)}</td>
        <td class="num pos">${pct(r.best_roi_pct)}</td>
        <td class="num ${r.ruin_rate_pct > 0 ? 'neg' : 'pos'}">${r.ruin_rate_pct.toFixed(0)}%</td>
        <td class="num">${r.mean_dd_pct.toFixed(1)}%</td>
        <td class="num dim">${r.mean_bets.toFixed(0)} bets</td>
      </tr>`).join('') + '</tbody></table>';
  });
  html += `<div class="callout info" style="margin-top:14px">
    Read the <b>ruin rate</b> column first. On <code>fair</code> — a game with no edge at all —
    every strategy that keeps betting loses money in the long run, and the bot's refusal to bet
    is the win. On <code>markov</code> the bot may still pass: the pattern is real, but a
    3× payout demands a lot of edge. On <code>markov_strong</code> it must make money, or
    something is broken.</div>`;
  $('#sim-result').innerHTML = html;
}

function renderConfig() {
  if (S.config && $('#config-editor').children.length) return;
  api('/api/config').then(d => {
    S.config = d.config;
    const groups = [['capital', ['starting', 'stake_step', 'min_stake', 'max_stake_per_turn',
                                 'max_exposure_fraction', 'default_split_stake']],
                    ['honesty', ['confidence_threshold_percent', 'min_info_gain_bits',
                                 'max_p_value', 'recent_window', 'provisional_kelly_scale']],
                    ['bot_bet', ['kelly_fraction', 'min_edge_to_bet']],
                    ['brain', ['max_context_order', 'recency_decay', 'min_data_before_analysis']],
                    ['trust', ['decay', 'decide_margin', 'tilt_multiplier']]];
    $('#config-editor').innerHTML = groups.map(([g, keys]) => {
      const spec = d.config[g];
      if (!spec) return '';
      return `<div class="small mut" style="margin:10px 0 4px;text-transform:uppercase;letter-spacing:.06em">${g}</div>
      <div class="grid3">${keys.filter(k => k in spec).map(k => `
        <label class="small mut">${k.replace(/_/g, ' ')}
        <input type="number" step="any" data-cfg="${g}.${k}" value="${spec[k]}"></label>`).join('')}</div>`;
    }).join('');
  });
}

/* ---------------------------------------------------------------- boot */
api('/api/config').then(d => { S.config = d.config; }).catch(() => {})
  .then(() => refresh()).then(() => {
    // Each step is independently guarded. Wiring must never be all-or-nothing:
    // one missing element used to abort everything after it, which is how the
    // game screen became unreachable while the rest of the page looked fine.
    const step = (label, fn) => {
      try { fn(); } catch (err) {
        WIRING.failed.push(label + ' (' + err.message + ')');
        try { console.error('wiring failed:', label, err); } catch (e2) {}
      }
    };
    step('simulation selects', populateSimSelects);
    step('dashboard', wire);
    step('keyboard', wireKeys);
    step('game screen', wireTable);
  })
  .then(() => {
    let m = 'table';
    try { m = localStorage.getItem(MODE_KEY) || 'table'; } catch (e) {}
    try {
      const ro = localStorage.getItem('buzzcast.recordOnly');
      S.ui.recordOnly = ro === null ? true : ro === '1';   // recording-only is the default
    } catch (e) { S.ui.recordOnly = true; }
    setMode(m);
  }).catch(e => {
  // Say what actually broke. The old wording blamed the engine for anything,
  // including a missing button, which sent the reader looking in the wrong place.
  const bits = [];
  if (WIRING.failed.length) bits.push('parts of the screen did not start: ' + WIRING.failed.join('; '));
  bits.push(e && e.message ? e.message : String(e));
  document.body.insertAdjacentHTML('afterbegin',
    `<div class="callout" style="margin:16px">buzzcast could not start properly — ${esc(bits.join(' · '))}. `
    + `The engine itself may be fine: try a reload, then <code>python tests.py</code>.</div>`);
});
