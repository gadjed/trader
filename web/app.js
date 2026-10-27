"use strict";

// ------------------------------------------------------------------ helpers
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

const st = {
  player: JSON.parse(localStorage.getItem("player") || "null"),
  catalog: null, items: {}, market: [], marketById: {},
  selected: null, tf: 1, side: "buy", tab: "market", favs: new Set(),
  state: null, settings: null, recipes: [], selRecipe: null, charts: {}, seenNews: +localStorage.getItem("seenNews") || 0,
};

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (st.player) headers["X-Player"] = st.player.id;
  const res = await fetch("/api" + path, { ...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && path !== "/login") logout();
    const msg = typeof data.detail === "string" ? data.detail : (data.detail?.[0]?.msg || res.statusText);
    throw new Error(msg);
  }
  return data;
}

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = "toast"), 2600);
}

async function act(fn, okMsg) {
  try {
    const r = await fn();
    const msg = typeof okMsg === "function" ? okMsg(r) : okMsg;
    if (msg) toast(msg);
    refreshAll();
    return r;
  } catch (e) {
    toast(e.message, true);
  }
}

// 1 gold = 100 silver = 10000 copper
function money(c, plain = false) {
  if (c === null || c === undefined || isNaN(c)) return "—";
  c = Math.round(c);
  const neg = c < 0; c = Math.abs(c);
  const g = Math.floor(c / 10000), s = Math.floor((c % 10000) / 100), cu = c % 100;
  if (plain) return (neg ? "-" : "") + [g && g + "з", s && s + "с", (cu || (!g && !s)) && cu + "м"].filter(Boolean).join(" ");
  const parts = [];
  if (g) parts.push(`<span class="g">${g.toLocaleString("uk")}з</span>`);
  if (s) parts.push(`<span class="s">${s}с</span>`);
  if (cu || (!g && !s)) parts.push(`<span class="c">${cu}м</span>`);
  return `<span class="money">${neg ? "-" : ""}${parts.join(" ")}</span>`;
}
const pct = (x) => (x === null || x === undefined ? "—" : `<span class="${x > 0 ? "up" : x < 0 ? "down" : "muted"}">${x > 0 ? "+" : ""}${(x * 100).toFixed(1)}%</span>`);
const num = (n) => (n ?? 0).toLocaleString("uk");
const itemLabel = (it) => `<span class="icon">${it.icon}</span> ${esc(it.name)}`;

// ------------------------------------------------------------------ auth
function showLogin() { $("#login").classList.remove("hidden"); }
function logout() { st.player = null; st.feedCursor = null; localStorage.removeItem("player"); showLogin(); }
$("#logout").onclick = logout;
$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    st.player = await api("/login", { method: "POST", body: { name: $("#login-name").value } });
    localStorage.setItem("player", JSON.stringify(st.player));
    $("#login").classList.add("hidden");
    refreshAll();
  } catch (err) { toast(err.message, true); }
};

// ------------------------------------------------------------------ tabs
$$("#tabs button").forEach((b) => (b.onclick = () => openTab(b.dataset.tab)));
function openTab(tab) {
  st.tab = tab;
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + tab));
  if (tab === "news") { st.seenNews = st.lastNewsId || 0; localStorage.setItem("seenNews", st.seenNews); }
  refreshTab();
}

// ------------------------------------------------------------------ header / speed
$$("#speed button").forEach((b) => (b.onclick = async () => {
  const v = b.dataset.speed;
  const body = v === "pause" ? { paused: 1 } : { paused: 0, tick_seconds: +v };
  await act(() => api("/settings", { method: "POST", body }));
}));

async function refreshState() {
  const s = await api("/state");
  st.state = s;
  $("#game-time").textContent = `🕰️ ${s.time.label}`;
  $("#prewarm").classList.toggle("hidden", !s.prewarming);
  $("#fee-pct").textContent = `${+s.settings.ah_cut_pct.toFixed(1)}%`;
  $$("#speed button").forEach((b) => {
    const v = b.dataset.speed;
    b.classList.toggle("active", v === "pause" ? !!s.settings.paused : !s.settings.paused && +v === s.settings.tick_seconds);
  });
}

async function refreshMe() {
  if (!st.player) return;
  const me = await api("/me");
  st.me = me;
  if (!st.favPending) st.favs = new Set(me.favorites);
  $("#player-name").textContent = me.name;
  $("#gold").innerHTML = money(me.gold);
  const d = me.net_worth - me.start_gold;
  $("#networth").innerHTML = `${money(me.net_worth)} (${d >= 0 ? '<span class="up">+' : '<span class="down">'}${money(d, true)}</span>)`;
}

// ------------------------------------------------------------------ market list
async function loadCatalog() {
  st.catalog = await api("/catalog");
  st.catalog.items.forEach((it) => (st.items[it.id] = it));
  $("#cat-filter").innerHTML += st.catalog.categories.map((c) => `<option>${esc(c)}</option>`).join("");
  $("#prof-filter").innerHTML += Object.entries(st.catalog.craft_profs).map(([k, v]) => `<option value="${k}">${profIcon[k]} ${esc(v)}</option>`).join("");
  try { const v = JSON.parse(localStorage.getItem("rcView") || "{}")["prof-filter"]; if (v) $("#prof-filter").value = v; } catch {}
  $("#w-prof").innerHTML += Object.entries({ ...st.catalog.gather_profs, scavenger: "Збирач хламу", ...st.catalog.craft_profs })
    .map(([k, v]) => `<option value="${k}">${profIcon[k]} ${esc(v)}</option>`).join("");
}
const profIcon = { lumberjack: "🪓", miner: "⛏️", herbalist: "🌿", farmer: "🌾", hunter: "🏹", fisher: "🎣", scavenger: "🧹",
  carpenter: "🪚", blacksmith: "⚒️", tailor: "🧵", leatherworker: "🧳", alchemist: "⚗️", cook: "🍳", mason: "🧱", jeweler: "💍" };

["#search", "#cat-filter", "#sort", "#only-fav"].forEach((s) => $(s).addEventListener("input", renderList));

async function toggleFav(id) {
  // optimistic toggle, then sync with the server's answer
  st.favPending = true;
  st.favs.has(id) ? st.favs.delete(id) : st.favs.add(id);
  renderList();
  renderFavButton();
  try {
    const r = await api(`/favorites/${id}`, { method: "POST" });
    st.favs = new Set(r.favorites);
    toast(r.favorite ? "Додано в обране" : "Прибрано з обраного");
  } catch (e) {
    toast(e.message, true);
  } finally {
    st.favPending = false;
    renderList();
    renderFavButton();
  }
}

function renderFavButton() {
  const b = $("#d-fav");
  if (!b) return;
  const on = st.favs.has(st.selected);
  b.textContent = on ? "★ В обраному" : "☆ В обране";
  b.classList.toggle("on", on);
}

async function refreshMarket() {
  st.market = await api("/market");
  st.market.forEach((m) => (st.marketById[m.id] = m));
  renderList();
}

function renderList() {
  const q = $("#search").value.trim().toLowerCase();
  const cat = $("#cat-filter").value;
  const sort = $("#sort").value;
  const onlyFav = $("#only-fav").checked;
  const sat = (m) => m.ask_qty / m.stack;
  const sorters = {
    name: (a, b) => a.name.localeCompare(b.name, "uk"),
    volume: (a, b) => b.volume * (b.last || 0) - a.volume * (a.last || 0),
    change: (a, b) => (b.change ?? -9) - (a.change ?? -9),
    change_asc: (a, b) => (a.change ?? 9) - (b.change ?? 9),
    sat: (a, b) => sat(b) - sat(a),
    price: (a, b) => (b.last || b.ref) - (a.last || a.ref),
  };
  const matches = (m) => (!cat || m.category === cat) && (!q || m.name.toLowerCase().includes(q));
  // favorites live in their own section pinned to the bottom, regardless of filters;
  // with "only favorites" on, the main list shows filtered favorites and the section hides
  const main = st.market.filter((m) => matches(m) && (onlyFav ? st.favs.has(m.id) : !st.favs.has(m.id))).sort(sorters[sort]);
  const favs = st.market.filter((m) => st.favs.has(m.id)).sort(sorters[sort]);

  fillList($("#item-list"), main, onlyFav ? "У обраному нічого не знайдено" : "Нічого не знайдено");
  $("#fav-section").classList.toggle("hidden", onlyFav);
  $("#fav-count").textContent = favs.length ? `(${favs.length})` : "";
  fillList($("#fav-list"), favs, "Натисніть ☆ біля товару, щоб додати");
}

function fillList(list, rows, emptyText) {
  list.innerHTML = rows.map((m) => `
    <div class="item-row ${m.id === st.selected ? "sel" : ""}" data-id="${m.id}">
      <button class="fav-btn ${st.favs.has(m.id) ? "on" : ""}" data-fav="${m.id}" title="${st.favs.has(m.id) ? "Прибрати з обраного" : "Додати в обране"}">${st.favs.has(m.id) ? "★" : "☆"}</button>
      <div class="icon">${m.icon}</div>
      <div style="min-width:0"><div class="nm">${esc(m.name)}</div>
        <div class="sub">${m.ask_qty ? num(m.ask_qty) + " шт у лотах" : '<span class="down">немає лотів</span>'} · об. ${num(m.volume)}</div></div>
      <div class="px">${money(m.best_ask ?? m.last)}<br>${pct(m.change)}</div>
      <canvas class="spark" width="64" height="24" data-id="${m.id}"></canvas>
    </div>`).join("") || `<div class="muted small" style="padding:6px">${emptyText}</div>`;
  $$(".item-row", list).forEach((r) => (r.onclick = () => selectItem(+r.dataset.id)));
  $$("[data-fav]", list).forEach((b) => (b.onclick = (e) => { e.stopPropagation(); toggleFav(+b.dataset.fav); }));
  $$("canvas.spark", list).forEach((cv) => drawSpark(cv, st.marketById[cv.dataset.id].spark));
}

