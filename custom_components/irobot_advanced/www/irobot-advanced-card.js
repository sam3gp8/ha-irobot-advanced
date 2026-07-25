/**
 * iRobot Advanced — dashboard card and sidebar panel.
 *
 * No build step and no Lit dependency: plain custom elements against the
 * `hass` object, styled entirely with Home Assistant's CSS variables so it
 * follows the active theme.
 *
 * Usage in a dashboard:
 *   type: custom:irobot-advanced-card
 *   entity: vacuum.roomba        # optional; auto-detected when omitted
 */

const DOMAIN = "irobot_advanced";

const TABS = [
  { id: "control", label: "Control", icon: "M12,2A10,10 0 1,0 22,12A10,10 0 0,0 12,2" },
  { id: "map", label: "Map" },
  { id: "obstacles", label: "Obstacles" },
  { id: "history", label: "History" },
];

const STYLES = `
  :host { display: block; }
  .wrap {
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, none);
    border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color, #e0e0e0));
    overflow: hidden;
    color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, inherit);
  }
  .head { display: flex; align-items: center; gap: 14px; padding: 16px; }
  .avatar {
    width: 44px; height: 44px; border-radius: 50%;
    background: #fff; flex: none;
    display: grid; place-items: center; overflow: hidden;
    border: 1px solid var(--divider-color);
  }
  .avatar img { width: 78%; height: 78%; object-fit: contain; }
  .head h2 { margin: 0; font-size: 1.15rem; font-weight: 500; }
  .head .sub { color: var(--secondary-text-color); font-size: .85rem; margin-top: 2px; }
  .spacer { flex: 1; }
  .batt { text-align: right; font-size: .85rem; color: var(--secondary-text-color); }
  .batt b { display: block; font-size: 1.3rem; color: var(--primary-text-color); font-weight: 500; }

  .tabs { display: flex; border-bottom: 1px solid var(--divider-color); }
  .tabs button {
    flex: 1; padding: 12px 4px; background: none; border: none; cursor: pointer;
    font: inherit; font-size: .9rem; color: var(--secondary-text-color);
    border-bottom: 2px solid transparent;
  }
  .tabs button[aria-selected="true"] { color: var(--primary-color); border-bottom-color: var(--primary-color); }
  .tabs button:hover { background: var(--secondary-background-color); }

  .body { padding: 16px; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; }
  .row.tight { gap: 6px; }
  button.act {
    flex: 1 1 auto; min-width: 88px; padding: 10px 12px; cursor: pointer;
    font: inherit; font-size: .875rem;
    border-radius: 8px; border: 1px solid var(--divider-color);
    background: var(--secondary-background-color); color: var(--primary-text-color);
  }
  button.act:hover { border-color: var(--primary-color); }
  button.act.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
  button.act[disabled] { opacity: .45; cursor: default; }

  h3 { margin: 22px 0 8px; font-size: .78rem; text-transform: uppercase;
       letter-spacing: .06em; color: var(--secondary-text-color); font-weight: 600; }
  h3:first-child { margin-top: 0; }

  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip {
    padding: 7px 13px; border-radius: 999px; cursor: pointer; font: inherit; font-size: .85rem;
    border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color);
  }
  .chip:hover { border-color: var(--primary-color); color: var(--primary-color); }

  .grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
  .stat { padding: 12px; border-radius: 8px; background: var(--secondary-background-color); }
  .stat span { display: block; font-size: .75rem; color: var(--secondary-text-color); }
  .stat b { font-size: 1.05rem; font-weight: 500; }

  .map { width: 100%; border-radius: 8px; display: block; background: var(--secondary-background-color); }

  .obs { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
  .obs figure { margin: 0; border-radius: 8px; overflow: hidden; background: var(--secondary-background-color); }
  .obs img { width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block; cursor: pointer; }
  .obs figcaption { padding: 8px 10px; font-size: .78rem; }
  .obs figcaption b { display: block; font-weight: 500; }
  .obs figcaption span { color: var(--secondary-text-color); }

  table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  th, td { text-align: left; padding: 9px 6px; border-bottom: 1px solid var(--divider-color); }
  th { font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
       color: var(--secondary-text-color); font-weight: 600; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }

  .empty { padding: 28px 8px; text-align: center; color: var(--secondary-text-color); font-size: .88rem; }
  .err { padding: 10px 12px; border-radius: 8px; font-size: .82rem; margin-bottom: 12px;
         background: var(--error-color, #db4437); color: #fff; }

  dialog { border: none; border-radius: 12px; padding: 0; max-width: 92vw; background: var(--card-background-color); }
  dialog::backdrop { background: rgba(0,0,0,.6); }
  dialog img { max-width: 100%; max-height: 78vh; display: block; }
  dialog .cap { padding: 12px 16px; color: var(--primary-text-color); font-size: .85rem; }
`;

