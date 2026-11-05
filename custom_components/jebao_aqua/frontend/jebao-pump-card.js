/**
 * Jebao pump card: status, power, speed, feeding and the pump's own schedule.
 *
 *   type: custom:jebao-pump-card
 *   device: <device id>
 *
 * The integration loads this file, so it needs no dashboard resource. It finds its
 * entities by translation key, and saves schedules through jebao_aqua.set_schedule.
 */

const DOMAIN = "jebao_aqua";
const MIN_SPEED = 30;
const MAX_SPEED = 100;
const MAX_SLOTS = 48;
const DAY = 24 * 60;
const MODES = { run: "Run", feed: "Feed pause", off: "Stop" };

const toMinutes = (text) => {
  const [hour, minute] = String(text).split(":").map(Number);
  return hour * 60 + minute;
};

const toTime = (minutes) => {
  const value = ((minutes % DAY) + DAY) % DAY;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(Math.floor(value / 60))}:${pad(value % 60)}`;
};

/** The parts of the day a slot covers, as [start, end] minutes; an end of 00:00 is 24:00. */
const spans = (slot) => {
  const start = toMinutes(slot.start);
  const end = toMinutes(slot.end) || DAY;
  return start < end ? [[start, end]] : [[start, DAY], [0, end]];
};

/** Why a schedule can't be saved, or null. These are the service's own rules. */
const scheduleProblem = (slots) => {
  if (slots.length > MAX_SLOTS) return `A schedule has at most ${MAX_SLOTS} periods`;
  for (const slot of slots) {
    if (!slot.start || !slot.end) return "Every period needs a start and an end";
    if (toMinutes(slot.start) === (toMinutes(slot.end) || DAY)) {
      return `${slot.start}-${slot.end} has no length`;
    }
  }
  for (let i = 0; i < slots.length; i++) {
    for (let j = i + 1; j < slots.length; j++) {
      for (const [aStart, aEnd] of spans(slots[i])) {
        for (const [bStart, bEnd] of spans(slots[j])) {
          if (aStart < bEnd && bStart < aEnd) {
            return `${slots[i].start}-${slots[i].end} and ${slots[j].start}-${slots[j].end} overlap`;
          }
        }
      }
    }
  }
  return null;
};

const STYLE = `
  ha-card { display: block; padding: 16px; color: var(--primary-text-color); }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .name { font-size: 1.15em; font-weight: 500; }
  .status { padding: 3px 10px; border-radius: 12px; font-size: .85em; white-space: nowrap;
    color: #fff; background: var(--success-color, #43a047); }
  .status.fault { background: var(--error-color, #db4437); white-space: normal; }
  .status.offline { background: var(--disabled-color, #9e9e9e); }
  .row { display: flex; align-items: center; gap: 12px; min-height: 40px; margin-top: 8px; }
  .row label { flex: none; width: 64px; }
  .row input[type=range] { flex: 1; min-width: 0; accent-color: var(--primary-color); }
  .value { flex: none; width: 2.5em; text-align: right; font-variant-numeric: tabular-nums; }
  .spacer { flex: 1; }
  .hint { font-size: .85em; color: var(--secondary-text-color); margin: 2px 0 0; }
  .error { font-size: .9em; color: var(--error-color, #db4437); margin: 8px 0 0; }
  hr { border: 0; border-top: 1px solid var(--divider-color, #e0e0e0); margin: 12px 0 4px; }
  button { font: inherit; padding: 6px 14px; border-radius: 8px; cursor: pointer;
    border: 1px solid var(--divider-color, #e0e0e0); background: none; color: inherit; }
  button.primary, button.on { border-color: transparent; color: #fff;
    background: var(--primary-color); }
  button:disabled { opacity: .5; cursor: default; }
  button.icon { padding: 2px 9px; }
  input[type=number], input[type=time], select { font: inherit; padding: 4px 6px; border-radius: 6px;
    color: inherit; background: none; border: 1px solid var(--divider-color, #e0e0e0); }
  input[type=number] { width: 3.5em; }
  option { color: #000; }
  .bar { position: relative; height: 16px; margin-top: 10px; border-radius: 4px; overflow: hidden;
    background: var(--divider-color, #e0e0e0); }
  .seg { position: absolute; top: 0; bottom: 0; background: var(--primary-color); }
  .seg.feed { background: var(--warning-color, #ffa600); }
  .seg.off { background: var(--disabled-color, #9e9e9e); }
  .now { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--error-color, #db4437); }
  .hours { display: flex; justify-content: space-between; font-size: .75em; margin-top: 2px;
    color: var(--secondary-text-color); }
  .period { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 0;
    border-bottom: 1px solid var(--divider-color, #e0e0e0); }
  .period .speed { display: flex; align-items: center; gap: 8px; flex: 1 1 140px; min-width: 120px; }
  .period .speed input { flex: 1; min-width: 0; accent-color: var(--primary-color); }
  .actions { display: flex; gap: 8px; margin-top: 12px; }
`;

class JebaoPumpCard extends HTMLElement {
  static getStubConfig(hass) {
    const entry = Object.values(hass.entities || {}).find(
      (e) => e.platform === DOMAIN && e.translation_key === "pump_status"
    );
    return { device: entry ? entry.device_id : "" };
  }

  static getConfigElement() {
    return document.createElement("jebao-pump-card-editor");
  }

  setConfig(config) {
    if (config.device === undefined) throw new Error("Choose a pump");
    this._config = config;
    this._draft = null;
    this._error = "";
    if (this.shadowRoot) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this._render();
    }
    this._update();
  }

  getCardSize() {
    return 6;
  }

  _entity(key) {
    const entry = Object.values(this._hass.entities || {}).find(
      (e) =>
        e.device_id === this._config.device &&
        e.platform === DOMAIN &&
        e.translation_key === key
    );
    return entry ? this._hass.states[entry.entity_id] : undefined;
  }

  _available(state) {
    return !!state && state.state !== "unavailable" && state.state !== "unknown";
  }

  _slots() {
    const schedule = this._entity("timeron");
    return (schedule && schedule.attributes.slots) || [];
  }

  async _call(domain, service, data, target) {
    this._error = "";
    try {
      await this._hass.callService(domain, service, data, target);
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._showError();
  }

  _toggle(state) {
    const service = state.state === "on" ? "turn_off" : "turn_on";
    return this._call("switch", service, {}, { entity_id: state.entity_id });
  }

  _setNumber(state, value) {
    return this._call("number", "set_value", { value }, { entity_id: state.entity_id });
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="head">
          <div class="name" id="name"></div>
          <div class="status" id="status"></div>
        </div>
        <div class="row">
          <label>Power</label><div class="spacer"></div>
          <button id="power"></button>
        </div>
        <div class="row">
          <label>Speed</label>
          <input id="speed" type="range" min="${MIN_SPEED}" max="${MAX_SPEED}" step="1">
          <div class="value" id="speedValue"></div>
        </div>
        <p class="hint" id="speedHint" hidden>Changing the speed stops the schedule.</p>
        <div class="row">
          <label>Feeding</label>
          <input id="feedTime" type="number" min="1" max="60" step="1" aria-label="Feed minutes">
          <span>min</span><div class="spacer"></div>
          <button id="feed"></button>
        </div>
        <hr>
        <div class="row">
          <label>Schedule</label>
          <span class="hint" id="scheduleState"></span><div class="spacer"></div>
          <button id="edit">Edit</button>
          <button id="schedule"></button>
        </div>
        <div class="bar" id="bar"></div>
        <div class="hours"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>
        <div id="editor"></div>
        <p class="error" id="error" hidden></p>
      </ha-card>`;

    const $ = (id) => this.shadowRoot.getElementById(id);
    $("power").addEventListener("click", () => this._toggle(this._entity("switchon")));
    $("feed").addEventListener("click", () => this._toggle(this._entity("feedswitch")));
    $("schedule").addEventListener("click", () => this._toggle(this._entity("timeron")));
    $("edit").addEventListener("click", () => this._openEditor());
    $("speed").addEventListener("input", (ev) => {
      $("speedValue").textContent = ev.target.value;
    });
    $("speed").addEventListener("change", (ev) =>
      this._setNumber(this._entity("motor_speed"), Number(ev.target.value))
    );
    $("feedTime").addEventListener("change", (ev) => {
      const minutes = Math.min(60, Math.max(1, Math.round(Number(ev.target.value)) || 1));
      ev.target.value = minutes;
      this._setNumber(this._entity("feedtime"), minutes);
    });
    this._renderEditor();
  }

  _update() {
    if (!this.shadowRoot || !this._hass || !this._config) return;
    const $ = (id) => this.shadowRoot.getElementById(id);
    const device = (this._hass.devices || {})[this._config.device];
    const status = this._entity("pump_status");
    const power = this._entity("switchon");
    const speed = this._entity("motor_speed");
    const feed = this._entity("feedswitch");
    const feedTime = this._entity("feedtime");
    const schedule = this._entity("timeron");
    const online = this._available(status);

    $("name").textContent = device ? device.name_by_user || device.name : "Jebao pump";
    $("status").textContent = online ? status.state : "Offline";
    $("status").className = `status ${!online ? "offline" : status.state === "OK" ? "" : "fault"}`;

    const setSwitch = (button, state, on, off) => {
      const isOn = !!state && state.state === "on";
      button.textContent = isOn ? on : off;
      button.className = isOn ? "on" : "";
      button.disabled = !this._available(state);
    };
    setSwitch($("power"), power, "On", "Off");
    setSwitch($("feed"), feed, "Stop feeding", "Feed");
    setSwitch($("schedule"), schedule, "On", "Off");

    const active = this.shadowRoot.activeElement;
    if (this._available(speed)) {
      if (active !== $("speed")) $("speed").value = Number(speed.state);
      $("speedValue").textContent = active === $("speed") ? $("speed").value : Math.round(speed.state);
    }
    $("speed").disabled = !this._available(speed);
    if (this._available(feedTime) && active !== $("feedTime")) {
      $("feedTime").value = Math.round(feedTime.state);
    }
    $("feedTime").disabled = !this._available(feedTime);
    $("edit").disabled = !this._available(schedule);

    const running = !!schedule && schedule.state === "on";
    $("speedHint").hidden = !running;
    const mode = schedule && schedule.attributes.current_mode;
    const count = this._slots().length;
    $("scheduleState").textContent = running
      ? MODES[mode] || "Running"
      : `${count} period${count === 1 ? "" : "s"}`;

    if (!this._draft) this._drawBar($("bar"), this._slots());
  }

  _drawBar(bar, slots) {
    const now = new Date();
    const parts = [];
    for (const slot of slots) {
      if (!slot.start || !slot.end) continue;
      for (const [start, end] of spans(slot)) {
        const opacity = slot.mode === "run" ? 0.35 + (0.65 * (slot.speed || 0)) / MAX_SPEED : 1;
        parts.push(
          `<div class="seg ${slot.mode}" title="${slot.start}-${slot.end}" style="left:${
            (start / DAY) * 100
          }%;width:${((end - start) / DAY) * 100}%;opacity:${opacity}"></div>`
        );
      }
    }
    const minutes = now.getHours() * 60 + now.getMinutes();
    parts.push(`<div class="now" style="left:${(minutes / DAY) * 100}%"></div>`);
    bar.innerHTML = parts.join("");
  }

  _openEditor() {
    const speed = this._entity("motor_speed");
    this._speed = this._available(speed) ? Math.round(speed.state) : MAX_SPEED;
    this._draft = this._slots()
      .map((slot) => ({ ...slot }))
      .sort((a, b) => toMinutes(a.start) - toMinutes(b.start));
    this._error = "";
    this._renderEditor();
  }

  _closeEditor() {
    this._draft = null;
    this._renderEditor();
    this._update();
  }

  _addPeriod() {
    const last = this._draft[this._draft.length - 1];
    const start = last ? toMinutes(last.end) : 8 * 60;
    this._draft.push({
      start: toTime(start),
      end: toTime(start + 60),
      mode: "run",
      speed: this._speed,
    });
    this._renderEditor();
  }

  _renderEditor() {
    const root = this.shadowRoot.getElementById("editor");
    const edit = this.shadowRoot.getElementById("edit");
    const draft = this._draft;
    edit.hidden = !!draft;
    if (!draft) {
      root.innerHTML = "";
      this._showError();
      return;
    }
    root.innerHTML = `
      ${draft
        .map(
          (slot, i) => `
        <div class="period" data-index="${i}">
          <input type="time" data-field="start" value="${slot.start}" aria-label="Start">
          <span>to</span>
          <input type="time" data-field="end" value="${slot.end}" aria-label="End">
          <select data-field="mode" aria-label="Mode">
            ${Object.entries(MODES)
              .map(
                ([value, label]) =>
                  `<option value="${value}" ${slot.mode === value ? "selected" : ""}>${label}</option>`
              )
              .join("")}
          </select>
          <div class="speed">${
            slot.mode === "run"
              ? `<input type="range" data-field="speed" min="${MIN_SPEED}" max="${MAX_SPEED}"
                   value="${slot.speed}" aria-label="Speed"><span class="value">${slot.speed}</span>`
              : ""
          }</div>
          <button class="icon" data-remove aria-label="Remove">&times;</button>
        </div>`
        )
        .join("")}
      <div class="actions">
        <button id="add">Add period</button><div class="spacer"></div>
        <button id="cancel">Cancel</button>
        <button id="save" class="primary">Save</button>
      </div>`;

    root.querySelectorAll(".period").forEach((row) => {
      const slot = draft[Number(row.dataset.index)];
      row.querySelector("[data-remove]").addEventListener("click", () => {
        draft.splice(draft.indexOf(slot), 1);
        this._renderEditor();
      });
      row.querySelectorAll("[data-field]").forEach((input) => {
        const field = input.dataset.field;
        input.addEventListener("input", () => {
          slot[field] = field === "speed" ? Number(input.value) : input.value;
          if (field === "speed") input.nextElementSibling.textContent = input.value;
          this._checkDraft();
        });
      });
      row.querySelector('[data-field="mode"]').addEventListener("change", (ev) => {
        slot.mode = ev.target.value;
        if (slot.mode === "run") slot.speed = slot.speed || this._speed;
        else delete slot.speed;
        this._renderEditor();
      });
    });
    root.querySelector("#add").addEventListener("click", () => this._addPeriod());
    root.querySelector("#cancel").addEventListener("click", () => this._closeEditor());
    root.querySelector("#save").addEventListener("click", () => this._saveDraft());
    this._checkDraft();
  }

  _checkDraft() {
    const problem = scheduleProblem(this._draft);
    this.shadowRoot.querySelector("#save").disabled = !!problem;
    this._error = problem || "";
    this._showError();
    this._drawBar(this.shadowRoot.getElementById("bar"), this._draft);
  }

  _showError() {
    const error = this.shadowRoot.getElementById("error");
    error.textContent = this._error;
    error.hidden = !this._error;
  }

  async _saveDraft() {
    const save = this.shadowRoot.querySelector("#save");
    save.disabled = true;
    await this._call(
      DOMAIN,
      "set_schedule",
      { slots: this._draft },
      { entity_id: this._entity("timeron").entity_id }
    );
    if (this._error) save.disabled = false;
    else this._closeEditor();
  }
}

class JebaoPumpCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.schema = [
        { name: "device", selector: { device: { integration: DOMAIN } } },
      ];
      this._form.computeLabel = () => "Pump";
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: { ...this._config, ...ev.detail.value } },
            bubbles: true,
            composed: true,
          })
        );
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
  }
}

if (!customElements.get("jebao-pump-card")) {
  customElements.define("jebao-pump-card", JebaoPumpCard);
  customElements.define("jebao-pump-card-editor", JebaoPumpCardEditor);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "jebao-pump-card",
    name: "Jebao pump",
    description: "Status, power, speed, feeding and the schedule of a Jebao pump",
  });
}