function drawSpark(cv, data) {
  const pts = data.filter((x) => x !== null);
  if (pts.length < 2) return;
  const ctx = cv.getContext("2d");
  const min = Math.min(...pts), max = Math.max(...pts), w = cv.width, h = cv.height;
  ctx.strokeStyle = pts[pts.length - 1] >= pts[0] ? "#5cc77a" : "#e5604f";
  ctx.lineWidth = 1.3;
  ctx.beginPath();
  pts.forEach((p, i) => {
    const x = (i / (pts.length - 1)) * w, y = h - 2 - ((p - min) / (max - min || 1)) * (h - 4);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

// ------------------------------------------------------------------ item detail
async function selectItem(id, tab = true) {
  st.selected = id;
  if (tab && st.tab !== "market") openTab("market");
  $$(".item-row").forEach((r) => r.classList.toggle("sel", +r.dataset.id === id));
  renderDetailShell(id);
  await refreshDetail(true);
}

function renderDetailShell(id) {
  const it = st.items[id];
  Object.values(st.charts).forEach((c) => c.destroy && c.destroy());
  st.charts = {};
  $("#detail").innerHTML = `
    <div class="panel">
      <div class="detail-head">
        <div class="big-icon">${it.icon}</div>
        <div><h2 style="margin:0">${esc(it.name)}</h2>
          <div class="muted small">${esc(it.category)} · рівень ${it.tier} · стак ${it.stack}
            ${it.gather_prof ? " · видобуває: " + esc(st.catalog.gather_profs[it.gather_prof]) : ""}</div></div>
        <button class="btn small fav-btn" id="d-fav" style="margin-left:auto"></button>
      </div>
      <div class="stats" id="d-stats"></div>
      <div class="stats ${st.moreStats ? "" : "hidden"}" id="d-stats-more"></div>
      <button class="btn ghost small more-toggle" id="d-more">${st.moreStats ? "▴ Менше" : "▾ Детальніше"}</button>
    </div>
    <div class="detail-grid">
      <div class="detail-main">
        <div class="panel book-panel">
          <div class="row between"><h3>Книга ордерів</h3><span class="small muted">клік по рядку → ціна у форму</span></div>
          <div id="d-book"></div>
        </div>
        <div class="panel">
          <div class="row between"><h3>Ціна</h3>
            <div class="tf" id="tf">${[[1, "30хв"], [4, "2год"], [12, "6год"], [48, "1 день"]]
              .map(([v, l]) => `<button data-tf="${v}" class="${v === st.tf ? "active" : ""}">${l}</button>`).join("")}</div></div>
          <div class="chart-box"><canvas id="c-price"></canvas></div>
        </div>
        <div class="panel">
          <h3>Обсяг торгів і насиченість ринку</h3>
          <div class="chart-box short"><canvas id="c-volume"></canvas></div>
        </div>
        <div class="panel">
          <div class="row between"><h3>Попит за годинами доби</h3><span class="small muted" id="profile-note"></span></div>
          <div class="chart-box short"><canvas id="c-profile"></canvas></div>
        </div>
        <div class="grid2">
          <div class="panel"><h3>Стакан: кількість за ціною</h3><div class="chart-box short"><canvas id="c-depth"></canvas></div></div>
          <div class="panel"><h3>Продано за добу за ціною</h3><div class="chart-box short"><canvas id="c-hist"></canvas></div></div>
        </div>
        <div class="grid2">
          <div class="panel"><h3>Крафт</h3><div id="d-recipes"></div></div>
          <div class="panel"><h3>Останні угоди</h3><div class="scroll" id="d-trades"></div></div>
        </div>
      </div>
      <aside class="detail-side">
        <div class="panel trade-form" id="trade-form"></div>
      </aside>
    </div>`;
  $$("#tf button").forEach((b) => (b.onclick = () => {
    st.tf = +b.dataset.tf;
    $$("#tf button").forEach((x) => x.classList.toggle("active", x === b));
    refreshDetail();
  }));
  $("#d-more").onclick = () => {
    st.moreStats = !st.moreStats;
    $("#d-stats-more").classList.toggle("hidden", !st.moreStats);
    $("#d-more").textContent = st.moreStats ? "▴ Менше" : "▾ Детальніше";
  };
  renderTradeForm(id);
  renderFavButton();
  $("#d-fav").onclick = () => toggleFav(id);
}

async function refreshDetail(first = false) {
  const id = st.selected;
  if (!id) return;
  const [d, candles, book, trades, profile] = await Promise.all([
    api(`/items/${id}`), api(`/items/${id}/candles?tf=${st.tf}&limit=160`), api(`/items/${id}/book`), api(`/items/${id}/trades?limit=60`),
    api(`/items/${id}/profile`),
  ]);
  if (id !== st.selected) return;
  st.detail = d;
  const m = st.marketById[id] || {};
  const owned = st.me?.inventory.find((x) => x.item.id === id)?.qty || 0;
  const mult = (x) => `<span class="${x > 1.05 ? "up" : x < 0.95 ? "down" : ""}">×${x.toFixed(2)}</span>`;
  const stat = ([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  $("#d-stats").innerHTML = [
    ["Остання ціна", `${money(m.last)} ${pct(m.change)}`], ["Ринкова", money(d.ref)],
    ["У лотах", `${num(m.ask_qty)} шт`], ["Продається", `${num(d.sold_day)} шт/добу`],
    ["Торговцю NPC", money(d.vendor_price)], ["У вас", num(owned) + " шт"],
  ].map(stat).join("");
  $("#d-stats-more").innerHTML = [
    ["Найкраща пропозиція", money(d.best_ask)], ["Найкращий попит", money(d.best_bid)],
    ["Базова вартість", money(d.base_price)], ["Лотів", num(m.listings)],
    ["Обсяг за добу", num(m.volume) + " шт"], ["Попит / видобуток", `${mult(d.demand_mult)} / ${mult(d.supply_mult)}`],
    ["Попит NPC (очік.)", `${num(d.demand_day)} шт/добу`], ["Покупців NPC", `~${num(d.buyers_day)}/добу`],
    ["Популярність", mult(d.popularity)],
  ].map(stat).join("");

  drawPriceChart(candles);
  drawVolumeChart(candles);
  drawDepth(book);
  drawHist(trades.histogram);
  drawProfile(profile);
  renderBook(book);
  $("#d-trades").innerHTML = trades.recent.length ? `<table><tr><th>Час</th><th class="num">Ціна</th><th class="num">К-сть</th><th>Покупець ← Продавець</th></tr>
    ${trades.recent.map((t) => `<tr><td class="small muted">${t.time.split(", ")[1]}</td><td class="num">${money(t.price)}</td><td class="num">${t.qty}</td>
      <td class="small">${esc(t.buyer)} ← ${esc(t.seller)}</td></tr>`).join("")}</table>` : '<div class="muted">Угод ще не було</div>';
  renderItemRecipes(d);
  if (first) {
    setPrice(st.side === "buy" ? (d.best_ask || Math.round(d.ref)) : (d.best_ask ? d.best_ask - 1 : Math.round(d.ref * 1.1)));
    updateQuote();
  }
}

// ---- crafting economics for the selected item
function renderItemRecipes(d) {
  const chip = (r) => `<span class="recipe-chip" data-item="${r.output.id}">${r.output.icon} ${esc(r.output.name)} ×${r.output_qty}</span>`;
  const signed = (v) => (v === null ? '<span class="muted">—</span>' : `<span class="${v > 0 ? "up" : v < 0 ? "down" : ""}">${v > 0 ? "+" : ""}${money(v, true)}</span>`);
  const line = (k, v, hint = "") => `<div><span class="muted" ${hint ? `title="${esc(hint)}"` : ""}>${k}</span><span>${v}</span></div>`;
  const recipe = (r) => {
    const e = r.econ, out = `${r.output.icon}×${r.output_qty}`;
    const ingRows = r.ingredients.map((g, i) => {
      const x = e.ingredients[i];
      return `<tr><td><span class="recipe-chip" data-item="${g.item.id}">${g.item.icon} ${esc(g.item.name)}</span></td>
        <td class="num">${g.qty}</td><td class="num ${x.have >= g.qty ? "up" : "muted"}">${x.have}</td>
        <td class="num">${x.cost_ask !== null ? money(x.cost_ask) : '<span class="down" title="Лотів не вистачає">мало лотів</span>'}</td>
        <td class="num muted">${money(x.cost_ref)}</td></tr>`;
    }).join("");
    // verdict: what to do with this recipe right now
    const best = Math.max(e.profit_now ?? -Infinity, e.profit_list);
    const how = e.profit_now !== null && e.profit_now >= e.profit_list ? "продаж у заявки" : "виставлений лот";
    let verdict;
    if (best > 0 && e.saving > 0) verdict = `<span class="up">Крафтити вигідно</span>: дешевше, ніж купити готове, а на продажі можна заробити до ${money(best, true)} (${how}).`;
    else if (best > 0) verdict = `<span class="up">Можна заробити до ${money(best, true)}</span> (${how})${e.saving !== null && e.saving <= 0 ? ", хоча для себе купити готове дешевше" : ""}.`;
    else if (e.saving > 0) verdict = `<span class="up">Для себе крафтити дешевше</span>, ніж купувати готове, але на перепродажі не заробити.`;
    else verdict = `<span class="down">Зараз не вигідно</span>: інгредієнти коштують більше, ніж результат.`;
    if (e.missing) verdict += ` <span class="muted">* Частини інгредієнтів немає в лотах — її оцінено за ринковою ціною, купити зараз не вийде.</span>`;
    return `<div class="recipe-econ">
      <div class="small"><b>${esc(r.profession_name)}</b>${r.is_alt ? ' <span class="tag">переробка</span>' : ""} → ${out}
        <button class="btn small" data-tree="${r.id}">🌳 дерево</button></div>
      <table class="small"><tr><th>Інгредієнт</th><th class="num">Треба</th><th class="num">Є</th><th class="num">Купити зараз</th><th class="num">Ринкова</th></tr>
        ${ingRows}
        <tr><td><b>Разом</b></td><td></td><td></td><td class="num"><b>${money(e.cost_ask)}</b>${e.missing ? ' <span class="down" title="Частину оцінено за ринковою ціною">*</span>' : ""}</td>
          <td class="num muted">${money(e.cost_ref)}</td></tr></table>
      <div class="quote">
        ${line(`Купити готове ${out}`, e.out_buy !== null ? money(e.out_buy) : '<span class="down">мало лотів</span>')}
        ${line(`Продати ${out} в заявки`, e.out_sell_now !== null ? money(e.out_sell_now) : '<span class="muted">мало заявок</span>', "Після комісії біржі")}
        ${line(`Виставити ${out} по ${money(e.out_list_price, true)}/шт`, money(e.out_sell_list), "Після комісії та депозиту, якщо лот продасться")}
        <hr style="border:0;border-top:1px solid var(--line);margin:5px 0">
        ${line("Економія: скрафтити замість купити", signed(e.saving), "Ціна готового мінус вартість інгредієнтів")}
        ${line("Прибуток: купити інгредієнти → скрафтити → продати в заявки", signed(e.profit_now))}
        ${line("Прибуток: купити інгредієнти → скрафтити → виставити лот", signed(e.profit_list))}
      </div>
      <div class="small">${verdict}</div>
    </div>`;
  };
  $("#d-recipes").innerHTML = `
    ${d.made_by.length ? `<div class="small muted">Як зробити (розрахунок на один крафт, за поточною книгою ордерів):</div>${d.made_by.map(recipe).join("")}`
      : '<div class="small muted">Сировина — тільки видобуток.</div>'}
    ${d.used_in.length ? `<div class="small muted" style="margin-top:8px">Використовується в:</div>${d.used_in.map(chip).join("")}` : ""}`;
  $$("#d-recipes [data-item]").forEach((e) => (e.onclick = () => selectItem(+e.dataset.item)));
  $$("#d-recipes [data-tree]").forEach((e) => (e.onclick = () => { openTab("craft"); selectRecipe(+e.dataset.tree); }));
}

// ---- charts
Chart.defaults.color = "#9b8f7d";
Chart.defaults.borderColor = "#2e2922";
Chart.defaults.font.size = 11;
const tooltipMoney = { callbacks: { label: (c) => `${c.dataset.label}: ${typeof c.raw === "number" && c.dataset.money !== false ? money(c.raw, true) : c.formattedValue}` } };

function upsertChart(key, canvasId, config) {
  const ch = st.charts[key];
  if (ch) {
    ch.data.labels = config.data.labels;
    config.data.datasets.forEach((ds, i) => Object.assign(ch.data.datasets[i], ds));
    ch.update("none");
    return ch;
  }
  const cv = document.getElementById(canvasId);
  if (!cv) return;
  st.charts[key] = new Chart(cv, config);
}

function drawPriceChart(cs) {
  const labels = cs.map((c) => c.time);
  upsertChart("price", "c-price", {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Макс", data: cs.map((c) => c.high), borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: "rgba(217,164,65,.12)", spanGaps: true },
        { label: "Мін", data: cs.map((c) => c.low), borderWidth: 0, pointRadius: 0, spanGaps: true },
        { label: "Закриття", data: cs.map((c) => c.close), borderColor: "#d9a441", borderWidth: 2, pointRadius: 0, tension: .2, spanGaps: true },
        { label: "Середня (VWAP)", data: cs.map((c) => c.vwap), borderColor: "#6aa8e8", borderWidth: 1.2, borderDash: [4, 3], pointRadius: 0, spanGaps: true },
        { label: "Найкраща пропозиція", data: cs.map((c) => c.best_ask), borderColor: "rgba(229,96,79,.7)", borderWidth: 1, pointRadius: 0, stepped: true },
        { label: "Найкращий попит", data: cs.map((c) => c.best_bid), borderColor: "rgba(92,199,122,.7)", borderWidth: 1, pointRadius: 0, stepped: true },
      ],
    },
    options: {
      maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { boxWidth: 12, filter: (l) => l.datasetIndex > 1 } }, tooltip: tooltipMoney },
      scales: { x: { ticks: { maxTicksLimit: 8 } }, y: { ticks: { callback: (v) => money(v, true) } } },
    },
  });
}

function drawVolumeChart(cs) {
  upsertChart("volume", "c-volume", {
    type: "bar",
    data: {
      labels: cs.map((c) => c.time),
      datasets: [
        { label: "Продано, шт", data: cs.map((c) => c.volume), backgroundColor: "rgba(106,168,232,.6)", yAxisID: "y", money: false },
        { type: "line", label: "Виставлено на продаж, шт", data: cs.map((c) => c.ask_qty), borderColor: "#e5604f", borderWidth: 1.5, pointRadius: 0, yAxisID: "y2", money: false },
        { type: "line", label: "Заявки на купівлю, шт", data: cs.map((c) => c.bid_qty), borderColor: "#5cc77a", borderWidth: 1, pointRadius: 0, yAxisID: "y2", money: false },
      ],
    },
    options: {
      maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { boxWidth: 12 } } },
      scales: { x: { ticks: { maxTicksLimit: 8 } }, y: { position: "left", beginAtZero: true }, y2: { position: "right", beginAtZero: true, grid: { display: false } } },
    },
  });
}

function drawDepth(book) {
  const bids = [...book.bids].reverse().slice(-15), asks = book.asks.slice(0, 15);
  const labels = [...bids, ...asks].map((l) => money(l.price, true));
  upsertChart("depth", "c-depth", {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Купівля", data: [...bids.map((l) => l.qty), ...asks.map(() => null)], backgroundColor: "rgba(92,199,122,.7)", money: false },
        { label: "Продаж", data: [...bids.map(() => null), ...asks.map((l) => l.qty)], backgroundColor: "rgba(229,96,79,.7)", money: false },
      ],
    },
    options: { maintainAspectRatio: false, animation: false, plugins: { legend: { display: false } },
      scales: { x: { stacked: true, ticks: { maxRotation: 60, autoSkip: true, maxTicksLimit: 12 } }, y: { stacked: true, beginAtZero: true } } },
  });
}

function drawHist(hist) {
  upsertChart("hist", "c-hist", {
    type: "bar",
    data: {
      labels: hist.map((h) => money(h.from, true)),
      datasets: [{ label: "Продано, шт", data: hist.map((h) => h.qty), backgroundColor: "rgba(217,164,65,.7)", money: false }],
    },
    options: { maintainAspectRatio: false, animation: false, plugins: { legend: { display: false } },
      scales: { x: { ticks: { maxRotation: 60, maxTicksLimit: 10 } }, y: { beginAtZero: true } } },
  });
}

function drawProfile(p) {
  $("#profile-note").textContent = `середнє за ${p.days} дн. · зараз ${String(p.now_hour).padStart(2, "0")}:00`;
  upsertChart("profile", "c-profile", {
    type: "bar",
    data: {
      labels: p.hours.map((h) => `${String(h.hour).padStart(2, "0")}:00`),
      datasets: [
        { label: "Продано в середньому, шт/год", data: p.hours.map((h) => h.sold), money: false,
          backgroundColor: p.hours.map((h) => (h.hour === p.now_hour ? "rgba(217,164,65,.9)" : "rgba(106,168,232,.6)")) },
        { type: "line", label: "Очікуваний попит NPC, шт/год", data: p.hours.map((h) => h.expected), money: false,
          borderColor: "#5cc77a", borderWidth: 1.5, pointRadius: 0, tension: .35 },
      ],
    },
    options: { maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { boxWidth: 12 } } }, scales: { x: { ticks: { maxTicksLimit: 12 } }, y: { beginAtZero: true } } },
  });
}

