(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const refreshButton = $("#refresh-button");
  const trackSelect = $("#track-select");
  const budgetInput = $("#budget-input");
  const state = { data: null, track: "soft", budget: 100, sort: "number", request: 0, offline: false };
  const safe = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const pct = (value, digits = 1) => value == null || !Number.isFinite(Number(value)) ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
  const dollars = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? "—" : `$${Number(value).toFixed(digits)}`;
  const price = (value) => value == null ? "—" : `$${Number(value).toFixed(2)}`;
  const trackName = (track) => ({ good: "Good", soft: "Soft", heavy: "Heavy" })[track] || "Soft";
  const timeLabel = (value) => {
    if (!value) return "Not recorded";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? safe(value) : new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeStyle: "short", timeZone: "Australia/Melbourne" }).format(date) + " AEDT";
  };
  const horseName = (m) => `${m.no}. ${m.name}`;
  const safeUrl = (value) => {
    try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) ? url.href : ""; } catch { return ""; }
  };

  function setStatus(text, offline = false) {
    const el = $("#connection-state");
    el.textContent = text;
    el.classList.toggle("is-offline", offline);
    el.setAttribute("aria-label", text);
  }

  function setRefreshing(active) {
    refreshButton.disabled = active;
    refreshButton.classList.toggle("is-refreshing", active);
    refreshButton.setAttribute("aria-busy", String(active));
  }

  async function requestData(fresh) {
    const requestId = ++state.request;
    const requestSettings = { track: state.track, budget: state.budget };
    let response;
    if (fresh) {
      response = await fetch("/api/analysis", {
        method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(requestSettings)
      });
    } else {
      const query = new URLSearchParams({ track: state.track, budget: String(state.budget) });
      response = await fetch(`/api/analysis?${query}`, { cache: "no-cache" });
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || `Data request failed (${response.status})`);
    }
    const data = await response.json();
    if (requestId !== state.request) return;
    state.data = data;
    state.offline = false;
    $("#page-error").hidden = true;
    setStatus(fresh ? "Saved Atlas data refreshed" : "Connected to Atlas");
    render();
  }

  async function loadFallback() {
    const response = await fetch("/data.json", { cache: "no-cache" });
    if (!response.ok) throw new Error("The saved fallback data is unavailable.");
    state.data = await response.json();
    state.offline = true;
    setStatus("Showing saved snapshot", true);
    $("#page-error").hidden = false;
    $("#page-error").textContent = "The live Atlas data could not be reached. Showing the last exported snapshot instead. Use Refresh odds & tips to try again.";
    render();
  }

  function planFor(metrics, budget) {
    const candidates = metrics.slice(0, 8).filter((m) => m.ev_best_au && m.ev_best_au > 0);
    const raw = candidates.map((m) => m.kelly_au * 0.25 * budget);
    const total = raw.reduce((sum, n) => sum + n, 0);
    const scale = total ? Math.min(1, (0.5 * budget) / total) : 0;
    const toSingle = (m, outlay) => {
      const eachWay = m.best_au_price >= 10;
      const unit = Math.round(eachWay ? outlay / 2 : outlay);
      return { name: m.name, no: m.no, bet: eachWay ? "Each-way" : "Win", unit, cost: unit * (eachWay ? 2 : 1), price: m.best_au_price, bookmaker: m.best_au_bookmaker, model_prob: m.model_prob, ev: m.ev_best_au };
    };
    let singles = candidates.map((m, i) => toSingle(m, raw[i] * scale)).filter((s) => s.unit >= 2);
    if (!singles.length && metrics.length) singles = [toSingle(metrics[0], budget * 0.3)];
    const used = singles.reduce((sum, s) => sum + s.cost, 0);
    const remaining = Math.max(0, budget - used);
    const triStake = Math.round(Math.min(0.2 * budget, remaining * 0.6));
    const ffStake = Math.round(Math.min(0.1 * budget, remaining - triStake));
    return {
      budget, singles,
      exotics: [
        { bet: "Trifecta box", runners: metrics.slice(0, 4).map((m) => [m.no, m.name]), combinations: 24, stake: triStake, flexi_pct: triStake / 24 * 100 },
        { bet: "First Four box", runners: metrics.slice(0, 6).map((m) => [m.no, m.name]), combinations: 360, stake: ffStake, flexi_pct: ffStake / 360 * 100 }
      ], total_staked: used + triStake + ffStake
    };
  }

  function getPlan() {
    const saved = state.data && state.data.plan;
    if (saved && saved.budget === state.budget && state.data.default_track === state.track) return saved;
    return planFor(state.data.tracks[state.track].metrics, state.budget);
  }

  function renderPicks(metrics) {
    $("#pick-cards").innerHTML = metrics.slice(0, 4).map((m) => `
      <article class="pick-card">
        <div class="pick-topline"><span>RUNNER ${String(m.no).padStart(2, "0")}</span><span class="rank-badge">MODEL RANK ${m.model_rank}</span></div>
        <h3>${safe(m.name)}</h3><p class="pick-subline">Barrier ${safe(m.barrier)} · ${safe(m.jockey)}</p>
        ${m.ev_best_au > 0 ? `<span class="pick-value">${pct(m.ev_best_au, 0)} model edge</span>` : ""}
        <div class="pick-price-row"><span class="pick-chance">MODEL CHANCE<strong>${pct(m.model_prob)}</strong></span><span class="pick-odds">BEST AU PRICE<strong>${price(m.best_au_price)}</strong></span></div>
      </article>`).join("");
    const alerts = (state.data.race?.notes || []).filter((note) => /shockletz|rider|jockey/i.test(note));
    $("#runner-alerts").innerHTML = alerts.map((note) => `<div class="warning-callout"><strong>Rider check:</strong> ${safe(note)}</div>`).join("");
  }

  function renderOdds(metrics) {
    const sorted = [...metrics];
    if (state.sort === "model") sorted.sort((a, b) => a.model_rank - b.model_rank);
    else if (state.sort === "best") sorted.sort((a, b) => (b.best_au_price || 0) - (a.best_au_price || 0));
    else if (state.sort === "horse") sorted.sort((a, b) => a.name.localeCompare(b.name));
    else sorted.sort((a, b) => a.no - b.no);
    $("#odds-rows").innerHTML = sorted.map((m) => `<tr>
      <td class="numeric">${m.no}</td><td class="runner-name">${safe(m.name)}</td><td class="numeric">${pct(m.model_prob)}</td>
      <td class="numeric">${price(m.tab_price)}</td><td class="numeric">${price(m.prices?.Ladbrokes)}</td><td class="numeric">${price(m.bet365_price)}</td>
      <td class="numeric ${m.ev_best_au > 0 ? "positive" : ""}">${price(m.best_au_price)} <small>${safe((m.best_au_bookmaker || []).join(", "))}</small></td>
      <td class="numeric">${price(m.best_price)} <small>${safe((m.best_bookmaker || []).join(", "))}</small></td></tr>`).join("");
    const books = state.data.tracks[state.track].bookmakers || [];
    $("#bookmaker-summary").innerHTML = [...books].sort((a, b) => (a.overround ?? 99) - (b.overround ?? 99)).slice(0, 6).map((b) =>
      `<span class="bookmaker-pill"><strong>${safe(b.bookmaker)}</strong> · ${b.overround ? `${pct(b.overround - 1, 1)} margin` : `${b.runners_priced} runners`}</span>`).join("");
    const gaps = state.data.odds_not_captured || [];
    $("#odds-gaps").textContent = gaps.length ? `Coverage note: ${gaps.map((g) => `${g.bookmaker}: ${g.reason}`).join(" ")}` : "Prices shown are snapshots, confirm the current quote and terms with the bookmaker.";
  }

  function renderTips(metrics) {
    const ranked = [...metrics].sort((a, b) => b.tip.points - a.tip.points || a.no - b.no).filter((m) => m.tip.mentions > 0);
    $("#tip-rows").innerHTML = ranked.map((m) => `<tr><td class="runner-name">${safe(horseName(m))}</td><td class="numeric">${Number(m.tip.points).toFixed(1)}</td><td class="numeric">${m.tip.mentions}</td><td class="numeric">${m.tip.expert_mentions}</td><td class="numeric">${m.tip.expert_top_picks}</td><td class="numeric">${pct(m.tip.share)}</td></tr>`).join("") || `<tr><td colspan="6" class="table-empty">No tip selections in this snapshot.</td></tr>`;
    const tipsters = state.data.tipsters || [];
    $("#tipster-count").textContent = `${state.data.tracks[state.track].n_tipsters} tipsters represented · ${ranked.length} runners named`;
    $("#tipster-details-count").textContent = `(${tipsters.length})`;
    $("#tipster-grid").innerHTML = tipsters.map((t) => {
      const href = safeUrl(t.url);
      const outlet = href ? `<a href="${safe(href)}" target="_blank" rel="noopener noreferrer">${safe(t.outlet)}</a>` : safe(t.outlet);
      const picks = (t.selections || []).map((s) => `${s.rank ? `${s.rank}. ` : ""}${s.horse}${s.kind && s.kind !== "ranked" ? ` (${s.kind.replaceAll("_", "-")})` : ""}`).join(" · ") || "No selections listed";
      return `<article class="tipster-card"><div class="tipster-name">${safe(t.tipster)}<span class="tier-label">${safe(t.tier)}</span></div><div class="tipster-outlet">${outlet}</div><div class="tipster-picks">${safe(picks)}</div></article>`;
    }).join("");
  }

  function renderForm(metrics) {
    const sorted = [...metrics].sort((a, b) => b.form_score - a.form_score);
    $("#form-rows").innerHTML = sorted.map((m) => {
      const h = m.horse || {};
      const wet = h.wet_track === 1 ? "Wet suited" : h.wet_track === -1 ? "Prefers dry" : "Neutral";
      return `<tr><td class="numeric">${m.no}</td><td class="runner-name">${safe(m.name)}</td><td class="numeric">${safe(h.last_form || "—")}</td><td class="numeric">${safe(h.career || "—")}</td><td class="stamina">${safe(h.stamina || "—")}</td><td>${wet}</td><td><div class="form-meter"><span><i style="width:${Math.max(0, Math.min(100, m.form_score * 100))}%"></i></span>${Number(m.form_score).toFixed(2)}</div></td></tr>`;
    }).join("");
    const notes = state.data.race?.notes || [];
    $("#race-notes").innerHTML = notes.filter((n) => !/shockletz|rider|jockey/i.test(n)).map((n) => `<div class="race-note">${safe(n)}</div>`).join("");
  }

  function renderPlan(metrics) {
    const plan = getPlan();
    const rows = [];
    for (const s of plan.singles || []) {
      rows.push(`<tr><td>${safe(s.bet)}</td><td class="runner-name">${safe(s.name)} (${s.no})</td><td class="numeric">${dollars(s.cost, 0)}${s.bet === "Each-way" ? ` <small>(${dollars(s.unit, 0)} each way)</small>` : ""}</td><td class="numeric">${price(s.price)}</td><td>${safe((s.bookmaker || []).join(", "))}</td><td class="numeric">${pct(s.model_prob)}</td><td class="numeric ${s.ev > 0 ? "positive" : ""}">${pct(s.ev, 0)}</td></tr>`);
    }
    for (const e of plan.exotics || []) {
      rows.push(`<tr><td>${safe(e.bet)}</td><td>${safe(e.runners.map((r) => `${r[0]} ${r[1]}`).join(" · "))}</td><td class="numeric">${dollars(e.stake, 0)} <small>(${Number(e.flexi_pct).toFixed(1)}% flexi)</small></td><td class="numeric">—</td><td>—</td><td class="numeric">—</td><td class="numeric">${e.combinations} combos</td></tr>`);
    }
    $("#plan-rows").innerHTML = rows.join("") || `<tr><td colspan="7" class="table-empty">No plan available for this snapshot.</td></tr>`;
    $("#plan-total").textContent = `Example budget: ${dollars(plan.budget, 0)}`;
    const reserve = Math.max(0, plan.budget - plan.total_staked);
    $("#reserve-note").textContent = `Illustrative outlay: ${dollars(plan.total_staked, 0)} of ${dollars(plan.budget, 0)}. Reserve: ${dollars(reserve, 0)}. This is an example only, not a recommendation.`;
  }

  function renderSources() {
    const race = state.data.race || {};
    const links = [...(race.sources || [])];
    const urls = (state.data.tipsters || []).map((t) => t.url).filter(Boolean);
    for (const url of urls) if (!links.includes(url)) links.push(url);
    $("#source-links").innerHTML = links.slice(0, 8).map((href) => {
      const safeHrefValue = safeUrl(href);
      if (!safeHrefValue) return "";
      let label = "Source";
      try { label = new URL(safeHrefValue).hostname.replace(/^www\./, ""); } catch { /* use default label */ }
      return `<a href="${safe(safeHrefValue)}" target="_blank" rel="noopener noreferrer">${safe(label)} ↗</a>`;
    }).join("");
  }

  function render() {
    if (!state.data) return;
    const race = state.data.race || {};
    const metrics = state.data.tracks?.[state.track]?.metrics;
    if (!metrics) return;
    $("#latest-price").textContent = timeLabel(state.data.latest_price_at);
    $("#updated-at").textContent = `${state.offline ? "Exported snapshot" : "Analysis generated"} ${timeLabel(state.data.generated_at)}`;
    $("#track-summary").textContent = trackName(state.track);
    $("#race-meta").innerHTML = `<span>${safe(race.venue || "Flemington")}</span><i></i><span>${safe(race.date || "3 November 2026")}</span><i></i><span>${safe(race.start_time || "3:00pm AEDT")}</span>`;
    $("#settings-status").textContent = `${state.data.weights.market * 100}% market · ${state.data.weights.tips * 100}% tips · ${state.data.weights.form * 100}% form`;
    renderPicks(metrics);
    renderOdds(metrics);
    renderTips(metrics);
    renderForm(metrics);
    renderPlan(metrics);
    renderSources();
  }

  async function refresh(fresh, quiet = false) {
    if (fresh) setRefreshing(true);
    if (!quiet) setStatus(fresh ? "Checking saved odds & tips…" : "Updating analysis…");
    try {
      await requestData(fresh);
    } catch (error) {
      if (!state.data && !fresh) {
        try { await loadFallback(); }
        catch (fallbackError) {
          $("#page-error").hidden = false;
          $("#page-error").textContent = fallbackError.message;
          setStatus("Data unavailable", true);
        }
      } else {
        $("#page-error").hidden = false;
        $("#page-error").textContent = `${error.message}. Keeping the last data loaded on this page.`;
        setStatus("Refresh failed; showing last loaded data", true);
      }
    } finally {
      if (fresh) setRefreshing(false);
    }
  }

  refreshButton.addEventListener("click", () => refresh(true));
  trackSelect.addEventListener("change", () => {
    state.track = trackSelect.value;
    if (state.data) render();
    refresh(true, true);
  });
  budgetInput.addEventListener("change", () => {
    const value = Number(budgetInput.value);
    if (!Number.isFinite(value) || value < 1 || value > 1000000) {
      budgetInput.value = String(state.budget);
      $("#page-error").hidden = false;
      $("#page-error").textContent = "Enter a budget from $1 to $1,000,000.";
      return;
    }
    state.budget = value;
    if (state.data) render();
    refresh(true, true);
  });
  $("#odds-sort").addEventListener("change", (event) => {
    state.sort = event.target.value;
    if (state.data) render();
  });

  refresh(false);
})();