/* ------------------------------------------------------------------ helpers */

function fmtTime(value) {
  if (!value) return "—";
  const n = Number(value);
  const d = Number.isFinite(n) && n > 0
    ? new Date(n > 1e11 ? n : n * 1000)
    : new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
}

function fmtDuration(mins) {
  const n = Number(mins);
  if (!Number.isFinite(n) || n <= 0) return "—";
  const h = Math.floor(n / 60);
  return h ? `${h}h ${Math.round(n % 60)}m` : `${Math.round(n)}m`;
}

function titleCase(text) {
  if (!text) return "";
  return String(text).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/* --------------------------------------------------------------- the card */

class IRobotAdvancedCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "control";
    this._cacheBust = Date.now();
    this._built = false;
  }

  setConfig(config) {
    this._config = config || {};
    this._entity = this._config.entity || null;
  }

  getCardSize() {
    return 12;
  }

  static getStubConfig() {
    return { entity: "" };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    // Only re-render when something this view depends on changed. Re-rendering
    // on every state push rebuilds the body innerHTML and steals clicks.
    const sig = this._signature();
    if (sig !== this._lastSig) {
      this._lastSig = sig;
      this._render();
    }
  }

  _signature() {
    const id = this._vacuumId();
    const vac = id && this._hass.states[id];
    if (!vac) return "none";
    const a = vac.attributes || {};
    // Include only fields the current tab renders, plus the tab itself.
    const base = [
      this._tab,
      vac.state,
      a.battery_level,
      a.phase,
      a.error,
      a.fan_speed,
      a.cycle,
    ];
    if (this._tab === "control") {
      base.push((a.regions || []).length, a.square_feet, a.bin_full);
    } else if (this._tab === "obstacles") {
      base.push(
        this._siblings(id).filter((e) => e.startsWith("image.")).length
      );
    } else if (this._tab === "history") {
      const sid = this._find(id, "sensor", "_total_missions");
      base.push(sid && this._hass.states[sid]?.state);
    }
    // Map tab intentionally excluded: its refresh is driven by the timer.
    return JSON.stringify(base);
  }

  connectedCallback() {
    // Nudge the map to refresh while the card is on screen.
    this._timer = setInterval(() => {
      if (this._tab === "map") {
        this._cacheBust = Date.now();
        this._render();
      }
    }, 10000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  /* ------------------------------------------------------ entity discovery */

  _vacuumId() {
    if (this._entity) return this._entity;
    const states = this._hass?.states || {};
    const registry = this._hass?.entities || {};
    for (const id of Object.keys(states)) {
      if (!id.startsWith("vacuum.")) continue;
      if (registry[id]?.platform === DOMAIN) return id;
    }
    // Fallback for frontends that don't expose the entity registry.
    return Object.keys(states).find((id) => id.startsWith("vacuum.")) || null;
  }

  /** Every entity belonging to the same device as the vacuum. */
  _siblings(vacuumId) {
    const registry = this._hass?.entities || {};
    const deviceId = registry[vacuumId]?.device_id;
    if (deviceId) {
      return Object.keys(registry).filter((id) => registry[id]?.device_id === deviceId);
    }
    const stem = vacuumId.split(".")[1];
    return Object.keys(this._hass?.states || {}).filter((id) => id.includes(stem));
  }

  _find(vacuumId, domain, suffix) {
    return this._siblings(vacuumId).find(
      (id) => id.startsWith(`${domain}.`) && id.endsWith(suffix)
    );
  }

  /* ----------------------------------------------------------------- build */

  _build() {
    this._built = true;
    const style = document.createElement("style");
    style.textContent = STYLES;

    const wrap = document.createElement("div");
    wrap.className = "wrap";
    wrap.innerHTML = `
      <div class="head"></div>
      <div class="tabs"></div>
      <div class="body"></div>
      <dialog><img alt=""><div class="cap"></div></dialog>
    `;

    this.shadowRoot.append(style, wrap);
    this._el = {
      head: wrap.querySelector(".head"),
      tabs: wrap.querySelector(".tabs"),
      body: wrap.querySelector(".body"),
      dialog: wrap.querySelector("dialog"),
    };

    this._el.dialog.addEventListener("click", () => this._el.dialog.close());

    this._el.tabs.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-tab]");
      if (!button) return;
      this._tab = button.dataset.tab;
      this._cacheBust = Date.now();
      this._lastSig = this._signature();
      this._render();
    });

    this._el.body.addEventListener("click", (event) => this._onBodyClick(event));
  }

  /* ------------------------------------------------------------- rendering */

  _render() {
    const vacuumId = this._vacuumId();
    if (!vacuumId || !this._hass.states[vacuumId]) {
      this._el.head.innerHTML = "";
      this._el.tabs.innerHTML = "";
      this._el.body.innerHTML = `<div class="empty">No iRobot Advanced vacuum found.</div>`;
      return;
    }

    this._vac = this._hass.states[vacuumId];
    this._vacId = vacuumId;

    this._renderHead();
    this._renderTabs();

    const body = this._el.body;
    const cloudError = this._vac.attributes.cloud_error;
    const banner = cloudError ? `<div class="err">Cloud: ${cloudError}</div>` : "";

    if (this._tab === "control") body.innerHTML = banner + this._control();
    else if (this._tab === "map") body.innerHTML = banner + this._map();
    else if (this._tab === "obstacles") body.innerHTML = banner + this._obstacles();
    else body.innerHTML = banner + this._history();
  }

  _renderHead() {
    const attrs = this._vac.attributes;
    const battery = attrs.battery_level;
    const name = attrs.friendly_name || "Roomba";
    this._el.head.innerHTML = `
      <div class="avatar"><img
          src="/api/brands/integration/irobot_advanced/icon.png"
          onerror="this.onerror=null;this.src='/irobot_advanced/irobot-icon.png'"
          alt=""></div>
      <div>
        <h2>${name}</h2>
        <div class="sub">${titleCase(attrs.phase || this._vac.state)}${
          attrs.error && attrs.error !== "None" ? ` — ${attrs.error}` : ""
        }</div>
      </div>
      <div class="spacer"></div>
      <div class="batt"><b>${battery ?? "—"}%</b>battery</div>
    `;
  }

  _renderTabs() {
    this._el.tabs.innerHTML = TABS.map(
      (tab) =>
        `<button data-tab="${tab.id}" aria-selected="${this._tab === tab.id}">${tab.label}</button>`
    ).join("");
  }

  _control() {
    const attrs = this._vac.attributes;
    const rooms = attrs.regions || [];
    const speeds = attrs.fan_speed_list || [];
    const current = attrs.fan_speed;

    const roomChips = rooms.length
      ? `<div class="chips">${rooms
          .map(
            (room) =>
              `<button class="chip" data-room="${room.region_id}" data-pmap="${room.pmap_id}">${
                room.name || `Room ${room.region_id}`
              }</button>`
          )
          .join("")}</div>`
      : `<div class="empty">No mapped rooms. Sign in to the cloud and run <code>refresh_maps</code>.</div>`;

    return `
      <h3>Commands</h3>
      <div class="row">
        <button class="act primary" data-svc="vacuum.start">Start</button>
        <button class="act" data-svc="vacuum.pause">Pause</button>
        <button class="act" data-svc="vacuum.stop">Stop</button>
        <button class="act" data-svc="vacuum.return_to_base">Dock</button>
      </div>
      <div class="row tight" style="margin-top:8px">
        <button class="act" data-svc="${DOMAIN}.locate_robot">Locate</button>
        <button class="act" data-svc="${DOMAIN}.empty_bin">Empty bin</button>
        <button class="act" data-svc="${DOMAIN}.refresh_maps">Refresh data</button>
      </div>

      <h3>Suction</h3>
      <div class="row tight">
        ${speeds
          .map(
            (speed) =>
              `<button class="act ${speed === current ? "primary" : ""}" data-speed="${speed}">${titleCase(
                speed
              )}</button>`
          )
          .join("")}
      </div>

      <h3>Clean a room</h3>
      ${roomChips}

      <h3>Status</h3>
      <div class="grid2">
        <div class="stat"><span>Cycle</span><b>${titleCase(attrs.cycle) || "—"}</b></div>
        <div class="stat"><span>Area this run</span><b>${attrs.square_feet ?? "—"} ft²</b></div>
        <div class="stat"><span>Runtime</span><b>${fmtDuration(attrs.elapsed_minutes)}</b></div>
        <div class="stat"><span>Bin</span><b>${attrs.bin_full ? "Full" : "OK"}</b></div>
      </div>
    `;
  }

  _map() {
    const cameraId = this._find(this._vacId, "camera", "_map");
    const camera = cameraId && this._hass.states[cameraId];
    if (!camera || !camera.attributes.entity_picture) {
      return `<div class="empty">No map available yet.</div>`;
    }
    const position = this._vac.attributes.position;
    const src = `${camera.attributes.entity_picture}${
      camera.attributes.entity_picture.includes("?") ? "&" : "?"
    }_=${this._cacheBust}`;

    return `
      <img class="map" src="${src}" alt="Robot map">
      <div class="grid2" style="margin-top:12px">
        <div class="stat"><span>Maps stored</span><b>${
          (this._vac.attributes.maps || []).length
        }</b></div>
        <div class="stat"><span>Rooms</span><b>${
          (this._vac.attributes.regions || []).length
        }</b></div>
        <div class="stat"><span>Position</span><b>${
          position ? `${Math.round(position.x)}, ${Math.round(position.y)}` : "unknown"
        }</b></div>
      </div>
    `;
  }

  _obstacles() {
    const images = this._siblings(this._vacId)
      .filter((id) => id.startsWith("image.") && id.includes("obstacle"))
      .map((id) => this._hass.states[id])
      .filter((state) => state && state.attributes.entity_picture);

    if (!images.length) {
      return `<div class="empty">No obstacle snapshots. These arrive with cloud access after a run.</div>`;
    }

    return `<div class="obs">${images
      .map((state) => {
        const attrs = state.attributes;
        const position = attrs.position || {};
        const coords =
          position.x != null ? `${Math.round(position.x)}, ${Math.round(position.y)}` : "";
        return `
          <figure>
            <img src="${attrs.entity_picture}" alt="Obstacle"
                 data-full="${attrs.entity_picture}"
                 data-cap="${titleCase(attrs.obstacle_type) || "Obstacle"} — ${fmtTime(state.state)}">
            <figcaption>
              <b>${titleCase(attrs.obstacle_type) || "Unclassified"}</b>
              <span>${fmtTime(state.state)}${coords ? ` · ${coords}` : ""}</span>
            </figcaption>
          </figure>`;
      })
      .join("")}</div>`;
  }

  _history() {
    const sensorId = this._find(this._vacId, "sensor", "_total_missions");
    const missions = sensorId
      ? this._hass.states[sensorId]?.attributes?.recent_missions || []
      : [];

    if (!missions.length) {
      return `<div class="empty">No mission history yet. This needs cloud access.</div>`;
    }

    return `
      <table>
        <thead>
          <tr><th>Started</th><th>Duration</th><th class="num">Area</th><th>Result</th></tr>
        </thead>
        <tbody>
          ${missions
            .map(
              (mission) => `
            <tr>
              <td>${fmtTime(mission.start)}</td>
              <td>${fmtDuration(mission.duration)}</td>
              <td class="num">${mission.area != null ? `${mission.area} ft²` : "—"}</td>
              <td>${titleCase(mission.status) || "—"}</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
    `;
  }

  /* ------------------------------------------------------------- actions */

  _onBodyClick(event) {
    const target = event.target;

    const image = target.closest("img[data-full]");
    if (image) {
      this._el.dialog.querySelector("img").src = image.dataset.full;
      this._el.dialog.querySelector(".cap").textContent = image.dataset.cap || "";
      this._el.dialog.showModal();
      return;
    }

    const svcButton = target.closest("button[data-svc]");
    if (svcButton) {
      const [domain, service] = svcButton.dataset.svc.split(".");
      this._hass.callService(domain, service, { entity_id: this._vacId });
      return;
    }

    const speedButton = target.closest("button[data-speed]");
    if (speedButton) {
      this._hass.callService("vacuum", "set_fan_speed", {
        entity_id: this._vacId,
        fan_speed: speedButton.dataset.speed,
      });
      return;
    }

    const roomButton = target.closest("button[data-room]");
    if (roomButton) {
      this._hass.callService(DOMAIN, "clean_rooms", {
        entity_id: this._vacId,
        regions: [roomButton.dataset.room],
        pmap_id: roomButton.dataset.pmap,
      });
    }
  }
}

customElements.define("irobot-advanced-card", IRobotAdvancedCard);

/* ------------------------------------------------------------- the panel */

class IRobotAdvancedPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._cards) this._build();
    this._cards.forEach((card) => {
      card.hass = hass;
    });
  }

  set narrow(value) {
    this._narrow = value;
  }

  _build() {
    this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      .page { padding: 16px; display: grid; gap: 16px;
              grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
              max-width: 1400px; margin: 0 auto; }
      .none { padding: 48px; text-align: center; color: var(--secondary-text-color); }
    `;
    const page = document.createElement("div");
    page.className = "page";

    const registry = this._hass.entities || {};
    const vacuums = Object.keys(this._hass.states).filter(
      (id) => id.startsWith("vacuum.") && registry[id]?.platform === DOMAIN
    );

    this._cards = [];
    if (!vacuums.length) {
      page.innerHTML = `<div class="none">No iRobot Advanced robots are set up yet.</div>`;
    } else {
      for (const entity of vacuums) {
        const card = document.createElement("irobot-advanced-card");
        card.setConfig({ entity });
        page.appendChild(card);
        this._cards.push(card);
      }
    }

    this.shadowRoot.append(style, page);
  }
}

customElements.define("irobot-advanced-panel", IRobotAdvancedPanel);

/* --------------------------------------------------- card picker metadata */

window.customCards = window.customCards || [];
window.customCards.push({
  type: "irobot-advanced-card",
  name: "iRobot Advanced",
  description: "Control, map, obstacle snapshots and mission history for an iRobot robot.",
  preview: true,
});

console.info("%c iRobot Advanced card loaded", "color: #41BDF5; font-weight: bold");