function renderBook(book) {
  const box = $("#d-book");
  // keep each column's scroll position across refreshes so the book doesn't jump
  const scroll = Object.fromEntries($$(".book-col", box).map((el) => [el.dataset.side, el.scrollTop]));
  const maxQ = Math.max(1, ...book.asks.map((l) => l.qty), ...book.bids.map((l) => l.qty));
  const withCum = (levels) => { let cum = 0; return levels.map((l) => ({ ...l, cum: (cum += l.qty) })); };
  const row = (l, side) => {
    // track left of the price shrinking towards auto-cancel: own order if any, else the level's soonest-expiring one
    const left = l.own_left ?? l.soon_left, total = l.own_total ?? l.soon_total;
    const frac = Math.max(0, Math.min(1, left / total));
    const tip = [`${side === "ask" ? "Купити все до цієї ціни: " : "Продати все до цієї ціни: "}${num(l.cum)} шт`,
      `Найближче автоскасування: через ${fmtTicks(l.soon_left)} (з ${fmtTicks(l.soon_total)})`];
    if (l.own_left !== null) tip.push(`Ваш ордер скасується через ${fmtTicks(l.own_left)}`);
    return `<tr class="lvl ${side} ${l.mine ? "mine" : ""}" data-price="${l.price}" data-side="${side}" data-cum="${l.cum}" title="${tip.join("\n")}">
    <td class="px"><div class="px-wrap"><div class="ttl-track"><div class="ttl ${frac < 0.15 ? "low" : ""} ${l.own_left !== null ? "own" : ""}" style="width:${(frac * 100).toFixed(1)}%"></div></div>${money(l.price)}</div></td>
    <td class="num">${num(l.qty)}</td><td class="num muted">${l.orders}${l.mine ? " ★" : ""}</td>
    <td class="barcell"><div class="bar" style="width:${(l.qty / maxQ) * 100}%"></div></td></tr>`;
  };
  const col = (side, title, levels, empty) => `
    <div class="book-side ${side}">
      <div class="book-title">${title} <span class="muted">${num(levels.reduce((a, l) => a + l.qty, 0))} шт</span></div>
      <table class="book-head"><tr><th>Ціна</th><th class="num">К-сть</th><th class="num">Орд.</th><th></th></tr></table>
      <div class="book-col" data-side="${side}"><table>${levels.map((l) => row(l, side)).join("")
        || `<tr><td colspan="4" class="muted center empty">${empty}</td></tr>`}</table></div>
    </div>`;
  const spread = book.asks.length && book.bids.length ? book.asks[0].price - book.bids[0].price : null;
  box.innerHTML = `
    <div class="book-spread">${spread !== null
      ? `<span class="up">${money(book.bids[0].price)}</span> ← спред ${money(spread)}
         <span class="muted">(${((spread / book.bids[0].price) * 100).toFixed(1)}%)</span> → <span class="down">${money(book.asks[0].price)}</span>`
      : '<span class="muted">спред — (одна зі сторін порожня)</span>'}</div>
    <div class="book-cols">
      ${col("bid", '<span class="up">Попит</span> · заявки на купівлю', withCum(book.bids), "заявок на купівлю немає")}
      ${col("ask", '<span class="down">Пропозиція</span> · лоти на продаж', withCum(book.asks), "лотів на продаж немає")}
    </div>
    <div class="small muted book-legend">★ ваш ордер · <span class="ttl-sample"></span> смуга біля ціни — скільки лишилось до автоскасування</div>`;
  $$(".book-col", box).forEach((el) => (el.scrollTop = scroll[el.dataset.side] || 0));
  $$("tr[data-price]", box).forEach((r) => (r.onclick = () => {
    setPrice(+r.dataset.price);
    // clicking the side you would trade against also fills the quantity available up to that level
    const cumQty = +r.dataset.cum;
    if (st.side === "buy" && r.dataset.side === "ask") $("#qty").value = cumQty;
    if (st.side === "sell" && r.dataset.side === "bid") {
      const owned = st.me?.inventory.find((x) => x.item.id === st.selected)?.qty || 0;
      $("#qty").value = Math.max(1, Math.min(cumQty, owned || cumQty));
    }
    updateQuote();
  }));
}

// ---- trade form
function renderTradeForm(id) {
  const f = $("#trade-form");
  f.innerHTML = `
    <div class="side-tabs">
      <button class="buy ${st.side === "buy" ? "active" : ""}" data-side="buy">Купити</button>
      <button class="sell ${st.side === "sell" ? "active" : ""}" data-side="sell">Продати</button>
    </div>
    <div class="field"><label>Ціна за штуку</label>
      <div class="price-in">
        <div class="unit"><input id="p-g" type="number" min="0" value="0"><span style="color:var(--gold)">з</span></div>
        <div class="unit"><input id="p-s" type="number" min="0" max="99" value="0"><span style="color:var(--silver)">с</span></div>
        <div class="unit"><input id="p-c" type="number" min="0" max="99" value="0"><span style="color:var(--copper)">м</span></div>
      </div></div>
    <div class="quick" id="quick"></div>
    <div class="field"><label>Кількість <span id="owned-hint"></span></label>
      <div class="row"><input id="qty" type="number" min="1" value="1" style="flex:1">
        <button class="btn small" id="qty-max">макс</button></div></div>
    <div class="field"><label>Термін ордера</label>
      <select id="hours"><option value="12">12 год</option><option value="24" selected>24 год</option><option value="48">48 год</option><option value="72">72 год</option></select></div>
    <div class="quote" id="quote"></div>
    <div class="row" id="trade-btns"></div>`;
  $$(".side-tabs button", f).forEach((b) => (b.onclick = () => { st.side = b.dataset.side; renderTradeForm(id); refreshDetail(true); }));
  ["#p-g", "#p-s", "#p-c", "#qty", "#hours"].forEach((s) => $(s).addEventListener("input", debounce(updateQuote, 200)));
  $("#qty-max").onclick = () => {
    if (st.side === "sell") $("#qty").value = st.me?.inventory.find((x) => x.item.id === id)?.qty || 0;
    else $("#qty").value = Math.max(1, Math.floor((st.me?.gold || 0) / Math.max(1, getPrice())));
    updateQuote();
  };
  const btns = $("#trade-btns");
  if (st.side === "buy") {
    btns.innerHTML = `<button class="btn buy" id="b-now">⚡ Купити зараз</button><button class="btn" id="b-order">📝 Заявка на купівлю</button>`;
    $("#b-now").onclick = () => submitOrder("buy", 0);
    $("#b-order").onclick = () => submitOrder("buy", +$("#hours").value);
  } else {
    btns.innerHTML = `<button class="btn sell" id="s-order">🏷️ Виставити лот</button><button class="btn" id="s-now">⚡ Продати в заявки</button>
      <button class="btn ghost" id="s-vendor">🏪 Торговцю NPC</button>`;
    $("#s-order").onclick = () => submitOrder("sell", +$("#hours").value);
    $("#s-now").onclick = () => submitOrder("sell", 0);
    $("#s-vendor").onclick = () => act(() => api("/vendor", { method: "POST", body: { item_id: id, qty: +$("#qty").value } }), (r) => `Продано торговцю за ${money(r.earned, true)}`);
  }
}

function renderQuick() {
  const d = st.detail;
  if (!d) return;
  const q = [];
  if (d.best_ask) q.push(["Мін. лот", d.best_ask], ["Підрізати −1м", d.best_ask - 1], ["Підрізати −5%", Math.round(d.best_ask * 0.95)]);
  if (d.best_bid) q.push(["Макс. заявка", d.best_bid], ["Перебити +1м", d.best_bid + 1]);
  q.push(["Ринкова", Math.round(d.ref)]);
  $("#quick").innerHTML = q.filter(([, v]) => v > 0).map(([l, v]) => `<button class="btn small" data-v="${v}" title="${money(v, true)}">${l}</button>`).join("");
  $$("#quick button").forEach((b) => (b.onclick = () => { setPrice(+b.dataset.v); updateQuote(); }));
}

function setPrice(c) {
  c = Math.max(1, Math.round(c || 1));
  $("#p-g").value = Math.floor(c / 10000);
  $("#p-s").value = Math.floor((c % 10000) / 100);
  $("#p-c").value = c % 100;
}
const getPrice = () => (+$("#p-g").value || 0) * 10000 + (+$("#p-s").value || 0) * 100 + (+$("#p-c").value || 0);

async function updateQuote() {
  if (!st.selected || !$("#quote")) return;
  renderQuick();
  const id = st.selected, price = getPrice(), qty = +$("#qty").value || 0, hours = +$("#hours").value;
  const owned = st.me?.inventory.find((x) => x.item.id === id)?.qty || 0;
  $("#owned-hint").innerHTML = st.side === "sell" ? `(у вас ${owned})` : `(вистачить на ${num(Math.floor((st.me?.gold || 0) / Math.max(1, price)))})`;
  if (!qty || !price) return;
  const q = await api(`/quote?item_id=${id}&side=${st.side}&qty=${qty}&price=${price}&hours=${hours}`);
  const rows = st.side === "buy"
    ? [["Сума заявки", money(price * qty)], ["Миттєво доступно ≤ вашої ціни", q.worst_price && q.worst_price <= price ? `${q.instant_qty} шт` : "0 шт"],
       ["Якщо скупити всі " + q.instant_qty + " шт", money(q.instant_cost)]]
    : [["Миттєво в заявки", `${q.instant_qty} шт → ${money(q.instant_proceeds)}`],
       ["Орієнтовно продасться за", q.eta_hours === null ? '<span class="down">попиту майже немає</span>'
         : q.eta_hours > hours ? `<span class="down">~${fmtHours(q.eta_hours)} (довше за термін лота)</span>` : `~${fmtHours(q.eta_hours)}`],
       [`Депозит лоту`, money(q.deposit)],
       [`Комісія біржі ${q.cut_pct}%`, money(price * qty - q.net_if_sold)], ["Ви отримаєте, якщо продасться", money(q.net_if_sold)],
       ["Торговцю NPC дасть", money(st.items[id].vendor_price * qty)]];
  $("#quote").innerHTML = rows.map(([k, v]) => `<div><span class="muted">${k}</span><span>${v}</span></div>`).join("");
}

const fmtTicks = (t) => fmtHours(Math.max(0, t) / 6); // 1 tick = 10 game minutes
const fmtHours = (h) => (h < 1 ? `${Math.max(10, Math.round(h * 6) * 10)} хв` : h < 48 ? `${h.toFixed(h < 10 ? 1 : 0)} год` : `${(h / 24).toFixed(1)} дн`);

async function submitOrder(side, hours) {
  const body = { item_id: st.selected, side, price: getPrice(), qty: +$("#qty").value, hours };
  // fills are reported by the trade feed; here only what the feed won't say
  await act(() => api("/orders", { method: "POST", body }), (r) =>
    r.filled ? (r.filled < body.qty && hours ? `Решта ${body.qty - r.filled} шт — у книзі` : "")
      : hours ? "Ордер виставлено" : "Немає зустрічних ордерів за такою ціною");
}

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ------------------------------------------------------------------ inventory
const GRADES = ["Хлам", "Звичайний", "Добротний", "Рідкісний", "Цінний", "Легендарний"];
const LIQUIDITY = [[150, "🔥 Ходовий (150+ шт/добу)"], [20, "📈 Середній попит (20–150)"], [1, "🐢 Повільний (1–20)"], [0, "💤 Мертвий ринок (<1)"]];
let INV_COLLAPSED;
try { INV_COLLAPSED = new Set(JSON.parse(localStorage.getItem("invCollapsed") || "[]")); } catch { INV_COLLAPSED = new Set(); }
// The row order and group of every item are frozen when the view is (re)sorted, so live price
// updates change the numbers but never move rows around. New items are appended to their group.
st.inv = { snap: null, seq: 0 };

function invGroupOf(x, by) {
  const it = x.item;
  if (by === "category") return { key: it.category, label: it.category, order: it.is_junk ? "~" : it.category };
  if (by === "grade") return { key: it.grade, label: `<span class="grade g${it.grade}"></span><span class="g${it.grade}">${GRADES[it.grade]}</span>`, order: 9 - it.grade };
  if (by === "tier") return it.is_junk ? { key: "junk", label: "Хлам", order: 99 }
    : { key: it.tier, label: it.tier === 0 ? "Сировина" : `Крафт ${"★".repeat(it.tier)} (рівень ${it.tier})`, order: it.tier };
  if (by === "liquidity") {
    const k = LIQUIDITY.findIndex(([lo]) => x.sold_day >= lo);
    return { key: k, label: LIQUIDITY[k][1], order: k };
  }
  return { key: "all", label: "", order: 0 };
}

function invSortVal(x, by) {
  if (by === "value") return -x.value;
  if (by === "qty") return -x.qty;
  if (by === "grade") return -(x.item.grade * 1e9 + x.item.base_price);
  if (by === "price") return -x.item.ref;
  return 0;
}

function invResort() {
  const by = $("#inv-group").value, sort = $("#inv-sort").value;
  const rows = [...(st.me?.inventory || [])].sort((a, b) =>
    invSortVal(a, sort) - invSortVal(b, sort) || a.item.name.localeCompare(b.item.name, "uk"));
  st.inv.snap = { by, sort, pos: {} };
  rows.forEach((x, k) => (st.inv.snap.pos[x.item.id] = { k, g: invGroupOf(x, by) }));
  st.inv.seq = rows.length;
  renderInventory();
}

