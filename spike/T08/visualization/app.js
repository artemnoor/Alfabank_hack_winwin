(() => {
  "use strict";

  const DATA = JSON.parse(document.getElementById("visual-data").textContent);
  const topicByCode = new Map(DATA.taxonomy.topics.map((row) => [row.code, row]));
  const eventByCode = new Map(DATA.taxonomy.events.map((row) => [row.code, row]));
  const resultById = new Map(DATA.cases.filter((row) => row.result).map((row) => [row.id, row.result]));
  const reviewCaseIds = new Set(DATA.disputedCaseIds);
  const overrides = new Map();
  const filters = { search: "", topic: "", event: "", state: "all", sort: "source" };
  const settings = {
    choice: 0.5,
    negative: 0.2,
    positive: 0.8,
    uncertainty: 0.2,
    unlisted: 0.2,
    gates: { choice: true, event_band: true, uncertainty: true, unlisted: true },
    preset: "current_strict",
  };
  const v2Settings = { negative: 0.2, positive: 0.8, evidence: 0.8, unlisted: 0.8 };
  let activePolicyMode = "legacy";
  let selectedId = DATA.cases[0]?.id ?? null;
  let activeTab = "lab";

  const PRESETS = [
    { id: "current_strict", label: "A · Current Strict", gates: { choice: true, event_band: true, uncertainty: true, unlisted: true } },
    { id: "ignore_unlisted_gate", label: "B · без сигнала «вне списка»", gates: { choice: true, event_band: true, uncertainty: true, unlisted: false } },
    { id: "ignore_uncertainty_gate", label: "C · без сигнала недостаточности", gates: { choice: true, event_band: true, uncertainty: false, unlisted: true } },
    { id: "ignore_both_signal_gates", label: "D · без двух сигналов", gates: { choice: true, event_band: true, uncertainty: false, unlisted: false } },
    { id: "choice_only", label: "E · только Choice", gates: { choice: true, event_band: false, uncertainty: false, unlisted: false } },
  ];

  const $ = (id) => document.getElementById(id);
  const node = (tag, className = "", text = undefined) => {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined && text !== null) item.textContent = String(text);
    return item;
  };
  const append = (parent, ...children) => {
    for (const child of children) if (child) parent.append(child);
    return parent;
  };
  const pct = (value, digits = 1) => value == null || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(digits)}%`;
  const scoreText = (value) => value == null ? "—" : Number(value).toFixed(2);
  const topicLabel = (code) => code ? (topicByCode.get(code)?.label ?? code) : "Не размечено";
  const eventLabel = (code) => eventByCode.get(code)?.label ?? code;
  const caseById = (id) => DATA.cases.find((row) => row.id === id);
  const liveCaseRows = () => DATA.cases.filter((row) => row.result);
  const choiceThreshold = () => settings.choice;

  function setOptions(select, rows, placeholder, selected = "") {
    select.replaceChildren();
    const first = node("option", "", placeholder);
    first.value = "";
    select.append(first);
    for (const row of rows) {
      const option = node("option", "", row.label);
      option.value = row.value;
      select.append(option);
    }
    select.value = selected;
  }

  function bindFilters() {
    setOptions($("filterTopic"), DATA.taxonomy.topics.map((row) => ({ value: row.code, label: row.label })), "Любая тема");
    setOptions($("filterEvent"), DATA.taxonomy.events.map((row) => ({ value: row.code, label: row.label })), "Любое событие");
    $("filterSearch").addEventListener("input", (event) => { filters.search = event.target.value.trim().toLocaleLowerCase("ru"); renderCaseList(); });
    $("filterTopic").addEventListener("change", (event) => { filters.topic = event.target.value; renderCaseList(); });
    $("filterEvent").addEventListener("change", (event) => { filters.event = event.target.value; renderCaseList(); });
    $("filterState").addEventListener("change", (event) => { filters.state = event.target.value; renderCaseList(); });
    $("filterSort").addEventListener("change", (event) => { filters.sort = event.target.value; renderCaseList(); });
  }

  function bindNavigation() {
    for (const tab of document.querySelectorAll("[data-tab]")) {
      tab.addEventListener("click", () => {
        activeTab = tab.dataset.tab;
        for (const button of document.querySelectorAll("[data-tab]")) button.setAttribute("aria-selected", String(button.dataset.tab === activeTab));
        $("labScreen").hidden = activeTab !== "lab";
        $("statsScreen").hidden = activeTab !== "stats";
        $("statsScreen").classList.toggle("active", activeTab === "stats");
        if (activeTab === "stats") renderStats();
      });
    }
  }

  function bindPolicy() {
    for (const button of document.querySelectorAll("[data-policy-mode]")) {
      button.addEventListener("click", () => {
        activePolicyMode = button.dataset.policyMode;
        for (const option of document.querySelectorAll("[data-policy-mode]")) {
          option.classList.toggle("active", option.dataset.policyMode === activePolicyMode);
          option.setAttribute("aria-pressed", String(option.dataset.policyMode === activePolicyMode));
        }
        renderAll();
      });
    }
    for (const preset of PRESETS) {
      const button = node("button", "preset", preset.label);
      button.type = "button";
      button.dataset.preset = preset.id;
      button.addEventListener("click", () => {
        settings.choice = 0.5;
        settings.negative = 0.2;
        settings.positive = 0.8;
        settings.uncertainty = 0.2;
        settings.unlisted = 0.2;
        settings.gates = { ...preset.gates };
        settings.preset = preset.id;
        syncSliders();
        renderAll();
      });
      $("presetButtons").append(button);
    }
    const fields = ["choice", "negative", "positive", "uncertainty", "unlisted"];
    for (const field of fields) {
      const input = $(`threshold-${field}`);
      input.addEventListener("input", () => {
        let value = Math.round(Number(input.value) * 100) / 100;
        if (activePolicyMode === "policy_v2") {
          if (field === "choice") return;
          if (field === "negative") value = Math.min(value, v2Settings.positive - 0.01);
          if (field === "positive") value = Math.max(value, v2Settings.negative + 0.01);
          const v2Field = { negative: "negative", positive: "positive", uncertainty: "evidence", unlisted: "unlisted" }[field];
          v2Settings[v2Field] = value;
        } else {
          if (field === "negative") value = Math.min(value, settings.positive - 0.01);
          if (field === "positive") value = Math.max(value, settings.negative + 0.01);
          if (field === "uncertainty" || field === "unlisted") value = Math.min(value, settings.positive - 0.01);
          settings[field] = value;
          if (field === "positive") {
            settings.uncertainty = Math.min(settings.uncertainty, value - 0.01);
            settings.unlisted = Math.min(settings.unlisted, value - 0.01);
          }
          settings.gates = { choice: true, event_band: true, uncertainty: true, unlisted: true };
          settings.preset = "custom";
        }
        syncSliders();
        renderAll();
      });
    }
    $("resetThresholds").addEventListener("click", () => {
      settings.choice = 0.5;
      settings.negative = 0.2;
      settings.positive = 0.8;
      settings.uncertainty = 0.2;
      settings.unlisted = 0.2;
      v2Settings.negative = 0.2;
      v2Settings.positive = 0.8;
      v2Settings.evidence = 0.8;
      v2Settings.unlisted = 0.8;
      settings.gates = { choice: true, event_band: true, uncertainty: true, unlisted: true };
      settings.preset = "current_strict";
      syncSliders();
      renderAll();
    });
    syncSliders();
  }

  function syncSliders() {
    const shown = activePolicyMode === "policy_v2"
      ? { choice: settings.choice, negative: v2Settings.negative, positive: v2Settings.positive, uncertainty: v2Settings.evidence, unlisted: v2Settings.unlisted }
      : settings;
    const pairs = [
      ["choice", shown.choice], ["negative", shown.negative], ["positive", shown.positive],
      ["uncertainty", shown.uncertainty], ["unlisted", shown.unlisted],
    ];
    for (const [field, value] of pairs) {
      const input = $(`threshold-${field}`);
      input.value = value.toFixed(2);
      $(`value-${field}`).textContent = value.toFixed(2);
    }
    $("threshold-negative").max = Math.max(0, shown.positive - 0.01).toFixed(2);
    $("threshold-positive").min = Math.min(1, shown.negative + 0.01).toFixed(2);
    $("threshold-uncertainty").max = "1";
    $("threshold-unlisted").max = "1";
    $("threshold-choice").closest(".threshold-control").hidden = activePolicyMode === "policy_v2";
    $("threshold-negative").closest(".threshold-control").hidden = false;
    const labels = activePolicyMode === "policy_v2"
      ? { negative: "Noul: отрицательный до ", positive: "Кандидат события при ≥ ", uncertainty: "Удержать кандидаты при evidence ≥ ", unlisted: "Отдельный review при unlisted ≥ " }
      : { positive: "Noul: положительный от ", uncertainty: "Review: мало доказательств > ", unlisted: "Review: событие вне списка > " };
    for (const [field, label] of Object.entries(labels)) $(`threshold-${field}`).labels[0].childNodes[0].nodeValue = label;
    $("thresholdHelp").textContent = activePolicyMode === "policy_v2"
      ? "В Policy v2: Noul ≤ отрицательного порога = negative, ≥ порога кандидата = positive, между ними = abstain. Положительные события становятся кандидатами; evidence ≥ порога удерживает только их; unlisted ≥ порога создаёт отдельную проверку. Choice и abstain сохраняются, но сами не создают review."
      : "Noul: score ≤ отрицательного порога → negative; score ≥ положительного → positive; между ними → abstain. Порог Choice принимает значение на границе. Сигналы review срабатывают только при score строго выше порога.";
    for (const button of document.querySelectorAll(".preset")) button.classList.toggle("active", button.dataset.preset === settings.preset);
    $("presetButtons").hidden = activePolicyMode === "policy_v2";
    $("legacyPresetNote").hidden = activePolicyMode !== "policy_v2";
    $("policyName").textContent = activePolicyMode === "policy_v2"
      ? "Policy v2 · независимые сигналы"
      : settings.preset === "custom" ? "Legacy · пользовательские пороги" : PRESETS.find((row) => row.id === settings.preset)?.label ?? "A · Current Strict";
    $("policyCaption").textContent = activePolicyMode === "policy_v2"
      ? "Choice и все оценки сохраняются. Кандидаты — event score ≥ порога; evidence удерживает кандидатов, unlisted создаёт отдельную проверку."
      : settings.preset === "custom"
        ? "Локальный пересчёт сохранённых оценок; историческая Legacy-логика. Это не новый запуск Jev."
        : "Legacy: экспериментальные сигналы сводятся к общему статусу новости; настройки применяются только в этом браузере.";
    $("filterState").querySelector('[value="review"]').textContent = activePolicyMode === "policy_v2" ? "Есть задача проверки" : "Нужна проверка";
    $("filterState").querySelector('[value="auto"]').textContent = activePolicyMode === "policy_v2" ? "Нет задачи проверки" : "Приняты порогами";
  }

  function currentGold(row) {
    const override = overrides.get(row.id);
    return override ? { topic: override.topic, events: new Set(override.events), changed: true } : {
      topic: row.expected_topic,
      events: new Set(row.expected_events),
      changed: false,
    };
  }

  function noulState(score, negative = settings.negative, positive = settings.positive) {
    if (score <= negative) return "negative";
    if (score >= positive) return "positive";
    return "abstain";
  }

  function decision(row, gates = settings.gates) {
    const result = row.result;
    if (!result) return { status: row.text?.trim() ? "missing" : "no_content", reasons: [], active: {}, raw: {}, predictions: new Set() };
    const raw = {
      choice: result.topic_confidence < choiceThreshold(),
      event_scores: DATA.taxonomy.events.some((event) => result.event_scores[event.code] > settings.negative && result.event_scores[event.code] < settings.positive),
      uncertainty: result.uncertainty_score > settings.uncertainty,
      unlisted: result.unlisted_event_score > settings.unlisted,
    };
    const isOtherTopic = result.topic === DATA.taxonomy.other_code;
    const active = {
      choice: Boolean(gates.choice && raw.choice),
      event_scores: Boolean(gates.event_band && raw.event_scores && !isOtherTopic),
      uncertainty: Boolean(gates.uncertainty && raw.uncertainty),
      unlisted: Boolean(gates.unlisted && raw.unlisted && !isOtherTopic),
    };
    const reasons = [];
    if (active.choice) reasons.push(`Choice confidence ${scoreText(result.topic_confidence)} ниже порога ${scoreText(settings.choice)}.`);
    const grayEvents = DATA.taxonomy.events.filter((event) => result.event_scores[event.code] > settings.negative && result.event_scores[event.code] < settings.positive);
    if (active.event_scores) reasons.push(`Оценки событий между ${scoreText(settings.negative)} и ${scoreText(settings.positive)}: ${grayEvents.map((event) => `${event.label} (${scoreText(result.event_scores[event.code])})`).join(", ")}.`);
    if (active.uncertainty) reasons.push(`Сигнал недостаточности доказательств ${scoreText(result.uncertainty_score)} выше порога ${scoreText(settings.uncertainty)}.`);
    if (active.unlisted) reasons.push(`Сигнал события вне списка ${scoreText(result.unlisted_event_score)} выше порога ${scoreText(settings.unlisted)}.`);
    const uncertain = Object.values(active).some(Boolean);
    const status = uncertain ? "uncertain" : isOtherTopic ? "other" : "classified";
    const predictions = new Set(DATA.taxonomy.events.filter((event) => result.event_scores[event.code] >= settings.positive).map((event) => event.code));
    return { status, reasons, raw, active, predictions, grayEvents };
  }

  function decisionV2(row) {
    const result = row.result;
    if (!result) return { status: row.text?.trim() ? "missing" : "no_content", reasons: [], active: {}, predictions: new Set(), eventStates: {}, eventAbstainCodes: [], blockedCodes: [], reviewTasks: [] };
    const eventStates = Object.fromEntries(DATA.taxonomy.events.map((event) => [event.code, noulState(result.event_scores[event.code], v2Settings.negative, v2Settings.positive)]));
    const eventAbstainCodes = DATA.taxonomy.events.filter((event) => eventStates[event.code] === "abstain").map((event) => event.code);
    const positiveCodes = DATA.taxonomy.events.filter((event) => eventStates[event.code] === "positive").map((event) => event.code);
    const evidenceThresholdReached = result.uncertainty_score >= v2Settings.evidence;
    const evidenceReview = positiveCodes.length > 0 && evidenceThresholdReached;
    const unlistedReview = result.unlisted_event_score >= v2Settings.unlisted;
    const candidateBlocked = evidenceReview;
    const predictions = new Set(candidateBlocked ? [] : positiveCodes);
    const blockedCodes = candidateBlocked ? positiveCodes : [];
    const reviewTasks = [];
    if (evidenceReview) reviewTasks.push(`Недостаточно доказательств: ${scoreText(result.uncertainty_score)} ≥ ${scoreText(v2Settings.evidence)}; кандидаты удержаны для проверки.`);
    if (unlistedReview) reviewTasks.push(`Событие вне списка: ${scoreText(result.unlisted_event_score)} ≥ ${scoreText(v2Settings.unlisted)}; отдельная задача проверки.`);
    const needsReview = reviewTasks.length > 0;
    const status = predictions.size ? (needsReview ? "candidates_and_review" : "candidates") : (candidateBlocked ? "candidates_held" : needsReview ? "unlisted_review" : "no_candidates");
    const reasons = reviewTasks;
    return {
      status, reasons, predictions, eventStates, eventAbstainCodes, positiveCodes,
      blockedCodes, evidenceThresholdReached, evidenceReview,
      unlistedReview, candidateBlocked, needsReview, reviewTasks,
      topicCode: result.topic, topicConfidence: result.topic_confidence,
      topicProbabilities: { ...result.topic_probabilities },
      eventScores: { ...result.event_scores },
      active: { evidence: evidenceReview, unlisted: unlistedReview },
    };
  }

  function activeDecision(row, gates = settings.gates) {
    return activePolicyMode === "policy_v2" ? decisionV2(row) : decision(row, gates);
  }

  function rowError(row, evaluated = decision(row)) {
    const gold = currentGold(row);
    const topicMismatch = row.result.topic !== gold.topic;
    const predicted = evaluated.predictions;
    const fp = [...predicted].filter((code) => !gold.events.has(code));
    const fn = [...gold.events].filter((code) => !predicted.has(code));
    const eventMismatch = fp.length > 0 || fn.length > 0;
    return { topicMismatch, fp, fn, eventMismatch, any: topicMismatch || eventMismatch, gold };
  }

  function metricSet(rows, gates) {
    const observed = rows.filter((row) => row.result);
    if (!observed.length) return { total: 0, accepted: 0, topicAccuracy: null, precision: null, recall: null, f1: null, exact: null, autoErrorRate: null, tp: 0, fp: 0, fn: 0, review: 0, topicCorrect: 0, acceptedError: 0 };
    let topicCorrect = 0; let tp = 0; let fp = 0; let fn = 0; let exact = 0; let accepted = 0; let acceptedError = 0;
    let acceptedTopicCorrect = 0; let acceptedTp = 0; let acceptedFp = 0; let acceptedFn = 0; let acceptedExact = 0;
    for (const row of observed) {
      const evaluated = decision(row, gates);
      const error = rowError(row, evaluated);
      const topicOk = row.result.topic === error.gold.topic;
      const eventOk = !error.eventMismatch;
      topicCorrect += Number(topicOk);
      tp += [...evaluated.predictions].filter((code) => error.gold.events.has(code)).length;
      fp += error.fp.length;
      fn += error.fn.length;
      exact += Number(eventOk);
      if (evaluated.status !== "uncertain") {
        accepted += 1;
        acceptedError += Number(!topicOk || !eventOk);
        acceptedTopicCorrect += Number(topicOk);
        acceptedTp += [...evaluated.predictions].filter((code) => error.gold.events.has(code)).length;
        acceptedFp += error.fp.length;
        acceptedFn += error.fn.length;
        acceptedExact += Number(eventOk);
      }
    }
    const precision = tp + fp ? tp / (tp + fp) : null;
    const recall = tp + fn ? tp / (tp + fn) : null;
    const f1 = 2 * tp + fp + fn ? 2 * tp / (2 * tp + fp + fn) : null;
    const acceptedPrecision = acceptedTp + acceptedFp ? acceptedTp / (acceptedTp + acceptedFp) : null;
    const acceptedRecall = acceptedTp + acceptedFn ? acceptedTp / (acceptedTp + acceptedFn) : null;
    const acceptedF1 = 2 * acceptedTp + acceptedFp + acceptedFn ? 2 * acceptedTp / (2 * acceptedTp + acceptedFp + acceptedFn) : null;
    return {
      total: observed.length, accepted, review: observed.length - accepted,
      coverage: accepted / observed.length, reviewRate: (observed.length - accepted) / observed.length,
      topicCorrect, topicAccuracy: topicCorrect / observed.length,
      precision, recall, f1, tp, fp, fn, exactCount: exact, exact: exact / observed.length,
      autoErrorRate: accepted ? acceptedError / accepted : null, acceptedError,
      acceptedTopicAccuracy: accepted ? acceptedTopicCorrect / accepted : null,
      acceptedEventF1: acceptedF1,
      acceptedEventPrecision: acceptedPrecision,
      acceptedEventRecall: acceptedRecall,
      acceptedExactEventSetAccuracy: accepted ? acceptedExact / accepted : null,
    };
  }

  function metricSetV2(rows) {
    const observed = rows.filter((row) => row.result);
    let tp = 0; let fp = 0; let fn = 0; let exact = 0; let candidateStories = 0;
    let reviewStories = 0; let eventAbstains = 0; let evidenceReviews = 0; let unlistedReviews = 0;
    let evidenceBlockedStories = 0; let topicCorrect = 0;
    for (const row of observed) {
      const evaluated = decisionV2(row);
      const gold = currentGold(row);
      const predicted = evaluated.predictions;
      const truePositive = [...predicted].filter((code) => gold.events.has(code));
      const falsePositive = [...predicted].filter((code) => !gold.events.has(code));
      const falseNegative = [...gold.events].filter((code) => !predicted.has(code));
      tp += truePositive.length; fp += falsePositive.length; fn += falseNegative.length;
      exact += Number(falsePositive.length === 0 && falseNegative.length === 0);
      candidateStories += Number(predicted.size > 0);
      reviewStories += Number(evaluated.needsReview);
      eventAbstains += evaluated.eventAbstainCodes.length;
      evidenceReviews += Number(evaluated.evidenceReview);
      unlistedReviews += Number(evaluated.unlistedReview);
      evidenceBlockedStories += Number(evaluated.blockedCodes.length > 0);
      topicCorrect += Number(row.result.topic === gold.topic);
    }
    const precision = tp + fp ? tp / (tp + fp) : null;
    const recall = tp + fn ? tp / (tp + fn) : null;
    const f1 = 2 * tp + fp + fn ? 2 * tp / (2 * tp + fp + fn) : null;
    return {
      total: observed.length, tp, fp, fn, precision, recall, f1, exact,
      exactRate: observed.length ? exact / observed.length : null,
      candidateStories, candidateCoverage: observed.length ? candidateStories / observed.length : null,
      reviewStories, noReviewStories: observed.length - reviewStories,
      eventAbstains, evidenceReviews, unlistedReviews,
      scopedReviewItems: evidenceReviews + unlistedReviews,
      evidenceBlockedStories, topicCorrect, topicAccuracy: observed.length ? topicCorrect / observed.length : null,
    };
  }

  function caseStatusLabel(row, evaluated = activeDecision(row)) {
    if (!row.result) return row.text?.trim() ? "Нет ответа Jev" : "Пустой текст";
    if (activePolicyMode === "policy_v2") {
      if (evaluated.blockedCodes.length) return `Кандидаты удержаны: evidence`;
      if (evaluated.predictions.size && evaluated.needsReview) return `${evaluated.predictions.size} кандидат(а) + отдельная проверка`;
      if (evaluated.predictions.size) return `${evaluated.predictions.size} кандидат(а) к передаче`;
      return evaluated.needsReview ? "Проверить событие вне списка" : "Сохранён · без кандидатов";
    }
    if (evaluated.status === "uncertain") return "Нужна проверка";
    if (evaluated.status === "other") return "Другая тема";
    return "Автоматически принято";
  }

  function renderTop() {
    const cards = activePolicyMode === "policy_v2" ? (() => {
      const metrics = metricSetV2(DATA.cases);
      const candidateCount = liveCaseRows().reduce((count, row) => count + decisionV2(row).predictions.size, 0);
      return [
        ["Новости в корпусе", "49", "непустых · плюс 1 пустой тест"],
        ["Ответы Jev", `${DATA.meta.resultCount}/49`, "4 ответа отсутствуют"],
        ["Тема совпала", `${metrics.topicCorrect}/45`, `${pct(metrics.topicAccuracy)} на всех ответах`],
        ["Event F1 кандидатов", pct(metrics.f1), `${metrics.tp} TP · ${metrics.fp} FP · ${metrics.fn} FN`],
        ["Истории с кандидатами", `${metrics.candidateStories}/45`, `${candidateCount} меток · все только кандидаты`],
      ];
    })() : (() => {
      const metrics = metricSet(DATA.cases, settings.gates);
      return [
        ["Новости в корпусе", "49", "непустых · плюс 1 пустой тест"],
        ["Ответы Jev", `${DATA.meta.resultCount}/49`, "4 ответа отсутствуют"],
        ["Тема совпала", `${metrics.topicCorrect}/45`, `${pct(metrics.topicAccuracy)} на всех ответах`],
        ["Event micro-F1", pct(metrics.f1), `${metrics.tp} TP · ${metrics.fp} FP · ${metrics.fn} FN`],
        ["Автопринято", `${metrics.accepted}/45`, `${pct(metrics.coverage)} среди ответов`],
      ];
    })();
    const root = $("topMetrics");
    root.replaceChildren();
    for (const [label, value, sub] of cards) {
      const card = node("div", "metric");
      append(card, node("div", "metric-label", label), node("div", "metric-value", value), node("div", "metric-sub", sub));
      root.append(card);
    }
    $("resultCountBadge").textContent = `${DATA.meta.resultCount} сохранённых ответов`;
  }

  function visibleCases() {
    let rows = DATA.cases.filter((row) => {
      const searchText = `${row.id} ${row.title ?? ""} ${row.text ?? ""}`.toLocaleLowerCase("ru");
      if (filters.search && !searchText.includes(filters.search)) return false;
      const evaluated = activeDecision(row);
      const gold = currentGold(row);
      const hasTopic = (row.result?.topic === filters.topic) || gold.topic === filters.topic;
      if (filters.topic && !hasTopic) return false;
      const hasEvent = filters.event && (gold.events.has(filters.event) || row.result?.predicted_events?.includes(filters.event) || evaluated.predictions.has(filters.event));
      if (filters.event && !hasEvent) return false;
      const error = row.result ? rowError(row, evaluated).any : false;
      const status = evaluated.status;
      if (filters.state === "review" && (activePolicyMode === "policy_v2" ? !evaluated.needsReview : status !== "uncertain")) return false;
      if (filters.state === "auto" && (activePolicyMode === "policy_v2" ? (!row.result || evaluated.needsReview) : status === "uncertain")) return false;
      if (filters.state === "error" && !error) return false;
      if (filters.state === "clean" && (!row.result || error)) return false;
      if (filters.state === "missing" && (!row.text?.trim() || row.result)) return false;
      if (filters.state === "disputed" && !reviewCaseIds.has(row.id)) return false;
      if (filters.state === "unlisted" && (!row.result || (activePolicyMode === "policy_v2" ? !evaluated.unlistedReview : row.result.unlisted_event_score <= settings.unlisted))) return false;
      if (filters.state === "evidence" && (!row.result || (activePolicyMode === "policy_v2" ? !evaluated.evidenceReview : row.result.uncertainty_score <= settings.uncertainty))) return false;
      if (filters.state === "empty" && row.text?.trim()) return false;
      return true;
    });
    if (filters.sort === "confidence_low") rows.sort((a, b) => (a.result?.topic_confidence ?? 2) - (b.result?.topic_confidence ?? 2));
    if (filters.sort === "events_high") rows.sort((a, b) => (b.result?.predicted_events?.length ?? -1) - (a.result?.predicted_events?.length ?? -1));
    if (filters.sort === "review_first") rows.sort((a, b) => Number(activeDecision(b).needsReview ?? activeDecision(b).status === "uncertain") - Number(activeDecision(a).needsReview ?? activeDecision(a).status === "uncertain"));
    if (filters.sort === "errors_first") rows.sort((a, b) => Number(b.result ? rowError(b, activeDecision(b)).any : false) - Number(a.result ? rowError(a, activeDecision(a)).any : false));
    return rows;
  }

  function renderCaseList() {
    const root = $("caseList");
    root.replaceChildren();
    const rows = visibleCases();
    $("visibleCaseCount").textContent = `${rows.length} из ${DATA.cases.length}`;
    if (!rows.length) { root.append(node("div", "empty-state", "Ничего не найдено. Измените фильтры.")); return; }
    for (const row of rows) {
      const evaluated = activeDecision(row);
      const card = node("button", `case-card${row.id === selectedId ? " selected" : ""}`);
      card.type = "button";
      card.setAttribute("aria-current", String(row.id === selectedId));
      card.addEventListener("click", () => { selectedId = row.id; renderAll(); window.scrollTo({ top: 0, behavior: "smooth" }); });
      const top = node("div", "case-card-top");
      append(top, node("span", "case-id", row.id));
      if (reviewCaseIds.has(row.id)) top.append(node("span", "badge amber small", "разметка на ревью"));
      const title = node("div", "case-title", row.title || "Пустой текст");
      const summary = node("div", "case-summary", row.text || "Текст отсутствует.");
      const meta = node("div", "case-meta");
      const status = node("span", `case-status${(activePolicyMode === "policy_v2" ? evaluated.needsReview : evaluated.status === "uncertain") ? " review" : ""}${evaluated.status === "missing" ? " missing" : ""}`, caseStatusLabel(row, evaluated));
      meta.append(status);
      if (row.result) {
        meta.append(node("span", "badge small", activePolicyMode === "policy_v2" ? `${evaluated.predictions.size} кандидатов` : `${evaluated.predictions.size} событий`));
        if (rowError(row, evaluated).any) meta.append(node("span", "badge red small", "есть расхождение"));
      } else if (row.text?.trim()) meta.append(node("span", "badge red small", "без результата"));
      append(card, top, title, summary, meta);
      root.append(card);
    }
  }

  function labelChip(text, kind = "") { return node("span", `label-chip${kind ? ` ${kind}` : ""}`, text); }

  function renderComparison() {
    const root = $("comparisonBody");
    root.replaceChildren();
    const row = caseById(selectedId);
    if (!row) return;
    const gold = currentGold(row);
    const evaluated = activeDecision(row);
    const error = row.result ? rowError(row, evaluated) : null;
    const original = node("div", "gold-block");
    const originalHeading = node("div", "gold-heading");
    append(originalHeading, node("span", "", "Предварительная разметка"), node("span", "badge amber small", "не утверждена человеком"));
    original.append(originalHeading);
    const topicLine = node("div", "compare-line");
    append(topicLine, node("span", "compare-key", "Основная тема"), node("span", "compare-val", topicLabel(row.expected_topic)));
    original.append(topicLine);
    const expectedStatus = node("div", "compare-line");
    append(expectedStatus, node("span", "compare-key", "Черновой статус"), node("span", "compare-val", row.expected_status));
    original.append(expectedStatus);
    const eventHead = node("div", "subsection-label", `Ожидались события · ${row.expected_events.length}`);
    original.append(eventHead);
    const originalEvents = node("div", "label-list");
    for (const code of row.expected_events) {
      const v2Held = activePolicyMode === "policy_v2" && evaluated.blockedCodes.includes(code);
      originalEvents.append(labelChip(eventLabel(code), v2Held ? "review" : error?.fn.includes(code) ? "fn" : error?.fp.includes(code) ? "fp" : "correct"));
    }
    if (!row.expected_events.length) originalEvents.append(labelChip("Событий нет"));
    original.append(originalEvents);
    if (gold.changed) {
      const changed = node("div", "gold-block");
      const heading = node("div", "gold-heading");
      append(heading, node("span", "", "Ваш вариант"), node("span", "badge blue small", "черновик"));
      changed.append(heading);
      const changedTopic = node("div", "compare-line");
      append(changedTopic, node("span", "compare-key", "Тема"), node("span", "compare-val", topicLabel(gold.topic)));
      changed.append(changedTopic);
      const chips = node("div", "label-list");
      for (const code of gold.events) chips.append(labelChip(eventLabel(code), ""));
      if (!gold.events.size) chips.append(labelChip("Событий нет"));
      changed.append(node("div", "subsection-label", "Предлагаемый набор"), chips);
      original.append(changed);
    }

    const model = node("div", "gold-block");
    model.append(node("div", "gold-heading", "Сохранённый ответ Jev"));
    if (!row.result) {
      const absent = node("div", "missing-box");
      append(absent, node("strong", "", row.text?.trim() ? "Ответ Jev отсутствует" : "Пустой тестовый текст"), node("span", "", row.text?.trim() ? "Классификация не выполняется. Эта запись исключена из метрик точности." : "Локальный кейс no_content; он не отправлялся в Jev."));
      model.append(absent);
    } else {
      const jevTopic = node("div", "compare-line");
      append(jevTopic, node("span", "compare-key", "Тема Jev"), node("span", "compare-val", topicLabel(row.result.topic)));
      const jevTopicValue = jevTopic.querySelector(".compare-val");
      jevTopicValue.classList.add(error.topicMismatch ? "wrong" : "correct");
      jevTopicValue.textContent += error.topicMismatch ? " · ошибка темы" : " · совпало";
      model.append(jevTopic);
      const stored = node("div", "compare-line");
      append(stored, node("span", "compare-key", activePolicyMode === "policy_v2" ? "Сохранённый Legacy status" : "Сохранённый статус"), node("span", `compare-val ${row.result.classification_status === "uncertain" ? "" : ""}`, row.result.classification_status));
      model.append(stored);
      model.append(node("div", "subsection-label", activePolicyMode === "policy_v2" ? "Event-кандидаты, переданные по Policy v2" : "События Jev при моих порогах"));
      const pred = node("div", "label-list");
      for (const code of evaluated.predictions) pred.append(labelChip(eventLabel(code), gold.events.has(code) ? "correct" : "fp"));
      if (!evaluated.predictions.size) pred.append(labelChip(activePolicyMode === "policy_v2" ? "Кандидаты не переданы" : "Положительных событий нет"));
      model.append(pred);
      if (activePolicyMode === "policy_v2" && evaluated.blockedCodes.length) {
        const blocked = node("div", "gold-block");
        blocked.append(node("div", "subsection-label", "Положительная оценка удержана сигналом доказательств"));
        const held = node("div", "label-list");
        for (const code of evaluated.blockedCodes) held.append(labelChip(eventLabel(code), "review"));
        blocked.append(held);
        model.append(blocked);
      }
      const signals = node("div", "gold-block");
      const signalRows = [
        ["Событие вне списка", row.expected_unlisted_event, row.result.unlisted_event_score],
        ["Недостаточно доказательств", row.expected_uncertainty_signal, row.result.uncertainty_score],
      ];
      for (const [label, expected, score] of signalRows) {
        const line = node("div", "compare-line");
        const value = node("span", `compare-val${expected ? " amber-text" : ""}`, `${expected ? "ожидалось" : "не ожидалось"} · score ${scoreText(score)}`);
        append(line, node("span", "compare-key", label), value);
        signals.append(line);
      }
      model.append(signals);
      const diffs = node("div", "diff-list");
      if (error.topicMismatch) diffs.append(node("div", "", `Ошибка темы: Jev выбрал «${topicLabel(row.result.topic)}».`));
      for (const code of error.fp) diffs.append(node("div", "", activePolicyMode === "policy_v2" ? `Ложный кандидат (не факт) · ${eventLabel(code)}` : `Ложное срабатывание · ${eventLabel(code)}`));
      for (const code of error.fn) {
        if (activePolicyMode === "policy_v2" && evaluated.blockedCodes.includes(code)) diffs.append(node("div", "", `Не передан: положительная оценка удержана по доказательствам · ${eventLabel(code)}`));
        else if (activePolicyMode === "policy_v2") diffs.append(node("div", "", `Не передан: score ниже порога кандидата · ${eventLabel(code)}`));
        else diffs.append(node("div", "", `Пропущено · ${eventLabel(code)}`));
      }
      if (!error.any) diffs.append(node("div", "", "По текущим меткам и порогу событий расхождений нет."));
      model.append(diffs);
      model.append(node("div", "editor-note", `Сохранённый Jev: ${row.result.predicted_events.length} positive-категорий при исходном пороге ${scoreText(DATA.taxonomy.thresholds.noul_positive_at_or_above)}. Текущие метки считаются локально.`));
    }

    append(root, original, model, renderGoldEditor(row));
  }

  function renderGoldEditor(row) {
    const editor = node("details", "edit-gold");
    const summary = node("summary", "", "Предложить свою разметку для этой новости");
    editor.append(summary);
    if (!row.text?.trim()) {
      editor.append(node("div", "editor-note", "Для пустого текста метки не редактируются."));
      return editor;
    }
    const gold = currentGold(row);
    const topicLabelNode = node("label", "editor-label", "Предлагаемая основная тема");
    const topicSelect = node("select", "field");
    for (const topic of DATA.taxonomy.topics) {
      const option = node("option", "", `${topic.label} · ${topic.code}`);
      option.value = topic.code;
      topicSelect.append(option);
    }
    topicSelect.value = gold.topic;
    topicSelect.addEventListener("change", () => updateOverride(row, topicSelect.value, readEventChecks(checks), reason.value, editor.open));
    topicLabelNode.append(topicSelect);
    const eventsLabel = node("label", "editor-label", "Ожидаемые события (можно несколько)");
    const checks = node("div", "event-checks");
    for (const event of DATA.taxonomy.events) {
      const line = node("label", "event-check");
      const input = node("input");
      input.type = "checkbox";
      input.value = event.code;
      input.checked = gold.events.has(event.code);
      input.addEventListener("change", () => updateOverride(row, topicSelect.value, readEventChecks(checks), reason.value, true));
      append(line, input, node("span", "", event.label));
      checks.append(line);
    }
    eventsLabel.append(checks);
    const reasonLabel = node("label", "editor-label", "Основание изменения (для экспорта)");
    const reason = node("textarea", "field");
    reason.rows = 3;
    reason.placeholder = "Что в тексте подтверждает эту метку?";
    reason.value = overrides.get(row.id)?.rationale ?? "";
    reason.addEventListener("input", () => {
      const current = overrides.get(row.id);
      if (current) current.rationale = reason.value;
    });
    reasonLabel.append(reason);
    const actions = node("div", "editor-actions");
    const apply = node("button", "secondary-button", "Применить вариант");
    apply.type = "button";
    apply.addEventListener("click", () => updateOverride(row, topicSelect.value, readEventChecks(checks), reason.value, true));
    const undo = node("button", "secondary-button", "Отменить для новости");
    undo.type = "button";
    undo.disabled = !gold.changed;
    undo.addEventListener("click", () => { overrides.delete(row.id); renderAll(); });
    const exportButton = node("button", "primary-button", "Экспортировать мои решения JSON");
    exportButton.type = "button";
    exportButton.disabled = overrides.size === 0;
    exportButton.addEventListener("click", exportOverrides);
    append(actions, apply, undo, exportButton);
    append(editor, topicLabelNode, eventsLabel, reasonLabel, actions, node("div", "editor-note", "Это локальный черновик, не утверждённый gold. Встроенные исходные метки не меняются."));
    if (gold.changed) editor.open = true;
    return editor;
  }

  function readEventChecks(root) {
    return [...root.querySelectorAll("input[type=checkbox]:checked")].map((input) => input.value);
  }

  function updateOverride(row, topic, events, rationale, openEditor) {
    const originalEvents = [...row.expected_events].sort();
    const proposedEvents = [...new Set(events)].sort();
    const same = topic === row.expected_topic && JSON.stringify(originalEvents) === JSON.stringify(proposedEvents);
    if (same) overrides.delete(row.id);
    else overrides.set(row.id, { topic, events: proposedEvents, rationale: String(rationale ?? "").trim() });
    renderAll();
    const editor = document.querySelector("#comparisonBody details.edit-gold");
    if (editor && openEditor) editor.open = true;
  }

  function exportOverrides() {
    const changes = [...overrides.entries()].map(([id, value]) => {
      const original = caseById(id);
      return {
        case_id: id,
        original: { topic: original.expected_topic, events: original.expected_events },
        proposed: { topic: value.topic, events: value.events },
        rationale: value.rationale,
        taxonomy_id: DATA.taxonomy.id,
        taxonomy_version: DATA.taxonomy.version,
      };
    });
    const payload = {
      schema_version: "t08-label-review-export-v1",
      status: "user_proposal_not_approved_gold",
      taxonomy_id: DATA.taxonomy.id,
      taxonomy_version: DATA.taxonomy.version,
      corpus_id: DATA.meta.corpusId,
      corpus_version: DATA.meta.corpusVersion,
      changes,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = node("a");
    link.href = url;
    link.download = "jev-label-proposals.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  function renderDetail() {
    const root = $("detailBody");
    root.replaceChildren();
    const row = caseById(selectedId);
    if (!row) return;
    const result = row.result;
    const evaluated = activeDecision(row);
    const error = result ? rowError(row, evaluated) : null;
    const heading = node("div", "detail-title-row");
    const left = node("div");
    append(left, node("div", "detail-id", row.id), node("h2", "detail-title", row.title || "Пустой текст"));
    const isReview = activePolicyMode === "policy_v2" ? evaluated.needsReview : evaluated.status === "uncertain";
    const headStatus = node("span", `badge${!result ? " red" : isReview ? " amber" : " green"}`, caseStatusLabel(row, evaluated));
    append(heading, left, headStatus);
    root.append(heading);
    const badgeRow = node("div", "detail-badges");
    badgeRow.append(node("span", "badge blue", `корпус ${DATA.meta.corpusVersion}`));
    if (reviewCaseIds.has(row.id)) badgeRow.append(node("span", "badge amber", "нужна проверка gold"));
    if (overrides.has(row.id)) badgeRow.append(node("span", "badge blue", "есть ваша правка"));
    if (result) badgeRow.append(node("span", "badge", `модель ${result.model_version}`));
    root.append(badgeRow);
    root.append(makePipeline());

    if (!result) {
      const absent = node("div", "missing-box");
      append(absent, node("strong", "", row.text?.trim() ? "Ответ Jev отсутствует. Классификация не выполняется." : "Пустой тестовый текст · no_content"), node("span", "", row.text?.trim() ? "Эта запись остаётся видимой, но у неё нет оценок модели и она не учитывается как ошибка или пропуск события." : "Это локальная проверка обработки пустого ввода; запрос в Jev не выполнялся."));
      root.append(absent);
      if (row.text?.trim()) {
        root.append(node("div", "section-heading", ""));
        root.append(storyCard(row));
      }
      return;
    }

    const summary = node("div", "summary-grid");
    const topic = topicByCode.get(result.topic);
    const routeSummary = activePolicyMode !== "policy_v2"
      ? evaluated.status === "uncertain" ? "нужна общая проверка" : "пороговая проверка пройдена"
      : evaluated.blockedCodes.length
        ? "кандидаты удержаны по недостатку доказательств"
        : evaluated.predictions.size && evaluated.needsReview
          ? "кандидаты доступны · есть отдельная задача"
          : evaluated.predictions.size
            ? "кандидаты доступны · не подтверждённые факты"
            : evaluated.needsReview
              ? "отдельная задача · кандидатов нет"
              : "сохранено · кандидатов нет";
    summary.append(summaryCell("Тема Jev", topic?.label ?? result.topic, `Choice ${scoreText(result.topic_confidence)}`));
    summary.append(summaryCell(activePolicyMode === "policy_v2" ? "Event-кандидаты" : "Положительные события", String(evaluated.predictions.size), activePolicyMode === "policy_v2" ? (evaluated.blockedCodes.length ? `${evaluated.blockedCodes.length} удержано по evidence · не подтверждённые факты` : "кандидаты, не подтверждённые факты") : `по порогу ${scoreText(settings.positive)}`));
    summary.append(summaryCell("Решение сейчас", activePolicyMode === "policy_v2" ? routeSummary : evaluated.status, activePolicyMode === "policy_v2" ? `${evaluated.reasons.length} отдельных задач проверки` : evaluated.status === "uncertain" ? `${evaluated.reasons.length} активных причин` : "пороговая проверка пройдена"));
    root.append(summary);
    root.append(storyCard(row));
    root.append(sectionHeading("Choice · основная тема", "Choice выбирает одну главную тему. Значения показывают ответ и сохранённые оценки; это не калиброванные вероятности."));
    root.append(renderChoice(result));
    root.append(sectionHeading("Noul · бизнес-события", "Каждый тип события оценивается отдельно. Между отрицательным и положительным порогами состояние — abstain."));
    root.append(renderEvents(result, evaluated));
    root.append(sectionHeading("Дополнительные сигналы", "Не смешиваем событие вне списка с недостаточностью доказательств."));
    root.append(renderSignals(result, evaluated));
    root.append(sectionHeading("Итоговая проверка приложения", "Это наблюдаемая логика наших порогов, а не скрытое объяснение Jev."));
    root.append(renderDecision(row, evaluated));
  }

  function makePipeline() {
    const pipeline = node("div", "pipeline");
    const labels = ["Текст новости", "Choice", "Noul", "Наши пороги"];
    labels.forEach((label, index) => {
      const step = node("div", "pipeline-step");
      append(step, node("span", "step-num", String(index + 1)), node("span", "", label));
      pipeline.append(step);
    });
    return pipeline;
  }

  function storyCard(row) {
    const card = node("div", "story-box");
    append(card, node("div", "story-label", "Полный синтетический текст новости"), node("div", "story-text", row.text));
    return card;
  }

  function summaryCell(label, value, note) {
    const card = node("div", "summary-cell");
    append(card, node("div", "summary-label", label), node("div", "summary-value", value), node("div", "summary-note", note));
    return card;
  }

  function sectionHeading(title, copy) {
    const section = node("div", "section-heading");
    append(section, node("div", "", title), node("p", "", copy));
    return section;
  }

  function renderChoice(result) {
    const card = node("div", "choice-card");
    const topic = topicByCode.get(result.topic);
    const meta = node("div", "choice-meta");
    const chosen = node("div", "choice-name", `Выбрано: ${topic?.label ?? result.topic}`);
    const badge = node("span", "badge blue", `confidence ${scoreText(result.topic_confidence)} · сохранено`);
    append(meta, chosen, badge);
    card.append(meta);
    const accepted = result.topic_confidence >= settings.choice;
    card.append(node("div", "editor-note", activePolicyMode === "policy_v2"
      ? "В этом потоке тема Choice и её confidence сохраняются для следующих этапов. Они не блокируют передачу event-кандидатов."
      : (accepted ? "Confidence не ниже порога: проверка Choice пройдена." : "Confidence ниже порога: приложение отправит тему на ручную проверку.")));
    const entries = DATA.taxonomy.topics.map((item) => ({ item, score: result.topic_probabilities[item.code] })).sort((a, b) => b.score - a.score);
    const bars = node("div", "bars");
    for (const { item, score } of entries) bars.append(makeBar(item.label, score, "topic"));
    card.append(bars);
    return card;
  }

  function makeBar(label, score, kind = "") {
    const row = node("div", "bar-row");
    append(row, node("span", "bar-label", label));
    const track = node("div", "bar-track");
    const fill = node("div", `bar-fill${kind ? ` ${kind}` : ""}`);
    fill.style.width = `${Math.max(0, Math.min(100, score * 100))}%`;
    track.append(fill);
    append(row, track, node("span", "bar-value", scoreText(score)));
    return row;
  }

  function renderEvents(result, evaluated = activePolicyMode === "policy_v2" ? decisionV2({ result }) : null) {
    const root = node("div", "event-list");
    for (const event of DATA.taxonomy.events) {
      const score = result.event_scores[event.code];
      const state = activePolicyMode === "policy_v2"
        ? evaluated.eventStates[event.code]
        : noulState(score);
      const detail = node("details", "event-item");
      const summary = node("summary", "event-summary");
      append(summary, node("span", "event-name", event.label));
      const track = node("div", "bar-track");
      const fill = node("div", `bar-fill${state === "positive" ? " event-positive" : state === "abstain" ? " event-abstain" : ""}`);
      fill.style.width = `${score * 100}%`;
      track.append(fill);
      append(summary, track, node("span", "bar-value", scoreText(score)), node("span", `state-chip ${state}`, state === "positive" ? "positive" : state === "negative" ? "negative" : "abstain"));
      const extra = node("div", "event-extra");
      if (activePolicyMode === "policy_v2") {
        const routing = evaluated.predictions.has(event.code)
          ? "Кандидат для следующего этапа · не подтверждённый факт."
          : evaluated.blockedCodes.includes(event.code)
            ? "Положительная оценка есть, но кандидат удержан из-за сигнала недостаточности доказательств."
          : state === "abstain"
              ? "Оценка сохранена как abstain. По этой схеме она сама по себе не создаёт проверку и не блокирует другие категории."
              : "Не передаётся как кандидат по текущему порогу.";
        extra.append(node("div", `candidate-routing${evaluated.predictions.has(event.code) ? " candidate" : evaluated.blockedCodes.includes(event.code) ? " blocked" : state === "abstain" ? " saved-state" : ""}`, routing));
      }
      append(extra, node("div", "event-def", event.definition));
      const criteria = node("div", "include-exclude");
      const include = node("div", "criterion");
      append(include, node("b", "", "Считать событием, если"), node("span", "", event.include));
      const exclude = node("div", "criterion exclude");
      append(exclude, node("b", "", "Не считать, если"), node("span", "", event.exclude));
      append(criteria, include, exclude);
      extra.append(criteria);
      const negative = activePolicyMode === "policy_v2" ? v2Settings.negative : settings.negative;
      const positive = activePolicyMode === "policy_v2" ? v2Settings.positive : settings.positive;
      extra.append(node("div", "editor-note", `Состояние по сохранённой оценке: ${scoreText(score)} ${state === "positive" ? `≥ ${scoreText(positive)}` : state === "negative" ? `≤ ${scoreText(negative)}` : `между ${scoreText(negative)} и ${scoreText(positive)}`}.`));
      append(detail, summary, extra);
      root.append(detail);
    }
    return root;
  }

  function renderSignals(result, evaluated = activePolicyMode === "policy_v2" ? decisionV2({ result }) : null) {
    const grid = node("div", "signal-grid");
    const signals = [
      { title: "Событие вне списка", key: "unlisted", score: result.unlisted_event_score, cutoff: activePolicyMode === "policy_v2" ? v2Settings.unlisted : settings.unlisted, triggered: activePolicyMode === "policy_v2" ? evaluated.unlistedReview : result.unlisted_event_score > settings.unlisted, copy: "Отдельно оценивает, есть ли событие, которому не нашлось подходящей метки в нашем справочнике." },
      { title: "Недостаточно доказательств", key: "evidence", score: result.uncertainty_score, cutoff: activePolicyMode === "policy_v2" ? v2Settings.evidence : settings.uncertainty, triggered: activePolicyMode === "policy_v2" ? evaluated.evidenceThresholdReached : result.uncertainty_score > settings.uncertainty, copy: "Отдельно показывает, насколько сообщение расплывчато, неполно, похоже на слух или содержит противоречия." },
    ];
    for (const signal of signals) {
      const card = node("div", "signal-card");
      const top = node("div", "signal-value-row");
      append(top, node("span", "", signal.title), node("strong", "signal-value", scoreText(signal.score)));
      card.append(top);
      const state = signal.triggered ? "сработал" : "ниже порога";
      card.append(makeBar(`Порог ${scoreText(signal.cutoff)}`, signal.score, signal.triggered ? "event-abstain" : "topic"));
      card.append(node("div", "signal-copy", signal.copy));
      card.append(node("div", "editor-note", activePolicyMode === "policy_v2"
        ? (signal.key === "evidence"
          ? `Score ${scoreText(signal.score)} ${signal.triggered ? "≥" : "<"} порога ${scoreText(signal.cutoff)}. ${evaluated.candidateBlocked ? "Есть event-кандидаты — они удержаны для проверки." : evaluated.positiveCodes?.length ? "Кандидаты передаются; это значение их не удержало." : "Положительных event-кандидатов нет, поэтому удерживать нечего и задача не создаётся."}`
          : `${state}: score ${scoreText(signal.score)} ${signal.triggered ? "≥" : "<"} ${scoreText(signal.cutoff)}. ${signal.triggered ? "Создаётся отдельная задача проверки; известные event-кандидаты остаются доступными." : "Отдельная задача не создаётся."}`)
        : `${state}; Legacy review gate ${settings.gates[signal.key === "unlisted" ? "unlisted" : "uncertainty"] ? "включён" : "выключен"}.`));
      grid.append(card);
    }
    return grid;
  }

  function renderDecision(row, evaluated) {
    if (activePolicyMode === "policy_v2") return renderDecisionV2(row, evaluated);
    const card = node("div", `decision-card${evaluated.status === "uncertain" ? " uncertain" : evaluated.status === "classified" ? " classified" : ""}`);
    const head = node("div", "decision-title");
    append(head, node("span", "", evaluated.status === "uncertain" ? "Ручная проверка нужна" : evaluated.status === "other" ? "Другая тема" : "Результат принят порогами"), node("span", `badge${evaluated.status === "uncertain" ? " amber" : evaluated.status === "classified" ? " green" : ""}`, evaluated.status));
    card.append(head);
    if (evaluated.reasons.length) {
      const list = node("ul", "reason-list");
      for (const reason of evaluated.reasons) list.append(node("li", "", reason));
      card.append(list);
    } else card.append(node("div", "decision-explain", "Ни одно включённое правило review не сработало."));
    if (row.result.topic === DATA.taxonomy.other_code) {
      card.append(node("div", "decision-explain", "Для темы other_uncertain историческая логика не активирует review по event-band и unlisted. Choice и недостаточность доказательств продолжают проверяться."));
    }
    const inactive = [];
    if (!settings.gates.event_band && evaluated.raw.event_scores) inactive.push("event-band отключён выбранной политикой");
    if (!settings.gates.uncertainty && evaluated.raw.uncertainty) inactive.push("сигнал недостаточности отключён");
    if (!settings.gates.unlisted && evaluated.raw.unlisted) inactive.push("сигнал вне списка отключён");
    if (row.result.topic === DATA.taxonomy.other_code) {
      if (evaluated.raw.event_scores) inactive.push("event-band не применяется к other_uncertain");
      if (evaluated.raw.unlisted) inactive.push("unlisted не применяется к other_uncertain");
    }
    if (inactive.length) card.append(node("div", "decision-explain", `Неактивные сигналы: ${inactive.join("; ")}.`));
    card.append(node("div", "decision-explain", `В сохранённой записи Jev указан статус «${row.result.classification_status}». Текущее решение выше — локальный пересчёт по выбранным порогам.`));
    return card;
  }

  function renderDecisionV2(row, evaluated) {
    const card = node("div", `decision-card${evaluated.needsReview ? " uncertain" : " classified"}`);
    const title = evaluated.blockedCodes.length
      ? `${evaluated.blockedCodes.length} кандидат(а) удержаны для проверки`
      : evaluated.predictions.size
        ? `${evaluated.predictions.size} event-кандидат(а) доступны для передачи`
        : "Положительных event-кандидатов нет";
    const head = node("div", "decision-title");
    append(head, node("span", "", title), node("span", `badge${evaluated.needsReview ? " amber" : " green"}`, evaluated.needsReview ? `${evaluated.reviewTasks.length} задача проверки` : evaluated.predictions.size ? "кандидаты не подтверждены" : "сохранено без кандидатов"));
    card.append(head);
    card.append(node("div", "decision-explain", "Схема обработки: технически корректный ответ сохраняет тему Choice и все оценки Noul. Каждая event-оценка ≥ порога становится кандидатом, а не подтверждённым фактом."));
    const topics = [
      ["1 · Choice и оценки", `тема «${topicLabel(row.result.topic)}» и все event scores сохранены; Choice confidence ${scoreText(row.result.topic_confidence)} не блокирует события`],
      ["2 · Положительные события", `${evaluated.positiveCodes.length} оценок ≥ ${scoreText(v2Settings.positive)}; ${evaluated.blockedCodes.length ? "кандидаты удержаны" : `${evaluated.predictions.size} передано как кандидаты`}`],
      ["3 · Недостаточно доказательств", `score ${scoreText(row.result.uncertainty_score)}; порог ${scoreText(v2Settings.evidence)}; ${evaluated.evidenceReview ? "кандидаты удержаны для проверки" : evaluated.positiveCodes.length ? "кандидаты не удерживаются" : "кандидатов нет, удерживать нечего"}`],
      ["4 · Событие вне списка", `score ${scoreText(row.result.unlisted_event_score)}; порог ${scoreText(v2Settings.unlisted)}; ${evaluated.unlistedReview ? "отдельная задача проверки" : "без отдельной задачи"}; не блокирует известные события`],
    ];
    const list = node("ul", "reason-list");
    for (const [label, value] of topics) list.append(node("li", "", `${label}: ${value}.`));
    card.append(list);
    if (evaluated.reasons.length) {
      const tasks = node("div", "review-task-list");
      for (const reason of evaluated.reasons) tasks.append(node("div", "review-task", reason));
      card.append(tasks);
    }
    if (evaluated.blockedCodes.length) {
      card.append(node("div", "decision-explain", `Удержаны положительные оценки: ${evaluated.blockedCodes.map(eventLabel).join(", ")}.`));
    }
    card.append(node("div", "editor-note", "Negative и abstain оценки тоже сохраняются. Abstain само по себе не создаёт review. Кандидаты не являются подтверждёнными фактами; последующие этапы должны проверять их и собирать доказательства."));
    return card;
  }

  function renderStats() {
    const legacyMetrics = metricSet(DATA.cases, settings.gates);
    const v2Metrics = metricSetV2(DATA.cases);
    const metrics = activePolicyMode === "policy_v2" ? v2Metrics : legacyMetrics;
    const root = $("statsMetrics");
    root.replaceChildren();
    const items = activePolicyMode === "policy_v2" ? [
      ["Topic Accuracy", pct(v2Metrics.topicAccuracy), `${v2Metrics.topicCorrect}/${v2Metrics.total} ответов`],
      ["Event Precision", pct(v2Metrics.precision), `${v2Metrics.tp} TP · ${v2Metrics.fp} FP`],
      ["Event Recall", pct(v2Metrics.recall), `${v2Metrics.tp} TP · ${v2Metrics.fn} не передано`],
      ["Event F1 кандидатов", pct(v2Metrics.f1), "среди автоматически переданных event-кандидатов"],
      ["Exact Event-Set", pct(v2Metrics.exactRate), `${v2Metrics.exact}/${v2Metrics.total} выходных наборов`],
      ["Candidate Coverage", pct(v2Metrics.candidateCoverage), `${v2Metrics.candidateStories}/${v2Metrics.total} с кандидатами`],
      ["Есть задача review", pct(v2Metrics.reviewStories / v2Metrics.total), `${v2Metrics.reviewStories}/${v2Metrics.total} историй`],
      ["False Positives", String(v2Metrics.fp), "ложные кандидаты по draft gold"],
      ["Не передано", String(v2Metrics.fn), "включая policy hold и negative"],
      ["Задачи проверки", String(v2Metrics.scopedReviewItems), `${v2Metrics.eventAbstains} оценок abstain сохранено без review`],
    ] : [
      ["Topic Accuracy", pct(legacyMetrics.topicAccuracy), `${legacyMetrics.topicCorrect}/${legacyMetrics.total} ответов`],
      ["Event Precision", pct(legacyMetrics.precision), `${legacyMetrics.tp} TP · ${legacyMetrics.fp} FP`],
      ["Event Recall", pct(legacyMetrics.recall), `${legacyMetrics.tp} TP · ${legacyMetrics.fn} FN`],
      ["Event micro-F1", pct(legacyMetrics.f1), "по текущему порогу positive"],
      ["Exact Event-Set", pct(legacyMetrics.exact), `${legacyMetrics.exactCount}/${legacyMetrics.total} новостей`],
      ["Auto Coverage", pct(legacyMetrics.coverage), `${legacyMetrics.accepted}/${legacyMetrics.total} без review`],
      ["Review Rate", pct(legacyMetrics.reviewRate), `${legacyMetrics.review}/${legacyMetrics.total} ответов`],
      ["False Positives", String(legacyMetrics.fp), "среди 15 категорий событий"],
      ["False Negatives", String(legacyMetrics.fn), "относительно черновой разметки"],
      ["Ошибки среди auto", pct(legacyMetrics.autoErrorRate), `${legacyMetrics.acceptedError}/${legacyMetrics.accepted} принятых`],
    ];
    for (const [label, value, sub] of items) root.append(summaryMetric(label, value, sub));
    $("policyComparison").replaceChildren(policyComparisonCard(v2Metrics));
    const charts = $("chartsGrid");
    charts.replaceChildren();
    charts.append(chartCard("Основные темы Jev", "Распределение только по 45 сохранённым ответам.", topicDistribution()));
    charts.append(chartCard("Положительные события", `Текущий positive-порог ${scoreText(settings.positive)}; оценки не являются калиброванными вероятностями.`, eventDistribution()));
    charts.append(chartCard("События с наибольшими расхождениями", "FP и FN на текущем пороге и текущих метках.", eventErrors()));
    charts.append(chartCard(
      activePolicyMode === "policy_v2" ? "Причины задач проверки · Policy v2" : "Причины ручной проверки · Legacy",
      activePolicyMode === "policy_v2"
        ? "Удержание кандидатов по недостатку доказательств и отдельные задачи по событиям вне списка. Один случай может попасть в обе группы."
        : "Показаны причины по исходной Legacy-логике. Счётчики могут пересекаться.",
      triggerDistribution(),
    ));
    charts.append(scatterCard());
    charts.append(policyTableCard());
    $("statsFootnote").textContent = `Метрики относятся к 45 сохранённым ответам на синтетических новостях и предварительных метках. 4 из 49 непустых новостей без ответа исключены из точности и event FN; ещё 1 пустой кейс не классифицируется. Модельные оценки не калиброваны. Диаграммы и пресеты A–E ниже остаются Legacy-диагностикой; таблица выше сравнивает реальную передачу Legacy и Policy v2. Результаты не доказывают качество на реальном новостном потоке.`;
  }

  function legacyOutputMetrics() {
    // The comparison baseline is always Legacy Current Strict. Preset gates
    // remain available for the interactive Legacy diagnostics elsewhere, but
    // must not silently change the named baseline after switching to v2.
    const currentStrictGates = { choice: true, event_band: true, uncertainty: true, unlisted: true };
    const observed = liveCaseRows();
    let tp = 0; let fp = 0; let fn = 0; let exact = 0; let emittedStories = 0; let emittedEvents = 0;
    const falsePositives = [];
    for (const row of observed) {
      const legacy = decision(row, currentStrictGates);
      const predicted = legacy.status === "uncertain" ? new Set() : legacy.predictions;
      const gold = currentGold(row).events;
      const truePositives = [...predicted].filter((code) => gold.has(code));
      const falsePositive = [...predicted].filter((code) => !gold.has(code));
      const falseNegative = [...gold].filter((code) => !predicted.has(code));
      tp += truePositives.length; fp += falsePositive.length; fn += falseNegative.length;
      emittedEvents += predicted.size;
      emittedStories += Number(predicted.size > 0);
      exact += Number(falsePositive.length === 0 && falseNegative.length === 0);
      for (const code of falsePositive) falsePositives.push({ case_id: row.id, code });
    }
    const precision = tp + fp ? tp / (tp + fp) : null;
    const recall = tp + fn ? tp / (tp + fn) : null;
    return {
      total: observed.length, tp, fp, fn,
      precision, recall, f1: 2 * tp + fp + fn ? 2 * tp / (2 * tp + fp + fn) : null,
      exact: observed.length ? exact / observed.length : null,
      emittedStories, emittedEvents, acceptedStories: metricSet(DATA.cases, currentStrictGates).accepted,
      reviewStories: metricSet(DATA.cases, currentStrictGates).review,
      falsePositives,
    };
  }

  function policyComparisonCard(v2Metrics) {
    const card = node("section", "chart-card policy-v2-comparison");
    append(card, node("div", "chart-title", "Legacy vs Policy v2 · один и тот же набор из 45 ответов"));
    card.append(node("div", "chart-desc", "Считается только то, что реально прошло бы дальше. Legacy передаёт целиком только прошедшие новости; v2 — отдельные event-кандидаты. 4 запроса без ответа исключены."));
    const legacy = legacyOutputMetrics();
    const v2 = v2Metrics;
    const riskyCodes = new Set(["sanctions", "trade_restriction", "legal_enforcement", "insolvency_default", "product_recall_quality_safety", "production_operational_disruption"]);
    const dangerous = (rows) => rows.filter((row) => riskyCodes.has(row.code));
    const legacyDanger = dangerous(legacy.falsePositives);
    const v2Danger = dangerous(liveCaseRows().flatMap((row) => {
      const gold = currentGold(row).events;
      return [...decisionV2(row).predictions].filter((code) => !gold.has(code)).map((code) => ({ case_id: row.id, code }));
    }));
    const table = node("table", "policy-table policy-v2-table");
    const head = node("thead");
    const header = node("tr");
    for (const label of ["Режим", "Передано дальше", "P", "R", "F1", "Точные наборы", "TP / FP / FN", "Stories с review", "Условно значимые FP*"]) header.append(node("th", "", label));
    head.append(header); table.append(head);
    const body = node("tbody");
    const rows = [
      { name: "Legacy · Current Strict", output: `${legacy.acceptedStories}/45 целых новостей · ${legacy.emittedEvents} меток`, p: legacy.precision, r: legacy.recall, f1: legacy.f1, exact: `${Math.round(legacy.exact * legacy.total)}/${legacy.total} · ${pct(legacy.exact)}`, counts: `${legacy.tp} / ${legacy.fp} / ${legacy.fn}`, review: `${legacy.reviewStories}/45`, danger: legacyDanger },
      { name: "Policy v2", output: `${v2.candidateStories}/45 новостей · ${v2MetricsCandidateCount(v2)} event-меток`, p: v2.precision, r: v2.recall, f1: v2.f1, exact: `${Math.round(v2.exactRate * v2.total)}/${v2.total} · ${pct(v2.exactRate)}`, counts: `${v2.tp} / ${v2.fp} / ${v2.fn}`, review: `${v2.reviewStories}/45`, danger: v2Danger },
    ];
    for (const row of rows) {
      const tr = node("tr", `policy-row${row.name === "Policy v2" ? " policy-v2-row" : ""}`);
      const dangerousLabel = `${row.danger.length}${row.danger.length ? ` · ${row.danger.map((item) => `${item.case_id}: ${item.code}`).join(", ")}` : ""}`;
      for (const value of [row.name, row.output, pct(row.p), pct(row.r), pct(row.f1), row.exact, row.counts, row.review, dangerousLabel]) tr.append(node("td", "", value));
      body.append(tr);
    }
    table.append(body);
    const wrap = node("div", "chart-body policy-table-wrap");
    wrap.append(table);
    card.append(wrap);
    card.append(node("div", "policy-v2-note", `Policy v2: ${v2Metrics.evidenceReviews} историй с удержанными event-кандидатами · ${v2Metrics.unlistedReviews} отдельных задач по событиям вне списка · ${v2Metrics.eventAbstains} event-оценок abstain сохранено без review. Всего ${v2Metrics.reviewStories}/45 историй с задачей проверки. *Группа «условно значимых» категорий не утверждена и служит только исследовательским индикатором.`));
    card.append(node("div", "policy-v2-caveat", "Важно: Legacy F1=0.840 в старом отчёте считается по всем сырым оценкам 45 ответов. Эта таблица считает фактическую передачу дальше: Legacy блокирует review-новости, а v2 считает удержанные категории как не переданные автоматически. Это не сравнение качества самой модели."));
    return card;
  }

  function v2MetricsCandidateCount(metrics) {
    return liveCaseRows().reduce((count, row) => count + decisionV2(row).predictions.size, 0);
  }

  function summaryMetric(label, value, sub) {
    const card = node("div", "metric");
    append(card, node("div", "metric-label", label), node("div", "metric-value", value), node("div", "metric-sub", sub));
    return card;
  }

  function chartCard(title, description, body) {
    const card = node("section", "chart-card");
    append(card, node("div", "chart-title", title), node("div", "chart-desc", description), body);
    return card;
  }

  function chartRows(values, onClick = null, formatter = (value) => String(value)) {
    const body = node("div", "chart-body");
    if (!values.length) { body.append(node("div", "chart-empty", "Нет данных для отображения.")); return body; }
    const max = Math.max(1, ...values.map((row) => row.value));
    for (const row of values) {
      const button = node(onClick ? "button" : "div", `chart-row${onClick ? " clickable" : ""}`);
      if (onClick) { button.type = "button"; button.addEventListener("click", () => onClick(row)); }
      append(button, node("span", "bar-label", row.label));
      const bar = node("div", "chart-bar");
      const fill = node("i");
      fill.style.width = `${Math.max(2, row.value / max * 100)}%`;
      if (row.kind === "fp") fill.style.background = "var(--red)";
      if (row.kind === "fn") fill.style.background = "var(--amber)";
      bar.append(fill);
      append(button, bar, node("span", "chart-num", formatter(row.value)));
      body.append(button);
    }
    return body;
  }

  function topicDistribution() {
    const counts = new Map(DATA.taxonomy.topics.map((topic) => [topic.code, 0]));
    for (const row of liveCaseRows()) counts.set(row.result.topic, (counts.get(row.result.topic) ?? 0) + 1);
    const values = [...counts].filter(([, count]) => count > 0).map(([code, value]) => ({ code, value, label: topicLabel(code) })).sort((a, b) => b.value - a.value);
    return chartRows(values, (row) => { filters.topic = row.code; $("filterTopic").value = row.code; activeTab = "lab"; switchToLab(); renderAll(); });
  }

  function eventDistribution() {
    const counts = new Map(DATA.taxonomy.events.map((event) => [event.code, 0]));
    for (const row of liveCaseRows()) for (const code of decision(row).predictions) counts.set(code, counts.get(code) + 1);
    const values = [...counts].filter(([, count]) => count > 0).map(([code, value]) => ({ code, value, label: eventLabel(code) })).sort((a, b) => b.value - a.value);
    return chartRows(values, (row) => { filters.event = row.code; $("filterEvent").value = row.code; activeTab = "lab"; switchToLab(); renderAll(); });
  }

  function eventErrors() {
    const counts = new Map(DATA.taxonomy.events.map((event) => [event.code, { fp: 0, fn: 0 }]));
    for (const row of liveCaseRows()) {
      const error = rowError(row);
      for (const code of error.fp) counts.get(code).fp += 1;
      for (const code of error.fn) counts.get(code).fn += 1;
    }
    const values = [...counts].map(([code, data]) => ({ code, value: data.fp + data.fn, label: eventLabel(code), fp: data.fp, fn: data.fn })).filter((row) => row.value).sort((a, b) => b.value - a.value).slice(0, 10);
    const body = node("div", "chart-body");
    if (!values.length) return append(body, node("div", "chart-empty", "Расхождений нет при текущих параметрах."));
    const max = Math.max(1, ...values.map((row) => row.value));
    for (const row of values) {
      const line = node("button", "chart-row clickable");
      line.type = "button";
      line.addEventListener("click", () => { filters.event = row.code; $("filterEvent").value = row.code; activeTab = "lab"; switchToLab(); renderAll(); });
      append(line, node("span", "bar-label", row.label));
      const bar = node("div", "chart-bar");
      const fp = node("i"); fp.style.width = `${row.value / max * 100}%`;
      const fpPart = row.value ? row.fp / row.value * 100 : 0;
      fp.style.background = `linear-gradient(90deg, var(--red) ${fpPart}%, var(--amber) ${fpPart}%)`;
      bar.append(fp);
      append(line, bar, node("span", "chart-num", `${row.fp}/${row.fn}`));
      body.append(line);
    }
    body.append(node("div", "editor-note", "В конце каждой строки: FP / FN. Нажмите, чтобы отфильтровать новости по событию."));
    return body;
  }

  function triggerDistribution() {
    if (activePolicyMode === "policy_v2") {
      const rows = [
        { key: "evidenceReview", label: "Кандидаты удержаны: мало доказательств" },
        { key: "unlistedReview", label: "Отдельная задача: событие вне списка" },
      ];
      const values = rows.map(({ key, label }) => ({
        key,
        label,
        value: liveCaseRows().filter((row) => decisionV2(row)[key]).length,
      }));
      return chartRows(values, () => {
        filters.state = "review";
        $("filterState").value = "review";
        activeTab = "lab";
        switchToLab();
        renderAll();
      });
    }
    const names = [
      ["choice", "Низкая уверенность Choice"], ["event_scores", "Event score в серой зоне"],
      ["uncertainty", "Недостаточно доказательств"], ["unlisted", "Событие вне списка"],
    ];
    const values = names.map(([key, label]) => ({ key, label, value: liveCaseRows().filter((row) => decision(row).active[key]).length }));
    return chartRows(values, (row) => { filters.state = "review"; $("filterState").value = "review"; activeTab = "lab"; switchToLab(); renderAll(); });
  }

  function metricsForGates(gates) { return metricSet(DATA.cases, gates); }

  function scatterCard() {
    const gatesRows = PRESETS.map((preset) => ({ preset, metrics: metricsForGates(preset.gates) }));
    const card = node("section", "chart-card");
    append(card, node("div", "chart-title", "Coverage vs Error Rate"), node("div", "chart-desc", "Доля принятых ответов и ошибки среди них. Точки сравнивают диагностические политики."));
    const wrap = node("div", "scatter-wrap");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 480 250");
    svg.setAttribute("class", "scatter");
    const x0 = 50, x1 = 452, y0 = 206, y1 = 25;
    const line = (x1v, y1v, x2v, y2v, className) => { const item = document.createElementNS("http://www.w3.org/2000/svg", "line"); item.setAttribute("x1", x1v); item.setAttribute("y1", y1v); item.setAttribute("x2", x2v); item.setAttribute("y2", y2v); item.setAttribute("class", className); return item; };
    for (const tick of [0, 25, 50, 75, 100]) {
      const x = x0 + (x1 - x0) * tick / 100;
      svg.append(line(x, y1, x, y0, "grid-line"));
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text"); label.setAttribute("x", x); label.setAttribute("y", y0 + 18); label.setAttribute("text-anchor", "middle"); label.textContent = `${tick}%`; svg.append(label);
      const y = y0 - (y0 - y1) * tick / 100;
      svg.append(line(x0, y, x1, y, "grid-line"));
    }
    svg.append(line(x0, y1, x0, y0, "axis"), line(x0, y0, x1, y0, "axis"));
    const ylabel = document.createElementNS("http://www.w3.org/2000/svg", "text"); ylabel.setAttribute("x", 12); ylabel.setAttribute("y", 110); ylabel.setAttribute("transform", "rotate(-90 12 110)"); ylabel.setAttribute("text-anchor", "middle"); ylabel.textContent = "Ошибки среди авто"; svg.append(ylabel);
    gatesRows.forEach(({ preset, metrics }, index) => {
      const coverage = (metrics.coverage ?? 0) * 100;
      const risk = (metrics.autoErrorRate ?? 0) * 100;
      const cx = x0 + (x1 - x0) * coverage / 100;
      const cy = y0 - (y0 - y1) * risk / 100;
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", cx); circle.setAttribute("cy", cy); circle.setAttribute("r", "6"); circle.setAttribute("fill", index === 0 ? "#ff3347" : ["#f1bd64", "#8aafff", "#55d69e", "#c19aff"][index - 1]);
      circle.setAttribute("tabindex", "0"); circle.setAttribute("role", "button"); circle.setAttribute("aria-label", `${preset.label}: покрытие ${pct(metrics.coverage)}, ошибки ${pct(metrics.autoErrorRate)}`);
      circle.addEventListener("click", () => selectPreset(preset.id));
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title"); title.textContent = `${preset.label} · coverage ${pct(metrics.coverage)} · error ${pct(metrics.autoErrorRate)}`; circle.append(title);
      svg.append(circle);
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text"); label.setAttribute("x", cx + 8); label.setAttribute("y", cy - 6); label.textContent = String.fromCharCode(65 + index); svg.append(label);
    });
    wrap.append(svg);
    const legend = node("div", "scatter-legend");
    append(legend, node("span", "", "X — доля без review"), node("span", "", "Y — ошибка среди принятых"), node("span", "", "Нажмите на точку, чтобы выбрать режим."));
    append(wrap, legend);
    card.append(wrap);
    return card;
  }

  function policyTableCard() {
    const card = node("section", "chart-card");
    append(card, node("div", "chart-title", "Сравнение политик"), node("div", "chart-desc", "Одинаковые пороги, меняется набор включённых сигналов. Ни один вариант не объявлен production-ready."));
    const wrap = node("div", "chart-body policy-table-wrap");
    const table = node("table", "policy-table");
    const thead = node("thead");
    const tr = node("tr");
    for (const label of ["Режим", "Авто", "Coverage", "Тема точна", "Event F1", "Exact set", "Ошибки авто"]) tr.append(node("th", "", label));
    thead.append(tr); table.append(thead);
    const tbody = node("tbody");
    for (const preset of PRESETS) {
      const metrics = metricsForGates(preset.gates);
      const line = node("tr", `policy-row${settings.preset === preset.id ? " selected" : ""}`);
      line.tabIndex = 0;
      line.addEventListener("click", () => selectPreset(preset.id));
      const name = node("td", "", preset.label);
      append(line, name, node("td", "", `${metrics.accepted}/${metrics.total}`), node("td", "", pct(metrics.coverage)), node("td", "", pct(metrics.acceptedTopicAccuracy)), node("td", "", pct(metrics.acceptedEventF1)), node("td", "", pct(metrics.acceptedExactEventSetAccuracy)), node("td", "", `${metrics.acceptedError}/${metrics.accepted}`));
      tbody.append(line);
    }
    table.append(tbody); wrap.append(table);
    card.append(wrap);
    return card;
  }

  function selectPreset(id) {
    const button = document.querySelector(`.preset[data-preset="${id}"]`);
    if (button) button.click();
  }

  function switchToLab() {
    activeTab = "lab";
    $("labTab").setAttribute("aria-selected", "true");
    $("statsTab").setAttribute("aria-selected", "false");
    $("labScreen").hidden = false;
    $("statsScreen").hidden = true;
    $("statsScreen").classList.remove("active");
  }

  function renderAll() {
    syncSliders();
    renderTop();
    renderCaseList();
    renderDetail();
    renderComparison();
    if (activeTab === "stats") renderStats();
  }

  bindFilters();
  bindNavigation();
  bindPolicy();
  renderAll();
})();
