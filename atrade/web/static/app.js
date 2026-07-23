// a-trade 持仓配置 Web UI
(function () {
  const TOKEN_KEY = "a_trade_web_token";

  function token() { return localStorage.getItem(TOKEN_KEY) || ""; }
  function setToken(t) {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  }
  function authHeaders() {
    const t = token();
    return t ? { Authorization: "Bearer " + t } : {};
  }

  function toast(msg, kind) {
    const el = document.getElementById("status");
    el.textContent = msg;
    el.className = "status show " + (kind || "");
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.className = "status"; }, 3500);
  }

  async function fetchJSON(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, authHeaders(), opts.headers || {});
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const resp = await fetch(url, opts);
    const text = await resp.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { raw: text }; }
    return { ok: resp.ok, status: resp.status, data: data };
  }

  function renderCard(h) {
    const sym = h.symbol;
    const card = document.createElement("div");
    card.className = "card" + (h.enabled === false ? " disabled" : "");
    card.dataset.symbol = sym;
    card.innerHTML =
      '<div class="card-head">' +
        '<div class="card-title">' + sym + " " + (h.name || "") + '</div>' +
        '<label class="muted"><input type="checkbox" class="enabled-toggle" ' +
          (h.enabled !== false ? "checked" : "") + '> 启用</label>' +
      '</div>' +
      '<div class="row"><label>成本价</label><input class="cost" type="number" step="0.01" value="' + (h.cost_price || 0) + '"></div>' +
      '<div class="row"><label>数量(手)</label><input class="qty" type="number" step="0.01" value="' + ((h.quantity || 0) / 100) + '"></div>' +
      '<div class="row"><label>买入日</label><input class="date" type="text" placeholder="YYYY-MM-DD" value="' + (h.buy_date || "") + '"></div>' +
      '<div class="row"><label>备注</label><input class="note" type="text" maxlength="200" value="' + (h.note || "").replace(/"/g, "&quot;") + '"></div>' +
      '<div class="actions">' +
        '<button class="primary save">保存</button>' +
        '<button class="toggle">' + (h.enabled === false ? "启用" : "停用") + '</button>' +
        '<button class="danger delete">🗑 删除</button>' +
      '</div>';

    card.querySelector(".save").onclick = async function () {
      const lots = parseFloat(card.querySelector(".qty").value);
      const shares = Math.round(lots * 100);
      const patch = {
        cost_price: parseFloat(card.querySelector(".cost").value),
        quantity: shares,
        buy_date: card.querySelector(".date").value,
        note: card.querySelector(".note").value,
      };
      const r = await fetchJSON("/api/holdings/" + sym, { method: "PUT", body: patch });
      if (r.ok) {
        toast(sym + " 已保存", "ok");
        await refresh();
      } else {
        toast("保存失败: " + r.status + " " + JSON.stringify(r.data), "err");
      }
    };

    card.querySelector(".toggle").onclick = async function () {
      const newEnabled = h.enabled === false;
      const r = await fetchJSON("/api/holdings/" + sym, {
        method: "PUT", body: { enabled: newEnabled },
      });
      if (r.ok) {
        toast(sym + " 已" + (newEnabled ? "启用" : "停用"), "ok");
        await refresh();
      } else {
        toast("切换失败: " + r.status, "err");
      }
    };

    card.querySelector(".delete").onclick = async function () {
      if (!confirm("确认删除 " + sym + "？")) return;
      const r = await fetchJSON("/api/holdings/" + sym, { method: "DELETE" });
      if (r.ok) {
        toast(sym + " 已删除", "ok");
        await refresh();
      } else {
        toast("删除失败: " + r.status + " " + JSON.stringify(r.data), "err");
      }
    };

    card.querySelector(".enabled-toggle").onchange = async function (e) {
      const r = await fetchJSON("/api/holdings/" + sym, {
        method: "PUT", body: { enabled: e.target.checked },
      });
      if (!r.ok) toast("切换失败: " + r.status, "err");
      await refresh();
    };
    return card;
  }

  async function refresh() {
    const r = await fetchJSON("/api/holdings");
    if (!r.ok) {
      toast("加载失败: " + r.status, "err");
      return;
    }
    const main = document.getElementById("list");
    main.innerHTML = "";
    r.data.forEach(function (h) { main.appendChild(renderCard(h)); });
  }

  async function reloadConfig() {
    const r = await fetchJSON("/api/reload", { method: "POST" });
    if (r.ok) {
      toast("已重载: " + JSON.stringify(r.data), "ok");
    } else {
      toast("重载失败: " + r.status + " " + JSON.stringify(r.data), "err");
    }
  }

  function openAddDialog() {
    document.getElementById("add-symbol").value = "";
    document.getElementById("add-name").value = "";
    document.getElementById("add-cost").value = "";
    document.getElementById("add-qty").value = "";
    document.getElementById("add-date").value = "";
    document.getElementById("add-note").value = "";
    document.getElementById("add-dialog").style.display = "flex";
  }

  function closeAddDialog() {
    document.getElementById("add-dialog").style.display = "none";
  }

  async function submitAdd() {
    const sym = document.getElementById("add-symbol").value.trim();
    const body = {
      symbol: sym,
      name: document.getElementById("add-name").value.trim() || sym,
      cost_price: parseFloat(document.getElementById("add-cost").value),
      quantity: Math.round(parseFloat(document.getElementById("add-qty").value) * 100),
      buy_date: document.getElementById("add-date").value.trim(),
      note: document.getElementById("add-note").value.trim(),
    };
    const r = await fetchJSON("/api/holdings", { method: "POST", body: body });
    if (r.ok) {
      toast(body.symbol + " 已新增", "ok");
      closeAddDialog();
      await refresh();
    } else {
      toast("新增失败: " + r.status + " " + JSON.stringify(r.data), "err");
    }
  }

  async function refreshTrades() {
    const r = await fetchJSON("/api/t-trades?limit=10");
    const container = document.getElementById("trades");
    if (!container) return;
    container.innerHTML = "";
    if (!r.ok) {
      container.innerHTML = '<p class="muted">交易记录加载失败</p>';
      return;
    }
    if (r.data.length === 0) {
      container.innerHTML = '<p class="muted">今日暂无成交</p>';
      return;
    }
    const ul = document.createElement("ul");
    ul.style.cssText = "list-style:none;padding:0;margin:0";
    r.data.forEach(function (t) {
      const li = document.createElement("li");
      li.style.cssText = "padding:6px 0;border-bottom:1px solid var(--border);font-size:13px";
      const time = (t.timestamp || "").slice(11, 16);
      const dirColor = t.direction === "BUY" ? "var(--buy)" : "var(--sell)";
      const skip = t.skipped_reason ? ` <span class="muted">(${t.skipped_reason})</span>` : "";
      li.innerHTML = `<span class="muted">${time}</span> ` +
        `<b style="color:${dirColor}">${t.direction}</b> ` +
        `${t.symbol} ${t.shares}股 @ ${t.price} ` +
        `→ 剩余 ${t.holding_qty_after}股${skip}`;
      ul.appendChild(li);
    });
    container.appendChild(ul);
  }

  async function backfillNames() {
    const r = await fetchJSON("/api/holdings/backfill-names", { method: "POST" });
    if (r.ok) {
      const updated = r.data.holdings ? r.data.holdings.length : (r.data.updated || 0);
      toast("名称已更新: " + updated + " 条", "ok");
      await refresh();
    } else {
      toast("回填失败: " + r.status + " " + JSON.stringify(r.data), "err");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    const tokInput = document.getElementById("token-input");
    tokInput.value = token();
    document.getElementById("save-token").onclick = function () {
      setToken(tokInput.value.trim());
      toast("Token 已保存", "ok");
      refresh();
    };
    document.getElementById("reload-btn").onclick = function () {
      reloadConfig().then(refreshTrades);
    };
    document.getElementById("backfill-btn").onclick = backfillNames;
    document.getElementById("add-btn").onclick = openAddDialog;
    document.getElementById("add-cancel").onclick = closeAddDialog;
    document.getElementById("add-submit").onclick = function () {
      submitAdd().then(refreshTrades);
    };
    refresh();
    refreshTrades();
  });
})();