function renderInventory() {
  const me = st.me;
  if (!me) return;
  if (!st.inv.snap) return invResort();
  // lazily learn which items feed or equip workers (for the 🍞 / 🛠 hints)
  if (!st.workerRules) { st.workerRules = {}; api("/workers").then((d) => { st.workerRules = d.rules; renderInventory(); }).catch(() => {}); }
  const R = st.workerRules;
  const { by, pos } = st.inv.snap;
  for (const x of me.inventory) if (!pos[x.item.id]) pos[x.item.id] = { k: st.inv.seq++, g: invGroupOf(x, by) };

  const q = $("#inv-q").value.trim().toLowerCase(), hideJunk = $("#inv-junk").checked;
  const rows = me.inventory.filter((x) => (!q || x.item.name.toLowerCase().includes(q) || x.item.category.toLowerCase().includes(q))
    && !(hideJunk && x.item.is_junk));
  const total = me.inventory.reduce((s, x) => s + x.value, 0);
  const units = me.inventory.reduce((s, x) => s + x.qty, 0);
  $("#inv-summary").innerHTML = `${me.inventory.length} позицій · ${num(units)} шт · оцінка <b>${money(total)}</b> · у заявках ${money(me.escrow)}`;

  const groups = new Map();
  for (const x of rows) {
    const g = pos[x.item.id].g;
    if (!groups.has(g.key)) groups.set(g.key, { ...g, rows: [] });
    groups.get(g.key).rows.push(x);
  }
  const ordered = [...groups.values()].sort((a, b) => (a.order < b.order ? -1 : a.order > b.order ? 1 : 0));

  const row = (x) => {
    const it = x.item, m = st.marketById[it.id] || {};
    const food = R.nutrition?.[it.id], tool = R.tools?.[it.id];
    const uses = (food ? `<span class="use" title="Їжа для працівників: ${food} од. ситості">🍞${food}</span>` : "")
      + (tool ? `<span class="use" title="Інструмент: ${esc(tool.join(", "))}">🛠</span>` : "");
    const liq = x.sold_day >= 150 ? "up" : x.sold_day < 1 ? "down" : "";
    return `<tr>
      <td class="nm" data-open="${it.id}" title="${esc(it.name)} — ${GRADES[it.grade]}, ${esc(it.category)}">
        <span class="grade g${it.grade}"></span>${it.icon} <span class="t g${it.grade}">${esc(it.name)}</span>${uses}</td>
      <td class="num c-qty"><b>${num(x.qty)}</b></td>
      <td class="num c-px" title="Ринкова ціна за шт · найдешевший лот ${money(m.best_ask, true)} · найкраща заявка ${money(m.best_bid, true)}">${money(Math.round(it.ref))}</td>
      <td class="num c-liq ${liq}" title="Продається на ринку за добу">${num(x.sold_day)}/д</td>
      <td class="num c-val">${money(x.value)}</td>
      <td class="c-act"><button class="btn small sell" data-sell="${it.id}">Продати</button>
        <button class="btn small" data-vend="${it.id}" data-q="${x.qty}" title="${money(it.vendor_price * x.qty, true)}">NPC</button></td></tr>`;
  };
  const head = `<tr><th class="c-name">Товар</th><th class="num c-qty">К-сть</th><th class="num c-px">Ціна/шт</th>
    <th class="num c-liq">Попит</th><th class="num c-val">Оцінка</th><th class="c-act"></th></tr>`;
  const table = (rs) => `<table class="inv">${head}${rs.sort((a, b) => pos[a.item.id].k - pos[b.item.id].k).map(row).join("")}</table>`;

  const box = $("#inv-list");
  const scroll = window.scrollY;
  if (!rows.length) box.innerHTML = `<div class="muted">${me.inventory.length ? "Нічого не знайдено" : "Порожньо. Купіть щось на ринку або найміть працівників."}</div>`;
  else if (!by) box.innerHTML = table(rows);
  else box.innerHTML = ordered.map((g) => {
    const id = `${by}:${g.key}`;
    const val = g.rows.reduce((s, x) => s + x.value, 0);
    return `<details class="inv-group" data-g="${esc(id)}" ${INV_COLLAPSED.has(id) && !q ? "" : "open"}>
      <summary><b>${g.label}</b><span class="sum">${g.rows.length} поз. · ${money(val)}</span></summary>${table(g.rows)}</details>`;
  }).join("");
  window.scrollTo(0, scroll);

  $$("details.inv-group", box).forEach((d) => d.addEventListener("toggle", () => {
    if ($("#inv-q").value.trim()) return; // search force-opens groups; don't remember that
    d.open ? INV_COLLAPSED.delete(d.dataset.g) : INV_COLLAPSED.add(d.dataset.g);
    try { localStorage.setItem("invCollapsed", JSON.stringify([...INV_COLLAPSED])); } catch {}
  }));
  $$("[data-open]", box).forEach((td) => (td.onclick = () => selectItem(+td.dataset.open)));
  $$("[data-sell]", box).forEach((b) => (b.onclick = () => { st.side = "sell"; selectItem(+b.dataset.sell); }));
  $$("[data-vend]", box).forEach((b) => (b.onclick = () => {
    if (confirm(`Продати всі ${b.dataset.q} шт торговцю за ${b.title}?`))
      act(() => api("/vendor", { method: "POST", body: { item_id: +b.dataset.vend, qty: +b.dataset.q } }), (r) => `Отримано ${money(r.earned, true)}`);
  }));
}

(() => {
  const saved = (() => { try { return JSON.parse(localStorage.getItem("invView") || "{}"); } catch { return {}; } })();
  if (saved.group !== undefined) $("#inv-group").value = saved.group;
  if (saved.sort) $("#inv-sort").value = saved.sort;
  $("#inv-junk").checked = !!saved.junk;
  const save = () => { try { localStorage.setItem("invView", JSON.stringify({ group: $("#inv-group").value, sort: $("#inv-sort").value, junk: $("#inv-junk").checked })); } catch {} };
  ["#inv-group", "#inv-sort"].forEach((sel) => $(sel).addEventListener("change", () => { save(); invResort(); }));
  $("#inv-junk").addEventListener("change", () => { save(); renderInventory(); });
  $("#inv-q").addEventListener("input", () => renderInventory());
  $("#inv-resort").onclick = invResort;
  const setAll = (open) => $$("details.inv-group").forEach((d) => (d.open = open));
  $("#inv-expand").onclick = () => setAll(true);
  $("#inv-collapse").onclick = () => setAll(false);
})();

// ------------------------------------------------------------------ orders
async function refreshOrders() {
  const [orders, trades] = await Promise.all([api("/me/orders"), api("/me/trades")]);
  const open = orders.filter((o) => o.status === "open"), hist = orders.filter((o) => o.status !== "open");
  const statusName = { filled: "виконано", cancelled: "скасовано", expired: "прострочено" };
  $("#open-orders").innerHTML = open.length ? `<table><tr><th>Товар</th><th>Тип</th><th class="num">Ціна</th><th class="num">Залишок</th><th class="num">Ринок</th><th>Спливає</th><th></th></tr>
    ${open.map((o) => {
      const m = st.marketById[o.item_id] || {};
      const best = o.side === "sell" ? m.best_ask : m.best_bid;
      const beaten = best && (o.side === "sell" ? best < o.price : best > o.price);
      return `<tr><td><a href="#" data-item="${o.item_id}">${itemLabel(o.item)}</a></td><td>${o.side === "sell" ? '<span class="down">продаж</span>' : '<span class="up">купівля</span>'}</td>
      <td class="num">${money(o.price)}</td><td class="num">${o.qty_left}/${o.qty}</td>
      <td class="num">${money(best)} ${beaten ? '<span class="tag" style="color:var(--down)">перебито</span>' : ""}</td>
      <td class="small">${Math.round(o.expires_in / 6)} год</td><td><button class="btn small" data-cancel="${o.id}">✕</button></td></tr>`;
    }).join("")}</table>` : '<div class="muted">Немає активних ордерів</div>';
  $("#order-history").innerHTML = hist.length ? `<table><tr><th>Створено</th><th>Товар</th><th>Тип</th><th class="num">Ціна</th><th class="num">Виконано</th><th>Статус</th></tr>
    ${hist.slice(0, 80).map((o) => `<tr><td class="small muted">${o.created}</td><td>${itemLabel(o.item)}</td><td>${o.side === "sell" ? "продаж" : "купівля"}</td>
      <td class="num">${money(o.price)}</td><td class="num">${o.qty - o.qty_left}/${o.qty}</td><td>${statusName[o.status]}</td></tr>`).join("")}</table>` : '<div class="muted">Історія порожня</div>';
  $("#my-trades").innerHTML = trades.length ? `<div class="scroll"><table><tr><th>Час</th><th>Товар</th><th></th><th class="num">Ціна</th><th class="num">К-сть</th><th class="num">Сума</th><th>Контрагент</th></tr>
    ${trades.map((t) => `<tr><td class="small muted">${t.time}</td><td>${itemLabel(t.item)}</td><td>${t.side === "buy" ? '<span class="up">купили</span>' : '<span class="down">продали</span>'}</td>
      <td class="num">${money(t.price)}</td><td class="num">${t.qty}</td><td class="num">${money(t.price * t.qty)}</td><td class="small">${esc(t.side === "buy" ? t.seller : t.buyer)}</td></tr>`).join("")}</table></div>` : '<div class="muted">Угод ще не було</div>';
  $$("[data-cancel]").forEach((b) => (b.onclick = () => act(() => api(`/orders/${b.dataset.cancel}/cancel`, { method: "POST" }), "Ордер скасовано")));
  $$("#tab-orders [data-item]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); selectItem(+a.dataset.item); }));
}

// ------------------------------------------------------------------ crafting
// Recipe list: like the inventory, the order is frozen until the user changes sorting (or presses ↻),
// so prices ticking every few seconds don't shuffle rows under the cursor.
st.rc = { snap: null, seq: 0, view: "graph", times: 1, tree: null, treeKey: null };
let RC_COLLAPSED;
try { RC_COLLAPSED = new Set(JSON.parse(localStorage.getItem("rcCollapsed") || "[]")); } catch { RC_COLLAPSED = new Set(); }
(() => {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("rcView") || "{}"); } catch {}
  for (const [id, v] of Object.entries(saved)) {
    const el = $("#" + id);
    if (el) el.type === "checkbox" ? (el.checked = v) : (el.value = v);
  }
  const ids = ["prof-filter", "rc-group", "rc-sort", "only-craftable", "rc-partial", "rc-profit", "rc-workers", "show-alt"];
  const save = () => {
    try { localStorage.setItem("rcView", JSON.stringify(Object.fromEntries(ids.map((id) => { const el = $("#" + id); return [id, el.type === "checkbox" ? el.checked : el.value]; })))); } catch {}
  };
  ids.forEach((id) => $("#" + id).addEventListener("change", () => { save(); id === "rc-group" || id === "rc-sort" ? rcResort() : renderRecipes(); }));
  $("#rc-q").addEventListener("input", renderRecipes);
  $("#rc-resort").onclick = rcResort;
})();

async function refreshRecipes(periodic = false) {
  st.recipes = await api("/craft/recipes");
  renderRecipes();
  if (st.selRecipe) {
    if (!periodic || !$("#craft-detail").contains(document.activeElement)) renderRecipeCard();
    loadTree(periodic);
  }
}

const rcGroupOf = (r, by) => {
  const o = r.output;
  if (by === "profession") return { key: r.profession, label: `${profIcon[r.profession] || ""} ${esc(r.profession_name)}`, order: r.profession_name };
  if (by === "category") return { key: o.category, label: esc(o.category), order: o.category };
  if (by === "tier") return { key: o.tier, label: r.is_alt ? "Переробка" : `Рівень ${o.tier} ${"★".repeat(o.tier)}`, order: o.tier };
  if (by === "grade") return { key: o.grade, label: `<span class="grade g${o.grade}"></span><span class="g${o.grade}">${GRADES[o.grade]}</span>`, order: 9 - o.grade };
  return { key: "all", label: "", order: 0 };
};
const rcReady = (r) => r.ingredients.reduce((s, g, k) => s + r.have[k] / g.qty, 0) / r.ingredients.length;
const rcSortVal = (r, by) => ({
  profit: -(r.profit ?? -1e12), margin: -(r.margin ?? -1e9), value: -(r.output.ref * r.output_qty),
  liquidity: -r.sold_day, ready: -(r.can_craft * 10 + rcReady(r)), tier: r.output.tier, name: 0,
}[by]);

function rcResort() {
  const by = $("#rc-group").value, sort = $("#rc-sort").value;
  const rows = [...st.recipes].sort((a, b) => rcSortVal(a, sort) - rcSortVal(b, sort) || a.output.name.localeCompare(b.output.name, "uk"));
  st.rc.snap = { by, pos: {} };
  rows.forEach((r, k) => (st.rc.snap.pos[r.id] = { k, g: rcGroupOf(r, by) }));
  st.rc.seq = rows.length;
  renderRecipes();
}

