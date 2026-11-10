/* KR Ledger sidebar panel. Plain web component, no build step. */

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
const KIND_LABEL = { expense: "지출", income: "수입", transfer: "이체", refund: "취소·환불" };
const fmt = new Intl.NumberFormat("ko-KR");

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const won = (n) => `${fmt.format(Math.round(Number(n) || 0))}원`;
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

const STYLE = `
:host {
  display: block; min-height: 100%;
  background: var(--primary-background-color); color: var(--primary-text-color);
  font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
  --kl-expense: var(--kr-ledger-expense-color, #e5484d);
  --kl-income: var(--kr-ledger-income-color, #3e7bfa);
  --kl-transfer: var(--secondary-text-color);
  --kl-card: var(--card-background-color, #fff);
  --kl-line: var(--divider-color, rgba(127,127,127,.2));
  --kl-muted: var(--secondary-text-color);
  --kl-accent: var(--primary-color);
  --kl-radius: var(--ha-card-border-radius, 12px);
}
* { box-sizing: border-box; }
.toolbar { display: flex; align-items: center; gap: 4px; height: var(--header-height, 56px); padding: 0 12px;
  border-bottom: 1px solid var(--kl-line); background: var(--app-header-background-color, var(--kl-card));
  color: var(--app-header-text-color, var(--primary-text-color)); position: sticky; top: 0; z-index: 2; }
.toolbar h1 { font-size: 20px; font-weight: 500; margin: 0 0 0 4px; flex: 1; }
button { font: inherit; color: inherit; cursor: pointer; }
.icon-btn { background: none; border: 0; width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; }
.icon-btn:hover { background: var(--kl-line); }
.icon-btn svg { width: 22px; height: 22px; fill: currentColor; }
.wrap { max-width: 1100px; margin: 0 auto; padding: 16px; display: grid; gap: 16px; }
.month-nav { display: flex; align-items: center; gap: 8px; }
.month-nav .label { font-size: 22px; font-weight: 600; min-width: 140px; text-align: center; font-variant-numeric: tabular-nums; }
.chip { border: 1px solid var(--kl-line); background: var(--kl-card); border-radius: 999px; padding: 6px 12px; font-size: 13px; }
.chip.active { background: var(--kl-accent); border-color: var(--kl-accent); color: var(--text-primary-color, #fff); }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.card { background: var(--kl-card); border-radius: var(--kl-radius); border: 1px solid var(--kl-line); }
.stat { padding: 14px 16px; }
.stat .k { font-size: 13px; color: var(--kl-muted); }
.stat .v { font-size: 22px; font-weight: 650; margin-top: 4px; font-variant-numeric: tabular-nums; }
.stat .s { font-size: 12px; color: var(--kl-muted); margin-top: 2px; }
.expense { color: var(--kl-expense); } .income { color: var(--kl-income); } .transfer, .muted { color: var(--kl-muted); }
.tabs { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; }
.tabs .chip { white-space: nowrap; }
.badge { display: inline-block; min-width: 18px; padding: 0 5px; margin-left: 4px; border-radius: 9px; font-size: 11px; line-height: 18px;
  background: var(--kl-expense); color: #fff; text-align: center; }
.grid { display: grid; grid-template-columns: repeat(7, 1fr); }
.grid .wd { padding: 8px 0; text-align: center; font-size: 12px; color: var(--kl-muted); border-bottom: 1px solid var(--kl-line); }
.grid .wd:first-child, .day.sun .num { color: var(--kl-expense); }
.day.sat .num { color: var(--kl-income); }
.day { min-height: 84px; padding: 6px; border-right: 1px solid var(--kl-line); border-bottom: 1px solid var(--kl-line);
  display: flex; flex-direction: column; gap: 2px; background: none; border-top: 0; border-left: 0; text-align: left; }
.day:nth-child(7n+7) { border-right: 0; }
.day.out { opacity: .35; }
.day.sel { background: color-mix(in srgb, var(--kl-accent) 12%, transparent); }
.day .num { font-size: 13px; font-weight: 600; width: 24px; height: 24px; display: grid; place-items: center; border-radius: 50%; }
.day.today .num { background: var(--kl-accent); color: var(--text-primary-color, #fff); }
.day .amt { font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.day .dot { font-size: 10px; color: var(--kl-muted); }
.section-h { display: flex; align-items: baseline; justify-content: space-between; padding: 14px 16px 6px; }
.section-h h2 { margin: 0; font-size: 16px; font-weight: 600; }
.section-h .t { font-size: 13px; color: var(--kl-muted); font-variant-numeric: tabular-nums; }
.row { display: grid; grid-template-columns: 52px 1fr auto; gap: 10px; align-items: center; padding: 10px 16px; border-top: 1px solid var(--kl-line);
  background: none; border-left: 0; border-right: 0; border-bottom: 0; width: 100%; text-align: left; }
.row:hover { background: color-mix(in srgb, var(--kl-line) 50%, transparent); }
.row .time { font-size: 12px; color: var(--kl-muted); font-variant-numeric: tabular-nums; }
.row .main { min-width: 0; }
.row .m { font-weight: 550; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row .sub { font-size: 12px; color: var(--kl-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row .a { font-weight: 650; font-variant-numeric: tabular-nums; white-space: nowrap; }
.tag { display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 6px; border: 1px solid var(--kl-line); margin-right: 4px; }
.empty { padding: 28px 16px; text-align: center; color: var(--kl-muted); }
.bar { padding: 10px 16px; border-top: 1px solid var(--kl-line); display: grid; gap: 6px; }
.bar .top { display: flex; justify-content: space-between; font-size: 14px; }
.bar .track { height: 8px; border-radius: 4px; background: var(--kl-line); overflow: hidden; }
.bar .fill { height: 100%; background: var(--kl-expense); border-radius: 4px; }
.raw { padding: 12px 16px; border-top: 1px solid var(--kl-line); display: grid; gap: 6px; }
.raw pre { margin: 0; white-space: pre-wrap; word-break: break-all; font: 13px/1.45 inherit; font-family: inherit; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
.btn { border: 1px solid var(--kl-line); background: var(--kl-card); border-radius: 8px; padding: 7px 14px; font-size: 14px; }
.btn.primary { background: var(--kl-accent); border-color: var(--kl-accent); color: var(--text-primary-color, #fff); }
.btn.danger { color: var(--kl-expense); }
.acc { display: grid; grid-template-columns: 1fr auto; gap: 8px 12px; padding: 12px 16px; border-top: 1px solid var(--kl-line); align-items: center; }
.acc .lbl { font-size: 12px; color: var(--kl-muted); }
.acc .ctl { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
input, select, textarea { font: inherit; color: var(--primary-text-color); background: var(--kl-card); border: 1px solid var(--kl-line);
  border-radius: 8px; padding: 8px 10px; width: 100%; }
.acc input[type=text] { width: 180px; } .acc select { width: auto; }
label.sw { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; white-space: nowrap; }
label.sw input { width: auto; }
.overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); display: grid; place-items: center; z-index: 10; padding: 16px; }
.dialog { width: min(440px, 100%); max-height: 90vh; overflow: auto; padding: 20px; display: grid; gap: 12px; }
.dialog h3 { margin: 0; font-size: 18px; }
.dialog .f { display: grid; gap: 4px; } .dialog .f span { font-size: 12px; color: var(--kl-muted); }
.dialog .two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.dialog .src { font-size: 12px; color: var(--kl-muted); background: color-mix(in srgb, var(--kl-line) 40%, transparent); padding: 8px 10px; border-radius: 8px; white-space: pre-wrap; }
.fab { position: fixed; right: 20px; bottom: 20px; width: 56px; height: 56px; border-radius: 50%; border: 0;
  background: var(--kl-accent); color: var(--text-primary-color, #fff); box-shadow: 0 4px 12px rgba(0,0,0,.25); display: grid; place-items: center; z-index: 3; }
.fab svg { width: 26px; height: 26px; fill: currentColor; }
.sched { padding: 8px 16px; border-top: 1px solid var(--kl-line); display: flex; justify-content: space-between; gap: 12px; font-size: 14px; }
.layout { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 16px; align-items: start; }
@media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
@media (max-width: 600px) {
  .wrap { padding: 12px; gap: 12px; }
  .day { min-height: 58px; padding: 4px 2px; } .day .amt { font-size: 10px; } .day .dot { display: none; }
  .stat .v { font-size: 18px; } .acc { grid-template-columns: 1fr; } .acc .ctl { justify-content: flex-start; }
  .acc input[type=text] { width: 100%; }
}
`;

