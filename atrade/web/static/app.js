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
      '<div class="row"><label>锁利(%)</label><input class="take-profit" type="number" step="0.1" placeholder="默认 ' + ((h.trailing_defaults.take_profit_pct || 0.03) * 100) + '" value="' + (h.trailing_override.take_profit_pct == null ? "" : h.trailing_override.take_profit_pct * 100) + '"></div>' +
      '<div class="row"><label>止损(%)</label><input class="stop-loss" type="number" step="0.1" placeholder="默认 ' + ((h.trailing_defaults.stop_loss_pct || 0.02) * 100) + '" value="' + (h.trailing_override.stop_loss_pct == null ? "" : h.trailing_override.stop_loss_pct * 100) + '"></div>' +
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
      const takeProfitValue = card.querySelector(".take-profit").value.trim();
      const stopLossValue = card.querySelector(".stop-loss").value.trim();
      const riskResult = r.ok ? await fetchJSON("/api/t-settings/" + sym, {
        method: "PUT",
        body: {
          take_profit_pct: takeProfitValue === "" ? null : parseFloat(takeProfitValue) / 100,
          stop_loss_pct: stopLossValue === "" ? null : parseFloat(stopLossValue) / 100,
        },
      }) : { ok: false, status: r.status, data: r.data };
      if (r.ok && riskResult.ok) {
        toast(sym + " 已保存", "ok");
        await refresh();
      } else {
        toast("保存失败: " + riskResult.status + " " + JSON.stringify(riskResult.data), "err");
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
    document.getElementById("add-take-profit").value = "";
    document.getElementById("add-stop-loss").value = "";
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
    const takeProfitValue = document.getElementById("add-take-profit").value.trim();
    const stopLossValue = document.getElementById("add-stop-loss").value.trim();
    if (takeProfitValue !== "" || stopLossValue !== "") {
      body.trailing = {};
      if (takeProfitValue !== "") body.trailing.take_profit_pct = parseFloat(takeProfitValue) / 100;
      if (stopLossValue !== "") body.trailing.stop_loss_pct = parseFloat(stopLossValue) / 100;
    }
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


  // ===== 回测对话框 =====
  function openBacktestDialog() {
    const today = new Date().toISOString().slice(0, 10);
    document.getElementById("bt-symbol").value = "";
    document.getElementById("bt-cost").value = "";
    document.getElementById("bt-qty").value = "";
    document.getElementById("bt-start").value = "2024-01-01";
    document.getElementById("bt-end").value = today;
    document.getElementById("bt-sweep").checked = false;
    document.getElementById("bt-push").checked = true;
    document.getElementById("backtest-dialog").style.display = "flex";
  }

  function closeBacktestDialog() {
    document.getElementById("backtest-dialog").style.display = "none";
  }

  async function submitBacktest(portfolio) {
    closeBacktestDialog();
    const today = new Date().toISOString().slice(0, 10);
    let url, body;
    if (portfolio) {
      url = "/api/backtest/portfolio";
      body = {
        start_date: document.getElementById("bt-start").value || "2024-01-01",
        end_date: document.getElementById("bt-end").value || today,
        push: document.getElementById("bt-push").checked,
      };
    } else {
      const symbol = document.getElementById("bt-symbol").value.trim();
      const cost = parseFloat(document.getElementById("bt-cost").value);
      const qty = parseInt(document.getElementById("bt-qty").value, 10);
      if (!/^\d{6}$/.test(symbol)) {
        toast("代码必须是 6 位数字", "err"); return;
      }
      if (!(cost > 0) || !(qty > 0)) {
        toast("成本 / 数量必须 > 0", "err"); return;
      }
      url = "/api/backtest/run";
      body = {
        symbol: symbol,
        cost_price: cost,
        quantity: qty,
        start_date: document.getElementById("bt-start").value || "2024-01-01",
        end_date: document.getElementById("bt-end").value || today,
        sweep: document.getElementById("bt-sweep").checked,
        push: document.getElementById("bt-push").checked,
      };
    }
    const r = await fetchJSON(url, { method: "POST", body: body });
    if (r.ok) {
      toast("回测任务已提交：" + r.data.job_id, "ok");
    } else {
      toast("回测失败：" + r.status + " " + JSON.stringify(r.data), "err");
    }
  }

  async function refreshBacktests() {
    const r = await fetchJSON("/api/backtest/jobs?limit=10");
    const box = document.getElementById("backtest-list");
    if (!r.ok) {
      box.innerHTML = "<p class=\"muted\">回测历史加载失败：" + r.status + "</p>";
      return;
    }
    if (!r.data || !r.data.length) {
      box.innerHTML = "<p class=\"muted\">暂无回测任务</p>";
      return;
    }
    const rows = r.data.map(function (j) {
      const summary = j.summary || {};
      const badge =
        j.status === "completed" ? "🟢" :
        j.status === "running" ? "🟡" :
        j.status === "failed" ? "🔴" : "⚪";
      const detail = summary.best
        ? "最佳 +" + (summary.best.take_profit_pct * 100).toFixed(1) +
          "% / -" + (summary.best.stop_loss_pct * 100).toFixed(1) +
          "% 胜率 " + (summary.best.win_rate * 100).toFixed(0) + "%"
        : (summary.net_t_profit != null ? "T 净额 " + summary.net_t_profit : "");
      return "<div class=\"card\"><div class=\"card-head\">" +
        "<div class=\"card-title\">" + badge + " " + (j.symbol || "(组合)") + " " +
        (j.type === "sweep" ? "[Sweep]" : j.type === "portfolio" ? "[组合]" : "[单股]") +
        "</div><div class=\"muted\">" + j.created_at + "</div></div>" +
        "<div class=\"row\">状态 " + j.status +
        (detail ? " ｜ " + detail : "") + "</div></div>";
    }).join("");
    box.innerHTML = rows;
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

    // ===== 回测 =====
    document.getElementById("backtest-btn").onclick = openBacktestDialog;
    document.getElementById("bt-cancel").onclick = closeBacktestDialog;
    document.getElementById("bt-submit").onclick = function () {
      submitBacktest(false).then(refreshBacktests);
    };
    document.getElementById("bt-portfolio").onclick = function () {
      submitBacktest(true).then(refreshBacktests);
    };
    refreshBacktests();

    refresh();
    refreshTrades();
  });
})();
