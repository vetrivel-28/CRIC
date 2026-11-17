(() => {
  "use strict";

  const REQUEST_TIMEOUT_MS = 12_000;
  const MAX_VISIBLE_BOWLERS = 40;
  const state = {
    options: null,
    selectedBatter: null,
    selected: new Map(),
    lastRequest: null,
    lastPayload: null,
    submitting: false,
  };
  const apiHealth = {
    service: { state: "checking", message: "Checking local service" },
    dashboard: { state: "checking", message: "Checking dashboard data" },
  };

  const elements = {
    serviceStatus: document.getElementById("service-status"),
    pageError: document.getElementById("page-error"),
    pageErrorMessage: document.getElementById("page-error-message"),
    retryLoad: document.getElementById("retry-load"),
    form: document.getElementById("recommendation-form"),
    phase: document.getElementById("phase"),
    batterSearch: document.getElementById("batter-search"),
    batterResults: document.getElementById("batter-results"),
    selectedBatter: document.getElementById("selected-batter"),
    matchId: document.getElementById("match-id"),
    innings: document.getElementById("innings-number"),
    battingTeam: document.getElementById("batting-team"),
    bowlingTeam: document.getElementById("bowling-team"),
    over: document.getElementById("current-over"),
    search: document.getElementById("bowler-search"),
    bowlerResults: document.getElementById("bowler-results"),
    candidates: document.getElementById("selected-candidates"),
    candidateCount: document.getElementById("candidate-count"),
    useSituation: document.getElementById("use-situation"),
    situationFields: document.getElementById("situation-fields"),
    situationType: document.getElementById("situation-type"),
    situationValue: document.getElementById("situation-value"),
    submit: document.getElementById("submit-button"),
    formMessage: document.getElementById("form-message"),
    results: document.getElementById("results-section"),
    resultWarnings: document.getElementById("result-warnings"),
    scenarioSummary: document.getElementById("scenario-summary"),
    recommendations: document.getElementById("recommendations"),
    excludedSection: document.getElementById("excluded-section"),
    excluded: document.getElementById("excluded-list"),
  };

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function setServiceStatus(stateName, message) {
    apiHealth.service = { state: stateName, message };
    renderServiceStatus();
  }

  function renderServiceStatus() {
    const status = apiHealth.service.state === "error"
      ? { state: "error", message: apiHealth.service.message }
      : apiHealth.dashboard.state === "error"
        ? { state: "error", message: apiHealth.dashboard.message }
        : apiHealth.service.state !== "ready"
          ? apiHealth.service
          : apiHealth.dashboard.state === "ready"
            ? { state: "ready", message: "Dashboard API connected" }
            : apiHealth.service;
    elements.serviceStatus.dataset.state = status.state;
    elements.serviceStatus.lastChild.textContent = status.message;
  }

  function setError(message) {
    elements.pageErrorMessage.textContent = message;
    elements.pageError.hidden = false;
  }

  function clearError() {
    elements.pageError.hidden = true;
    elements.pageErrorMessage.textContent = "";
  }

  async function requestJson(url, options = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: { Accept: "application/json", ...(options.headers || {}) },
      });
      let payload;
      try {
        payload = await response.json();
      } catch {
        throw new Error("The local service returned an unreadable response.");
      }
      if (!response.ok) {
        const code = payload && payload.error && payload.error.code;
        const messages = {
          invalid_json: "The request could not be read. Check your selections and retry.",
          invalid_request: "Some selections are invalid. Review the form and try again.",
          unknown_identifier: "A selected player is not present in the loaded historical data. Reload the options and retry.",
          request_too_large: "The request is too large. Select fewer candidates.",
          frontend_unavailable: "The local application files are unavailable.",
        };
        throw new Error(messages[code] || "The local service could not complete the request.");
      }
      return payload;
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("The local service took too long to respond. Check it is running, then retry.");
      }
      if (error instanceof TypeError) {
        throw new Error("Cannot reach the local recommendation service. Start it and retry.");
      }
      throw error;
    } finally {
      window.clearTimeout(timer);
    }
  }

  function isOptionPlayer(value) {
    return value && typeof value.id === "string" && value.id.length > 0 &&
      typeof value.name === "string" && value.name.length > 0;
  }

  function validateOptions(payload) {
    if (!payload || !Array.isArray(payload.phases) || !payload.phases.length ||
        !payload.phases.every((value) => typeof value === "string") ||
        !Array.isArray(payload.batters) || !payload.batters.every(isOptionPlayer) ||
        !Array.isArray(payload.bowlers) || !payload.bowlers.every(isOptionPlayer) ||
        !Array.isArray(payload.situations) ||
        !payload.situations.every((item) => item && typeof item.type === "string" &&
          Array.isArray(item.values) && item.values.every((value) => typeof value === "string"))) {
      throw new Error("The local service returned an unexpected player-options format.");
    }
    return payload;
  }

  function fillSelect(select, items, placeholder, valueOf, labelOf) {
    select.replaceChildren(new Option(placeholder, ""));
    for (const item of items) {
      select.add(new Option(labelOf(item), valueOf(item)));
    }
    select.disabled = false;
  }

  function renderSituationValues() {
    if (!state.options) return;
    const selectedType = elements.situationType.value;
    const group = state.options.situations.find((item) => item.type === selectedType);
    const values = group ? group.values : [];
    fillSelect(elements.situationValue, values, values.length ? "Select a value" : "No historical values", (value) => value, (value) => value);
    elements.situationValue.disabled = !elements.useSituation.checked || values.length === 0;
  }

  function populateOptions(payload) {
    state.options = validateOptions(payload);
    fillSelect(elements.phase, state.options.phases, "Select a phase", (value) => value, (value) => value);
    fillSelect(
      elements.situationType,
      state.options.situations,
      "Select a type",
      (item) => item.type,
      (item) => item.type,
    );
    elements.situationType.disabled = !elements.useSituation.checked;
    renderSituationValues();
    elements.search.disabled = false;
    elements.batterSearch.disabled = false;
    elements.useSituation.disabled = false;
    elements.submit.disabled = false;
    renderBowlerChoices();
    renderBatterChoices();
    setServiceStatus("ready", "Local service ready");
  }

  async function loadOptions() {
    clearError();
    setServiceStatus("", "Checking local service");
    elements.submit.disabled = true;
    try {
      const health = await requestJson("/health");
      if (!health || health.status !== "ok" || health.execution_mode !== "local_python") {
        throw new Error("The local recommendation service is not ready.");
      }

      const options = await requestJson("/api/v1/options");
      populateOptions(options);
    } catch (error) {
      state.options = null;
      setServiceStatus("error", "Local service unavailable");
      setError(error.message || "Could not load local historical player options.");
      elements.submit.disabled = true;
      elements.search.disabled = true;
      elements.batterSearch.disabled = true;
      elements.useSituation.disabled = true;
      elements.bowlerResults.replaceChildren(node("p", "empty-hint", "Start the local service, then retry."));
    }
  }

  window.addEventListener("cric:dashboard-status", (event) => {
    apiHealth.dashboard = event.detail;
    renderServiceStatus();
  });

  function renderWithMinimumSample(payload = state.lastPayload) {
    if (!payload) return;
    const minimum = Number(document.getElementById("decision-min-balls").value);
    const recommendations = payload.recommendations.filter((item) => {
      const sample = item.metrics.performance && item.metrics.performance.sample_balls;
      return minimum === 0 || (Number.isFinite(sample) && sample >= minimum);
    });
    const filteredCount = payload.recommendations.length - recommendations.length;
    const warnings = [...payload.warnings];
    if (minimum > 0 && filteredCount) {
      warnings.push(`${filteredCount} candidate${filteredCount === 1 ? " did" : "s did"} not meet the selected ${minimum}-legal-ball minimum for phase/career performance evidence.`);
    }
    renderRecommendations({ ...payload, recommendations, warnings, minimum_sample_filtered: filteredCount > 0 && recommendations.length === 0 });
  }

  function selectedIds() {
    return new Set(state.selected.keys());
  }

  function renderBatterChoices() {
    if (!state.options) return;
    const query = elements.batterSearch.value.trim().toLocaleLowerCase();
    const matches = state.options.batters.filter((batter) =>
      (!query || batter.name.toLocaleLowerCase().includes(query) || batter.id.toLocaleLowerCase().includes(query))
    );
    const shown = matches.slice(0, MAX_VISIBLE_BOWLERS);
    const fragment = document.createDocumentFragment();
    if (!shown.length) {
      fragment.append(node("p", "empty-hint", "No matching historical batters."));
    } else {
      for (const batter of shown) {
        const button = node("button", "lookup-choice");
        button.type = "button";
        button.dataset.batterId = batter.id;
        button.append(node("span", "", batter.name), node("code", "", batter.id));
        fragment.append(button);
      }
    }
    if (matches.length > shown.length) {
      fragment.append(node("p", "empty-hint", `Showing ${shown.length} of ${matches.length}; refine your search.`));
    }
    elements.batterResults.replaceChildren(fragment);
    if (state.selectedBatter) {
      elements.selectedBatter.replaceChildren(
        node("span", "", "Selected: "),
        node("strong", "", `${state.selectedBatter.name} · ${state.selectedBatter.id}`),
      );
    } else {
      elements.selectedBatter.textContent = "No batter selected.";
    }
  }

  function renderBowlerChoices() {
    if (!state.options) return;
    const query = elements.search.value.trim().toLocaleLowerCase();
    const chosen = selectedIds();
    const matches = state.options.bowlers.filter((bowler) =>
      !chosen.has(bowler.id) &&
      (!query || bowler.name.toLocaleLowerCase().includes(query) || bowler.id.toLocaleLowerCase().includes(query))
    );
    const shown = matches.slice(0, MAX_VISIBLE_BOWLERS);
    const fragment = document.createDocumentFragment();
    if (!shown.length) {
      fragment.append(node("p", "empty-hint", query ? "No matching unselected bowlers." : "All matching bowlers are selected."));
    } else {
      for (const bowler of shown) {
        const button = node("button", "bowler-choice");
        button.type = "button";
        button.dataset.bowlerId = bowler.id;
        button.append(
          node("span", "choice-add", "+"),
          node("span", "choice-name", bowler.name),
          node("code", "choice-id", bowler.id),
        );
        fragment.append(button);
      }
    }
    if (matches.length > shown.length) {
      fragment.append(node("p", "empty-hint", `Showing ${shown.length} of ${matches.length}; refine your search.`));
    }
    elements.bowlerResults.replaceChildren(fragment);
  }

  function renderSelectedCandidates() {
    const fragment = document.createDocumentFragment();
    elements.candidateCount.textContent = String(state.selected.size);
    if (!state.selected.size) {
      fragment.append(node("p", "empty-hint", "No bowlers selected yet."));
      elements.candidates.replaceChildren(fragment);
      return;
    }
    for (const [id, candidate] of state.selected) {
      const row = node("div", "selected-candidate");
      const label = node("div", "candidate-name");
      label.append(node("strong", "", candidate.name), node("code", "", id));

      const oversLabel = node("label", "compact-field", "Overs remaining (optional)");
      const overs = document.createElement("input");
      overs.type = "number";
      overs.min = "0";
      overs.step = "0.1";
      overs.inputMode = "decimal";
      overs.setAttribute("aria-label", `Overs remaining for ${candidate.name}`);
      overs.value = candidate.oversRemaining;
      overs.addEventListener("input", () => {
        candidate.oversRemaining = overs.value;
      });
      oversLabel.append(overs);

      const availability = node("label", "compact-field availability-field");
      const available = document.createElement("input");
      available.type = "checkbox";
      available.checked = candidate.available;
      available.setAttribute("aria-label", `${candidate.name} is available`);
      available.addEventListener("change", () => {
        candidate.available = available.checked;
      });
      availability.append(available, node("span", "", "Available"));

      const remove = node("button", "remove-candidate", "×");
      remove.type = "button";
      remove.dataset.removeBowler = id;
      remove.setAttribute("aria-label", `Remove ${candidate.name}`);
      row.append(label, oversLabel, availability, remove);
      fragment.append(row);
    }
    elements.candidates.replaceChildren(fragment);
  }

  function addCandidate(id) {
    if (!state.options || state.selected.has(id)) return;
    if (state.selected.size >= 30) {
      elements.formMessage.textContent = "The API accepts at most 30 candidate bowlers.";
      return;
    }
    const bowler = state.options.bowlers.find((item) => item.id === id);
    if (!bowler) {
      elements.formMessage.textContent = "That bowler is not in the loaded historical catalog. Reload options.";
      return;
    }
    state.selected.set(id, { name: bowler.name, available: true, oversRemaining: "" });
    elements.formMessage.textContent = "";
    renderSelectedCandidates();
    renderBowlerChoices();
  }

  function optionalText(input, key, context) {
    const value = input.value.trim();
    if (value) context[key] = value;
  }

  function buildRequest() {
    const phase = elements.phase.value;
    const batterId = state.selectedBatter && state.selectedBatter.id;
    if (!phase || !state.options.phases.includes(phase)) {
      throw new Error("Select a valid innings phase.");
    }
    if (!batterId || !state.options.batters.some((item) => item.id === batterId)) {
      throw new Error("Select a batter from the historical player catalog.");
    }

    const candidates = [];
    for (const [bowlerId, candidate] of state.selected) {
      const entry = { bowler_id: bowlerId, available: candidate.available };
      if (candidate.oversRemaining !== "") {
        const value = Number(candidate.oversRemaining);
        if (!Number.isFinite(value) || value < 0) {
          throw new Error(`Enter a valid nonnegative overs remaining value for ${candidate.name}.`);
        }
        entry.overs_remaining = value;
      }
      candidates.push(entry);
    }
    const request = { batter_id: batterId, phase, candidates };

    const context = {};
    optionalText(elements.matchId, "match_id", context);
    optionalText(elements.battingTeam, "batting_team", context);
    optionalText(elements.bowlingTeam, "bowling_team", context);
    for (const [input, key, label] of [
      [elements.innings, "innings_number", "Innings number"],
      [elements.over, "over", "Current over"],
    ]) {
      if (input.value !== "") {
        const value = Number(input.value);
        if (!Number.isFinite(value) || value < 0 || !Number.isInteger(value)) {
          throw new Error(`${label} must be a nonnegative whole number.`);
        }
        context[key] = value;
      }
    }
    if (Object.keys(context).length) request.context = context;

    if (elements.useSituation.checked) {
      const type = elements.situationType.value;
      const value = elements.situationValue.value;
      const group = state.options.situations.find((item) => item.type === type);
      if (!group || !group.values.includes(value)) {
        throw new Error("Select a historical situation type and value.");
      }
      request.situation = { type, value };
    }
    return request;
  }

  function isFiniteOrNull(value) {
    return value === null || (typeof value === "number" && Number.isFinite(value));
  }

  function validateRecommendation(item, seenIds) {
    if (!item || !Number.isInteger(item.rank) || typeof item.bowler_id !== "string" ||
        typeof item.bowler_name !== "string" || seenIds.has(item.bowler_id) ||
        !(item.score === null || (Number.isFinite(item.score) && item.score >= 0 && item.score <= 100)) ||
        !item.metrics || typeof item.metrics !== "object" ||
        !Array.isArray(item.evidence) || !item.evidence.every((line) => typeof line === "string") ||
        !Array.isArray(item.warnings) || !item.warnings.every((line) => typeof line === "string") ||
        !item.data_availability || typeof item.data_availability !== "object" ||
        !["performance", "matchup", "situation"].every((key) =>
          typeof item.data_availability[key] === "string"
        )) {
      return false;
    }
    for (const metricGroup of Object.values(item.metrics)) {
      if (!metricGroup || typeof metricGroup !== "object" ||
          !isFiniteOrNull(metricGroup.economy) ||
          !isFiniteOrNull(metricGroup.bowling_strike_rate_balls_per_wicket) ||
          !isFiniteOrNull(metricGroup.wicket_rate_per_100_legal_balls) ||
          !Number.isFinite(metricGroup.sample_balls) || metricGroup.sample_balls < 0 ||
          !["no_legal_balls", "very_small_sample", "limited_sample", "broader_sample"]
            .includes(metricGroup.sample_assessment)) {
        return false;
      }
    }
    seenIds.add(item.bowler_id);
    return true;
  }

  function validateResponse(payload) {
    if (!payload || payload.status !== "ok" || payload.execution_mode !== "local_python" ||
        payload.model_type !== "deterministic_interpretable_baseline" ||
        !(payload.situation === null || (
          payload.situation && typeof payload.situation.type === "string" &&
          typeof payload.situation.value === "string"
        )) ||
        !Array.isArray(payload.recommendations) || !Array.isArray(payload.excluded) ||
        !Array.isArray(payload.warnings) || !payload.warnings.every((line) => typeof line === "string")) {
      throw new Error("The local service returned an unexpected recommendation format.");
    }
    const seen = new Set();
    if (!payload.recommendations.every((item, index) =>
      validateRecommendation(item, seen) && item.rank === index + 1
    )) {
      throw new Error("The local service returned invalid recommendation data.");
    }
    if (!payload.excluded.every((item) =>
      item && typeof item.bowler_id === "string" && typeof item.reason === "string"
    )) {
      throw new Error("The local service returned invalid exclusion details.");
    }
    return payload;
  }

  function displayMetric(value, digits = 2) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "n/a";
    return Number(value).toFixed(digits);
  }

  function appendMetric(group, label, value, sampleBalls) {
    const item = node("div", "metric-item");
    item.append(node("span", "", label));
    const unavailable = value === null || value === undefined || !Number.isFinite(Number(value));
    const strong = node("strong", unavailable ? "unavailable" : "", displayMetric(value));
    if (unavailable) {
      strong.title = sampleBalls === 0
        ? "No legal balls are available in this sample."
        : label === "Bowling strike rate"
          ? "No bowler-credited wickets are available in this sample."
          : "The source metric is unavailable for this sample.";
    }
    item.append(strong);
    group.append(item);
  }

  function renderMetricCard(source, data, availability) {
    const card = node("article", "metric-card");
    const label = {
      performance: "Phase / career performance",
      matchup: "Batter matchup",
      situation: "Situation",
    }[source];
    const statusText = {
      phase: "Historical phase evidence",
      career: "Historical career fallback",
      available: "Historical evidence available",
      no_matchup_evidence: "Historical matchup unavailable",
      no_situation_evidence: "Historical situation unavailable",
      not_requested: "Not requested",
    }[availability] || "Historical evidence unavailable";
    card.append(node("h4", "", label));
    const grid = node("div", "metric-values");
    appendMetric(grid, "Economy", data ? data.economy : null, data && data.sample_balls);
    appendMetric(grid, "Bowling strike rate", data ? data.bowling_strike_rate_balls_per_wicket : null, data && data.sample_balls);
    appendMetric(grid, "Wicket rate / 100 legal balls", data ? data.wicket_rate_per_100_legal_balls : null, data && data.sample_balls);
    card.append(grid);
    if (data) {
      const assessments = {
        no_legal_balls: ["sample-assessment sample-none", "No legal balls · rates unavailable"],
        very_small_sample: ["sample-assessment sample-very-small", "Very small sample"],
        limited_sample: ["sample-assessment sample-limited", "Limited sample"],
        broader_sample: ["sample-assessment sample-broader", "Broader sample"],
      };
      const [className, text] = assessments[data.sample_assessment];
      card.append(node("span", className, text));
      card.append(node("p", "metric-sample", `Sample size: ${displayMetric(data.sample_balls, 0)} legal balls`));
    } else {
      card.append(node("p", "metric-sample metric-sample-unavailable", statusText));
    }
    card.append(node("p", "metric-availability", statusText));
    return card;
  }

  function renderRecommendations(payload) {
    const fragment = document.createDocumentFragment();
    elements.resultWarnings.replaceChildren();
    for (const warning of payload.warnings) {
      fragment.append(node("p", "result-warning", warning));
    }
    elements.resultWarnings.replaceChildren(fragment);
    const batter = state.options.batters.find((item) => item.id === payload.batter_id);
    const scenario = [
      payload.phase || "All phases",
      batter ? `${batter.name} · ${batter.id}` : payload.batter_id,
    ];
    if (payload.situation) {
      scenario.push(`${payload.situation.type}: ${payload.situation.value}`);
    }
    elements.scenarioSummary.textContent = `Requested historical scenario: ${scenario.join(" · ")}`;
    elements.recommendations.replaceChildren();

    if (!payload.recommendations.length) {
      const noResultsMessage = payload.minimum_sample_filtered
        ? "No candidates meet the selected minimum sample. Reduce the minimum or choose different candidates."
        : "No bowlers were ranked. Add candidates, or review the exclusion reasons below.";
      elements.recommendations.append(node("div", "no-results", noResultsMessage));
    } else {
      for (const recommendation of payload.recommendations) {
        const card = node("article", "recommendation-card");
        const main = node("div", "recommendation-main");
        main.append(node("span", "rank-mark", `#${recommendation.rank}`));
        const name = node("div", "bowler-title");
        name.append(node("h3", "", recommendation.bowler_name), node("code", "", recommendation.bowler_id));
        main.append(name);
        const score = node("div", "score-box");
        score.append(
          node("strong", "score-value", recommendation.score === null ? "—" : displayMetric(recommendation.score)),
          node("span", "score-caption", "relative score · 0–100"),
        );
        main.append(score);
        card.append(main);

        const metrics = node("div", "metric-grid");
        for (const source of ["performance", "matchup", "situation"]) {
          const statusKey = source === "performance"
            ? recommendation.data_availability.performance
            : recommendation.data_availability[source];
          metrics.append(renderMetricCard(source, recommendation.metrics[source], statusKey));
        }
        card.append(metrics);

        const detail = node("div", "card-detail");
        const availability = node("p", "availability-line");
        const performanceSource = recommendation.data_availability.performance === "phase"
          ? "requested phase" : "career fallback";
        const matchupSource = recommendation.data_availability.matchup === "available"
          ? "historical matchup available" : "historical matchup unavailable";
        const situationSource = {
          available: "historical situation available",
          no_situation_evidence: "historical situation unavailable",
          not_requested: "situation not requested",
        }[recommendation.data_availability.situation];
        availability.textContent = `Performance: ${performanceSource}; ${matchupSource}; ${situationSource}.`;
        detail.append(availability);
        if (recommendation.evidence.length) {
          const evidence = node("ul", "detail-list");
          for (const line of recommendation.evidence) evidence.append(node("li", "", line));
          detail.append(evidence);
        }
        if (recommendation.warnings.length) {
          const warnings = node("ul", "detail-list warnings");
          for (const line of recommendation.warnings) warnings.append(node("li", "", line));
          detail.append(warnings);
        }
        card.append(detail);
        elements.recommendations.append(card);
      }
    }

    const excluded = node("div");
    for (const item of payload.excluded) {
      const knownBowler = state.options && state.options.bowlers.find((bowler) => bowler.id === item.bowler_id);
      const label = knownBowler ? `${knownBowler.name} · ${item.bowler_id}` : item.bowler_id;
      const row = node("div", "excluded-row");
      row.append(node("span", "", label), node("strong", "", item.reason.replaceAll("_", " ")));
      excluded.append(row);
    }
    elements.excluded.replaceChildren(excluded);
    elements.excludedSection.hidden = payload.excluded.length === 0;
    elements.results.hidden = false;
    elements.results.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function showRequestError(message) {
    elements.results.hidden = false;
    elements.resultWarnings.replaceChildren();
    const notice = node("div", "notice notice-error");
    notice.append(node("span", "", message));
    const retry = node("button", "button button-small button-secondary", "Retry request");
    retry.type = "button";
    retry.addEventListener("click", () => submitRequest(state.lastRequest));
    notice.append(retry);
    elements.resultWarnings.append(notice);
    elements.recommendations.replaceChildren();
    elements.excludedSection.hidden = true;
    elements.results.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function submitRequest(request) {
    if (state.submitting || !request) return;
    state.submitting = true;
    state.lastRequest = request;
    state.lastPayload = null;
    elements.submit.disabled = true;
    elements.submit.querySelector("span:first-child").textContent = "Loading historical data…";
    elements.formMessage.textContent = "";
    try {
      const payload = validateResponse(await requestJson("/api/v1/recommendations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      }));
      state.lastPayload = payload;
      renderWithMinimumSample(payload);
    } catch (error) {
      showRequestError(error.message || "The recommendation request failed. Please retry.");
    } finally {
      state.submitting = false;
      elements.submit.disabled = !state.options;
      elements.submit.querySelector("span:first-child").textContent = "Get recommendations";
    }
  }

  elements.retryLoad.addEventListener("click", loadOptions);
  document.getElementById("refresh-dashboard").addEventListener("click", loadOptions);
  document.getElementById("decision-min-balls").addEventListener("change", () => renderWithMinimumSample());
  window.addEventListener("cric:clear-filters", () => {
    document.getElementById("decision-min-balls").value = "30";
    renderWithMinimumSample();
  });
  elements.batterSearch.addEventListener("input", renderBatterChoices);
  elements.batterResults.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-batter-id]");
    if (!button || !state.options) return;
    state.selectedBatter = state.options.batters.find((item) => item.id === button.dataset.batterId) || null;
    elements.batterSearch.value = "";
    renderBatterChoices();
  });
  elements.search.addEventListener("input", renderBowlerChoices);
  elements.bowlerResults.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-bowler-id]");
    if (button) addCandidate(button.dataset.bowlerId);
  });
  elements.candidates.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-remove-bowler]");
    if (!button) return;
    state.selected.delete(button.dataset.removeBowler);
    renderSelectedCandidates();
    renderBowlerChoices();
  });
  elements.situationType.addEventListener("change", renderSituationValues);
  elements.useSituation.addEventListener("change", () => {
    elements.situationFields.hidden = !elements.useSituation.checked;
    elements.situationType.disabled = !elements.useSituation.checked;
    renderSituationValues();
  });
  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      submitRequest(buildRequest());
    } catch (error) {
      elements.formMessage.textContent = error.message;
    }
  });

  loadOptions();
})();
