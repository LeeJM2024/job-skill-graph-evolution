const state = {
  currentPipeline: null,
  reviewItems: [],
  backups: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  return response.json();
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
}

function skillsHtml(skills) {
  return `
    <div class="tag-row">
      ${(skills || []).map((skill) => `<span class="tag">${skill.normalized_skill}${skill.kg_display_skill ? ` · ${skill.kg_display_skill}` : ""}</span>`).join("") || `<span class="muted">暂无技能结果。</span>`}
    </div>
  `;
}

function openReviewDialog(itemId) {
  const item = state.reviewItems.find((entry) => entry.item_id === itemId);
  if (!item) return;
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
      await api(`/api/review/${itemId}/confirm-existing`, {
        method: "POST",
        body: JSON.stringify({ merge_database: true }),
      });
      await refreshReview();
      await refreshBackups();
      $("#review-dialog").close();
    });
  }
  const mergeNew = $("#merge-new");
  if (mergeNew) {
    mergeNew.addEventListener("click", async () => {
      await api(`/api/review/${itemId}/confirm-new-job`, {
        method: "POST",
        body: JSON.stringify({
          standard_category: $("#new-category").value,
          standard_job_title: $("#new-title").value,
          match_keywords: $("#new-keywords").value,
          merge_database: true,
        }),
      });
      await refreshReview();
      await refreshBackups();
      $("#review-dialog").close();
    });
  }
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
}

function pipelinePayload() {
  return {
    month_start: $("#month-start").value,
    month_end: $("#month-end").value,
    pass_threshold: Number($("#pass-threshold").value || 0.9),
  };
}

function bindEvents() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".nav-item").forEach((item) => item.classList.remove("active"));
      $$(".view").forEach((view) => view.classList.remove("active"));
      button.classList.add("active");
      $(`#view-${button.dataset.view}`).classList.add("active");
    });
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
    const item = await api("/api/jobs/submit-one-dry-run", { method: "POST", body: JSON.stringify(data) });
    await refreshReview();
    openReviewDialog(item.item_id);
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
}

async function boot() {
  bindEvents();
  try {
    await api("/api/health");
    $("#health").textContent = "本地服务正常";
  } catch {
    $("#health").textContent = "服务异常";
  }
  await Promise.all([refreshRuns(), refreshReview(), refreshBackups()]);
}

boot();