function renderRecipes() {
  if (!st.recipes.length) return;
  if (!st.rc.snap) return rcResort();
  const { by, pos } = st.rc.snap;
  const prof = $("#prof-filter").value, only = $("#only-craftable").checked, alt = $("#show-alt").checked,
    partial = $("#rc-partial").checked, prof_only = $("#rc-profit").checked, mine = $("#rc-workers").checked;
  const q = $("#rc-q").value.trim().toLowerCase();
  const rows = st.recipes.filter((r) => (!prof || r.profession === prof) && (!only || r.can_craft > 0) && (alt || !r.is_alt)
    && (!partial || r.have.some((h) => h > 0)) && (!prof_only || r.profit > 0) && (!mine || r.known_by.length)
    && (!q || r.output.name.toLowerCase().includes(q) || r.ingredients.some((g) => g.item.name.toLowerCase().includes(q))));
  for (const r of rows) if (!pos[r.id]) pos[r.id] = { k: st.rc.seq++, g: rcGroupOf(r, by) };
  rows.sort((a, b) => pos[a.id].k - pos[b.id].k);
  $("#rc-count").textContent = `${rows.length} з ${st.recipes.length} рецептів · можна зробити зараз: ${st.recipes.filter((r) => r.can_craft).length}`;

  const row = (r) => `
    <div class="recipe-row ${r.id === st.selRecipe ? "sel" : ""}" data-id="${r.id}">
      <div class="icon">${r.output.icon}</div>
      <div><div class="t"><span class="grade g${r.output.grade}"></span><span class="g${r.output.grade}">${esc(r.output.name)}</span> ×${r.output_qty}
          ${r.output.tier ? `<span class="stars-s">${"★".repeat(r.output.tier)}</span>` : ""}
          ${r.is_alt ? '<span class="tag">переробка</span>' : ""}${r.known_by.length ? ` <span title="Знають: ${esc(r.known_by.join(", "))}">👷</span>` : ""}</div>
        <div class="ings">${r.ingredients.map((g, k) => `<span class="ing ${r.have[k] >= g.qty ? "ok" : r.have[k] ? "part" : ""}" title="${esc(g.item.name)}: є ${r.have[k]} з ${g.qty}">${g.item.icon}${g.qty}</span>`).join("")}
          ${r.can_craft ? `<span class="small up">✓ ×${r.can_craft}</span>` : ""}</div></div>
      <div class="num small">${money(r.profit)}<br>${pct(r.margin)}</div>
    </div>`;
  const list = $("#recipe-list"), scroll = list.scrollTop;
  if (!rows.length) list.innerHTML = '<div class="muted small" style="padding:8px">Нічого не знайдено</div>';
  else if (!by) list.innerHTML = rows.map(row).join("");
  else {
    const groups = new Map();
    for (const r of rows) {
      const g = pos[r.id].g;
      if (!groups.has(g.key)) groups.set(g.key, { ...g, rows: [] });
      groups.get(g.key).rows.push(r);
    }
    list.innerHTML = [...groups.values()].sort((a, b) => (a.order < b.order ? -1 : a.order > b.order ? 1 : 0)).map((g) => {
      const id = `${by}:${g.key}`;
      return `<details class="rc-group" data-g="${esc(id)}" ${RC_COLLAPSED.has(id) && !q ? "" : "open"}>
        <summary>${g.label}<span class="n">${g.rows.length}${g.rows.some((r) => r.can_craft) ? ` · <span class="up">✓${g.rows.filter((r) => r.can_craft).length}</span>` : ""}</span></summary>
        ${g.rows.map(row).join("")}</details>`;
    }).join("");
    $$("details.rc-group", list).forEach((d) => d.addEventListener("toggle", () => {
      if ($("#rc-q").value.trim()) return;
      d.open ? RC_COLLAPSED.delete(d.dataset.g) : RC_COLLAPSED.add(d.dataset.g);
      try { localStorage.setItem("rcCollapsed", JSON.stringify([...RC_COLLAPSED])); } catch {}
    }));
  }
  list.scrollTop = scroll;
  $$("#recipe-list .recipe-row").forEach((e) => (e.onclick = () => selectRecipe(+e.dataset.id)));
}

async function selectRecipe(id) {
  if (!st.recipes.length) await refreshRecipes();
  if (st.selRecipe !== id) st.rc.times = 1;
  st.selRecipe = id;
  $$("#recipe-list .recipe-row").forEach((e) => e.classList.toggle("sel", +e.dataset.id === id));
  // make sure the chosen recipe is visible even if filters hide it or its group is collapsed
  const el = $(`#recipe-list .recipe-row[data-id="${id}"]`);
  if (el) { const d = el.closest("details"); if (d) d.open = true; el.scrollIntoView({ block: "nearest" }); }
  st.rc.tree = null;
  renderRecipeCard();
  loadTree();
}

async function loadTree(periodic = false) {
  const r = st.recipes.find((x) => x.id === st.selRecipe);
  if (!r) return;
  const key = `${r.id}:${st.rc.times}`;
  const tree = await api(`/craft/tree/${r.output.id}?qty=${r.output_qty * st.rc.times}&recipe_id=${r.id}`);
  if (`${st.selRecipe}:${st.rc.times}` !== key) return; // a newer selection won the race
  st.rc.tree = tree;
  renderCraftGraph(periodic);
  renderCraftPlan();
}

function renderRecipeCard() {
  const r = st.recipes.find((x) => x.id === st.selRecipe);
  if (!r) return;
  const o = r.output, n = st.rc.times;
  const uses = st.recipes.filter((x) => x.ingredients.some((g) => g.item.id === o.id) && x.id !== r.id);
  const alts = st.recipes.filter((x) => x.output.id === o.id && x.id !== r.id);
  $("#craft-detail").innerHTML = `
    <div class="rc-head"><span class="big">${o.icon}</span>
      <div style="flex:1"><h2><span class="g${o.grade}">${esc(o.name)}</span> ×${r.output_qty}</h2>
        <div class="small muted"><span class="grade g${o.grade}"></span>${GRADES[o.grade]} · ${esc(o.category)} · ${o.tier ? `рівень ${o.tier} ${"★".repeat(o.tier)}` : "сировина"}
          · ${profIcon[r.profession] || ""} ${esc(r.profession_name)}${r.is_alt ? " · переробка хламу" : ""}
          · попит ${num(r.sold_day)} шт/добу${r.known_by.length ? ` · 👷 знають: ${esc(r.known_by.join(", "))}` : ""}</div></div></div>
    <div class="stats">
      <div class="stat"><div class="k">Інгредієнти за лотами</div><div class="v">${money(r.cost_ask * n)}</div></div>
      <div class="stat"><div class="k">Інгредієнти за ринком</div><div class="v">${money(r.cost_ref * n)}</div></div>
      <div class="stat"><div class="k">Виручка після комісії</div><div class="v">${money(r.value * n)}</div></div>
      <div class="stat"><div class="k">Прибуток / маржа</div><div class="v">${money(r.profit * n)} ${pct(r.margin)}</div></div>
    </div>
    <div class="rc-actions">
      <span class="small muted">Партій:</span>
      <input type="number" id="craft-times" min="1" max="1000" value="${n}" style="width:80px">
      ${[1, 5, 10, 25].map((k) => `<button class="btn small" data-times="${k}">${k}</button>`).join("")}
      ${r.can_craft ? `<button class="btn small" data-times="${r.can_craft}">макс ${r.can_craft}</button>` : ""}
      <button class="btn primary" id="craft-btn" ${r.can_craft >= n ? "" : "disabled"} title="${r.can_craft >= n ? "" : "Не вистачає інгредієнтів — див. план нижче"}">🔨 Створити ${n * r.output_qty} шт</button>
      <button class="btn" id="craft-market">📈 На ринок</button>
    </div>
    ${alts.length ? `<div class="small muted" style="margin-bottom:6px">Інші рецепти цього предмета: ${alts.map((x) => `<a href="#" data-recipe="${x.id}">${esc(x.profession_name)}${x.is_alt ? " (переробка)" : ""}</a>`).join(", ")}</div>` : ""}
    <div class="row between" style="margin-top:6px">
      <h3 style="margin:0">🕸️ Граф крафту</h3>
      <span class="seg2"><button data-view="graph" class="${st.rc.view === "graph" ? "active" : ""}">Граф</button><button data-view="tree" class="${st.rc.view === "tree" ? "active" : ""}">Список</button></span>
    </div>
    <p class="small muted" style="margin:4px 0 6px">Ліва смужка вузла: <span class="up">є в інвентарі</span> · <span style="color:var(--accent)">частково</span> · <span class="down">немає</span>.
      Зеленим — дешевший шлях: 🛒 купити готове чи 🔨 зробити. Клік по вузлу — відкрити його рецепт, подвійний клік — ринок.</p>
    <div id="rc-graph"><span class="muted">завантаження…</span></div>
    <h3 style="margin-top:16px">🧾 План: що потрібно на ${n} ${n === 1 ? "партію" : "партій"}</h3>
    <div id="rc-plan"><span class="muted">завантаження…</span></div>
    <h3 style="margin-top:16px">↗️ Де використовується ${esc(o.name)}</h3>
    <div class="uses">${uses.length ? uses.map((x) => `<span class="recipe-chip" data-recipe="${x.id}" title="${esc(x.profession_name)} · прибуток ${money(x.profit, true)}">${x.output.icon} ${esc(x.output.name)}</span>`).join("")
      : '<span class="muted small">Ні в чому — це кінцевий товар (продається споживачам)</span>'}</div>`;
  if (st.rc.tree) { renderCraftGraph(); renderCraftPlan(); }

  const setTimes = (k) => { st.rc.times = Math.max(1, Math.min(1000, k | 0 || 1)); renderRecipeCard(); loadTree(); };
  let deb;
  $("#craft-times").oninput = (e) => { clearTimeout(deb); deb = setTimeout(() => setTimes(+e.target.value), 400); };
  $$("[data-times]", $("#craft-detail")).forEach((b) => (b.onclick = () => setTimes(+b.dataset.times)));
  $("#craft-btn").onclick = () => act(() => api("/craft", { method: "POST", body: { recipe_id: r.id, times: st.rc.times } }), (x) => `Створено ${x.crafted} шт`);
  $("#craft-market").onclick = () => selectItem(o.id);
  $$("[data-view]", $("#craft-detail")).forEach((b) => (b.onclick = () => { st.rc.view = b.dataset.view; renderRecipeCard(); }));
  $$("#craft-detail [data-recipe]").forEach((e) => (e.onclick = (ev) => { ev.preventDefault(); selectRecipe(+e.dataset.recipe); }));
}

// ---- graph: the recipe tree folded into a DAG (same item from several branches = one node)
function renderCraftGraph(keepScroll = true) {
  const box = $("#rc-graph");
  if (!box || !st.rc.tree) return;
  if (st.rc.view === "tree") {
    box.innerHTML = `<div class="tree"><ul>${renderNode(st.rc.tree)}</ul></div>`;
    $$(".toggle", box).forEach((t) => (t.onclick = () => {
      const ul = t.parentElement.querySelector(":scope > ul");
      if (ul) { ul.classList.toggle("hidden"); t.textContent = ul.classList.contains("hidden") ? "▸" : "▾"; }
    }));
    $$("[data-item]", box).forEach((e) => (e.onclick = () => openItemRecipe(+e.dataset.item)));
    return;
  }
  const inv = Object.fromEntries((st.me?.inventory || []).map((x) => [x.item.id, x.qty]));
  const nodes = new Map(), edges = new Map();
  (function walk(n, depth, parent) {
    let v = nodes.get(n.item.id);
    if (!v) nodes.set(n.item.id, (v = { item: n.item, qty: 0, depth, buy: 0, craft: 0, canBuy: true, canCraft: !!n.recipe, gather: n.gather, prof: n.recipe?.profession }));
    v.qty += n.qty;
    v.depth = Math.max(v.depth, depth);
    if (n.buy_cost === null) v.canBuy = false; else v.buy += n.buy_cost;
    if (n.recipe) v.craft += n.craft_cost;
    if (parent !== undefined) {
      const k = `${n.item.id}>${parent}`;
      edges.set(k, (edges.get(k) || 0) + n.qty);
    }
    for (const ch of n.recipe?.children || []) walk(ch, depth + 1, n.item.id);
  })(st.rc.tree, 0);
  // an item used both near the root and deep down must sit left of everything that consumes it
  let changed = true;
  while (changed) {
    changed = false;
    for (const k of edges.keys()) {
      const [c, p] = k.split(">").map(Number);
      if (nodes.get(c).depth <= nodes.get(p).depth) { nodes.get(c).depth = nodes.get(p).depth + 1; changed = true; }
    }
  }
  const W = 184, H = 58, GX = 70, GY = 14, PAD = 12;
  const maxD = Math.max(...[...nodes.values()].map((v) => v.depth));
  const cols = [];
  for (const v of nodes.values()) (cols[v.depth] ||= []).push(v);
  // order each column by the average position of its consumers (fewer crossing edges)
  cols.forEach((col, d) => {
    if (d === 0) { col[0].y = 0; return; }
    for (const v of col) {
      const ys = [...edges.keys()].filter((k) => +k.split(">")[0] === v.item.id).map((k) => nodes.get(+k.split(">")[1]).y ?? 0);
      v.order = ys.reduce((a, b) => a + b, 0) / (ys.length || 1);
    }
    col.sort((a, b) => a.order - b.order || a.item.name.localeCompare(b.item.name, "uk"));
    col.forEach((v, k) => (v.y = k));
  });
  const tallest = Math.max(...cols.map((c) => c.length));
  for (const col of cols) {
    const off = (tallest - col.length) / 2;
    col.forEach((v) => { v.py = PAD + (v.y + off) * (H + GY); v.px = PAD + (maxD - v.depth) * (W + GX); });
  }
  const width = PAD * 2 + (maxD + 1) * W + maxD * GX, height = PAD * 2 + tallest * H + (tallest - 1) * GY;

  const paths = [...edges.entries()].map(([k, q]) => {
    const [c, p] = k.split(">").map(Number), a = nodes.get(c), b = nodes.get(p);
    const x1 = a.px + W, y1 = a.py + H / 2, x2 = b.px, y2 = b.py + H / 2, dx = (x2 - x1) / 2;
    return `<path data-e="${c}>${p}" d="M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}"/>
      <text x="${x2 - 6}" y="${y2 - 4}" text-anchor="end">×${num(q)}</text>`;
  }).join("");
  const nodeHtml = [...nodes.values()].map((v) => {
    const have = inv[v.item.id] || 0;
    const cls = have >= v.qty ? "have" : have > 0 ? "part" : "none";
    const craftBetter = v.canCraft && (!v.canBuy || v.craft < v.buy);
    const buy = v.canBuy ? `<span class="${craftBetter ? "" : "best"}">🛒${money(v.buy, true)}</span>` : "🛒—";
    const craft = v.canCraft ? ` · <span class="${craftBetter ? "best" : ""}">🔨${money(v.craft, true)}</span>` : "";
    const src = v.depth === 0 ? `🔨 ${money(v.craft, true)} собівартість` : `${buy}${craft}${!v.canCraft && v.gather ? ` · ⛏${esc(v.gather)}` : ""}`;
    return `<div class="gnode ${cls} ${v.depth === 0 ? "root" : ""}" data-n="${v.item.id}" style="left:${v.px}px;top:${v.py}px"
        title="${esc(v.item.name)} — потрібно ${v.qty}, є ${have}${v.prof ? ` · робить: ${esc(v.prof)}` : ""}">
      <div class="l1">${v.item.icon}<span class="nm g${v.item.grade}">${esc(v.item.name)}</span><span class="q">${num(v.qty)}</span></div>
      <div class="l2">є ${num(have)}${have >= v.qty ? " ✓" : ""}</div>
      <div class="l2">${src}</div></div>`;
  }).join("");

  const old = $(".cgraph-wrap", box), sl = old?.scrollLeft, stp = old?.scrollTop;
  box.innerHTML = `<div class="cgraph-wrap"><div class="cgraph" style="width:${width}px;height:${height}px">
    <svg width="${width}" height="${height}">${paths}</svg>${nodeHtml}</div></div>`;
  const wrap = $(".cgraph-wrap", box);
  if (keepScroll && old) { wrap.scrollLeft = sl; wrap.scrollTop = stp; } else wrap.scrollLeft = wrap.scrollWidth; // result is on the right
  $$(".gnode", box).forEach((g) => {
    const id = +g.dataset.n;
    g.onmouseenter = () => $$("path", box).forEach((p) => p.classList.toggle("hl", p.dataset.e.split(">").map(Number).includes(id)));
    g.onmouseleave = () => $$("path.hl", box).forEach((p) => p.classList.remove("hl"));
    g.onclick = () => openItemRecipe(id);
    g.ondblclick = () => selectItem(id);
  });
}

