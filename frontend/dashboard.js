(() => {
  "use strict";

  const API = "/api/v1/dashboard";
  const PAGE_SIZE = 25;
  const PALETTE = ["#005746", "#00A16A", "#0F8888", "#6F838B", "#7FEA00"];
  const charts = new Map();
  const state = {
    options: null,
    overview: null,
    datasets: [],
    activeDataset: null,
    matchupPage: 1,
    matchupSort: { column: "wickets", order: "desc" },
    wicketPage: 1,
    wicketSort: { column: "wicket_event_id", order: "desc" },
    datasetPage: 1,
    datasetSort: null,
    matchupTimer: null,
    wicketTimer: null,
    datasetTimer: null,
    loadedTabs: new Set(),
    activeTab: "bowler-analytics",
    phaseRows: [],
    phaseSort: { column: "wickets", order: "desc" },
    requestVersions: { overview: 0, bowler: 0, matchup: 0, wicket: 0, phase: 0, dataset: 0, catalog: 0 },
  };

  const byId = (id) => document.getElementById(id);
  const countFormat = new Intl.NumberFormat();

  class DashboardError extends Error {
    constructor(message, status = 0) {
      super(message);
      this.status = status;
    }
  }

  function showNotice(message, isError = false) {
    const notice = byId("dashboard-notice");
    notice.textContent = message;
    notice.classList.toggle("is-error", isError);
    notice.hidden = !message;
  }

  function announceDashboardStatus(stateName, message) {
    window.dispatchEvent(new CustomEvent("cric:dashboard-status", {
      detail: { state: stateName, message },
    }));
  }

  async function requestJson(path, params = {}) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") query.set(key, value);
    }
    const url = `${API}/${path}${query.size ? `?${query}` : ""}`;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    let response;
    try {
      response = await fetch(url, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
    } catch (error) {
      if (error.name === "AbortError") {
        throw new DashboardError("The dashboard request timed out. Retry after checking the local service.");
      }
      throw new DashboardError("Cannot reach the local dashboard API. Restart the CRIC service and retry.");
    } finally {
      window.clearTimeout(timeout);
    }
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new DashboardError("The local dashboard returned an unreadable response.", response.status);
    }
    if (!response.ok) {
      throw new DashboardError(payload?.error?.message || `Dashboard request failed (${response.status}).`, response.status);
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new DashboardError("The local dashboard returned an unexpected response format.", response.status);
    }
    return payload;
  }

  function element(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined && text !== null) result.textContent = String(text);
    return result;
  }

  function setSelect(select, values, placeholder, valueOf, labelOf, includeEmpty = true) {
    const selected = select.value;
    const items = [];
    if (includeEmpty) items.push(new Option(placeholder, ""));
    for (const value of values) items.push(new Option(labelOf(value), valueOf(value)));
    select.replaceChildren(...items);
    if ([...select.options].some((option) => option.value === selected)) select.value = selected;
  }

  function setPlayerSelect(select, players, placeholder) {
    const selected = select.value;
    const options = [new Option(placeholder, "")];
    for (const player of players) options.push(new Option(`${player.name} · ${player.id}`, player.id));
    select.replaceChildren(...options);
    if ([...select.options].some((option) => option.value === selected)) select.value = selected;
  }

  function validSeries(series, labelKey, valueKey) {
    return Array.isArray(series) && series.every((item) =>
      item && typeof item[labelKey] === "string" && Number.isFinite(item[valueKey]) && item[valueKey] >= 0
    );
  }

  function chartEmpty(canvasId, message) {
    const canvas = byId(canvasId);
    if (!canvas) return;
    const empty = canvas.parentElement.querySelector(".chart-empty");
    const existing = charts.get(canvasId);
    if (existing) {
      existing.destroy();
      charts.delete(canvasId);
    }
    canvas.hidden = true;
    const messageElement = empty || element("p", "chart-empty");
    if (!empty) canvas.parentElement.append(messageElement);
    messageElement.textContent = message;
    messageElement.classList.toggle("is-loading", message.startsWith("Loading"));
    messageElement.hidden = false;
  }

  function drawChart(canvasId, type, labels, datasets, options = {}, emptyMessage = "No records match the current filters.") {
    if (!labels.length || !datasets.some((dataset) => dataset.data.length)) {
      chartEmpty(canvasId, emptyMessage);
      return;
    }
    if (!window.Chart) {
      chartEmpty(canvasId, "Charts are unavailable. Check the network connection and refresh.");
      return;
    }

    const canvas = byId(canvasId);
    if (!canvas) return;
    const empty = canvas.parentElement.querySelector(".chart-empty");
    const previous = charts.get(canvasId);
    if (previous) previous.destroy();
    canvas.hidden = false;
    empty.hidden = true;

    try {
      const chart = new window.Chart(canvas, {
        type,
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: "nearest", intersect: false },
          plugins: {
            legend: { display: datasets.length > 1, position: "bottom", labels: { usePointStyle: true, color: "#687a8d", font: { size: 10 }, padding: 15 } },
            tooltip: { enabled: true },
          },
          ...options,
        },
      });
      charts.set(canvasId, chart);
    } catch {
      chartEmpty(canvasId, "This chart could not be rendered. Refresh the dashboard to retry.");
    }
  }

  function axisOptions(xTitle, yTitle, horizontal = false) {
    return {
      indexAxis: horizontal ? "y" : "x",
      scales: {
        x: {
          beginAtZero: true,
          grid: { display: !horizontal, color: "#edf1f5" },
          ticks: { color: "#75869a", precision: 0 },
          title: { display: Boolean(horizontal ? yTitle : xTitle), text: horizontal ? yTitle : xTitle, color: "#718096", font: { size: 10 } },
        },
        y: {
          beginAtZero: true,
          grid: { display: horizontal, color: "#edf1f5" },
          ticks: { color: "#75869a", precision: 0, autoSkip: !horizontal },
          title: { display: Boolean(horizontal ? xTitle : yTitle), text: horizontal ? xTitle : yTitle, color: "#718096", font: { size: 10 } },
        },
      },
    };
  }

  function setComponentState(id, message, retry) {
    const container = byId(id);
    if (!container) return;
    container.replaceChildren();
    if (message.startsWith("Loading")) container.append(element("span", "loading-spinner"));
    if (message) container.append(element("span", "", message));
    if (retry) {
      const button = element("button", "button button-small button-secondary", "Retry");
      button.type = "button";
      button.addEventListener("click", retry);
      container.append(button);
    }
    container.hidden = !message;
    container.classList.toggle("is-error", Boolean(retry));
  }

  function renderOverviewCharts(data) {
    if (!validSeries(data.wickets_by_phase, "phase", "wickets") ||
        !Array.isArray(data.top_bowlers) ||
        !data.top_bowlers.every((row) => row && typeof row.bowler_name === "string" &&
          Number.isFinite(row.wickets) && Number.isFinite(row.legal_balls))) {
      throw new DashboardError("The overview API returned invalid chart data.");
    }

    const bowlers = data.top_bowlers;
    drawChart("overview-phase-wickets-chart", "bar", data.wickets_by_phase.map((item) => item.phase), [{
      label: "Credited wickets",
      data: data.wickets_by_phase.map((item) => item.wickets),
      backgroundColor: PALETTE[1],
      borderRadius: 4,
      maxBarThickness: 65,
    }], {
      ...axisOptions("Dataset phase", "Credited wickets"),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => ` ${countFormat.format(context.parsed.y)} credited wickets` } } },
    }, "No qualifying phase wicket totals are available.");

    drawChart("top-bowlers-chart", "bar", bowlers.map((item) => item.bowler_name), [{
      label: "Bowler-credited wickets",
      data: bowlers.map((item) => item.wickets),
      backgroundColor: PALETTE[2],
      borderRadius: 3,
      maxBarThickness: 28,
    }], {
      ...axisOptions("Bowler", "Credited wickets", true),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => {
        const item = bowlers[context.dataIndex];
        return [` ${context.parsed.x} credited wickets`, ` ${countFormat.format(item.legal_balls)} legal balls · ${item.sample_size_flag || "sample status unavailable"}`];
      } } } },
    }, "No bowler totals are available.");
  }

  function renderKpis(kpis) {
    const fields = {
      "kpi-matches": "matches",
      "kpi-bowlers": "bowlers",
      "kpi-batters": "batters_in_matchups",
      "kpi-wickets": "bowler_credited_wickets",
      "kpi-matchups": "matchup_records",
      "kpi-datasets": "datasets",
    };
    for (const [elementId, key] of Object.entries(fields)) {
      const value = kpis[key];
      byId(elementId).textContent = Number.isFinite(value) ? countFormat.format(value) : "Unavailable";
    }
  }

  async function loadOverview() {
    const requestVersion = ++state.requestVersions.overview;
    chartEmpty("overview-phase-wickets-chart", "Loading credited wickets by phase…");
    chartEmpty("top-bowlers-chart", "Loading top bowler records…");
    setComponentState("kpi-error", "Loading dataset summary…");
    try {
      const data = await requestJson("overview", { min_balls: 30 });
      if (requestVersion !== state.requestVersions.overview) return;
      if (!data.kpis || typeof data.kpis !== "object") throw new DashboardError("The overview response is missing dataset totals.");
      state.overview = data;
      renderKpis(data.kpis);
      renderOverviewCharts(data);
      setComponentState("kpi-error", "");
      showNotice("");
    } catch (error) {
      if (requestVersion !== state.requestVersions.overview) return;
      showNotice(error.message || "Overview analytics could not be loaded.", true);
      setComponentState("kpi-error", error.message || "Dataset summary is unavailable.", loadOverview);
      for (const canvas of ["top-bowlers-chart", "overview-phase-wickets-chart"]) {
        chartEmpty(canvas, error.message || "Overview data is unavailable.");
      }
    }
  }

  function renderBowlerSummary(data) {
    const selected = data.selected_bowler;
    if (!selected) {
      for (const id of ["bowler-wickets", "bowler-economy", "bowler-average", "bowler-strike-rate", "bowler-balls"]) byId(id).textContent = "n/a";
      return;
    }
    const metrics = {
      "bowler-wickets": selected.wickets,
      "bowler-economy": selected.economy,
      "bowler-average": selected.bowling_average,
      "bowler-strike-rate": selected.bowling_strike_rate,
      "bowler-balls": selected.legal_balls,
    };
    for (const [id, value] of Object.entries(metrics)) {
      const target = byId(id);
      target.textContent = value === null ? "n/a" : id === "bowler-wickets" || id === "bowler-balls"
        ? countFormat.format(value) : formatMetric(value);
      if (value === null) target.title = id === "bowler-economy"
        ? "No legal balls are available for this economy calculation."
        : "No bowler-credited wickets are available for this rate.";
    }
  }

  function renderBowlerCharts(data) {
    const phases = data.phase_performance || [];
    const selected = data.selected_bowler;
    if (!selected) {
      chartEmpty("bowler-phase-chart", "Select a bowler to see phase performance.");
      chartEmpty("bowler-season-chart", "Select a bowler to see season wickets.");
      return;
    }
    drawChart("bowler-phase-chart", "bar", phases.map((item) => item.phase), [
      { label: "Economy · runs per 6 legal balls", data: phases.map((item) => item.economy), backgroundColor: PALETTE[2], borderRadius: 3 },
      { type: "line", label: "Credited wickets", data: phases.map((item) => item.wickets), borderColor: PALETTE[1], backgroundColor: PALETTE[1], yAxisID: "y1", tension: 0.15, pointRadius: 4 },
    ], {
      scales: {
        x: { grid: { display: false }, ticks: { color: "#6F838B" } },
        y: { beginAtZero: true, grid: { color: "#e4ebea" }, title: { display: true, text: "Economy", color: "#6F838B" }, ticks: { color: "#6F838B" } },
        y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Credited wickets", color: "#6F838B" }, ticks: { color: "#6F838B", precision: 0 } },
      },
      plugins: { tooltip: { callbacks: { label: (context) => ` ${context.dataset.label}: ${context.parsed.y === null ? "n/a" : formatMetric(context.parsed.y)}`, afterBody: (items) => {
        const row = phases[items[0].dataIndex];
        return `Sample: ${countFormat.format(row.legal_balls)} legal balls`;
      } } } },
    }, "No phase records are available for this bowler.");

    const seasons = (data.season_wickets || []).filter((item) => /^\d{4}$/.test(item.season));
    drawChart("bowler-season-chart", "line", seasons.map((item) => item.season), [{
      label: "Credited wickets",
      data: seasons.map((item) => item.wickets),
      borderColor: PALETTE[1],
      backgroundColor: "rgb(0 161 106 / 12%)",
      fill: true,
      tension: 0.15,
      pointRadius: 3,
    }], {
      scales: {
        x: { grid: { display: false }, ticks: { color: "#6F838B", maxRotation: 0 }, title: { display: true, text: "Dataset season", color: "#6F838B" } },
        y: { beginAtZero: true, grid: { color: "#e4ebea" }, ticks: { color: "#6F838B", precision: 0 }, title: { display: true, text: "Wickets", color: "#6F838B" } },
      },
    }, "No chronological season records are available for this bowler.");
  }

  async function loadBowler() {
    const requestVersion = ++state.requestVersions.bowler;
    chartEmpty("bowler-phase-chart", "Loading bowler phase performance…");
    chartEmpty("bowler-season-chart", "Loading bowler season records…");
    setComponentState("bowler-error", "Loading bowler statistics…");
    try {
      const data = await requestJson("bowler", { bowler_id: byId("bowler-select").value });
      if (requestVersion !== state.requestVersions.bowler) return;
      renderBowlerSummary(data);
      renderBowlerCharts(data);
      setComponentState("bowler-error", "");
    } catch (error) {
      if (requestVersion !== state.requestVersions.bowler) return;
      setComponentState("bowler-error", error.message || "Bowler analytics could not be loaded.", loadBowler);
      for (const canvas of ["bowler-phase-chart", "bowler-season-chart"]) chartEmpty(canvas, error.message || "Bowler analytics are unavailable.");
    }
  }

  function formatMetric(value, digits = 2) {
    if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "n/a";
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
  }

  function metricCell(value, metric, row) {
    const cell = document.createElement("td");
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
      cell.textContent = "n/a";
      cell.title = metric === "economy"
        ? (row.legal_balls > 0 ? "The source rate is unavailable." : "No legal balls in this sample.")
        : metric === "bowling_strike_rate" || metric === "bowling_average"
          ? (row.wickets > 0 ? "The source rate is unavailable." : "No bowler-credited wickets in this sample.")
          : (row.legal_balls > 0 ? "The source rate is unavailable." : "No valid balls faced in this sample.");
    } else {
      cell.textContent = formatMetric(value);
    }
    return cell;
  }

  function renderMatchupTable(data) {
    const body = byId("matchup-table").tBodies[0];
    body.replaceChildren();
    if (!data.rows.length) {
      body.append(tableMessage("No records match the selected filters.", 9));
    } else {
      for (const row of data.rows) {
        const tr = document.createElement("tr");
        tr.append(
          tableCell(`${row.batter_name} · ${row.batter_id}`),
          tableCell(formatMetric(row.batter_runs)),
          metricCell(row.batter_strike_rate, "batter_strike_rate", row),
          tableCell(formatMetric(row.runs_conceded)),
          tableCell(row.wickets),
          metricCell(row.economy, "economy", row),
          metricCell(row.bowling_strike_rate, "bowling_strike_rate", row),
          tableCell(countFormat.format(row.legal_balls)),
        );
        const sampleCell = document.createElement("td");
        sampleCell.append(element("span", `sample-pill sample-${row.sample_assessment}`, row.sample_assessment.replaceAll("_", " ")));
        tr.append(sampleCell);
        body.append(tr);
      }
    }
    byId("matchup-count").textContent = `${countFormat.format(data.total)} matchup records · ${countFormat.format(data.summary.legal_balls)} legal balls on this page · minimum ${countFormat.format(data.filters.minimum_legal_balls)} balls`;
    byId("matchup-page-label").textContent = `Page ${data.page} of ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
    byId("matchup-prev").disabled = data.page <= 1;
    byId("matchup-next").disabled = data.page * data.page_size >= data.total;

    const leaders = data.rows.slice(0, 10);
    drawChart("matchup-chart", "bar", leaders.map((item) => item.batter_name), [
      { label: "Batter runs", data: leaders.map((item) => item.batter_runs), backgroundColor: PALETTE[2], borderRadius: 3, yAxisID: "y" },
      { type: "line", label: "Credited wickets", data: leaders.map((item) => item.wickets), borderColor: PALETTE[1], backgroundColor: PALETTE[1], yAxisID: "y1", pointRadius: 3 },
    ], {
      scales: {
        x: { grid: { display: false }, ticks: { color: "#6F838B", maxRotation: 0, autoSkip: true } },
        y: { beginAtZero: true, grid: { color: "#e4ebea" }, ticks: { color: "#6F838B" }, title: { display: true, text: "Batter runs", color: "#6F838B" } },
        y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false }, ticks: { color: "#6F838B", precision: 0 }, title: { display: true, text: "Credited wickets", color: "#6F838B" } },
      },
      plugins: { tooltip: { callbacks: { afterBody: (items) => `Sample: ${countFormat.format(leaders[items[0].dataIndex].legal_balls)} legal balls` } } },
    }, "No matchup records meet the sample threshold.");
    drawChart("matchup-economy-chart", "bar", leaders.map((item) => item.batter_name), [{
      label: "Economy · runs per 6 legal balls",
      data: leaders.map((item) => item.economy),
      backgroundColor: PALETTE[1],
      borderRadius: 3,
      maxBarThickness: 24,
    }], {
      ...axisOptions("Batter", "Economy"),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => {
        const item = leaders[context.dataIndex];
        return [` Economy ${formatMetric(context.parsed.y)} runs / 6 legal balls`, `Sample: ${countFormat.format(item.legal_balls)} legal balls`];
      } } } },
    }, "No matchup rates are available for these records.");
  }

  function loadTableError(tableId, message, colspan) {
    const body = byId(tableId).tBodies[0];
    body.replaceChildren(tableMessage(message, colspan));
  }

  async function loadMatchups() {
    const requestVersion = ++state.requestVersions.matchup;
    chartEmpty("matchup-chart", "Loading bowler-batter records…");
    chartEmpty("matchup-economy-chart", "Loading matchup economy…");
    setComponentState("matchup-error", "Loading matchup records…");
    byId("matchup-count").textContent = "Loading matchup records…";
    byId("matchup-table").tBodies[0].replaceChildren(tableMessage("Loading matchup records…", 9));
    try {
      const data = await requestJson("matchups", {
        bowler_id: byId("matchup-bowler").value,
        batter_id: byId("matchup-batter").value,
        min_balls: byId("matchup-min-balls").value,
        page: state.matchupPage,
        page_size: PAGE_SIZE,
        sort: state.matchupSort.column,
        order: state.matchupSort.order,
      });
      if (requestVersion !== state.requestVersions.matchup) return;
      renderMatchupTable(data);
      setComponentState("matchup-error", "");
    } catch (error) {
      if (requestVersion !== state.requestVersions.matchup) return;
      loadTableError("matchup-table", error.message || "Matchup data could not be loaded.", 9);
      byId("matchup-count").textContent = "Matchup data unavailable";
      setComponentState("matchup-error", error.message || "Matchup data unavailable.", loadMatchups);
      chartEmpty("matchup-chart", error.message || "Matchup data unavailable.");
      chartEmpty("matchup-economy-chart", error.message || "Matchup data unavailable.");
    }
  }

  function tableCell(value) {
    return element("td", "", value === null || value === undefined ? "Unavailable" : value);
  }

  function tableMessage(message, colspan) {
    const row = document.createElement("tr");
    const cell = element("td", "table-state", message);
    cell.colSpan = colspan;
    row.append(cell);
    return row;
  }

  function renderWicketCharts(data) {
    const dismissal = data.dismissal_types.filter((item) => item && typeof item.kind === "string" &&
      Number.isFinite(item.events) && Number.isFinite(item.bowler_credited));
    drawChart("wicket-type-chart", "bar", dismissal.map((item) => item.kind), [
      { label: "Bowler-credited", data: dismissal.map((item) => item.bowler_credited), backgroundColor: PALETTE[1], borderRadius: 3 },
      { label: "Other / not credited", data: dismissal.map((item) => Math.max(0, item.events - item.bowler_credited)), backgroundColor: PALETTE[3], borderRadius: 3 },
    ], {
      indexAxis: "y",
      scales: { x: { stacked: true, beginAtZero: true, grid: { color: "#e4ebea" }, ticks: { color: "#6F838B", precision: 0 }, title: { display: true, text: "Dismissal events", color: "#6F838B" } }, y: { stacked: true, grid: { display: false }, ticks: { color: "#6F838B", autoSkip: false } } },
      plugins: { tooltip: { callbacks: { label: (context) => ` ${context.dataset.label}: ${countFormat.format(context.parsed.x)}` } } },
    }, "No dismissal types are available for the selected filters.");
    const bowlers = (data.top_bowlers || []).slice(0, 12);
    drawChart("wicket-bowler-chart", "bar", bowlers.map((item) => item.bowler_name), [{
      label: "Bowler-credited dismissals",
      data: bowlers.map((item) => item.wickets),
      backgroundColor: PALETTE[1],
      borderRadius: 3,
      maxBarThickness: 24,
    }], {
      ...axisOptions("Bowler", "Credited wickets", true),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => {
        const item = bowlers[context.dataIndex];
        const sample = item.legal_balls === null || item.legal_balls === undefined
          ? "Legal-ball sample unavailable for this season/phase combination."
          : `${countFormat.format(item.legal_balls)} legal balls`;
        return [` ${countFormat.format(item.wickets)} credited wickets`, sample];
      } } } },
    }, "No credited wickets match the selected filters.");
  }

  function renderWicketTable(data) {
    const body = byId("wicket-table").tBodies[0];
    body.replaceChildren();
    if (!data.events.length) {
      body.append(tableMessage("No records match the selected filters.", 7));
    } else {
      for (const event of data.events) {
        const row = document.createElement("tr");
        row.append(
          tableCell(event.season),
          tableCell(`${event.match_id} · innings ${event.innings_number ?? "—"} · ${event.over_number ?? "—"}.${event.ball_in_over ?? "—"}`),
          tableCell(event.over_phase || "Unassigned"),
          tableCell(event.bowler_name || "Unavailable"),
          tableCell(event.player_out_name || "Unavailable"),
          tableCell(event.kind || "Unavailable"),
        );
        const creditedCell = document.createElement("td");
        creditedCell.append(element("span", event.is_bowler_credited ? "credit-pill credited" : "credit-pill not-credited", event.is_bowler_credited ? "Credited" : "Not credited"));
        row.append(creditedCell);
        body.append(row);
      }
    }
    byId("wicket-count").textContent = `${countFormat.format(data.total)} matching dismissal events · ${countFormat.format(data.bowler_credited_event_count)} credited to bowlers`;
    byId("wicket-page-label").textContent = `Page ${data.page} of ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
    byId("wicket-prev").disabled = data.page <= 1;
    byId("wicket-next").disabled = data.page * data.page_size >= data.total;
    renderWicketCharts(data);
  }

  async function loadWickets() {
    const requestVersion = ++state.requestVersions.wicket;
    chartEmpty("wicket-type-chart", "Loading dismissal breakdown…");
    chartEmpty("wicket-bowler-chart", "Loading bowler dismissal totals…");
    setComponentState("wicket-error", "Loading wicket records…");
    byId("wicket-count").textContent = "Loading wicket records…";
    byId("wicket-table").tBodies[0].replaceChildren(tableMessage("Loading dismissal records…", 7));
    try {
      const data = await requestJson("wickets", {
        bowler_id: byId("wicket-bowler").value,
        phase: byId("wicket-phase").value,
        season: byId("wicket-season").value,
        dismissal_type: byId("dismissal-filter").value,
        page: state.wicketPage,
        page_size: PAGE_SIZE,
        sort: state.wicketSort.column,
        order: state.wicketSort.order,
      });
      if (requestVersion !== state.requestVersions.wicket) return;
      renderWicketTable(data);
      setComponentState("wicket-error", "");
    } catch (error) {
      if (requestVersion !== state.requestVersions.wicket) return;
      loadTableError("wicket-table", error.message || "Wicket data could not be loaded.", 7);
      byId("wicket-count").textContent = "Wicket data unavailable";
      setComponentState("wicket-error", error.message || "Wicket data unavailable.", loadWickets);
      chartEmpty("wicket-type-chart", error.message || "Wicket data unavailable.");
      chartEmpty("wicket-bowler-chart", error.message || "Wicket data unavailable.");
    }
  }

  function renderDatasetMetadata(dataset, profile) {
    const container = byId("dataset-metadata");
    const heading = element("div", "dataset-profile-heading");
    const details = element("div", "dataset-profile-summary");
    details.append(
      element("strong", "", dataset.name),
      element("span", "", `${countFormat.format(profile.rows)} records · ${profile.column_count} columns · ${(dataset.size_bytes / 1024 / 1024).toFixed(2)} MB`),
      element("span", "", dataset.path),
    );
    const integrity = element("span", dataset.integrity_status === "VERIFIED" ? "integrity-tag verified" : "integrity-tag", dataset.integrity_status || "Integrity status unavailable");
    heading.append(details, integrity);
    const profileGrid = element("div", "column-profile-grid");
    for (const column of profile.columns) {
      const item = element("div", "column-profile");
      item.append(
        element("code", "", column),
        element("span", "column-type", profile.types[column] || "unknown"),
        element("span", "column-missing", `${countFormat.format(profile.missing_values[column] ?? 0)} missing`),
      );
      profileGrid.append(item);
    }
    const description = element("p", "dataset-description", dataset.purpose);
    container.replaceChildren(heading, description, profileGrid);
  }

  function renderDatasetRows(data, dataset) {
    const table = byId("dataset-table");
    const head = table.tHead.rows[0];
    const body = table.tBodies[0];
    head.replaceChildren();
    body.replaceChildren();
    for (const field of data.profile.columns) {
      const th = document.createElement("th");
      const sortButton = element("button", "table-sort", `${field}${state.datasetSort?.column === field ? (state.datasetSort.order === "asc" ? " ↑" : " ↓") : ""}`);
      sortButton.type = "button";
      sortButton.dataset.datasetSort = field;
      th.append(sortButton);
      head.append(th);
    }
    if (!data.rows.length) {
      body.append(tableMessage("No rows match this dataset search.", data.profile.column_count));
    } else {
      for (const row of data.rows) {
        const tr = document.createElement("tr");
        for (const field of data.profile.columns) {
          tr.append(tableCell(row[field] || "—"));
        }
        body.append(tr);
      }
    }
    byId("dataset-table-title").textContent = dataset.name;
    byId("dataset-table-count").textContent = `${countFormat.format(data.total)} matching records · page ${data.page}`;
    byId("dataset-page-label").textContent = `Page ${data.page} of ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
    byId("dataset-prev").disabled = data.page <= 1;
    byId("dataset-next").disabled = data.page * data.page_size >= data.total;
    renderDatasetMetadata(dataset, data.profile);
  }

  async function loadDatasetPage() {
    const dataset = state.datasets.find((item) => item.id === state.activeDataset);
    if (!dataset) return;
    const requestVersion = ++state.requestVersions.dataset;
    const params = {
      dataset: dataset.id,
      page: state.datasetPage,
      page_size: byId("dataset-page-size").value,
      search: byId("dataset-search").value.trim(),
    };
    if (state.datasetSort) {
      params.sort = state.datasetSort.column;
      params.order = state.datasetSort.order;
    }
    byId("dataset-table-count").textContent = "Reading dataset profile and page…";
    try {
      const data = await requestJson("dataset", params);
      if (requestVersion !== state.requestVersions.dataset) return;
      renderDatasetRows(data, dataset);
    } catch (error) {
      if (requestVersion !== state.requestVersions.dataset) return;
      const retry = element("button", "button button-small button-secondary", "Retry");
      retry.type = "button";
      retry.addEventListener("click", loadDatasetPage);
      byId("dataset-metadata").replaceChildren(
        element("div", "result-warning", error.message || "Dataset profile is unavailable."),
        retry,
      );
      byId("dataset-table-count").textContent = "Dataset data unavailable";
      byId("dataset-table").tBodies[0].replaceChildren(tableMessage(error.message || "Dataset rows could not be loaded.", 1));
    }
  }

  async function loadCatalog() {
    const requestVersion = ++state.requestVersions.catalog;
    try {
      const result = await requestJson("datasets");
      if (requestVersion !== state.requestVersions.catalog) return;
      if (!Array.isArray(result.datasets)) throw new DashboardError("The dataset catalog has an invalid response format.");
      state.datasets = result.datasets;
      const select = byId("dataset-select");
      const options = state.datasets.map((item) => ({ value: item.id, label: `${item.name} · ${item.rows === null ? "row count unknown" : countFormat.format(item.rows)}` }));
      setSelect(select, options, "Select a dataset", (item) => item.value, (item) => item.label);
      select.value = options.find((item) => item.label.startsWith("matches.csv"))?.value || options[0]?.value || "";
      state.activeDataset = select.value;
      byId("dataset-search").disabled = !select.value;
      await loadDatasetPage();
    } catch (error) {
      if (requestVersion !== state.requestVersions.catalog) return;
      byId("dataset-select").replaceChildren(new Option("Dataset catalog unavailable", ""));
      const retry = element("button", "button button-small button-secondary", "Retry");
      retry.type = "button";
      retry.addEventListener("click", loadCatalog);
      byId("dataset-metadata").replaceChildren(
        element("div", "result-warning", error.message || "The dataset catalog could not be loaded."),
        retry,
      );
    }
  }

  async function loadFilterOptions() {
    announceDashboardStatus("checking", "Checking dashboard data");
    const options = await requestJson("options");
    if (!Array.isArray(options.phases) || !Array.isArray(options.seasons) ||
        !Array.isArray(options.dismissal_types) || !Array.isArray(options.bowlers) || !Array.isArray(options.batters)) {
      throw new DashboardError("The dashboard filter options have an invalid response format.");
    }
    state.options = options;
    for (const id of ["phase-select", "wicket-phase"]) {
      setSelect(byId(id), options.phases, "All phases", (value) => value, (value) => value);
    }
    setSelect(byId("wicket-season"), options.seasons.filter((season) => season !== "Unresolved"), "All available seasons", (value) => value, (value) => value);
    setSelect(byId("dismissal-filter"), options.dismissal_types, "All dismissal types", (value) => value, (value) => value);
    setPlayerSelect(byId("bowler-select"), options.bowlers, "Select a bowler");
    setPlayerSelect(byId("matchup-bowler"), options.bowlers, "All bowlers");
    setPlayerSelect(byId("matchup-batter"), options.batters, "All batters");
    setPlayerSelect(byId("phase-bowler"), options.bowlers, "All bowlers");
    setPlayerSelect(byId("wicket-bowler"), options.bowlers, "All bowlers");
    announceDashboardStatus("ready", "Dashboard API connected");
    return options;
  }

  function debounce(callback, key, delay = 350) {
    window.clearTimeout(state[key]);
    state[key] = window.setTimeout(callback, delay);
  }

  function bindSorting() {
    document.querySelectorAll("button[data-sort][data-table]").forEach((button) => {
      button.addEventListener("click", () => {
        const table = button.dataset.table;
        const current = table === "matchup" ? state.matchupSort : state.wicketSort;
        const next = {
          column: button.dataset.sort,
          order: current.column === button.dataset.sort && current.order === "desc" ? "asc" : "desc",
        };
        if (table === "matchup") {
          state.matchupSort = next;
          state.matchupPage = 1;
          loadMatchups();
        } else {
          state.wicketSort = next;
          state.wicketPage = 1;
          loadWickets();
        }
      });
    });
    byId("dataset-table").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-dataset-sort]");
      if (!button) return;
      const column = button.dataset.datasetSort;
      state.datasetSort = {
        column,
        order: state.datasetSort?.column === column && state.datasetSort.order === "desc" ? "asc" : "desc",
      };
      state.datasetPage = 1;
      loadDatasetPage();
    });
  }

  function loadActiveAnalyticsTab() {
    const loaders = {
      "bowler-analytics": loadBowler,
      "matchup-analytics": loadMatchups,
      "phase-analysis": loadPhaseDetail,
      "wicket-analysis": loadWickets,
    };
    const load = loaders[state.activeTab];
    if (load) load();
  }

  function activatePage(page, requestedTab) {
    const targetPage = ["analytics", "decision-support"].includes(page) ? page : "overview";
    for (const panel of document.querySelectorAll(".page-panel")) panel.hidden = panel.id !== targetPage;
    document.querySelectorAll("[data-page-link]").forEach((link) => {
      const active = link.dataset.pageLink === targetPage;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    if (targetPage === "analytics") {
      activateAnalyticsTab(requestedTab || state.activeTab || "bowler-analytics");
    }
    if (targetPage === "decision-support") document.title = "CRIC | Historical Decision Support";
    else if (targetPage === "analytics") document.title = "CRIC | Performance Analytics";
    else document.title = "CRIC | Cricket Performance Analytics";
  }

  function activateAnalyticsTab(tab) {
    const validTabs = ["bowler-analytics", "matchup-analytics", "phase-analysis", "wicket-analysis"];
    state.activeTab = validTabs.includes(tab) ? tab : "bowler-analytics";
    document.querySelectorAll(".analytics-panel").forEach((panel) => {
      panel.hidden = panel.id !== state.activeTab;
    });
    document.querySelectorAll("[data-analytics-tab]").forEach((button) => {
      const active = button.dataset.analyticsTab === state.activeTab;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    });
    if (state.options && !state.loadedTabs.has(state.activeTab)) {
      state.loadedTabs.add(state.activeTab);
      loadActiveAnalyticsTab();
    }
    requestAnimationFrame(() => requestAnimationFrame(() => {
      for (const [id, chart] of charts) {
        const canvas = byId(id);
        if (canvas && canvas.closest(".analytics-panel")?.id === state.activeTab) chart.resize();
      }
    }));
  }

  function activateFromHash() {
    const hash = decodeURIComponent(location.hash.slice(1));
    const legacyTabs = {
      "bowler-performance": "bowler-analytics",
      matchups: "matchup-analytics",
      phases: "phase-analysis",
      wickets: "wicket-analysis",
    };
    const tabId = document.getElementById(hash)?.classList.contains("analytics-panel")
      ? hash : legacyTabs[hash];
    if (hash === "coach") return activatePage("decision-support");
    if (hash === "data-explorer") {
      activatePage("overview");
      byId("data-explorer").open = true;
      return;
    }
    if (tabId) return activatePage("analytics", tabId);
    activatePage(hash === "analytics" ? "analytics" : hash === "decision-support" ? "decision-support" : "overview");
  }

  function clearAllFilters() {
    byId("bowler-select").value = "";
    byId("matchup-bowler").value = "";
    byId("matchup-batter").value = "";
    byId("matchup-min-balls").value = "30";
    byId("phase-select").value = "";
    byId("phase-bowler").value = "";
    byId("wicket-bowler").value = "";
    byId("wicket-phase").value = "";
    byId("wicket-season").value = "";
    byId("dismissal-filter").value = "";
    byId("decision-min-balls").value = "30";
    state.matchupPage = 1;
    state.wicketPage = 1;
    window.dispatchEvent(new CustomEvent("cric:clear-filters"));
    loadActiveAnalyticsTab();
  }

  function bindEvents() {
    byId("bowler-select").addEventListener("change", loadBowler);
    for (const id of ["matchup-bowler", "matchup-batter", "matchup-min-balls"]) {
      byId(id).addEventListener("change", () => {
        state.matchupPage = 1;
        loadMatchups();
      });
    }
    byId("matchup-prev").addEventListener("click", () => { state.matchupPage = Math.max(1, state.matchupPage - 1); loadMatchups(); });
    byId("matchup-next").addEventListener("click", () => { state.matchupPage += 1; loadMatchups(); });

    for (const id of ["wicket-bowler", "wicket-season", "wicket-phase", "dismissal-filter"]) {
      byId(id).addEventListener("change", () => {
        state.wicketPage = 1;
        loadWickets();
      });
    }
    byId("wicket-prev").addEventListener("click", () => { state.wicketPage = Math.max(1, state.wicketPage - 1); loadWickets(); });
    byId("wicket-next").addEventListener("click", () => { state.wicketPage += 1; loadWickets(); });

    byId("dataset-select").addEventListener("change", () => {
      state.activeDataset = byId("dataset-select").value;
      state.datasetPage = 1;
      state.datasetSort = null;
      byId("dataset-search").value = "";
      byId("dataset-search").disabled = !state.activeDataset;
      loadDatasetPage();
    });
    byId("dataset-search").addEventListener("input", () => {
      state.datasetPage = 1;
      debounce(loadDatasetPage, "datasetTimer");
    });
    byId("dataset-page-size").addEventListener("change", () => { state.datasetPage = 1; loadDatasetPage(); });
    byId("dataset-prev").addEventListener("click", () => { state.datasetPage = Math.max(1, state.datasetPage - 1); loadDatasetPage(); });
    byId("dataset-next").addEventListener("click", () => { state.datasetPage += 1; loadDatasetPage(); });
    byId("data-explorer").addEventListener("toggle", () => {
      if (byId("data-explorer").open && !state.loadedTabs.has("data-explorer")) {
        state.loadedTabs.add("data-explorer");
        loadCatalog();
      }
    });

    byId("refresh-dashboard").addEventListener("click", () => {
      showNotice("");
      loadOverview();
      loadActiveAnalyticsTab();
      if (byId("data-explorer").open) loadCatalog();
      window.dispatchEvent(new CustomEvent("cric:refresh"));
    });
    document.querySelectorAll(".clear-filters").forEach((button) => button.addEventListener("click", clearAllFilters));
    document.querySelectorAll("[data-page-link]").forEach((link) => link.addEventListener("click", (event) => {
      event.preventDefault();
      const page = link.dataset.pageLink;
      history.pushState(null, "", `#${page}`);
      activatePage(page);
    }));
    document.querySelectorAll("[data-analytics-tab]").forEach((button) => button.addEventListener("click", () => {
      const tab = button.dataset.analyticsTab;
      history.pushState(null, "", `#${tab}`);
      activatePage("analytics", tab);
    }));
    window.addEventListener("hashchange", () => activateFromHash());
    bindSorting();
  }

  function renderPhaseTable(rows) {
    const sorted = [...rows].sort((left, right) => {
      const { column, order } = state.phaseSort;
      const a = left[column];
      const b = right[column];
      const result = typeof a === "number" && typeof b === "number"
        ? a - b : String(a ?? "").localeCompare(String(b ?? ""), undefined, { numeric: true });
      return order === "asc" ? result : -result;
    });
    const body = byId("phase-table").tBodies[0];
    body.replaceChildren();
    if (!sorted.length) {
      body.append(tableMessage("No records match the selected phase and sample threshold.", 8));
      return;
    }
    for (const item of sorted) {
      const row = document.createElement("tr");
      row.append(
        tableCell(`${item.bowler_name} · ${item.bowler_id}`),
        tableCell(item.phase || "All phases"),
        tableCell(countFormat.format(item.legal_balls)),
        tableCell(formatMetric(item.runs_conceded)),
        tableCell(item.wickets),
        metricCell(item.economy, "economy", item),
        metricCell(item.bowling_average, "bowling_average", item),
        metricCell(item.bowling_strike_rate, "bowling_strike_rate", item),
      );
      body.append(row);
    }
  }

  function renderPhaseDetail(data) {
    const phase = byId("phase-select").value;
    const selected = byId("phase-bowler").value;
    const rows = selected
      ? (data.phase_performance || []).filter((item) => (!phase || item.phase === phase) && item.legal_balls >= 30)
      : (data.phase_comparison || []).filter((item) => !phase || item.phase === phase);
    state.phaseRows = rows;
    renderPhaseTable(rows);
    const labels = rows.map((item) => selected ? (item.phase || "All phases") : item.bowler_name);
    drawChart("phase-economy-chart", "bar", labels, [{
      label: "Economy · runs per 6 legal balls",
      data: rows.map((item) => item.economy),
      backgroundColor: PALETTE[2],
      borderRadius: 3,
      maxBarThickness: 22,
    }], {
      ...axisOptions(selected ? "Phase" : "Bowler", "Economy", true),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => ` Economy ${formatMetric(context.parsed.x)} runs / 6 legal balls`, afterBody: (items) => `Sample: ${countFormat.format(rows[items[0].dataIndex].legal_balls)} legal balls` } } },
    }, "No phase performance rows meet the 30 legal-ball threshold.");
    drawChart("phase-wickets-chart", "bar", labels, [{
      label: "Credited wickets",
      data: rows.map((item) => item.wickets),
      backgroundColor: PALETTE[1],
      borderRadius: 3,
      maxBarThickness: 22,
    }], {
      ...axisOptions(selected ? "Phase" : "Bowler", "Credited wickets", true),
      plugins: { legend: { display: false }, tooltip: { callbacks: { afterBody: (items) => `Sample: ${countFormat.format(rows[items[0].dataIndex].legal_balls)} legal balls` } } },
    }, "No phase wicket rows meet the sample threshold.");
  }

  async function loadPhaseDetail() {
    const requestVersion = ++state.requestVersions.phase;
    chartEmpty("phase-economy-chart", "Loading phase economy comparisons…");
    chartEmpty("phase-wickets-chart", "Loading phase wicket comparisons…");
    setComponentState("phase-error", "Loading bowling phase records…");
    byId("phase-table").tBodies[0].replaceChildren(tableMessage("Loading phase comparisons…", 8));
    try {
      const data = await requestJson("bowler", {
        bowler_id: byId("phase-bowler").value,
        phase: byId("phase-select").value,
        min_balls: 30,
      });
      if (requestVersion !== state.requestVersions.phase) return;
      renderPhaseDetail(data);
      setComponentState("phase-error", "");
    } catch (error) {
      if (requestVersion !== state.requestVersions.phase) return;
      setComponentState("phase-error", error.message || "Phase analytics could not be loaded.", loadPhaseDetail);
      for (const canvas of ["phase-economy-chart", "phase-wickets-chart"]) chartEmpty(canvas, error.message || "Phase analytics could not be loaded.");
    }
  }

  function wirePhaseFilters() {
    byId("phase-select").addEventListener("change", loadPhaseDetail);
    byId("phase-bowler").addEventListener("change", loadPhaseDetail);
    byId("phase-table").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-phase-sort]");
      if (!button) return;
      const column = button.dataset.phaseSort;
      state.phaseSort = {
        column,
        order: state.phaseSort.column === column && state.phaseSort.order === "desc" ? "asc" : "desc",
      };
      renderPhaseTable(state.phaseRows);
    });
  }

  async function retryDashboardOptions() {
    try {
      await loadFilterOptions();
      setComponentState("kpi-error", "");
      await loadOverview();
      activateFromHash();
    } catch (error) {
      announceDashboardStatus("error", "Dashboard analytics unavailable");
      setComponentState("kpi-error", error.message || "Dashboard filter options are unavailable.", retryDashboardOptions);
    }
  }

  async function start() {
    bindEvents();
    try {
      await loadFilterOptions();
      await loadOverview();
      activateFromHash();
    } catch (error) {
      announceDashboardStatus("error", "Dashboard analytics unavailable");
      showNotice(error.message || "Dashboard filter options could not be loaded.", true);
      setComponentState("kpi-error", error.message || "Dashboard filter options are unavailable.", retryDashboardOptions);
      for (const id of ["bowler-error", "matchup-error", "phase-error", "wicket-error"]) {
        setComponentState(id, error.message || "Dashboard filters are unavailable.");
      }
    }
  }

  wirePhaseFilters();
  start();
})();