const ICON = {
  left: "M15.41 16.59 10.83 12l4.58-4.59L14 6l-6 6 6 6z",
  right: "M8.59 16.59 13.17 12 8.59 7.41 10 6l6 6-6 6z",
  refresh: "M17.65 6.35A7.96 7.96 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4z",
  plus: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z",
};
const svg = (name) => `<svg viewBox="0 0 24 24"><path d="${ICON[name]}"/></svg>`;

class KrLedgerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    const now = new Date();
    this._year = now.getFullYear();
    this._month = now.getMonth() + 1;
    this._selected = ymd(now);
    this._tab = "calendar";
    this._kind = "all";
    this._data = null;
    this._meta = { categories: [], special: [] };
    this._accounts = [];
    this._unparsed = [];
    this._dialog = null;
    this._error = null;
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this.shadowRoot.addEventListener("change", (e) => this._onChange(e));
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menu) { this._menu.hass = hass; }
    if (first) { this._init(); }
  }
  set narrow(v) { this._narrow = v; if (this._menu) this._menu.narrow = v; }
  set panel(p) { this._panel = p; }

  async _init() {
    this._render();
    try {
      this._meta = await this._ws({ type: "kr_ledger/meta" });
    } catch (e) { /* not fatal */ }
    await this._load();
    try {
      this._unsub = await this._hass.connection.subscribeEvents(() => this._load(), "kr_ledger_transaction");
    } catch (e) { /* non-admin users can't subscribe to custom events; refresh on focus instead */ }
    this._onVis = () => { if (document.visibilityState === "visible") this._load(); };
    document.addEventListener("visibilitychange", this._onVis);
  }

  disconnectedCallback() {
    if (this._unsub) { this._unsub(); this._unsub = null; }
    if (this._onVis) document.removeEventListener("visibilitychange", this._onVis);
  }

  connectedCallback() {
    if (this._hass && !this._unsub && this._data) this._load();
  }

  _ws(msg) { return this._hass.callWS(msg); }

  async _load() {
    try {
      this._error = null;
      this._data = await this._ws({ type: "kr_ledger/month", year: this._year, month: this._month });
      if (this._tab === "review") this._unparsed = await this._ws({ type: "kr_ledger/unparsed" });
      if (this._tab === "accounts") this._accounts = await this._ws({ type: "kr_ledger/accounts" });
    } catch (e) {
      this._error = e && e.message ? e.message : String(e);
    }
    this._render();
  }

  // ------------------------------------------------------------------ events
  async _onClick(e) {
    const el = e.target.closest("[data-a]");
    if (!el) return;
    const a = el.dataset.a;
    if (a === "prev" || a === "next") {
      const d = new Date(this._year, this._month - 1 + (a === "next" ? 1 : -1), 1);
      this._year = d.getFullYear(); this._month = d.getMonth() + 1; this._selected = null;
      return this._load();
    }
    if (a === "today") {
      const d = new Date(); this._year = d.getFullYear(); this._month = d.getMonth() + 1; this._selected = ymd(d);
      return this._load();
    }
    if (a === "refresh") return this._load();
    if (a === "tab") { this._tab = el.dataset.v; return this._load(); }
    if (a === "kind") { this._kind = el.dataset.v; return this._render(); }
    if (a === "day") { this._selected = this._selected === el.dataset.v ? null : el.dataset.v; return this._render(); }
    if (a === "tx") {
      const tx = (this._data?.transactions || []).find((t) => String(t.id) === el.dataset.v);
      if (tx) { this._dialog = { mode: "edit", tx: { ...tx } }; this._render(); }
      return;
    }
    if (a === "add") {
      const base = this._selected || ymd(new Date());
      this._dialog = { mode: "add", tx: { kind: "expense", amount: "", occurred_at: `${base}T${pad(new Date().getHours())}:${pad(new Date().getMinutes())}` } };
      return this._render();
    }
    if (a === "raw-add") {
      const raw = this._unparsed.find((r) => String(r.id) === el.dataset.v);
      if (!raw) return;
      const m = `${raw.title || ""} ${raw.body || ""}`.match(/([\d,]+)\s*원/);
      this._dialog = { mode: "add", rawId: raw.id, source: `${raw.title || ""}\n${raw.body || ""}`,
        tx: { kind: "expense", amount: m ? m[1].replace(/,/g, "") : "", occurred_at: raw.post_time.slice(0, 16) } };
      return this._render();
    }
    if (a === "raw-dismiss") {
      await this._ws({ type: "kr_ledger/unparsed/dismiss", raw_id: Number(el.dataset.v) });
      return this._load();
    }
    if (a === "close") { this._dialog = null; return this._render(); }
    if (a === "overlay" && e.target === el) { this._dialog = null; return this._render(); }
    if (a === "save") return this._save();
    if (a === "delete") {
      if (!confirm("이 내역을 삭제할까요?")) return;
      await this._ws({ type: "kr_ledger/transaction/delete", tx_id: this._dialog.tx.id });
      this._dialog = null;
      return this._load();
    }
  }

  async _onChange(e) {
    const el = e.target;
    if (el.dataset.acc) {
      const id = Number(el.dataset.acc);
      const msg = { type: "kr_ledger/account/update", account_id: id };
      if (el.name === "include") msg.include = el.checked;
      else msg[el.name] = el.value;
      await this._ws(msg);
      return this._load();
    }
  }

  async _save() {
    const root = this.shadowRoot;
    const val = (n) => root.querySelector(`[name="d-${n}"]`)?.value ?? "";
    const amount = Number(String(val("amount")).replace(/[^\d.]/g, ""));
    if (!amount) { alert("금액을 입력하세요."); return; }
    const msg = {
      kind: val("kind"),
      amount,
      merchant: val("merchant") || null,
      category: val("category") || null,
      memo: val("memo") || null,
      account_label: val("account") || null,
    };
    const when = val("when");
    if (when) msg.occurred_at = when.length === 16 ? `${when}:00` : when;
    try {
      if (this._dialog.mode === "edit") {
        await this._ws({ type: "kr_ledger/transaction/update", tx_id: this._dialog.tx.id, ...msg });
      } else {
        if (this._dialog.rawId) msg.raw_id = this._dialog.rawId;
        await this._ws({ type: "kr_ledger/transaction/add", ...msg });
      }
      this._dialog = null;
      await this._load();
    } catch (err) {
      alert(`저장하지 못했습니다: ${err.message || err}`);
    }
  }

  // ------------------------------------------------------------------ render
  _render() {
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLE}</style>
      <div class="toolbar">
        <span id="menu"></span>
        <h1>가계부</h1>
        <button class="icon-btn" data-a="refresh" title="새로고침" aria-label="새로고침">${svg("refresh")}</button>
      </div>
      <div class="wrap">${this._error ? `<div class="card empty">불러오지 못했습니다: ${esc(this._error)}</div>` : this._body()}</div>
      <button class="fab" data-a="add" title="직접 추가" aria-label="직접 추가">${svg("plus")}</button>
      ${this._dialog ? this._dialogHtml() : ""}`;
    if (!this._menu) {
      this._menu = document.createElement("ha-menu-button");
    }
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;
    root.getElementById("menu").appendChild(this._menu);
  }

  _body() {
    const d = this._data;
    if (!d) return `<div class="card empty">불러오는 중…</div>`;
    const days = Object.values(d.days || {});
    const sum = (k) => days.reduce((s, x) => s + (Number(x[k]) || 0), 0);
    const expense = sum("net_expense"), income = sum("income"), refund = sum("refund"), transfer = sum("transfer");
    const foreign = (d.foreign || []).map((f) => `${esc(f.currency)} ${fmt.format(f.total)}`).join(" · ");
    const tab = (v, label, badge) =>
      `<button class="chip ${this._tab === v ? "active" : ""}" data-a="tab" data-v="${v}">${label}${badge ? `<span class="badge">${badge}</span>` : ""}</button>`;
    let content = "";
    if (this._tab === "calendar") content = this._calendarTab();
    else if (this._tab === "list") content = this._listTab(d.transactions);
    else if (this._tab === "category") content = this._categoryTab();
    else if (this._tab === "review") content = this._reviewTab();
    else if (this._tab === "accounts") content = this._accountsTab();
    return `
      <div class="month-nav">
        <button class="icon-btn" data-a="prev" aria-label="이전 달">${svg("left")}</button>
        <div class="label">${this._year}년 ${this._month}월</div>
        <button class="icon-btn" data-a="next" aria-label="다음 달">${svg("right")}</button>
        <button class="chip" data-a="today">오늘</button>
      </div>
      <div class="summary">
        <div class="card stat"><div class="k">지출</div><div class="v expense">${won(expense)}</div>
          <div class="s">${refund ? `취소·환불 ${won(refund)} 반영` : "&nbsp;"}</div></div>
        <div class="card stat"><div class="k">수입</div><div class="v income">${won(income)}</div><div class="s">&nbsp;</div></div>
        <div class="card stat"><div class="k">수입 − 지출</div><div class="v">${won(income - expense)}</div>
          <div class="s">이체 ${won(transfer)} 제외</div></div>
        ${foreign ? `<div class="card stat"><div class="k">해외 결제</div><div class="v" style="font-size:18px">${foreign}</div><div class="s">원화 확정 전</div></div>` : ""}
      </div>
      <div class="tabs">
        ${tab("calendar", "달력")}${tab("list", "내역")}${tab("category", "분류")}
        ${tab("review", "확인 필요", d.unparsed || 0)}${tab("accounts", "계좌·카드")}
      </div>
      ${content}`;
  }

  _calendarTab() {
    const d = this._data;
    const first = new Date(this._year, this._month - 1, 1);
    const start = new Date(first); start.setDate(1 - first.getDay());
    const today = ymd(new Date());
    const sched = {};
    for (const s of d.schedules || []) if (s.due_date) (sched[s.due_date] ||= []).push(s);
    let cells = WEEKDAYS.map((w) => `<div class="wd">${w}</div>`).join("");
    for (let i = 0; i < 42; i++) {
      const day = new Date(start); day.setDate(start.getDate() + i);
      if (i >= 35 && day.getMonth() !== first.getMonth()) break;
      const key = ymd(day);
      const t = d.days[key];
      const cls = ["day", day.getMonth() !== first.getMonth() ? "out" : "", key === today ? "today" : "",
        key === this._selected ? "sel" : "", day.getDay() === 0 ? "sun" : "", day.getDay() === 6 ? "sat" : ""].join(" ");
      cells += `<button class="${cls}" data-a="day" data-v="${key}">
        <span class="num">${day.getDate()}</span>
        ${t && t.net_expense ? `<span class="amt expense">-${fmt.format(Math.round(t.net_expense))}</span>` : ""}
        ${t && t.income ? `<span class="amt income">+${fmt.format(Math.round(t.income))}</span>` : ""}
        ${sched[key] ? `<span class="dot">● 예정 ${sched[key].length}</span>` : ""}
      </button>`;
    }
    const list = this._selected
      ? (d.transactions || []).filter((t) => t.date === this._selected)
      : d.transactions || [];
    const title = this._selected ? `${Number(this._selected.slice(5, 7))}월 ${Number(this._selected.slice(8))}일` : "이번 달 전체";
    const dayExp = list.filter((t) => t.kind === "expense").reduce((s, t) => s + Number(t.amount || 0), 0)
      - list.filter((t) => t.kind === "refund").reduce((s, t) => s + Number(t.amount || 0), 0);
    const upcoming = (d.schedules || []).filter((s) => s.due_date >= ymd(new Date()));
    return `<div class="layout">
      <div class="card"><div class="grid">${cells}</div></div>
      <div style="display:grid;gap:16px">
        <div class="card">
          <div class="section-h"><h2>${title}</h2><span class="t">지출 ${won(dayExp)}</span></div>
          ${this._rows(list)}
        </div>
        ${upcoming.length ? `<div class="card"><div class="section-h"><h2>다가오는 결제</h2></div>
          ${upcoming.map((s) => `<div class="sched"><span>${esc(s.due_date.slice(5).replace("-", "/"))} · ${esc(s.issuer)} ${esc(s.title)}</span>
            <span class="expense">${s.amount ? won(s.amount) : ""}</span></div>`).join("")}</div>` : ""}
      </div>
    </div>`;
  }

  _listTab(all) {
    const kinds = [["all", "전체"], ["expense", "지출"], ["income", "수입"], ["transfer", "이체"], ["refund", "취소·환불"]];
    const filtered = (all || []).filter((t) => this._kind === "all" || t.kind === this._kind);
    const groups = {};
    for (const t of filtered) (groups[t.date] ||= []).push(t);
    const body = Object.keys(groups).sort().reverse().map((date) => {
      const rows = groups[date];
      const exp = rows.reduce((s, t) => s + (t.kind === "expense" ? Number(t.amount) : t.kind === "refund" ? -Number(t.amount) : 0), 0);
      const dt = new Date(`${date}T00:00:00`);
      return `<div class="section-h"><h2>${dt.getMonth() + 1}월 ${dt.getDate()}일 (${WEEKDAYS[dt.getDay()]})</h2>
        <span class="t">${exp ? `지출 ${won(exp)}` : ""}</span></div>${this._rows(rows)}`;
    }).join("");
    return `<div class="tabs">${kinds.map(([v, l]) => `<button class="chip ${this._kind === v ? "active" : ""}" data-a="kind" data-v="${v}">${l}</button>`).join("")}</div>
      <div class="card">${body || `<div class="empty">내역이 없습니다</div>`}</div>`;
  }

  _rows(list) {
    if (!list.length) return `<div class="empty">내역이 없습니다</div>`;
    return list.map((t) => {
      const sign = t.kind === "income" ? "+" : t.kind === "expense" ? "-" : t.kind === "refund" ? "+" : "";
      const cls = t.kind === "income" ? "income" : t.kind === "expense" ? "expense" : t.kind === "refund" ? "income" : "transfer";
      const amount = t.currency === "KRW" ? won(t.amount) : `${esc(t.currency)} ${fmt.format(t.amount)}`;
      const time = t.time_known ? t.occurred_at.slice(11, 16) : "—";
      const tags = [t.kind !== "expense" ? `<span class="tag">${KIND_LABEL[t.kind] || t.kind}</span>` : "",
        t.category ? `<span class="tag">${esc(t.category)}</span>` : "",
        t.account_include === false ? `<span class="tag">제외</span>` : ""].join("");
      const acc = t.account_name || t.account_label || t.issuer || "";
      return `<button class="row" data-a="tx" data-v="${t.id}">
        <span class="time">${time}</span>
        <span class="main"><div class="m">${esc(t.merchant || KIND_LABEL[t.kind] || "")}</div>
          <div class="sub">${tags}${esc(acc)}${t.memo ? ` · ${esc(t.memo)}` : ""}</div></span>
        <span class="a ${cls}">${sign}${amount}</span>
      </button>`;
    }).join("");
  }

  _categoryTab() {
    const cats = (this._data.categories || []).filter((c) => c.total > 0);
    const total = cats.reduce((s, c) => s + c.total, 0);
    if (!cats.length) return `<div class="card empty">이번 달 지출이 없습니다</div>`;
    return `<div class="card"><div class="section-h"><h2>분류별 지출</h2><span class="t">${won(total)}</span></div>
      ${cats.map((c) => {
        const pct = total ? (c.total / total) * 100 : 0;
        return `<div class="bar"><div class="top"><span>${esc(c.category)} <span class="muted">${c.n}건</span></span>
          <span>${won(c.total)} <span class="muted">${pct.toFixed(0)}%</span></span></div>
          <div class="track"><div class="fill" style="width:${pct.toFixed(1)}%"></div></div></div>`;
      }).join("")}
      <div class="empty" style="padding:12px 16px;text-align:left">내역을 눌러 분류를 바꾸면 같은 사용처는 다음부터 자동으로 분류됩니다.</div></div>`;
  }

  _reviewTab() {
    if (!this._unparsed.length) return `<div class="card empty">확인이 필요한 알림이 없습니다</div>`;
    return `<div class="card"><div class="section-h"><h2>인식하지 못한 금융 알림</h2><span class="t">${this._unparsed.length}건</span></div>
      ${this._unparsed.map((r) => `<div class="raw">
        <div class="sub muted">${esc(r.post_time.slice(0, 16).replace("T", " "))} · ${esc(r.package)}</div>
        <pre>${esc(r.title || "")}\n${esc(r.body || "")}</pre>
        <div class="actions"><button class="btn primary" data-a="raw-add" data-v="${r.id}">가계부에 입력</button>
          <button class="btn" data-a="raw-dismiss" data-v="${r.id}">무시</button></div>
      </div>`).join("")}
      <div class="empty" style="padding:12px 16px;text-align:left">자주 오는 형식이면 GitHub 이슈로 알려 주세요. 이름·계좌번호는 지우고 보내 주세요.</div></div>`;
  }

  _accountsTab() {
    const list = this._accounts.filter((a) => a.tx_count > 0);
    if (!list.length) return `<div class="card empty">아직 계좌·카드가 없습니다</div>`;
    return `<div class="card"><div class="section-h"><h2>계좌·카드</h2><span class="t">제외하면 합계에서 빠집니다</span></div>
      ${list.map((a) => `<div class="acc">
        <div><div>${esc(a.name || a.label)}</div><div class="lbl">${esc(a.label)} · ${a.tx_count}건</div></div>
        <div class="ctl">
          <input type="text" name="name" data-acc="${a.id}" value="${esc(a.name || "")}" placeholder="이름" aria-label="이름">
          <select name="owner_type" data-acc="${a.id}" aria-label="구분">
            <option value="personal" ${a.owner_type === "personal" ? "selected" : ""}>개인</option>
            <option value="business" ${a.owner_type === "business" ? "selected" : ""}>사업</option>
          </select>
          <label class="sw"><input type="checkbox" name="include" data-acc="${a.id}" ${a.include ? "checked" : ""}>가계부 포함</label>
        </div></div>`).join("")}</div>`;
  }

  _dialogHtml() {
    const { mode, tx, source } = this._dialog;
    const cats = [...(this._meta.categories || []), ...(this._meta.special || [])];
    const when = (tx.occurred_at || "").slice(0, 16);
    const opt = (v, l, cur) => `<option value="${v}" ${v === cur ? "selected" : ""}>${l}</option>`;
    const sourceText = source || (mode === "edit" && tx.raw_ids?.length ? `알림 ${tx.raw_ids.length}건에서 생성 · ${(tx.source_kinds || []).join(", ")}` : "");
    return `<div class="overlay" data-a="overlay"><div class="card dialog" role="dialog" aria-modal="true">
      <h3>${mode === "edit" ? "내역 수정" : "직접 추가"}</h3>
      ${sourceText ? `<div class="src">${esc(sourceText)}</div>` : ""}
      <div class="two">
        <label class="f"><span>유형</span><select name="d-kind">${Object.entries(KIND_LABEL).map(([v, l]) => opt(v, l, tx.kind)).join("")}</select></label>
        <label class="f"><span>금액${tx.currency && tx.currency !== "KRW" ? ` (${esc(tx.currency)})` : ""}</span>
          <input name="d-amount" inputmode="decimal" value="${esc(tx.amount)}"></label>
      </div>
      <label class="f"><span>사용처 / 상대방</span><input name="d-merchant" value="${esc(tx.merchant || "")}"></label>
      <div class="two">
        <label class="f"><span>분류</span><input name="d-category" list="kl-cats" value="${esc(tx.category || "")}">
          <datalist id="kl-cats">${cats.map((c) => `<option value="${esc(c)}">`).join("")}</datalist></label>
        <label class="f"><span>일시</span><input type="datetime-local" name="d-when" value="${esc(when)}"></label>
      </div>
      <label class="f"><span>계좌·카드</span><input name="d-account" value="${esc(tx.account_label || "")}"></label>
      <label class="f"><span>메모</span><input name="d-memo" value="${esc(tx.memo || "")}"></label>
      <div class="actions" style="justify-content:space-between">
        ${mode === "edit" ? `<button class="btn danger" data-a="delete">삭제</button>` : "<span></span>"}
        <span class="actions"><button class="btn" data-a="close">취소</button><button class="btn primary" data-a="save">저장</button></span>
      </div>
    </div></div>`;
  }
}

if (!customElements.get("kr-ledger-panel")) customElements.define("kr-ledger-panel", KrLedgerPanel);