function openItemRecipe(itemId) {
  const r = st.recipes.find((x) => x.output.id === itemId && !x.is_alt);
  if (r && r.id !== st.selRecipe) selectRecipe(r.id);
  else if (!r) selectItem(itemId);
}

// ---- plan: walk the tree using stock first, then the cheaper of buy/craft; gives a shopping list and craft steps
function renderCraftPlan() {
  const box = $("#rc-plan");
  if (!box || !st.rc.tree) return;
  const stock = Object.fromEntries((st.me?.inventory || []).map((x) => [x.item.id, x.qty]));
  const buy = new Map(), steps = new Map(), used = new Map();
  (function need(n, q, root) {
    if (!root) {
      const take = Math.min(stock[n.item.id] || 0, q);
      if (take) { stock[n.item.id] -= take; used.set(n.item.id, { item: n.item, qty: (used.get(n.item.id)?.qty || 0) + take }); }
      q -= take;
    }
    if (q <= 0) return;
    const craftBetter = n.recipe && (n.buy_cost === null || n.craft_cost < n.buy_cost);
    if (root || craftBetter) {
      const batches = Math.ceil(q / n.recipe.output_qty);
      for (const ch of n.recipe.children) need(ch, (ch.qty / n.recipe.batches) * batches);
      const s = steps.get(n.item.id) || { item: n.item, batches: 0, qty: 0, prof: n.recipe.profession };
      s.batches += batches; s.qty += batches * n.recipe.output_qty;
      steps.set(n.item.id, s);
    } else {
      const unit = (n.buy_cost ?? n.ref_cost) / n.qty;
      const b = buy.get(n.item.id) || { item: n.item, qty: 0, cost: 0, noLots: n.buy_cost === null, gather: n.gather };
      b.qty += q; b.cost += unit * q;
      buy.set(n.item.id, b);
    }
  })(st.rc.tree, st.rc.tree.qty, true);
  const toBuy = [...buy.values()], total = toBuy.reduce((s, b) => s + b.cost, 0);
  const r = st.recipes.find((x) => x.id === st.selRecipe);
  const revenue = r ? r.value * st.rc.times : 0;
  box.innerHTML = `
    <div class="grid2">
      <div><div class="small muted">🛒 Докупити</div>
        ${toBuy.length ? `<table class="plan"><tr><th>Товар</th><th class="num">К-сть</th><th class="num">≈ Вартість</th></tr>
          ${toBuy.map((b) => `<tr><td><a href="#" data-item="${b.item.id}">${b.item.icon} ${esc(b.item.name)}</a>${b.noLots ? ` <span class="down small" title="Немає лотів — оцінка за ринковою ціною">немає лотів${b.gather ? ` · ⛏ ${esc(b.gather)}` : ""}</span>` : ""}</td>
            <td class="num">${num(b.qty)}</td><td class="num">${money(b.cost)}</td></tr>`).join("")}
          <tr><td><b>Разом</b></td><td></td><td class="num"><b>${money(total)}</b></td></tr></table>`
          : '<div class="up">Усе є в інвентарі ✓</div>'}
        ${used.size ? `<div class="small muted" style="margin-top:6px">З інвентаря: ${[...used.values()].map((u) => `${u.item.icon}${num(u.qty)}`).join(" ")}</div>` : ""}
      </div>
      <div><div class="small muted">🔨 Порядок крафту</div>
        <ol class="small" style="margin:4px 0;padding-left:20px">${[...steps.values()].reverse().map((s) =>
          `<li>${s.item.icon} ${esc(s.item.name)} ×${num(s.qty)} <span class="muted">(${s.batches} парт., ${esc(s.prof)})</span></li>`).join("")}</ol>
        <div class="small" style="margin-top:6px">Докупка ${money(total)} → виручка ${money(revenue)} =
          <b class="${revenue - total >= 0 ? "up" : "down"}">${money(revenue - total)}</b>
          <span class="muted">(без урахування того, що вже є в інвентарі)</span></div>
      </div>
    </div>`;
  $$("[data-item]", box).forEach((e) => (e.onclick = (ev) => { ev.preventDefault(); selectItem(+e.dataset.item); }));
}

function renderNode(n) {
  const kids = n.recipe?.children || [];
  const craftCheaper = n.craft_cost !== null && (n.buy_cost === null || n.craft_cost < n.buy_cost);
  return `<li>
    <span class="toggle">${kids.length ? "▾" : ""}</span>
    <span class="node"><span class="q">${num(n.qty)}×</span><span data-item="${n.item.id}" style="cursor:pointer">${itemLabel(n.item)}</span>
      <span class="src">купити: ${n.buy_cost !== null ? `<span class="${!craftCheaper ? "cheaper" : ""}">${money(n.buy_cost)}</span>` : '<span class="down">немає лотів</span>'}</span>
      ${n.recipe ? `<span class="src">зробити (${esc(n.recipe.profession)}, ${n.recipe.batches}×): <span class="${craftCheaper ? "cheaper" : ""}">${money(n.craft_cost)}</span></span>` : ""}
      ${n.gather ? `<span class="tag">видобуває ${esc(n.gather)}</span>` : ""}
    </span>
    ${kids.length ? `<ul>${kids.map(renderNode).join("")}</ul>` : ""}
  </li>`;
}

// ------------------------------------------------------------------ workers
const GOOD_TRAITS = new Set(["hardworking", "lucky", "careful", "modest", "thrifty", "nightowl", "smart"]);
const BAD_TRAITS = new Set(["lazy", "glutton", "drunk", "greedy"]);
const wlogIcon = { hire: "🤝", level: "🎉", hungry: "🍞", beer: "🍺", unpaid: "💸", no_tool: "🛠️", tool_broken: "🔨",
  quit: "🚪", ended: "📜", fired: "🚪", renew: "📜" };
st.hireForm = {};
st.taskDraft = {};
["#w-role", "#w-prof", "#w-sort"].forEach((sel) => $(sel).addEventListener("input", () => renderWorkers()));

async function refreshWorkers(periodic = false) {
  // don't yank a dropdown or an input from under the user
  if (periodic && $("#tab-workers").contains(document.activeElement) && document.activeElement !== document.body) return;
  st.workers = await api("/workers");
  renderWorkers();
}

const stars = (l) => "★".repeat(l) + "☆".repeat(5 - l);
const itemChip = (id, extra = "") => { const it = st.items[id]; return `<span class="chip" title="${esc(it.name)}">${it.icon} ${esc(it.name)}${extra}</span>`; };
const traitTags = (w) => w.traits.map((t) => `<span class="trait ${GOOD_TRAITS.has(t.code) ? "good" : BAD_TRAITS.has(t.code) ? "bad" : ""}" title="${esc(t.desc)}">${esc(t.name)}</span>`).join(" ");
const moraleColor = (v) => (v >= 70 ? "var(--up)" : v >= 40 ? "var(--accent)" : "var(--down)");

function workerHead(w, right) {
  return `<div class="whead"><span class="wicon">${profIcon[w.profession] || "👷"}</span>
    <div class="who"><b>${esc(w.name)}</b> <span class="stars" title="${esc(w.level_name)}">${stars(w.level)}</span>
      <div class="small muted">${esc(w.level_name)} · ${esc(w.profession_name)}${w.spec ? ` · спец.: ${esc(w.spec)} (+30%)` : ""}</div></div>
    <div class="wstatus">${right}</div></div>
    ${w.traits.length ? `<div>${traitTags(w)}</div>` : ""}`;
}

function wageFor(w, f) {
  const r = st.workers.rules;
  return Math.max(1, Math.round(w.ask_wage * r.durations[f.days] * (f.food ? 1 - r.food_discount : 1) * (f.tool ? 1 - r.tool_discount : 1)));
}

function renderWorkers() {
  const d = st.workers;
  if (!d) return;
  const inv = Object.fromEntries((st.me?.inventory || []).map((x) => [x.item.id, x.qty]));
  const L = d.license, P = d.pantry;

  $("#w-summary").innerHTML = `<div class="w-summary">
    <div><div class="small muted">Ліцензія гільдії</div><b>${L.used} / ${L.slots}</b> працівників
      ${L.next ? `<button class="btn small" id="w-license">Розширити до ${L.next.slots} за ${money(L.next.price)}</button>` : '<span class="tag">максимум</span>'}</div>
    <div><div class="small muted">Фонд зарплат</div><b>${money(d.wage_bill)}</b> / день</div>
    <div><div class="small muted">Комора (для працівників на харчуванні)</div>
      <b>${num(P.nutrition)}</b> од. ситості${P.daily_need ? ` → вистачить на <b class="${P.days < 1 ? "down" : P.days < 3 ? "" : "up"}">${P.days} дн</b> (потреба ${num(P.daily_need)}/день)` : ""}
      ${P.beer_need ? `<br>🍺 Пиво: ${P.beer} (пиякам ${P.beer_need}/день)` : ""}</div>
    <div><div class="small muted">Ситість їжі</div><div class="chips">${Object.entries(d.rules.nutrition)
      .sort((a, b) => b[1] - a[1]).map(([id, n]) => itemChip(+id, ` · ${n}${inv[id] ? ` · є ${inv[id]}` : ""}`)).join("")}</div></div>
  </div>`;
  $("#w-license")?.addEventListener("click", () => act(() => api("/license/upgrade", { method: "POST" }), (r) => `Ліцензію розширено: ${r.slots} місць`).then(() => refreshWorkers()));

  // ---- my workers
  $("#w-mine").innerHTML = d.mine.map((w) => {
    const toolsHave = w.tools.filter((t) => inv[t.item_id]);
    const toolRow = w.tool
      ? `${itemChip(w.tool.item_id, ` +${Math.round(w.tool.bonus * 100)}%`)}
         <div class="meter" title="Знос: ${w.tool.durability}%"><div style="width:${w.tool.durability}%;background:${w.tool.durability < 25 ? "var(--down)" : "var(--accent)"}"></div></div>
         <button class="btn small" data-unequip="${w.id}">Зняти</button>`
      : toolsHave.length
        ? `<select data-equip-sel="${w.id}">${toolsHave.map((t) => `<option value="${t.item_id}">${st.items[t.item_id].icon} ${esc(st.items[t.item_id].name)} (+${Math.round(t.bonus * 100)}%) · є ${inv[t.item_id]}</option>`).join("")}</select>
           <button class="btn small primary" data-equip="${w.id}">Видати</button>`
        : `<span class="small ${w.tool_provided ? "down" : "muted"}">${w.tool_provided ? "Обіцяли інструмент, але не видали! " : "Власний простий інструмент. "}Підійде:
           ${w.tools.map((t) => `<a href="#" data-item="${t.item_id}">${st.items[t.item_id].icon} ${esc(st.items[t.item_id].name)}</a> +${Math.round(t.bonus * 100)}%`).join(", ")}</span>`;
    let job;
    if (w.role === "gatherer") {
      job = `<div class="wrow"><span class="k">Що збирати</span><select data-focus="${w.id}">
        <option value="">Будь-що (${w.finds.length} видів)</option>
        ${w.finds.map((i) => `<option value="${i}" ${w.focus_item_id === i ? "selected" : ""}>${st.items[i].icon} ${esc(st.items[i].name)}</option>`).join("")}
      </select></div>`;
    } else {
      const draft = st.taskDraft[w.id] || w.tasks.map((t) => ({ ...t }));
      const recipeOpts = (sel) => w.recipes.map((rid) => {
        const r = st.recipes.find((x) => x.id === rid);
        return r ? `<option value="${rid}" ${rid === sel ? "selected" : ""}>${r.output.icon} ${esc(r.output.name)} ×${r.output_qty}${r.is_alt ? " (переробка)" : ""}</option>` : "";
      }).join("");
      job = `<div><div class="small muted">Черга (перший можливий рецепт; «запас» — зупинитись, коли на складі стільки):</div>
        ${draft.map((t, k) => `<div class="task"><select data-task-r="${w.id}:${k}">${recipeOpts(t.recipe_id)}</select>
          <input type="number" min="0" placeholder="запас" title="Тримати запас (0 = без ліміту)" value="${t.keep || ""}" data-task-k="${w.id}:${k}">
          <button class="btn small" data-task-del="${w.id}:${k}">✕</button></div>`).join("") || '<div class="small down">Немає завдань — ремісник простоює</div>'}
        <div class="wrow" style="margin-top:4px">${draft.length < 3 ? `<button class="btn small" data-task-add="${w.id}">+ рецепт</button>` : ""}
          ${st.taskDraft[w.id] ? `<button class="btn small primary" data-task-save="${w.id}">Зберегти чергу</button>` : ""}
          <span class="small muted">знає ${w.recipes.length} рецептів</span></div></div>`;
    }
    const left = w.days_left, payIn = fmtTicks(w.next_pay_in);
    return `<div class="wcard ${w.hungry ? "hungry" : ""}">
      ${workerHead(w, `${esc(w.status_name)}${w.status_detail ? `<div class="small muted">${esc(w.status_detail)}</div>` : ""}`)}
      <div class="wrow"><span class="k">Настрій</span><div class="meter"><div style="width:${w.morale}%;background:${moraleColor(w.morale)}"></div></div><span class="small">${w.morale}</span></div>
      <div class="wrow"><span class="k">Досвід</span><span class="small">${w.xp} ${w.next_level_xp ? `/ ${w.next_level_xp} дн до «${esc(st.workers.rules.levels[w.level + 1])}»` : "(максимум)"}</span></div>
      <div class="wrow"><span class="k">Контракт</span><span class="small">ще <b>${left} дн</b> · ${money(w.wage)}/день · виплата через ${payIn}
        ${w.food_provided ? " · 🍞 ваше харчування" : ""}${w.tool_provided ? " · 🛠 ваш інструмент" : ""}${w.unpaid ? ' · <span class="down">борг по ЗП!</span>' : ""}</span></div>
      <div class="wrow"><span class="k">Інструмент</span>${toolRow}</div>
      ${job}
      <div class="wrow"><span class="k">Сьогодні</span><div class="chips">${w.today.length ? w.today.sort((a, b) => b.qty * st.items[b.item_id].base_price - a.qty * st.items[a.item_id].base_price)
        .map((t) => itemChip(t.item_id, ` ×${num(t.qty)}`)).join("") : '<span class="small muted">ще нічого</span>'}</div></div>
      <div class="wrow"><span class="k">Виробіток</span><span class="small">≈ ${money(w.daily_value)}/день за базовими цінами · окупність ${(w.daily_value / w.wage).toFixed(1)}×</span></div>
      <div class="wrow">
        <button class="btn small" data-renew="${w.id}" title="Нова ЗП з урахуванням рівня">Продовжити на 3 дні (${money(w.renew_wage, true)}/день)</button>
        <button class="btn small sell" data-fire="${w.id}" data-name="${esc(w.name)}" data-pen="${money(w.wage, true)}">Звільнити</button>
      </div>
    </div>`;
  }).join("") || '<div class="muted">Поки нікого. Найміть когось на ринку праці нижче — почніть із збирача або дешевого збирача хламу.</div>';

  // ---- labor market
  const role = $("#w-role").value, prof = $("#w-prof").value, sort = $("#w-sort").value;
  const full = L.used >= L.slots;
  const list = d.market.filter((w) => (!role || w.role === role) && (!prof || w.profession === prof))
    .sort(sort === "wage" ? (a, b) => a.ask_wage - b.ask_wage : sort === "value" ? (a, b) => b.daily_value / b.ask_wage - a.daily_value / a.ask_wage : (a, b) => b.level - a.level);
  $("#w-market").innerHTML = list.map((w) => {
    const f = (st.hireForm[w.id] ||= { days: 3, food: false, tool: false });
    const wage = wageFor(w, f);
    const what = w.role === "gatherer"
      ? `<div class="wrow"><span class="k">Знаходить</span><div class="chips">${w.finds.slice(0, 10).map((i) => `<span class="chip" title="${esc(st.items[i].name)}">${st.items[i].icon}</span>`).join("")}${w.finds.length > 10 ? `<span class="small muted">+${w.finds.length - 10}</span>` : ""}</div></div>`
      : `<div class="wrow"><span class="k">Знає</span><div class="chips">${w.recipes.slice(0, 10).map((rid) => { const r = st.recipes.find((x) => x.id === rid); return r ? `<span class="chip" title="${esc(r.output.name)}">${r.output.icon}</span>` : ""; }).join("")}${w.recipes.length > 10 ? `<span class="small muted">+${w.recipes.length - 10}</span>` : ""}</div></div>`;
    return `<div class="wcard">
      ${workerHead(w, `<span class="small muted">шукає роботу<br>ще ${fmtTicks(w.available_in)}</span>`)}
      ${what}
      <div class="wrow"><span class="k">Інструменти</span><span class="small">${w.tools.map((t) => `${st.items[t.item_id].icon} +${Math.round(t.bonus * 100)}%`).join(" · ")}</span></div>
      <div class="wrow"><span class="k">Їсть</span><span class="small">${w.food_need} од. ситості/день${w.drunk ? " + 🍺 пиво" : ""}${w.night ? " · 🌙 працює й уночі" : ""}</span></div>
      <div class="wrow"><span class="k">Просить</span><span class="small"><b>${money(w.ask_wage)}</b>/день · виробіток ≈ ${money(w.daily_value)}/день</span></div>
      <div class="wrow"><span class="k">Термін</span><span class="seg">${Object.keys(st.workers.rules.durations).map((k) => `<button data-hdays="${w.id}:${k}" class="${+k === f.days ? "active" : ""}">${k} дн</button>`).join("")}</span></div>
      <div class="wrow"><span class="k">Ви надаєте</span>
        <label class="small"><input type="checkbox" data-hfood="${w.id}" ${f.food ? "checked" : ""}> 🍞 харчування −${d.rules.food_discount * 100}%</label>
        <label class="small"><input type="checkbox" data-htool="${w.id}" ${f.tool ? "checked" : ""}> 🛠 інструмент −${d.rules.tool_discount * 100}%</label></div>
      <div class="wrow"><span class="k">Підсумок</span><span><b>${money(wage)}</b>/день · за контракт ${money(wage * f.days)} <span class="small muted">(перший день — одразу)</span></span></div>
      <button class="btn primary" data-hire="${w.id}" ${full ? 'disabled title="Немає вільних місць за ліцензією"' : ""}>🤝 Найняти</button>
    </div>`;
  }).join("") || '<div class="muted">Нікого немає — загляньте пізніше.</div>';

  bindWorkerActions();
}

