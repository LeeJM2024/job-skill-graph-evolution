const state = {
  domain: "company",
  currentPipeline: null,
  currentReviewItem: null,
  reviewItems: [],
  backups: [],
  overview: null,
  dataSources: [],
  currentSourceKey: "base",
  analytics: {
    jobs: [],
    months: [],
    migrationSkills: [],
    profileCompare: null,
    profileChangeTab: "added",
    loaded: false,
  },
  optimization: {
    jobs: [],
    skills: [],
    originalSkills: [],
    changes: [],
    pendingNormalized: null,
    editingSkill: "",
    currentJob: "",
    summary: {},
    loaded: false,
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, options = {}) {
  const separator = path.includes("?") ? "&" : "?";
  const response = await fetch(`${path}${separator}domain=${encodeURIComponent(state.domain)}`, {
    headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  return response.json();
}

function selectedSource() {
  return state.dataSources.find((source) => source.key === state.currentSourceKey) || state.dataSources[0] || null;
}

function sourceQueryParams(extra = {}) {
  const params = new URLSearchParams(extra);
  if (state.currentSourceKey) params.set("source_key", state.currentSourceKey);
  return params;
}

function sourceText(source = selectedSource()) {
  if (!source) return "当前未选择数据源";
  const rows = source.row_count ? ` · ${source.row_count} 条 JD` : "";
  return `${source.label}${rows}`;
}

function renderSourceIndicators() {
  const source = selectedSource();
  const text = sourceText(source);
  const path = source?.event_stream_path || "";
  const note = source?.note || "";
  $("#global-source-path").textContent = path ? `${text} ｜ ${path}` : text;
  $$("[data-source-indicator]").forEach((node) => {
    node.innerHTML = `
      <div>
        <strong>当前查看文件</strong>
        <span>${escapeHtml(path ? `${text} ｜ ${path}` : text)}</span>
      </div>
      ${note ? `<span>${escapeHtml(note)}</span>` : ""}
    `;
  });
}

function setLoading(isLoading) {
  $("#pipeline-loading").classList.toggle("hidden", !isLoading);
}

function metric(label, value, tone = "") {
  return `<div class="metric ${tone}"><span>${label}</span><strong>${value ?? "无"}</strong></div>`;
}

function percent(value) {
  if (value === undefined || value === null || value === "") return "无";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function signedPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0.00%";
  const sign = number > 0 ? "+" : "";
  return `${sign}${(number * 100).toFixed(2)}%`;
}

function numberText(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0";
  return number.toFixed(digits);
}

function changeTone(changeType) {
  if (changeType === "新增技能" || changeType === "频率上升技能") return "ok";
  if (changeType === "消失技能" || changeType === "频率下降技能") return "danger";
  return "warn";
}

function changeLabel(key) {
  return {
    added: "新增能力",
    removed: "删除能力",
    increased: "频率上升",
    decreased: "频率下降",
    modified: "修改能力",
    stable_core: "稳定核心",
  }[key] || key;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function switchView(viewName) {
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === viewName));
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${viewName}`));
  if (viewName === "analytics" && !state.analytics.loaded) {
    refreshAnalytics().catch((error) => {
      $("#trend-summary").textContent = error.message;
    });
  }
  if (viewName === "optimization" && !state.optimization.loaded) {
    refreshOptimizationProfile()
      .catch((error) => {
        $("#optimization-draft").textContent = error.message;
      });
  }
}

function renderMetrics(payload) {
  const report = payload?.report || {};
  $("#metrics").innerHTML = [
    metric("是否通过", report.passed === true ? "通过" : report.passed === false ? "未通过" : "无结果"),
    metric("岗位需求正确率", percent(report.job_demand_match_rate)),
    metric("技能频率正确率", percent(report.skill_frequency_match_rate)),
    metric("通过阈值", report.pass_threshold ?? "0.9"),
    metric("岗位差异行", report.job_demand_mismatch_count ?? "无"),
    metric("技能差异行", report.skill_frequency_mismatch_count ?? "无"),
    metric("岗位行数", `${report.job_demand_actual_rows ?? "?"} / ${report.job_demand_expected_rows ?? "?"}`),
    metric("技能行数", `${report.skill_frequency_actual_rows ?? "?"} / ${report.skill_frequency_expected_rows ?? "?"}`),
  ].join("");
}

function renderBarChart(selector, rows) {
  const max = Math.max(...(rows || []).map((row) => Number(row.value) || 0), 1);
  $(selector).innerHTML = (rows || [])
    .map((row) => {
      const value = Number(row.value) || 0;
      const width = Math.max(3, (value / max) * 100);
      return `
        <div class="bar-row">
          <span title="${row.label}">${row.label}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
          <strong>${Math.round(value)}</strong>
        </div>
      `;
    })
    .join("") || `<p class="muted">暂无图表数据。</p>`;
}

function renderTrend(rows) {
  const max = Math.max(...(rows || []).map((row) => Number(row.value) || 0), 1);
  $("#trend-chart").innerHTML = (rows || [])
    .map((row) => {
      const value = Number(row.value) || 0;
      const height = Math.max(4, (value / max) * 150);
      return `
        <div class="trend-col" title="${row.label}: ${Math.round(value)}">
          <div class="trend-bar" style="height:${height}px"></div>
          <span>${String(row.label).slice(5)}</span>
        </div>
      `;
    })
    .join("") || `<p class="muted">暂无月份趋势。</p>`;
}

function renderDiffTables(payload) {
  const diffs = payload?.diff_preview || {};
  $("#diff-tables").innerHTML = Object.entries(diffs)
    .map(([name, table]) => {
      const columns = table.columns || [];
      const rows = table.rows || [];
      return `
        <div>
          <h3>${name === "job_demand" ? "岗位需求差异" : "技能频率差异"} <span class="muted">${table.row_count ?? 0} 行</span></h3>
          <div class="table-wrap">
            <table>
              <thead><tr>${columns.map((col) => `<th>${col}</th>`).join("")}</tr></thead>
              <tbody>
                ${rows.map((row) => `<tr>${columns.map((col) => `<td>${row[col] ?? ""}</td>`).join("")}</tr>`).join("")}
              </tbody>
            </table>
          </div>
        </div>
      `;
    })
    .join("") || `<p class="muted">暂无差异文件。</p>`;
}

function renderPipeline(payload) {
  state.currentPipeline = payload;
  renderMetrics(payload);
  renderBarChart("#category-chart", payload?.charts?.category_distribution || []);
  renderBarChart("#skill-chart", payload?.charts?.top_skills || []);
  renderTrend(payload?.charts?.monthly_trend || []);
  renderDiffTables(payload);
  $("#report-path").textContent = payload?.paths?.comparison_report || "";
  const completed = payload?.completed;
  $("#pipeline-log").textContent = completed
    ? [`returncode: ${completed.returncode}`, completed.stdout || "", completed.stderr || ""].join("\n")
    : "已读取历史结果。";
}

function renderOverview() {
  const overview = state.overview || {};
  const pendingCount = state.reviewItems.length;
  const backupCount = state.backups.length;
  $("#overview-metrics").innerHTML = [
    metric("最新月份", overview.latest_month || "无"),
    metric("标准岗位数", overview.job_count ?? 0),
    metric("技能数", overview.skill_count ?? 0),
    metric("待审核", pendingCount),
    metric("本月新增技能", overview.latest_new_skill_count ?? 0),
    metric("本月下降技能", overview.latest_declining_skill_count ?? 0),
    metric("迁移技能数", overview.migration_skill_count ?? 0),
    metric("备份记录", backupCount),
  ].join("");
  $("#overview-review-list").innerHTML = state.reviewItems.slice(0, 5)
    .map((item) => {
      const route = item.result?.route || {};
      return `
        <article class="review-item">
          <div>
            <h3>${escapeHtml(item.input.job_title)}</h3>
            <p>${escapeHtml(item.input.month)} · ${escapeHtml(route.best_job?.name || "未命中")}</p>
            <div class="tag-row">${statusTag(route.status)}<span class="tag">技能：${item.result?.skills?.length || 0}</span></div>
          </div>
          <button class="secondary-btn" data-review="${item.item_id}">审核</button>
        </article>
      `;
    })
    .join("") || `<p class="muted">暂无待审核记录。</p>`;
  $$("[data-review]").forEach((button) => {
    button.addEventListener("click", () => openReviewDialog(button.dataset.review));
  });
}

function statusTag(status) {
  if (status === "existing_job") return `<span class="tag ok">已有岗位</span>`;
  if (status === "new_family") return `<span class="tag danger">疑似新族</span>`;
  return `<span class="tag warn">疑似新岗位</span>`;
}

function renderReviewItems(items) {
  const activeItems = (items || []).filter((item) => item.status === "pending");
  state.reviewItems = activeItems;
  $("#review-list").innerHTML = activeItems
    .map((item) => {
      if (item.review_type === "skill") {
        const skill = item.result?.skill || {};
        return `<article class="review-item"><div><h3>技能待审核：${escapeHtml(skill.normalized_skill || skill.raw_skill || "")}</h3><p>${escapeHtml(item.input?.job_title || "")} / ${escapeHtml(skill.kg_display_skill || "未归类")}</p><div class="tag-row"><span class="tag warn">技能待审核</span>${skill.is_new_skill_candidate ? '<span class="tag">新技能候选</span>' : ""}${skill.is_low_confidence ? '<span class="tag">低置信度</span>' : ""}</div></div><button class="secondary-btn" data-review="${item.item_id}">审核</button></article>`;
      }
      if (item.review_type === "dictionary_maintenance") {
        const proposal = item.result?.proposal || {};
        return `<article class="review-item"><div><h3>词典维护待审核</h3><p>${escapeHtml(proposal.standard_job_title || proposal.normalized_skill || "待补充")}</p><div class="tag-row"><span class="tag warn">词典维护</span></div></div><button class="secondary-btn" data-review="${item.item_id}">查看</button></article>`;
      }
      const route = item.result?.route || {};
      const bestCategory = route.best_category?.name || "未命中";
      const bestJob = route.best_job?.name || "未命中";
      const skills = item.result?.skills || [];
      return `
        <article class="review-item">
          <div>
            <h3>${item.input.job_title}</h3>
            <p>${item.input.month} · ${bestCategory} / ${bestJob}</p>
            <div class="tag-row">
              ${statusTag(route.status)}
              <span class="tag">状态：${item.status}</span>
              <span class="tag">技能：${skills.length}</span>
            </div>
          </div>
          <button class="secondary-btn" data-review="${item.item_id}">审核</button>
        </article>
      `;
    })
    .join("") || `<p class="muted">暂无待审核记录。</p>`;
  $$("[data-review]").forEach((button) => {
    button.addEventListener("click", () => openReviewDialog(button.dataset.review));
  });
  renderOverview();
}

function skillsHtml(skills) {
  return `
    <div class="tag-row">
      ${(skills || []).map((skill) => `<span class="tag">${skill.normalized_skill}${skill.kg_display_skill ? ` · ${skill.kg_display_skill}` : ""}</span>`).join("") || `<span class="muted">暂无技能结果。</span>`}
    </div>
  `;
}

function topCandidatesHtml(route) {
  const categories = route?.top_categories || route?.selected_categories || [];
  const jobs = route?.top_jobs || route?.selected_jobs || [];
  const row = (candidate) => `
    <li><strong>${escapeHtml(candidate.name)}</strong>
      <span>${Number(candidate.score || 0).toFixed(3)}</span>
      <small>${escapeHtml(candidate.metadata?.match_keywords || candidate.metadata?.aggregation_method || "")}</small>
    </li>`;
  const adjudication = route?.adjudication || {};
  return `
    <div class="candidate-grid">
      <div><h5>岗位大族 Top-K</h5><ol class="candidate-list">${categories.map(row).join("") || "<li>无候选</li>"}</ol></div>
      <div><h5>标准岗位 Top-K</h5><ol class="candidate-list">${jobs.map(row).join("") || "<li>无候选</li>"}</ol></div>
    </div>
    ${adjudication.route_status ? `<p class="muted">LLM 建议：${escapeHtml(adjudication.route_status)} / ${escapeHtml(adjudication.selected_standard_job || "未选择")}，置信度 ${Number(adjudication.confidence || 0).toFixed(2)}。${escapeHtml(adjudication.reason || "")}</p>` : ""}`;
}

function reviewedSkillsPayload(skills) {
  const reviewed = (skills || []).map((skill, index) => {
    const normalized = document.querySelector(`[data-skill-normalized="${index}"]`);
    const family = document.querySelector(`[data-skill-family="${index}"]`);
    const invalid = document.querySelector(`[data-skill-invalid="${index}"]`);
    return {
      ...skill,
      normalized_skill: normalized ? normalized.value : skill.normalized_skill,
      kg_display_skill: family ? family.value : skill.kg_display_skill,
      decision: invalid?.checked ? "invalid" : "confirmed",
    };
  });
  $$('[data-manual-skill]').forEach((input) => {
    const index = input.dataset.manualSkill;
    const normalized_skill = input.value.trim();
    const family = document.querySelector(`[data-manual-skill-family="${index}"]`)?.value.trim() || "";
    if (normalized_skill) {
      reviewed.push({
        raw_skill: normalized_skill,
        normalized_skill,
        kg_display_skill: family,
        skill_type: "manual",
        confidence: 1,
        normalization_method: "manual_input",
        decision: "confirmed",
      });
    }
  });
  return reviewed;
}

function appendManualReviewSkillRow() {
  const container = $("#manual-review-skills");
  if (!container) return;
  const index = container.children.length;
  container.insertAdjacentHTML("beforeend", `
    <div class="manual-skill-row">
      <input data-manual-skill="${index}" placeholder="手动输入规范技能名" />
      <input data-manual-skill-family="${index}" placeholder="技能大类" />
      <button class="ghost-btn" type="button" data-remove-manual-skill="${index}">删除</button>
    </div>
  `);
  container.querySelector(`[data-remove-manual-skill="${index}"]`).addEventListener("click", (event) => {
    event.currentTarget.parentElement.remove();
  });
}

function openReviewDialog(itemId) {
  const item = state.reviewItems.find((entry) => entry.item_id === itemId);
  if (!item) return;
  if (item.review_type === "skill") {
    openSkillReviewDialog(item);
    return;
  }
  if (item.review_type === "dictionary_maintenance") {
    $("#dialog-title").textContent = "词典维护待审核";
    $("#dialog-content").innerHTML = `<pre class="log-box">${escapeHtml(JSON.stringify(item.result || {}, null, 2))}</pre>`;
    $("#review-dialog").showModal();
    return;
  }
  if (item.review_type === "job") {
    switchView("manual");
    renderJobResult(item);
    return;
  }
  const route = item.result?.route || {};
  const isExisting = route.status === "existing_job";
  $("#dialog-title").textContent = isExisting ? "确认已有岗位" : "人工确认新岗位";
  $("#dialog-content").innerHTML = `
    <div class="panel">
      <h3>${item.input.job_title}</h3>
      <p>${item.input.month}</p>
      <p>${item.input.responsibility || "未填写职责"}</p>
      <p>${item.input.requirement || "未填写要求"}</p>
      <div class="tag-row">
        ${statusTag(route.status)}
        <span class="tag">族：${route.best_category?.name || "未命中"}</span>
        <span class="tag">岗位：${route.best_job?.name || "未命中"}</span>
        <span class="tag">原因：${route.reason || ""}</span>
      </div>
      ${skillsHtml(item.result?.skills || [])}
    </div>
    ${
      isExisting
        ? `
          <div class="dialog-actions">
            <button class="ghost-btn" id="reject-item" type="button">不更新</button>
            <button class="primary-btn" id="merge-existing" type="button">确认并入基础数据库</button>
          </div>
        `
        : `
          <div class="new-job-grid">
            <label>岗位族<input id="new-category" value="${route.best_category?.name || ""}" placeholder="例如：AI应用" /></label>
            <label>标准岗位<input id="new-title" value="${item.input.job_title}" /></label>
            <label class="wide">匹配关键词<input id="new-keywords" placeholder="不填则使用标准岗位名" /></label>
          </div>
          <div class="dialog-actions">
            <button class="ghost-btn" id="reject-item" type="button">不更新</button>
            <button class="primary-btn" id="merge-new" type="button">确认新岗位并入库</button>
          </div>
        `
    }
  `;
  $("#reject-item").addEventListener("click", async () => {
    await api(`/api/review/${itemId}/reject-update`, { method: "POST" });
    await refreshReview();
    $("#review-dialog").close();
  });
  const mergeExisting = $("#merge-existing");
  if (mergeExisting) {
    mergeExisting.addEventListener("click", async () => {
      const mergedItem = await api(`/api/review/${itemId}/confirm-existing`, {
        method: "POST",
        body: JSON.stringify({ merge_database: true }),
      });
      await Promise.all([refreshReview(), refreshBackups(), refreshAnalyticsOptions()]);
      state.analytics.loaded = false;
      if (state.currentReviewItem?.item_id === itemId) {
        renderMergedJobResult(item, mergedItem);
      }
      $("#review-dialog").close();
    });
  }
  const mergeNew = $("#merge-new");
  if (mergeNew) {
    mergeNew.addEventListener("click", async () => {
      const mergedItem = await api(`/api/review/${itemId}/confirm-new-job`, {
        method: "POST",
        body: JSON.stringify({
          standard_category: $("#new-category").value,
          standard_job_title: $("#new-title").value,
          match_keywords: $("#new-keywords").value,
          merge_database: true,
        }),
      });
      await Promise.all([refreshReview(), refreshBackups(), refreshAnalyticsOptions()]);
      state.analytics.loaded = false;
      if (state.currentReviewItem?.item_id === itemId) {
        renderMergedJobResult(item, mergedItem);
      }
      $("#review-dialog").close();
    });
  }
  $("#review-dialog").showModal();
}

function openSkillReviewDialog(item) {
  const skill = item.result?.skill || {};
  $("#dialog-title").textContent = "技能人工审核";
  $("#dialog-content").innerHTML = `
    <div class="new-job-grid">
      <label>原始技能<input value="${escapeHtml(skill.raw_skill || "")}" disabled /></label>
      <label>归一化技能<input id="review-skill-name" value="${escapeHtml(skill.normalized_skill || "")}" /></label>
      <label>技能大类<input id="review-skill-family" value="${escapeHtml(skill.kg_display_skill || "")}" /></label>
    </div>
    <div class="dialog-actions">
      <button class="secondary-btn" id="review-skill-confirm" type="button">确认</button>
      <button class="secondary-btn" id="review-skill-map" type="button">映射为已有技能</button>
      <button class="secondary-btn" id="review-skill-new" type="button">提交新技能词典建议</button>
      <button class="ghost-btn" id="review-skill-invalid" type="button">标记无效</button>
    </div>`;
  const submit = async (decision) => {
    await api(`/api/review/${item.item_id}/review-skill`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        normalized_skill: $("#review-skill-name").value,
        kg_display_skill: $("#review-skill-family").value,
      }),
    });
    await refreshReview();
    $("#review-dialog").close();
  };
  $("#review-skill-confirm").addEventListener("click", () => submit("confirmed"));
  $("#review-skill-map").addEventListener("click", () => submit("mapped"));
  $("#review-skill-new").addEventListener("click", () => submit("new_skill"));
  $("#review-skill-invalid").addEventListener("click", () => submit("invalid"));
  $("#review-dialog").showModal();
}

function renderBackups(rows) {
  state.backups = rows;
  $("#backup-list").innerHTML = rows
    .map((row) => `
      <article class="backup-item">
        <div>
          <h3>${row.backup_id}</h3>
          <p>${row.reason || "无说明"}</p>
          <p class="muted">${row.backup_dir}</p>
        </div>
        <span class="tag">${row.file_count} 个文件</span>
      </article>
    `)
    .join("") || `<p class="muted">暂无备份。</p>`;
}

function renderAnalyticsMetrics(payload) {
  $("#analytics-metrics").innerHTML = [
    metric("最新月份", payload.latest_month || "无"),
    metric("标准岗位数", payload.job_count ?? 0),
    metric("技能数", payload.skill_count ?? 0),
    metric("生命周期记录", payload.lifecycle_rows ?? 0),
    metric("迁移技能数", payload.migration_skill_count ?? 0),
    metric("频率记录", payload.frequency_rows ?? 0),
    metric("本月新增技能", payload.latest_new_skill_count ?? 0),
    metric("本月下降技能", payload.latest_declining_skill_count ?? 0),
  ].join("");
}

function renderLineChart(payload) {
  const months = payload.months || [];
  const series = payload.series || [];
  $("#trend-summary").textContent = `${payload.standard_job || ""} · ${months.length} 个月 · ${series.length} 个技能`;
  if (!months.length || !series.length) {
    $("#skill-line-chart").innerHTML = `<p class="muted">暂无趋势数据。</p>`;
    $("#skill-line-legend").innerHTML = "";
    return;
  }

  const width = 980;
  const height = 320;
  const padding = { top: 24, right: 24, bottom: 42, left: 48 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const colors = ["#176b5d", "#245c9f", "#a85f00", "#7c3aed", "#b42357", "#0f766e", "#4f46e5", "#b45309"];
  const x = (index) => padding.left + (months.length === 1 ? plotWidth / 2 : (index / (months.length - 1)) * plotWidth);
  const y = (value) => padding.top + plotHeight - Math.max(0, Math.min(1, Number(value) || 0)) * plotHeight;
  const grid = [0, 0.25, 0.5, 0.75, 1].map(
    (value) => `
      <line x1="${padding.left}" y1="${y(value)}" x2="${width - padding.right}" y2="${y(value)}" class="chart-grid-line" />
      <text x="10" y="${y(value) + 4}" class="chart-axis">${Math.round(value * 100)}%</text>
    `,
  ).join("");
  const lines = series.map((item, index) => {
    const points = item.points.map((point, pointIndex) => `${x(pointIndex)},${y(point.frequency)}`).join(" ");
    const color = colors[index % colors.length];
    const dots = item.points.map((point, pointIndex) => `
      <circle cx="${x(pointIndex)}" cy="${y(point.frequency)}" r="3" fill="${color}">
        <title>${item.skill} / ${point.month}: ${(Number(point.frequency) * 100).toFixed(2)}%</title>
      </circle>
    `).join("");
    return `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="2.5" />${dots}`;
  }).join("");
  const labels = months.map((month, index) => {
    if (months.length > 10 && index % 2 === 1) return "";
    return `<text x="${x(index)}" y="${height - 12}" class="chart-axis" text-anchor="middle">${month.slice(5)}</text>`;
  }).join("");

  $("#skill-line-chart").innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="岗位技能频率折线图">
      ${grid}
      <line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}" class="chart-axis-line" />
      <line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" class="chart-axis-line" />
      ${lines}
      ${labels}
    </svg>
  `;
  $("#skill-line-legend").innerHTML = series.map((item, index) => `
    <span><i style="background:${colors[index % colors.length]}"></i>${item.skill}</span>
  `).join("");
}

function renderLifecycle(payload) {
  $("#lifecycle-job").textContent = payload.standard_job || "";
  $("#lifecycle-summary").innerHTML = (payload.summary || [])
    .map((row) => `<div class="status-card"><span>${row.status}</span><strong>${row.count}</strong></div>`)
    .join("") || `<p class="muted">暂无生命周期数据。</p>`;
  $("#lifecycle-table").innerHTML = (payload.rows || [])
    .map((row) => `
      <tr>
        <td>${row.skill || ""}<div class="muted">${row.kg_display_skill || ""}</div></td>
        <td><span class="tag ${lifecycleTone(row.lifecycle_status)}">${row.lifecycle_status || ""}</span></td>
        <td>${percent(row.current_monthly_skill_frequency)}</td>
        <td>${row.recent_3m_skill_count ?? 0}</td>
        <td>${row.lifecycle_reason || ""}</td>
      </tr>
    `)
    .join("") || `<tr><td colspan="5">暂无生命周期记录。</td></tr>`;
}

function lifecycleTone(status) {
  if (status === "新兴技能" || status === "活跃技能" || status === "稳定核心技能") return "ok";
  if (status === "衰退技能" || status === "废弃技能") return "danger";
  return "warn";
}

function renderMigration(payload) {
  const skills = payload.skills || [];
  if (!state.analytics.migrationSkills.length) {
    state.analytics.migrationSkills = skills;
    $("#migration-skill").innerHTML = skills.map((skill) => `<option value="${skill}">${skill}</option>`).join("");
  }
  const selected = payload.selected;
  if (!selected) {
    $("#migration-detail").innerHTML = `<p class="muted">暂无迁移数据。</p>`;
    return;
  }
  $("#migration-skill").value = selected.skill;
  const pathText = selected.confirmed_migration_path || selected.migration_path || "";
  const steps = pathText.split(" -> ").filter(Boolean);
  $("#migration-detail").innerHTML = `
    <div class="metric-grid compact-metrics">
      ${metric("首现月份", selected.confirmed_first_seen_month || selected.first_seen_month || "无")}
      ${metric("累计覆盖岗位", selected.confirmed_cumulative_covered_job_count || selected.cumulative_covered_job_count || 0)}
      ${metric("扩散岗位数", selected.confirmed_spread_job_count || selected.spread_job_count || 0)}
      ${metric("总提及次数", selected.total_skill_mentions || 0)}
    </div>
    <p class="muted">${selected.migration_interpretation || ""}</p>
    <div class="path-list">
      ${steps.map((step, index) => `
        <div class="path-step">
          <span>${index + 1}</span>
          <strong>${step}</strong>
        </div>
      `).join("") || `<p class="muted">暂无路径。</p>`}
    </div>
  `;
}

function renderProfileCompare(payload) {
  state.analytics.profileCompare = payload;
  const summary = payload.summary || {};
  $("#profile-compare-summary").textContent = `${payload.standard_job || ""} · ${payload.from_month || ""} 对比 ${payload.to_month || ""}`;
  $("#profile-from-title").textContent = `${payload.from_month || ""} 旧画像`;
  $("#profile-to-title").textContent = `${payload.to_month || ""} 新画像`;
  $("#profile-change-metrics").innerHTML = [
    metric("新增能力", summary.added ?? 0, "ok"),
    metric("删除能力", summary.removed ?? 0, "danger"),
    metric("修改能力", summary.modified ?? 0, "warn"),
    metric("稳定核心", summary.stable_core ?? 0),
  ].join("");
  renderProfileList("#profile-from-list", payload.from_profile || []);
  renderProfileList("#profile-to-list", payload.to_profile || []);
  renderProfileFlow(summary);
  renderProfileChangeTable(state.analytics.profileChangeTab);
}

function renderProfileList(selector, rows) {
  $(selector).innerHTML = rows.slice(0, 18)
    .map((row) => {
      const frequency = Math.max(0, Math.min(1, Number(row.monthly_skill_frequency) || 0));
      return `
        <div class="profile-skill">
          <div>
            <strong>${escapeHtml(row.skill)}</strong>
            <span>${escapeHtml(row.kg_display_skill || row.snapshot_skill_status || "")}</span>
          </div>
          <em>${percent(row.monthly_skill_frequency)}</em>
          <i style="width:${Math.max(4, frequency * 100)}%"></i>
        </div>
      `;
    })
    .join("") || `<p class="muted">暂无岗位画像。</p>`;
}

function renderProfileFlow(summary) {
  const items = [
    ["added", summary.added ?? 0],
    ["removed", summary.removed ?? 0],
    ["increased", summary.increased ?? 0],
    ["decreased", summary.decreased ?? 0],
    ["stable_core", summary.stable_core ?? 0],
  ];
  const max = Math.max(...items.map(([, value]) => Number(value) || 0), 1);
  $("#profile-change-flow").innerHTML = items.map(([key, value]) => `
    <div class="change-flow-item ${key}">
      <span>${changeLabel(key)}</span>
      <strong>${value}</strong>
      <i style="width:${Math.max(6, (Number(value) || 0) / max * 100)}%"></i>
    </div>
  `).join("");
}

function profileRowsForTab(tab) {
  const changes = state.analytics.profileCompare?.changes || {};
  if (tab === "modified") {
    return [...(changes.increased || []), ...(changes.decreased || [])];
  }
  return changes[tab] || [];
}

function renderProfileChangeTable(tab) {
  state.analytics.profileChangeTab = tab;
  $$(".profile-tab").forEach((button) => button.classList.toggle("active", button.dataset.profileChange === tab));
  const rows = profileRowsForTab(tab).slice(0, 120);
  $("#profile-change-table").innerHTML = rows.map((row) => `
    <tr>
      <td><strong>${escapeHtml(row.skill)}</strong><div class="muted">${escapeHtml(row.kg_display_skill || "")}</div></td>
      <td><span class="tag ${changeTone(row.change_type)}">${escapeHtml(row.change_type || "")}</span></td>
      <td>${percent(row.from_monthly_skill_frequency)}</td>
      <td>${percent(row.to_monthly_skill_frequency)}</td>
      <td>${signedPercent(row.frequency_delta)}</td>
    </tr>
  `).join("") || `<tr><td colspan="5">暂无${changeLabel(tab)}记录。</td></tr>`;
}

function renderOptimizationProfile(payload) {
  state.optimization.jobs = payload.jobs || [];
  state.optimization.skills = (payload.skills || []).map((row) => ({
    ...row,
    manual_status: row.manual_status || "系统识别",
    manual_note: row.manual_note || "",
  }));
  state.optimization.originalSkills = state.optimization.skills.map((row) => ({ ...row }));
  state.optimization.currentJob = payload.standard_job || "";
  state.optimization.summary = payload.summary || {};
  state.optimization.changes = [];
  state.optimization.pendingNormalized = null;
  state.optimization.editingSkill = "";
  state.optimization.loaded = true;

  $("#optimization-job").value = state.optimization.currentJob;
  $("#optimization-job").innerHTML = [`<option value="">请选择标准岗位</option>`, ...state.optimization.jobs
    .map((job) => `<option value="${escapeHtml(job)}">${escapeHtml(job)}</option>`)
  ]
    .join("");
  $("#optimization-job").value = state.optimization.currentJob;
  renderOptimizationSkills();
  renderOptimizationChanges();
  resetOptimizationEdit();
  $("#optimization-normalize-result").textContent = "等待输入技能。";
  $("#optimization-draft").textContent = "暂无变更。";
}

function renderOptimizationSkills() {
  const skills = state.optimization.skills.filter((row) => row.manual_status !== "人工删除");
  const summary = state.optimization.summary || {};
  $("#optimization-summary").innerHTML = [
    metric("标准岗位", escapeHtml(state.optimization.currentJob || "未选择")),
    metric("当前技能数", skills.length),
    metric("来源月份", summary.source_month || "无"),
    metric("人工变更", state.optimization.changes.length),
  ].join("");
  $("#optimization-count").textContent = `${skills.length} 个技能`;
  $("#optimization-profile-note").textContent = state.optimization.currentJob
    ? `当前读取 job_current_profile_system.csv，来源：${summary.source_type || "system"}。`
    : "先输入岗位并点击查看。";
  $("#optimization-skill-table").innerHTML = skills.map((row) => `
    <tr class="${row.manual_status === "人工新增" ? "manual-added-row" : row.manual_status === "人工修改" ? "manual-edited-row" : ""}">
      <td><strong>${escapeHtml(row.skill)}</strong><div class="muted">${escapeHtml(row.manual_note || "")}</div></td>
      <td>${escapeHtml(row.kg_display_skill || "未标注")}</td>
      <td><span class="tag ${row.snapshot_skill_status === "人工新增技能" ? "warn" : "ok"}">${escapeHtml(row.snapshot_skill_status || "系统识别")}</span></td>
      <td>${String(row.is_core_skill) === "1" ? "是" : "否"}</td>
      <td><span class="tag ${row.manual_status === "系统识别" ? "" : "warn"}">${escapeHtml(row.manual_status || "系统识别")}</span></td>
      <td>
        <div class="row-actions">
          <button class="ghost-btn" type="button" data-optimization-edit="${escapeHtml(row.skill)}">修改</button>
          <button class="ghost-btn danger-btn" type="button" data-optimization-delete="${escapeHtml(row.skill)}">删除</button>
        </div>
      </td>
    </tr>
  `).join("") || `<tr><td colspan="6">没有找到该岗位的技能画像。</td></tr>`;

  $$("[data-optimization-edit]").forEach((button) => {
    button.addEventListener("click", () => beginOptimizationEdit(button.dataset.optimizationEdit));
  });
  $$("[data-optimization-delete]").forEach((button) => {
    button.addEventListener("click", () => deleteOptimizationSkill(button.dataset.optimizationDelete));
  });
}

function renderOptimizationChanges() {
  const changes = state.optimization.changes;
  $("#optimization-change-count").textContent = `${changes.length} 条变更`;
  $("#optimization-change-list").innerHTML = changes.map((change, index) => `
    <article class="change-item">
      <span>${index + 1}</span>
      <div>
        <strong>${changeActionText(change.action)}：${escapeHtml(change.skill)}</strong>
        <p>${escapeHtml(change.detail || change.note || "等待写入人工修正表。")}</p>
      </div>
    </article>
  `).join("") || `<p class="muted">暂无人工变更。</p>`;
}

function changeActionText(action) {
  return { add: "新增", delete: "删除", update: "修改" }[action] || action;
}

function resetOptimizationEdit() {
  $("#optimization-edit-skill").value = "";
  $("#optimization-edit-category").value = "";
  $("#optimization-edit-status").value = "稳定核心技能";
  $("#optimization-edit-core").value = "1";
  $("#optimization-edit-note").value = "";
}

function beginOptimizationEdit(skill) {
  const row = state.optimization.skills.find((item) => item.skill === skill);
  if (!row) return;
  state.optimization.editingSkill = skill;
  $("#optimization-edit-skill").value = row.skill || "";
  $("#optimization-edit-category").value = row.kg_display_skill || "";
  $("#optimization-edit-status").value = row.snapshot_skill_status || "观察中";
  $("#optimization-edit-core").value = String(row.is_core_skill) === "1" ? "1" : "0";
  $("#optimization-edit-note").value = row.manual_note || "";
}

function applyOptimizationEdit() {
  const skill = state.optimization.editingSkill;
  if (!skill) {
    $("#optimization-draft").textContent = "请先在技能列表中选择一项技能。";
    return;
  }
  const row = state.optimization.skills.find((item) => item.skill === skill);
  if (!row) return;
  const before = { ...row };
  row.kg_display_skill = $("#optimization-edit-category").value.trim();
  row.snapshot_skill_status = $("#optimization-edit-status").value;
  row.is_core_skill = $("#optimization-edit-core").value;
  row.manual_note = $("#optimization-edit-note").value.trim();
  if (row.manual_status !== "人工新增") {
    row.manual_status = "人工修改";
    row.source_type = "manual_update";
  }
  state.optimization.changes.push({
    action: "update",
    standard_job: state.optimization.currentJob,
    skill,
    before,
    after: { ...row },
    detail: "修改技能类别、状态、核心标记或备注。",
    note: row.manual_note,
  });
  renderOptimizationSkills();
  renderOptimizationChanges();
}

async function normalizeOptimizationSkill() {
  const raw = $("#optimization-new-skill").value.trim();
  if (!raw) {
    $("#optimization-normalize-result").textContent = "请先输入技能名称。";
    return;
  }
  const result = await api(`/api/optimization/normalize-skill?skill=${encodeURIComponent(raw)}`);
  state.optimization.pendingNormalized = result;
  const canConfirm = Boolean(result.normalized_skill && result.kg_display_skill && result.matched);
  const exists = state.optimization.skills.some(
    (row) => row.skill === result.normalized_skill && row.manual_status !== "人工删除",
  );
  $("#optimization-normalize-result").innerHTML = `
    <div class="confirm-title">
      <strong>${escapeHtml(result.normalized_skill || raw)}</strong>
      <span class="tag ${result.matched ? "ok" : "warn"}">${escapeHtml(result.match_source || "用户输入")}</span>
    </div>
    <p>${escapeHtml(result.message || "")}</p>
    <p>类别：${escapeHtml(result.kg_display_skill || "未标注")}</p>
    ${result.normalization_reason ? `<p>依据：${escapeHtml(result.normalization_reason)}</p>` : ""}
    ${
      exists
        ? `<p class="tag warn">该技能已在当前岗位画像中，无需重复添加。</p>`
        : !canConfirm
          ? `<p class="tag danger">暂不能加入：没有可靠的标准技能名和类别。</p>`
        : `<button id="optimization-confirm-add" class="primary-btn" type="button">确认加入岗位画像</button>`
    }
  `;
  $("#optimization-confirm-add")?.addEventListener("click", confirmOptimizationAdd);
}

function confirmOptimizationAdd() {
  const candidate = state.optimization.pendingNormalized;
  if (!candidate?.normalized_skill) return;
  const skill = candidate.normalized_skill;
  const existing = state.optimization.skills.find((row) => row.skill === skill);
  const newRow = {
    standard_job: state.optimization.currentJob,
    skill,
    kg_display_skill: candidate.kg_display_skill || "",
    monthly_jd_count: 0,
    monthly_skill_count: 0,
    monthly_skill_frequency: 0,
    cumulative_jd_count: 0,
    cumulative_skill_count: 0,
    cumulative_skill_frequency: 0,
    snapshot_skill_status: "人工新增技能",
    is_core_skill: 0,
    rank_in_month: "",
    source_month: state.optimization.summary.source_month || "",
    source_type: "manual_add",
    manual_status: "人工新增",
    manual_note: `由“${candidate.input}”归一化后人工加入。`,
  };
  if (existing) {
    Object.assign(existing, newRow);
  } else {
    state.optimization.skills.push(newRow);
  }
  state.optimization.changes.push({
    action: "add",
    standard_job: state.optimization.currentJob,
    skill,
    normalized_from: candidate.input,
    after: newRow,
    detail: `新增技能，初始化统计字段，标记为人工新增技能。`,
  });
  $("#optimization-new-skill").value = "";
  $("#optimization-normalize-result").textContent = "已加入当前页面画像。";
  state.optimization.pendingNormalized = null;
  renderOptimizationSkills();
  renderOptimizationChanges();
}

function deleteOptimizationSkill(skill) {
  const row = state.optimization.skills.find((item) => item.skill === skill);
  if (!row) return;
  if (!window.confirm(`确认从“${state.optimization.currentJob}”中删除“${skill}”？`)) return;
  row.manual_status = "人工删除";
  row.source_type = "manual_delete";
  state.optimization.changes.push({
    action: "delete",
    standard_job: state.optimization.currentJob,
    skill,
    before: { ...row },
    detail: "从当前生效画像中移除该技能；历史快照不被修改。",
  });
  renderOptimizationSkills();
  renderOptimizationChanges();
}

function buildOptimizationDraft() {
  const source = selectedSource();
  return {
    standard_job: state.optimization.currentJob,
    preview_type: "人工优化变更预览",
    selected_source_key: state.currentSourceKey,
    selected_source_label: source?.label || "",
    selected_event_stream_file: source?.event_stream_path || "",
    base_profile_file: "dataset/job_update/company_job_update/data/base/job_current_profile_system.csv",
    target_manual_file: "dataset/job_update/company_job_update/data/base/job_profile_manual_overrides.csv",
    effective_profile_file: "dataset/job_update/company_job_update/data/base/job_current_profile_effective.csv",
    write_policy: "当前仅预览本次页面调整，不直接写入系统画像文件。",
    changes: state.optimization.changes,
    effective_preview: state.optimization.skills.filter((row) => row.manual_status !== "人工删除"),
  };
}

async function refreshOptimizationProfile() {
  const params = new URLSearchParams();
  const job = $("#optimization-job").value.trim();
  if (job) params.set("standard_job", job);
  params.set("limit", "500");
  if (state.currentSourceKey) params.set("source_key", state.currentSourceKey);
  renderOptimizationProfile(await api(`/api/optimization/profile?${params}`));
}

async function openOptimizationForJob(job) {
  switchView("optimization");
  $("#optimization-job").value = job || $("#analytics-job").value || "";
  await refreshOptimizationProfile();
}

function processStepsHtml(item) {
  const route = item?.result?.route || {};
  const skills = item?.result?.skills || [];
  const update = item?.result?.update || {};
  const steps = [
    ["岗位标题清洗", item?.result?.routing_job_title || item?.input?.job_title],
    ["标准岗位匹配", route.best_job?.name || "未命中"],
    ["技能抽取", `${skills.length} 个技能`],
    ["频率更新预览", update.monthly_rows ? `${update.monthly_rows} 行月度频率` : "等待已有岗位确认"],
    ["人工确认", item?.status === "pending" ? "待审核" : item?.status || "待审核"],
  ];
  return `
    <div class="process-steps">
      ${steps.map(([title, detail], index) => `
        <div class="process-step">
          <span>${index + 1}</span>
          <div><strong>${title}</strong><p>${escapeHtml(detail)}</p></div>
        </div>
      `).join("")}
    </div>
  `;
}

function mergeTargetInfo(originalItem, mergedItem) {
  const mergedResult = mergedItem?.result || {};
  const originalResult = originalItem?.result || {};
  const result = Object.keys(mergedResult).length ? mergedResult : originalResult;
  const route = result.route || originalResult.route || {};
  const update = result.update || originalResult.update || {};
  const mergeResult = result.merge_result || {};
  const manualReview = result.manual_review || {};
  const standardJob =
    mergeResult.standard_job ||
    manualReview.standard_job_title ||
    update.standard_job ||
    route.best_job?.name ||
    originalItem?.input?.job_title ||
    "";
  const standardCategory =
    mergeResult.standard_category ||
    manualReview.standard_category ||
    route.best_category?.name ||
    "";
  const month = update.month || originalItem?.input?.month || "";
  return { result, route, update, mergeResult, standardJob, standardCategory, month };
}

function resetJobResultPanel() {
  state.currentReviewItem = null;
  $("#job-form").reset();
  $("#job-result-panel").innerHTML = `
    <div class="empty-result">
      <h3>等待新的 JD</h3>
      <p>可以继续输入下一条 JD，结果会在这里重新展示。</p>
    </div>
  `;
  $("#job-form [name='job_title']")?.focus();
}

function renderMergedJobResult(originalItem, mergedItem) {
  state.currentReviewItem = mergedItem || originalItem;
  const { result, mergeResult, standardJob, standardCategory, month } = mergeTargetInfo(originalItem, mergedItem);
  const skills = result.skills || originalItem?.result?.skills || [];
  const backup = result.backup || {};
  const backupText = backup.backup_id
    ? `备份编号：${backup.backup_id}`
    : "本次确认已完成；如启用备份，备份记录会显示在备份列表中。";

  $("#job-result-panel").innerHTML = `
    <div class="success-strip">已确认入库，基础 CSV 与 SQLite 数据已更新。</div>
    <div class="result-header">
      <div>
        <h3>${escapeHtml(originalItem?.input?.job_title || standardJob)}</h3>
        <p>${escapeHtml(month)} · ${escapeHtml(standardCategory || "未命中族")} / ${escapeHtml(standardJob || "未命中岗位")}</p>
      </div>
      <span class="tag ok">已入库</span>
    </div>

    <div class="result-section">
      <h4>入库结果</h4>
      <div class="metric-grid compact-metrics">
        ${metric("标准岗位", escapeHtml(standardJob || "未命中"))}
        ${metric("岗位族", escapeHtml(standardCategory || "未命中"))}
        ${metric("写入技能", mergeResult.skill_count ?? skills.length)}
        ${metric("事件流行数", mergeResult.event_rows ?? "已更新")}
        ${metric("频率表行数", mergeResult.frequency_rows ?? "已更新")}
        ${metric("技能池行数", mergeResult.skill_pool_rows ?? "已更新")}
      </div>
      <p class="muted">${escapeHtml(backupText)}</p>
    </div>

    <div class="result-section">
      <div class="panel-title-row">
        <h4>已入库技能</h4>
        <span class="muted">${skills.length} 个归一化技能</span>
      </div>
      <div class="tag-row">
        ${skills.map((skill) => `<span class="tag">${escapeHtml(skill.normalized_skill || skill.kg_display_skill || "")}</span>`).join("") || `<span class="muted">暂无技能结果。</span>`}
      </div>
    </div>

    <div class="dialog-actions result-actions">
      <button class="primary-btn" id="merged-open-analytics" type="button">查看该岗位趋势</button>
      <button class="ghost-btn" id="merged-next" type="button">继续提交下一条 JD</button>
    </div>
  `;

  $("#merged-open-analytics").addEventListener("click", () => openAnalyticsForJob(standardJob, month));
  $("#merged-next").addEventListener("click", resetJobResultPanel);
}

function renderJobResult(item) {
  if (item?.status === "auto_merged") {
    renderMergedJobResult(item, item);
    return;
  }
  state.currentReviewItem = item;
  const route = item?.result?.route || {};
  const skills = item?.result?.skills || [];
  const update = item?.result?.update || {};
  const isExisting = route.status === "existing_job";
  const bestCategory = route.best_category?.name || "未命中";
  const bestJob = route.best_job?.name || "未命中";
  const selectedJob = update.standard_job || bestJob;
  const selectedMonth = update.month || item?.input?.month || "";

  $("#job-result-panel").innerHTML = `
    <div class="result-header">
      <div>
        <h3>${escapeHtml(item.input.job_title)}</h3>
        <p>${escapeHtml(item.input.month)} · ${escapeHtml(bestCategory)} / ${escapeHtml(bestJob)}</p>
      </div>
      ${statusTag(route.status)}
    </div>

    ${processStepsHtml(item)}

    <div class="result-section">
      <h4>候选岗位与二次裁决</h4>
      ${topCandidatesHtml(route)}
    </div>

    <div class="result-section">
      <h4>岗位识别结果</h4>
      <div class="detail-grid">
        <div><span>原始岗位名</span><strong>${escapeHtml(item.result?.job_title || item.input.job_title)}</strong></div>
        <div><span>清洗后岗位名</span><strong>${escapeHtml(item.result?.routing_job_title || "无")}</strong></div>
        <div><span>标准岗位</span><strong>${escapeHtml(bestJob)}</strong></div>
        <div><span>岗位大族</span><strong>${escapeHtml(bestCategory)}</strong></div>
      </div>
      <p class="muted">${escapeHtml(route.reason || "暂无判断说明。")}</p>
    </div>

    <div class="result-section">
      <div class="panel-title-row">
        <h4>技能抽取结果</h4>
        <span class="muted">${skills.length} 个归一化技能</span>
      </div>
      <div class="table-wrap result-table-wrap">
        <table>
          <thead>
            <tr><th>归一化技能</th><th>KG 展示技能</th><th>技能类型</th><th>置信度</th></tr>
          </thead>
          <tbody>
            ${skills.map((skill, index) => `
              <tr>
                <td><input data-skill-normalized="${index}" value="${escapeHtml(skill.normalized_skill)}" /></td>
                <td><input data-skill-family="${index}" value="${escapeHtml(skill.kg_display_skill)}" /></td>
                <td><span class="tag">${escapeHtml(skill.skill_type || "未标注")}</span></td>
                <td>${skill.confidence == null ? "无" : Number(skill.confidence).toFixed(2)}${skill.is_new_skill_candidate ? " · 新技能候选" : ""}${skill.is_low_confidence ? " · 低置信度" : ""}<label><input data-skill-invalid="${index}" type="checkbox" /> 无效</label></td>
              </tr>
            `).join("") || `<tr><td colspan="4">暂无技能抽取结果。</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>

    <div class="result-section">
      <h4>更新影响预览</h4>
      <div class="metric-grid compact-metrics">
        ${metric("月度频率行", update.monthly_rows ?? "待确认")}
        ${metric("频率表总行", update.frequency_rows ?? "待确认")}
        ${metric("技能池行数", update.skill_pool_rows ?? "待确认")}
        ${metric("更新状态", item.result?.updated ? "可入库" : "需人工确认")}
      </div>
    </div>

    ${isExisting ? `
      <div class="result-section">
        <h4>确认既有标准岗位</h4>
        <label>从标准岗位 Top-K 中选择
          <select id="detail-standard-job">
            ${(route.top_jobs || route.selected_jobs || []).map((candidate) => `<option value="${escapeHtml(candidate.name)}" ${candidate.name === bestJob ? "selected" : ""}>${escapeHtml(candidate.name)} (${Number(candidate.score || 0).toFixed(3)})</option>`).join("")}
          </select>
        </label>
      </div>
    ` : `
      <div class="result-section">
        <h4>新岗位人工补充</h4>
        <div class="new-job-grid">
          <label>岗位族<input id="detail-new-category" value="${escapeHtml(bestCategory === "未命中" ? "" : bestCategory)}" placeholder="例如：AI应用" /></label>
          <label>标准岗位<input id="detail-new-title" value="${escapeHtml(item.input.job_title)}" /></label>
          <label class="wide">匹配关键词<input id="detail-new-keywords" placeholder="不填则使用标准岗位名" /></label>
        </div>
      </div>
    `}

    <div class="result-section">
      <div class="panel-title-row">
        <h4>手动补充技能</h4>
        <button class="ghost-btn" id="add-manual-review-skill" type="button">新增技能</button>
      </div>
      <p class="muted">仅填写你决定随本条 JD 入库的规范技能；删除系统技能可勾选“无效”。</p>
      <div id="manual-review-skills"></div>
    </div>

    <div class="result-section">
      <h4>从标准岗位 Top-K 中人工选择</h4>
      <label>最终标准岗位<select id="detail-manual-standard-job"></select></label>
    </div>

    <div class="dialog-actions result-actions">
      <button class="ghost-btn" id="detail-reject" type="button">不更新</button>
      <button class="secondary-btn" id="detail-open-review" type="button">打开审核弹窗</button>
      <button class="secondary-btn" id="detail-merge-as-existing" type="button">按所选 Top-K 作为既有岗位入库</button>
      <button class="primary-btn" id="detail-merge" type="button">${isExisting ? "确认并入基础数据库" : "确认新岗位并入库"}</button>
      <button class="ghost-btn" id="detail-open-analytics" type="button">查看该岗位趋势</button>
    </div>
  `;

  $("#detail-open-review").addEventListener("click", () => openReviewDialog(item.item_id));
  const manualJobSelect = $("#detail-manual-standard-job");
  if (manualJobSelect) {
    manualJobSelect.innerHTML = (route.top_jobs || route.selected_jobs || [])
      .map((candidate) => `<option value="${escapeHtml(candidate.name)}" ${candidate.name === bestJob ? "selected" : ""}>${escapeHtml(candidate.name)} (${Number(candidate.score || 0).toFixed(3)})</option>`)
      .join("");
  }
  $("#add-manual-review-skill").addEventListener("click", appendManualReviewSkillRow);
  $("#detail-open-analytics").addEventListener("click", () => openAnalyticsForJob(selectedJob, selectedMonth));
  $("#detail-reject").addEventListener("click", async () => {
    await api(`/api/review/${item.item_id}/reject-update`, { method: "POST" });
    await refreshReview();
    $("#job-result-panel").innerHTML = `<div class="empty-result"><h3>已标记为不更新</h3><p>该记录已从待审核队列移除。</p></div>`;
  });
  $("#detail-merge-as-existing").addEventListener("click", async () => {
    const button = $("#detail-merge-as-existing");
    button.disabled = true;
    try {
      const mergedItem = await api(`/api/review/${item.item_id}/confirm-existing`, {
        method: "POST",
        body: JSON.stringify({
          merge_database: true,
          standard_job_title: $("#detail-manual-standard-job")?.value || bestJob,
          skills: reviewedSkillsPayload(skills),
        }),
      });
      await Promise.all([refreshReview(), refreshBackups(), refreshAnalyticsOptions()]);
      state.analytics.loaded = false;
      renderMergedJobResult(item, mergedItem);
    } catch (error) {
      button.disabled = false;
      $("#job-result-panel").insertAdjacentHTML("afterbegin", `<div class="error-strip">${escapeHtml(error.message)}</div>`);
    }
  });
  $("#detail-merge").addEventListener("click", async () => {
    const mergeButton = $("#detail-merge");
    const originalText = mergeButton.textContent;
    mergeButton.disabled = true;
    mergeButton.textContent = "正在入库...";
    try {
      let mergedItem;
      if (isExisting) {
        mergedItem = await api(`/api/review/${item.item_id}/confirm-existing`, {
          method: "POST",
          body: JSON.stringify({
            merge_database: true,
            standard_job_title: $("#detail-manual-standard-job")?.value || $("#detail-standard-job")?.value || bestJob,
            skills: reviewedSkillsPayload(skills),
          }),
        });
      } else {
        mergedItem = await api(`/api/review/${item.item_id}/confirm-new-job`, {
          method: "POST",
          body: JSON.stringify({
            standard_category: $("#detail-new-category").value,
            standard_job_title: $("#detail-new-title").value,
            match_keywords: $("#detail-new-keywords").value,
            merge_database: true,
            skills: reviewedSkillsPayload(skills),
          }),
        });
      }
      await Promise.all([refreshReview(), refreshBackups(), refreshAnalyticsOptions()]);
      state.analytics.loaded = false;
      if (isExisting) {
        renderMergedJobResult(item, mergedItem);
      } else {
        $("#job-result-panel").innerHTML = `<div class="success-strip">已提交词典维护待审核。该新岗位尚未写入正式词典和基础数据，审核通过后再入库。</div>`;
      }
    } catch (error) {
      mergeButton.disabled = false;
      mergeButton.textContent = originalText;
      $("#job-result-panel").insertAdjacentHTML("afterbegin", `<div class="error-strip">${escapeHtml(error.message)}</div>`);
    }
  });
}

function renderRank(selector, payload) {
  const rows = payload.rows || [];
  $(selector).innerHTML = rows
    .map((row, index) => `
      <article class="rank-item">
        <span>${index + 1}</span>
        <div>
          <strong>${row.skill}</strong>
          <p>${row.standard_job} · ${row.change_type}</p>
        </div>
        <em>${signedPercent(row.frequency_delta)}</em>
      </article>
    `)
    .join("") || `<p class="muted">暂无榜单数据。</p>`;
}

async function refreshAnalyticsOptions() {
  const sourceParams = sourceQueryParams();
  const [jobs, months, overview] = await Promise.all([
    api(`/api/analytics/jobs?${sourceParams}`),
    api(`/api/analytics/months?${sourceParams}`),
    api(`/api/analytics/overview?${sourceParams}`),
  ]);
  state.analytics.jobs = jobs;
  state.analytics.months = months;
  state.overview = overview;
  $("#analytics-job").innerHTML = jobs.map((job) => `<option value="${job}">${job}</option>`).join("");
  $("#analytics-month-start").innerHTML = months.map((month) => `<option value="${month}">${month}</option>`).join("");
  $("#analytics-month-end").innerHTML = months.map((month) => `<option value="${month}">${month}</option>`).join("");
  if (months.length) {
    $("#analytics-month-start").value = months[0];
    $("#analytics-month-end").value = months[months.length - 1];
  }
  renderAnalyticsMetrics(overview);
  renderSourceIndicators();
  renderOverview();
}

async function refreshAnalytics() {
  if (!state.analytics.jobs.length) {
    await refreshAnalyticsOptions();
  }
  const job = $("#analytics-job").value || state.analytics.jobs[0] || "";
  const monthStart = $("#analytics-month-start").value || "";
  const monthEnd = $("#analytics-month-end").value || "";
  const topN = Number($("#analytics-top-n").value || 8);
  const params = new URLSearchParams({
    standard_job: job,
    month_start: monthStart,
    month_end: monthEnd,
    top_n: String(topN),
  });
  if (state.currentSourceKey) params.set("source_key", state.currentSourceKey);
  const rankParams = new URLSearchParams({ month: monthEnd, standard_job: job, limit: "12" });
  if (state.currentSourceKey) rankParams.set("source_key", state.currentSourceKey);
  const compareParams = new URLSearchParams({
    standard_job: job,
    from_month: monthStart,
    to_month: monthEnd,
    limit: "80",
  });
  if (state.currentSourceKey) compareParams.set("source_key", state.currentSourceKey);
  const sourceParams = sourceQueryParams();
  const [trend, lifecycleData, migrationData, emerging, declining, overviewData, profileCompare] = await Promise.all([
    api(`/api/analytics/job-trend?${params}`),
    api(`/api/analytics/lifecycle?${sourceQueryParams({ standard_job: job, limit: "80" })}`),
    api(`/api/analytics/skill-migration?${sourceQueryParams({ limit: "25" })}`),
    api(`/api/analytics/monthly-rank?${rankParams}&type=emerging`),
    api(`/api/analytics/monthly-rank?${rankParams}&type=declining`),
    api(`/api/analytics/overview?${sourceParams}`),
    api(`/api/analytics/profile-compare?${compareParams}`),
  ]);
  renderAnalyticsMetrics(overviewData);
  renderLineChart(trend);
  renderProfileCompare(profileCompare);
  renderLifecycle(lifecycleData);
  renderMigration(migrationData);
  $("#emerging-month").textContent = emerging.month || "";
  $("#declining-month").textContent = declining.month || "";
  renderRank("#emerging-rank", emerging);
  renderRank("#declining-rank", declining);
  state.analytics.loaded = true;
}

async function refreshRuns() {
  const runs = await api("/api/pipeline/runs");
  $("#run-select").innerHTML = runs.map((run) => `<option value="${run.run_id}">${run.run_id}</option>`).join("");
}

async function refreshReview() {
  const items = await api("/api/review/items");
  renderReviewItems(items);
}

async function refreshBackups() {
  const rows = await api("/api/database/backups");
  renderBackups(rows);
  renderOverview();
}

async function refreshOverview() {
  state.overview = await api(`/api/analytics/overview?${sourceQueryParams()}`);
  renderOverview();
}

async function refreshDataSources() {
  const sources = await api("/api/data-sources");
  state.dataSources = sources || [];
  if (!state.dataSources.some((source) => source.key === state.currentSourceKey)) {
    state.currentSourceKey = state.dataSources[0]?.key || "base";
  }
  $("#global-source-select").innerHTML = state.dataSources
    .map((source) => `<option value="${escapeHtml(source.key)}">${escapeHtml(sourceText(source))}</option>`)
    .join("");
  $("#global-source-select").value = state.currentSourceKey;
  renderSourceIndicators();
}

async function openAnalyticsForJob(job, month) {
  if (!state.analytics.jobs.length) {
    await refreshAnalyticsOptions();
  }
  if (job && state.analytics.jobs.includes(job)) {
    $("#analytics-job").value = job;
  }
  if (month && state.analytics.months.includes(month)) {
    $("#analytics-month-end").value = month;
  }
  state.analytics.loaded = false;
  switchView("analytics");
  await refreshAnalytics();
}

function pipelinePayload() {
  return {
    month_start: $("#month-start").value,
    month_end: $("#month-end").value,
    pass_threshold: Number($("#pass-threshold").value || 0.9),
  };
}

function bindEvents() {
  $("#domain-select").addEventListener("change", async (event) => {
    state.domain = event.target.value;
    state.currentSourceKey = "base";
    state.analytics.loaded = false;
    state.analytics.jobs = [];
    state.analytics.months = [];
    state.analytics.migrationSkills = [];
    state.optimization.loaded = false;
    state.optimization.currentJob = "";
    $("#optimization-job").innerHTML = `<option value="">请选择标准岗位</option>`;
    await refreshDataSources();
    await Promise.all([refreshOverview(), refreshReview(), refreshAnalyticsOptions()]);
    if ($("#view-optimization").classList.contains("active")) {
      await refreshOptimizationProfile();
    }
  });
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      switchView(button.dataset.view);
    });
  });

  $("#overview-open-manual").addEventListener("click", () => switchView("manual"));
  $("#overview-open-analytics").addEventListener("click", () => switchView("analytics"));
  $("#global-source-select").addEventListener("change", async () => {
    state.currentSourceKey = $("#global-source-select").value || "base";
    state.analytics.loaded = false;
    state.analytics.jobs = [];
    state.analytics.months = [];
    state.analytics.migrationSkills = [];
    state.optimization.loaded = false;
    state.optimization.currentJob = "";
    $("#optimization-job").innerHTML = `<option value="">请选择标准岗位</option>`;
    renderSourceIndicators();
    await Promise.all([refreshOverview(), refreshAnalyticsOptions()]);
    if ($("#view-optimization").classList.contains("active")) {
      await refreshOptimizationProfile();
    }
    if ($("#view-analytics").classList.contains("active")) {
      await refreshAnalytics();
    }
  });
  $("#overview-refresh").addEventListener("click", async () => {
    await Promise.all([refreshDataSources(), refreshOverview(), refreshReview(), refreshBackups()]);
  });

  $$(".profile-tab").forEach((button) => {
    button.addEventListener("click", () => renderProfileChangeTable(button.dataset.profileChange));
  });
  $("#open-optimization-from-profile").addEventListener("click", () => {
    openOptimizationForJob($("#analytics-job").value);
  });
  $("#optimization-load").addEventListener("click", refreshOptimizationProfile);
  $("#optimization-refresh").addEventListener("click", refreshOptimizationProfile);
  $("#optimization-normalize").addEventListener("click", normalizeOptimizationSkill);
  $("#optimization-apply-edit").addEventListener("click", applyOptimizationEdit);
  $("#optimization-job").addEventListener("keydown", (event) => {
    if (event.key === "Enter") refreshOptimizationProfile();
  });
  $("#optimization-new-skill").addEventListener("keydown", (event) => {
    if (event.key === "Enter") normalizeOptimizationSkill();
  });
  $("#optimization-save-draft").addEventListener("click", async () => {
    if (!state.optimization.changes.length) {
      $("#optimization-draft").textContent = "暂无可预览的变更。请先新增、删除或修改一个技能。";
      return;
    }
    try {
      const saved = await api("/api/optimization/overrides", {
        method: "POST",
        body: JSON.stringify({
          standard_job: state.optimization.currentJob,
          changes: state.optimization.changes,
        }),
      });
      $("#optimization-draft").textContent = `已写入 ${saved.domain} 数据库：${saved.saved_changes} 条人工覆盖记录。`;
      await refreshOptimizationProfile();
    } catch (error) {
      $("#optimization-draft").textContent = error.message;
    }
  });

  $("#refresh-runs").addEventListener("click", refreshRuns);
  $("#run-full").addEventListener("click", async () => {
    setLoading(true);
    try {
      renderPipeline(await api("/api/pipeline/run-full", { method: "POST", body: JSON.stringify(pipelinePayload()) }));
    } catch (error) {
      $("#pipeline-log").textContent = error.message;
    } finally {
      setLoading(false);
    }
  });
  $("#run-existing").addEventListener("click", async () => {
    const run_id = $("#run-select").value;
    if (!run_id) return;
    setLoading(true);
    try {
      renderPipeline(await api("/api/pipeline/run-existing", {
        method: "POST",
        body: JSON.stringify({ ...pipelinePayload(), run_id }),
      }));
    } catch (error) {
      $("#pipeline-log").textContent = error.message;
    } finally {
      setLoading(false);
    }
  });

  $("#job-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    $("#job-result-panel").innerHTML = `<div class="loading">正在处理 JD，完成后会展示岗位识别和技能更新预览。</div>`;
    const item = await api("/api/jobs/submit-one-dry-run", { method: "POST", body: JSON.stringify(data) });
    await refreshReview();
    renderJobResult(item);
  });

  $("#upload-csv").addEventListener("click", async () => {
    const file = $("#csv-file").files[0];
    if (!file) {
      $("#csv-summary").textContent = "请选择 CSV 文件。";
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    const result = await api("/api/jobs/import-csv", { method: "POST", body: formData });
    $("#csv-summary").textContent = `已导入 ${result.count} 条记录。`;
    await refreshReview();
  });

  $("#refresh-review").addEventListener("click", refreshReview);
  $("#manual-backup").addEventListener("click", async () => {
    await api("/api/database/backup", { method: "POST" });
    await refreshBackups();
  });
  $("#load-analytics").addEventListener("click", refreshAnalytics);
  $("#refresh-analytics").addEventListener("click", async () => {
    state.analytics.loaded = false;
    state.analytics.migrationSkills = [];
    await refreshAnalyticsOptions();
    await refreshAnalytics();
  });
  $("#migration-skill").addEventListener("change", async () => {
    const skill = $("#migration-skill").value;
    renderMigration(await api(`/api/analytics/skill-migration?${sourceQueryParams({ skill, limit: "25" })}`));
  });
}

async function boot() {
  bindEvents();
  try {
    await api("/api/health");
    $("#health").textContent = "本地服务正常";
  } catch {
    $("#health").textContent = "服务异常";
  }
  await refreshDataSources();
  await Promise.all([refreshRuns(), refreshReview(), refreshBackups(), refreshAnalyticsOptions()]);
}

boot();