function bindWorkerActions() {
  const box = $("#tab-workers");
  const post = (url, body, msg) => act(() => api(url, { method: "POST", body }), msg).then(() => refreshWorkers());
  $$("[data-hdays]", box).forEach((b) => (b.onclick = () => { const [id, k] = b.dataset.hdays.split(":"); st.hireForm[id].days = +k; renderWorkers(); }));
  $$("[data-hfood]", box).forEach((b) => (b.onchange = () => { st.hireForm[b.dataset.hfood].food = b.checked; renderWorkers(); }));
  $$("[data-htool]", box).forEach((b) => (b.onchange = () => { st.hireForm[b.dataset.htool].tool = b.checked; renderWorkers(); }));
  $$("[data-hire]", box).forEach((b) => (b.onclick = () => post(`/workers/${b.dataset.hire}/hire`, st.hireForm[b.dataset.hire], (r) => `Найнято за ${money(r.wage, true)}/день`)));
  $$("[data-fire]", box).forEach((b) => (b.onclick = () => {
    if (confirm(`Звільнити ${b.dataset.name}? Неустойка — ${b.dataset.pen}.`)) post(`/workers/${b.dataset.fire}/fire`, undefined, "Працівника звільнено");
  }));
  $$("[data-renew]", box).forEach((b) => (b.onclick = () => post(`/workers/${b.dataset.renew}/renew`, { days: 3 }, (r) => `Контракт продовжено, ЗП ${money(r.wage, true)}/день`)));
  $$("[data-equip]", box).forEach((b) => (b.onclick = () => post(`/workers/${b.dataset.equip}/equip`, { item_id: +$(`[data-equip-sel="${b.dataset.equip}"]`).value }, "Інструмент видано")));
  $$("[data-unequip]", box).forEach((b) => (b.onclick = () => post(`/workers/${b.dataset.unequip}/unequip`, undefined, (r) => (r.returned ? "Інструмент повернуто в інвентар" : "Інструмент зношений — викинуто"))));
  $$("[data-focus]", box).forEach((s) => (s.onchange = () => post(`/workers/${s.dataset.focus}/focus`, { item_id: s.value ? +s.value : null }, "Завдання змінено")));
  $$("[data-item]", box).forEach((a) => (a.onclick = (e) => { e.preventDefault(); selectItem(+a.dataset.item); }));
  // crafter queue editing happens in a local draft until saved
  const draftOf = (id) => (st.taskDraft[id] ||= st.workers.mine.find((w) => w.id === +id).tasks.map((t) => ({ ...t })));
  $$("[data-task-r]", box).forEach((s) => (s.onchange = () => { const [id, k] = s.dataset.taskR.split(":"); draftOf(id)[k].recipe_id = +s.value; renderWorkers(); }));
  $$("[data-task-k]", box).forEach((s) => (s.onchange = () => { const [id, k] = s.dataset.taskK.split(":"); draftOf(id)[k].keep = +s.value || 0; renderWorkers(); }));
  $$("[data-task-del]", box).forEach((b) => (b.onclick = () => { const [id, k] = b.dataset.taskDel.split(":"); draftOf(id).splice(+k, 1); renderWorkers(); }));
  $$("[data-task-add]", box).forEach((b) => (b.onclick = () => {
    const w = st.workers.mine.find((x) => x.id === +b.dataset.taskAdd);
    draftOf(w.id).push({ recipe_id: w.recipes[0], keep: 0 });
    renderWorkers();
  }));
  $$("[data-task-save]", box).forEach((b) => (b.onclick = () => {
    const id = b.dataset.taskSave;
    act(() => api(`/workers/${id}/tasks`, { method: "POST", body: { tasks: st.taskDraft[id] } }), "Чергу збережено")
      .then(() => { delete st.taskDraft[id]; refreshWorkers(); });
  }));
}

// ------------------------------------------------------------------ analytics
const catColors = {};
function catColor(cat, i) { return (catColors[cat] ||= `hsl(${(i * 137.5) % 360} 65% 60%)`); }

async function refreshAnalytics() {
  const idx = await api("/indices?limit=240");
  const labels = idx.labels;
  const datasets = Object.entries(idx.series).map(([cat, pts], i) => {
    const m = Object.fromEntries(pts.map((p) => [p.bucket, p.idx]));
    return { label: cat, data: labels.map((b) => m[b] ?? null), borderColor: catColor(cat, i), borderWidth: 1.5, pointRadius: 0, spanGaps: true, tension: .2, money: false };
  });
  upsertChart("indices", "chart-indices", {
    type: "line", data: { labels: labels.map((b) => "") , datasets },
    options: { maintainAspectRatio: false, animation: false, interaction: { mode: "nearest", intersect: false },
      plugins: { legend: { position: "right", labels: { boxWidth: 10 } } }, scales: { x: { display: false } } },
  });
  const mk = st.market;
  const row = (m, right) => `<div class="mini-row" data-item="${m.id}">${itemLabel(m)}<span class="r">${right}</span></div>`;
  const withCh = mk.filter((m) => m.change !== null && m.volume > 0);
  $("#top-gainers").innerHTML = [...withCh].sort((a, b) => b.change - a.change).slice(0, 8).map((m) => row(m, pct(m.change))).join("");
  $("#top-losers").innerHTML = [...withCh].sort((a, b) => a.change - b.change).slice(0, 8).map((m) => row(m, pct(m.change))).join("");
  $("#top-saturated").innerHTML = [...mk].sort((a, b) => b.ask_qty / b.stack - a.ask_qty / a.stack).slice(0, 8)
    .map((m) => row(m, `${(m.ask_qty / m.stack).toFixed(1)} ст.`)).join("");
  $("#top-deficit").innerHTML = mk.filter((m) => !m.ask_qty).sort((a, b) => b.ref - a.ref).slice(0, 8)
    .map((m) => row(m, m.best_bid ? `попит ${money(m.best_bid)}` : "—")).join("") || '<div class="muted">Дефіциту немає</div>';
  $("#top-volume").innerHTML = [...mk].sort((a, b) => b.volume * (b.last || 0) - a.volume * (a.last || 0)).slice(0, 8)
    .map((m) => row(m, money(m.volume * (m.last || 0)))).join("");
  if (!st.recipes.length) st.recipes = await api("/craft/recipes");
  $("#top-craft").innerHTML = [...st.recipes].filter((r) => r.margin !== null).sort((a, b) => b.profit - a.profit).slice(0, 8)
    .map((r) => `<div class="mini-row" data-recipe="${r.id}">${itemLabel(r.output)}<span class="r">${money(r.profit)} ${pct(r.margin)}</span></div>`).join("");
  $$("#tab-analytics [data-item]").forEach((e) => (e.onclick = () => selectItem(+e.dataset.item)));
  $$("#tab-analytics [data-recipe]").forEach((e) => (e.onclick = () => { openTab("craft"); selectRecipe(+e.dataset.recipe); }));
}

// ------------------------------------------------------------------ news / leaders
const kindIcon = { demand: "📣", supply: "⛏️", corner: "🐸", info: "ℹ️" };
async function refreshNews() {
  const news = await api("/news");
  st.lastNewsId = news[0]?.id || 0;
  const unseen = news.filter((n) => n.id > st.seenNews).length;
  $("#news-count").textContent = unseen;
  $("#news-count").classList.toggle("hidden", !unseen || st.tab === "news");
  if (st.tab !== "news") return;
  $("#news-list").innerHTML = news.map((n) => {
    const eff = n.kind === "corner" ? "" : ` · ${n.kind === "demand" ? "попит" : "видобуток"} ×${n.mult.toFixed(2)}`;
    const target = n.target_type === "category" ? JSON.parse(n.target).join(", ") : st.items[st.catalog.items.find((i) => i.code === n.target)?.id]?.name;
    return `<div class="news-item ${n.active ? "active" : ""}">
      <div class="t">${kindIcon[n.kind] || ""} ${esc(n.title)}</div>
      <div class="small">${esc(n.text)}</div>
      <div class="small muted">${n.time} · ${esc(target || "")}${eff}${n.active ? " · <b>діє</b>" : ""}</div></div>`;
  }).join("") || '<div class="muted">Поки тихо…</div>';
}

const stratName = { gatherer: "збирач", crafter: "ремісник", speculator: "перекупник", dumper: "новачок" };
async function refreshLeaders() {
  const rows = await api("/leaderboard");
  $("#leaders").innerHTML = `<table><tr><th>#</th><th>Торговець</th><th>Роль</th><th class="num">Золото</th><th class="num">Капітал</th></tr>
    ${rows.map((r, i) => `<tr class="${r.id === st.player?.id ? "mine" : ""}"><td>${i + 1}</td><td>${r.kind === "player" ? "🧑 " : "🤖 "}${esc(r.name)}</td>
      <td class="small muted">${r.kind === "player" ? "гравець" : stratName[r.strategy] || ""} ${esc(r.profession_name)}</td>
      <td class="num">${money(r.gold)}</td><td class="num">${money(r.net_worth)}</td></tr>`).join("")}</table>`;
}

// ------------------------------------------------------------------ settings
async function refreshSettings() {
  const d = await api("/settings");
  st.settings = d;
  const v = d.values;
  $("#presets").innerHTML = Object.entries(d.presets).map(([k, p]) => {
    const active = Object.entries({ ...defaultsOf(d), ...p.values }).every(([kk, vv]) => Math.abs(v[kk] - vv) < 1e-6);
    return `<button class="btn ${active ? "active" : ""}" data-preset="${k}" title="${esc(JSON.stringify(p.values))}">${esc(p.title)}</button>`;
  }).join("");
  $$("[data-preset]").forEach((b) => (b.onclick = () => act(() => api(`/settings/preset/${b.dataset.preset}`, { method: "POST" }), "Сценарій застосовано").then(refreshSettings)));
  const keys = ["ah_cut_pct", "deposit_pct", "demand_mult", "supply_mult", "volatility", "event_rate", "bot_activity", "tick_seconds", "gw2_weight"];
  if (!$("#settings-form").dataset.built) {
    $("#settings-form").innerHTML = keys.map((k) => {
      const s = d.spec[k];
      const step = s.max <= 1 ? 0.05 : s.max <= 10 ? 0.1 : 0.5;
      return `<div class="setting"><label>${esc(s.label)} <span id="val-${k}"></span></label>
        <input type="range" min="${s.min}" max="${s.max}" step="${step}" id="set-${k}">
        <div class="help">${esc(s.help)} (типово ${s.default})</div></div>`;
    }).join("") + `<div class="setting"><label>Синхронізація з GW2 <input type="checkbox" id="set-gw2_sync"></label>
      <div class="help">${esc(d.spec.gw2_sync.help)}</div></div>`;
    $("#settings-form").dataset.built = 1;
    keys.forEach((k) => {
      const el = $("#set-" + k);
      el.oninput = () => ($("#val-" + k).textContent = fmtSetting(k, +el.value));
      el.onchange = () => act(() => api("/settings", { method: "POST", body: { [k]: +el.value } })).then(refreshSettings);
    });
    $("#set-gw2_sync").onchange = (e) => act(() => api("/settings", { method: "POST", body: { gw2_sync: e.target.checked ? 1 : 0 } }),
      e.target.checked ? "Синхронізацію увімкнено" : "Синхронізацію вимкнено").then(refreshSettings);
  }
  keys.forEach((k) => { $("#set-" + k).value = v[k]; $("#val-" + k).textContent = fmtSetting(k, v[k]); });
  $("#set-gw2_sync").checked = !!v.gw2_sync;
  const g = await api("/gw2");
  $("#gw2-status").innerHTML = `Стан: ${v.gw2_sync ? '<span class="up">увімкнено</span>' : "вимкнено"} ·
    остання синхронізація: ${g.last_sync ? new Date(g.last_sync * 1000).toLocaleTimeString("uk") : "—"} ·
    товарів зіставлено: ${g.mapped}${g.error ? ` · <span class="down">${esc(g.error)}</span>` : ""}`;
  $("#gw2-sample").innerHTML = g.sample?.length ? `<table><tr><th>Товар</th><th class="num">GW2 mid</th><th class="num">Попит</th><th class="num">Пропозиція</th></tr>
    ${g.sample.map((x) => `<tr><td>${itemLabel(st.items[x.item_id])}</td><td class="num">${x.mid.toFixed(1)}</td><td class="num">×${x.demand}</td><td class="num">×${x.supply}</td></tr>`).join("")}</table>` : "";
}
const defaultsOf = (d) => Object.fromEntries(Object.entries(d.spec).filter(([k]) => !["tick_seconds", "paused", "gw2_sync", "gw2_weight"].includes(k)).map(([k, s]) => [k, s.default]));
const fmtSetting = (k, x) => (k.endsWith("_pct") ? `${x}%` : k === "tick_seconds" ? `${x} с` : `×${x}`);

$$("[data-event]").forEach((b) => (b.onclick = () => act(() => api("/admin/event", { method: "POST", body: { kind: b.dataset.event } }), (r) => r.title)));
$("#gw2-now").onclick = () => act(() => api("/gw2/sync", { method: "POST" }), "Синхронізовано з GW2").then(refreshSettings);
$("#gw2-rebase").onclick = () => act(() => api("/gw2/rebase", { method: "POST" }), "Базу скинуто").then(refreshSettings);

// ------------------------------------------------------------------ calculator
const calc = { cur: "0", acc: null, op: null, fresh: true, expr: "" };
const opSym = { "+": "+", "-": "−", "*": "×", "/": "÷" };
const calcFmt = (x) => (typeof x === "number" ? +x.toPrecision(12) : x).toString().replace(".", ",");

function calcApply(a, op, b) {
  switch (op) {
    case "+": return a + b;
    case "-": return a - b;
    case "*": return a * b;
    case "/": return b === 0 ? NaN : a / b;
  }
  return b;
}

function calcKey(k) {
  if (calc.cur === "Помилка" && k !== "C") calcKey("C");
  if (/^[0-9]$/.test(k)) {
    calc.cur = calc.fresh || calc.cur === "0" ? k : calc.cur + k;
    calc.fresh = false;
  } else if (k === ".") {
    if (calc.fresh) { calc.cur = "0."; calc.fresh = false; }
    else if (!calc.cur.includes(".")) calc.cur += ".";
  } else if (k === "C") {
    Object.assign(calc, { cur: "0", acc: null, op: null, fresh: true, expr: "" });
  } else if (k === "back") {
    if (!calc.fresh) calc.cur = calc.cur.length > 1 && calc.cur !== "-0" ? calc.cur.slice(0, -1).replace(/^-$/, "0") : "0";
  } else if (k === "neg") {
    calc.cur = calc.cur.startsWith("-") ? calc.cur.slice(1) : calc.cur === "0" ? "0" : "-" + calc.cur;
  } else if (k === "%") {
    // like on a pocket calculator: 200 + 5% = 210, 200 × 5% = 10
    const b = parseFloat(calc.cur);
    calc.cur = String(calc.acc !== null && (calc.op === "+" || calc.op === "-") ? calc.acc * b / 100 : b / 100);
    calc.fresh = false;
  } else if (k in opSym) {
    const b = parseFloat(calc.cur);
    if (calc.op && !calc.fresh) calc.acc = calcApply(calc.acc, calc.op, b);
    else if (calc.acc === null || !calc.op) calc.acc = b;
    calc.op = k;
    calc.fresh = true;
    calc.expr = `${calcFmt(calc.acc)} ${opSym[k]}`;
    calc.cur = String(calc.acc);
  } else if (k === "=") {
    if (!calc.op) return calcRender();
    const b = parseFloat(calc.cur);
    const r = calcApply(calc.acc, calc.op, b);
    calc.expr = `${calcFmt(calc.acc)} ${opSym[calc.op]} ${calcFmt(b)} =`;
    Object.assign(calc, { cur: String(r), acc: null, op: null, fresh: true });
  }
  if (calc.cur === "NaN" || calc.cur === "Infinity" || calc.cur === "-Infinity") {
    Object.assign(calc, { cur: "Помилка", acc: null, op: null, fresh: true });
  }
  calcRender();
}

function calcRender() {
  const v = calc.cur === "Помилка" ? calc.cur : calc.fresh ? calcFmt(parseFloat(calc.cur)) : calc.cur.replace(".", ",");
  $("#calc-display").textContent = v;
  $("#calc-expr").textContent = calc.expr;
}

$$("#calc [data-k]").forEach((b) => (b.onclick = () => calcKey(b.dataset.k)));
$("#calc-toggle").onclick = () => $("#calc").classList.toggle("hidden");
$("#calc-close").onclick = () => $("#calc").classList.add("hidden");

document.addEventListener("keydown", (e) => {
  if ($("#calc").classList.contains("hidden") || e.target.closest("input, select, textarea") || e.metaKey || e.ctrlKey) return;
  const map = { Enter: "=", "=": "=", Escape: "C", Backspace: "back", Delete: "C", ",": "." };
  const k = map[e.key] ?? e.key;
  if (/^[0-9]$/.test(k) || ["+", "-", "*", "/", ".", "%", "=", "C", "back"].includes(k)) {
    e.preventDefault();
    calcKey(k);
  }
});

// dragging by the title bar; position is remembered between sessions
(function calcDrag() {
  const box = $("#calc"), bar = $("#calc-bar");
  try {
    const pos = JSON.parse(localStorage.getItem("calcPos") || "null");
    if (pos) Object.assign(box.style, { left: pos.x + "px", top: pos.y + "px", right: "auto" });
  } catch {}
  let dx = 0, dy = 0, dragging = false;
  bar.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return;
    const r = box.getBoundingClientRect();
    dx = e.clientX - r.left; dy = e.clientY - r.top; dragging = true;
    bar.setPointerCapture(e.pointerId);
  });
  bar.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const x = Math.min(Math.max(0, e.clientX - dx), window.innerWidth - box.offsetWidth);
    const y = Math.min(Math.max(0, e.clientY - dy), window.innerHeight - 40);
    Object.assign(box.style, { left: x + "px", top: y + "px", right: "auto" });
  });
  bar.addEventListener("pointerup", () => {
    dragging = false;
    try { localStorage.setItem("calcPos", JSON.stringify({ x: box.offsetLeft, y: box.offsetTop })); } catch {}
  });
})();

// ------------------------------------------------------------------ trade feed notifications
const NOTE_MS = 8000, NOTE_MAX = 6;

async function refreshFeed() {
  const c = st.feedCursor;
  const f = await api(c ? `/me/feed?after_trade=${c.trade}&after_tick=${c.tick}&after_wlog=${c.wlog}` : "/me/feed");
  st.feedCursor = f.cursor;
  // one note per item / side / price within this refresh
  const groups = new Map();
  for (const t of f.trades) {
    const key = `${t.side}:${t.item.id}:${t.price}`;
    const g = groups.get(key) || { ...t, qty: 0, net: 0 };
    g.qty += t.qty; g.net += t.net;
    groups.set(key, g);
  }
  for (const g of groups.values()) {
    const sell = g.side === "sell";
    notify(sell ? "sell" : "buy", sell ? "💰" : "📦",
      `${sell ? "Продано" : "Куплено"} ${num(g.qty)} × ${g.item.icon} ${esc(g.item.name)} по ${money(g.price)}`,
      sell ? `отримано ${money(g.net, true)} (після комісії)` : `сплачено ${money(g.net, true)}`, g.item.id);
  }
  for (const e of f.workers || []) {
    notify(e.kind === "level" || e.kind === "hire" || e.kind === "renew" ? "buy" : e.kind === "ended" ? "sell" : "expired",
      wlogIcon[e.kind] || "👷", esc(e.text), "працівники", null);
    if (st.tab === "workers") refreshWorkers();
  }
  for (const o of f.expired) {
    const sell = o.side === "sell";
    notify("expired", "⌛", `${sell ? "Лот" : "Заявку"} прострочено: ${num(o.qty_left)} × ${o.item.icon} ${esc(o.item.name)} по ${money(o.price)}`,
      sell ? "непродане повернуто в інвентар" : `золото повернуто: ${money(o.price * o.qty_left, true)}`, o.item.id);
  }
}

function notify(kind, icon, html, sub, itemId) {
  const box = $("#feed");
  const n = document.createElement("div");
  n.className = `note ${kind}`;
  n.innerHTML = `<div class="ic">${icon}</div><div class="body"><div>${html}</div><div class="sub">${sub} · ${st.state?.time.label || ""}</div></div>
    <button class="x" title="Закрити">✕</button><div class="life" style="animation-duration:${NOTE_MS}ms"></div>`;
  const close = () => { n.classList.add("out"); setTimeout(() => n.remove(), 250); };
  $(".x", n).onclick = (e) => { e.stopPropagation(); close(); };
  n.onclick = () => (itemId ? selectItem(itemId) : kind !== "sell" && openTab("workers"));
  // the life bar runs out (paused while hovered), then the note closes itself
  $(".life", n).addEventListener("animationend", close);
  box.appendChild(n);
  while (box.children.length > NOTE_MAX) box.firstElementChild.remove();
}

// ------------------------------------------------------------------ refresh loop
async function refreshTab(periodic = false) {
  try {
    if (st.tab === "market") await refreshDetail();
    else if (st.tab === "inventory") renderInventory();
    else if (st.tab === "orders") await refreshOrders();
    else if (st.tab === "craft") await refreshRecipes(periodic);
    else if (st.tab === "workers") {
      if (!st.recipes.length) st.recipes = await api("/craft/recipes");
      await refreshWorkers(periodic);
    }
    else if (st.tab === "analytics") await refreshAnalytics();
    else if (st.tab === "leaders") await refreshLeaders();
    else if (st.tab === "settings" && !periodic) await refreshSettings();
  } catch (e) { console.warn(e); }
}

let busy = false;
async function refreshAll() {
  if (busy || !st.player) return;
  busy = true;
  try {
    await Promise.all([refreshState(), refreshMe(), refreshMarket()]);
    await Promise.all([refreshTab(true), refreshNews(), refreshFeed()]);
  } catch (e) { console.warn(e); } finally { busy = false; }
}

const syncTopbar = () => document.documentElement.style.setProperty("--topbar-h", $(".top").offsetHeight + "px");
window.addEventListener("resize", syncTopbar);
syncTopbar();

(async function init() {
  await loadCatalog();
  if (!st.player) showLogin();
  else {
    try { await api("/me"); } catch { return; }
  }
  await refreshAll();
  const first = st.market.slice().sort((a, b) => b.volume - a.volume)[0];
  if (first && !st.selected) selectItem(first.id, false);
  setInterval(refreshAll, 3000);
})();
