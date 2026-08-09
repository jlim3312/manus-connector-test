const $ = (id) => document.getElementById(id);

$("include-rear").addEventListener("change", (e) => {
  $("rear-block").hidden = !e.target.checked;
});

function numOrNull(id) {
  const v = $(id).value;
  return v === "" ? null : parseFloat(v);
}

function specRange(minId, maxId) {
  const min = numOrNull(minId), max = numOrNull(maxId);
  if (min === null || max === null) return null;
  return { min, max };
}

async function apiFetch(path, options = {}) {
  const key = $("api-key").value.trim();
  const resp = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", "X-API-Key": key, ...(options.headers || {}) },
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = body.detail || resp.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

$("autofill-btn").addEventListener("click", async () => {
  const status = $("autofill-status");
  status.textContent = "Looking up...";
  try {
    const data = await apiFetch("/v1/vehicles");
    const make = $("veh-make").value.trim().toLowerCase();
    const model = $("veh-model").value.trim().toLowerCase();
    const year = parseInt($("veh-year").value, 10);
    const match = data.vehicles.find(
      (v) => v.make.toLowerCase() === make && v.model.toLowerCase() === model &&
        (!year || (year >= v.year_min && year <= v.year_max))
    );
    if (!match) {
      status.textContent = "No seed match — enter spec manually from the printout.";
      return;
    }
    status.textContent = `Found seed spec for ${match.make} ${match.model}. Submit will auto-fill server-side; ` +
      `you may still enter spec fields manually to override.`;
  } catch (err) {
    status.textContent = "Lookup failed: " + err.message;
  }
});

function corner(prefix) {
  return {
    camber: numOrNull(`${prefix}-camber`),
    caster: numOrNull(`${prefix}-caster`),
    sai: numOrNull(`${prefix}-sai`),
    toe: numOrNull(`${prefix}-toe`),
  };
}

function buildPayload() {
  const payload = {
    front: { left: corner("fl"), right: corner("fr") },
    vehicle: {
      year: numOrNull("veh-year") ? parseInt($("veh-year").value, 10) : null,
      make: $("veh-make").value.trim() || null,
      model: $("veh-model").value.trim() || null,
      claim_number: $("veh-claim").value.trim() || null,
    },
  };

  const frontCamber = specRange("fs-camber-min", "fs-camber-max");
  const frontToe = specRange("fs-toe-min", "fs-toe-max");
  if (frontCamber && frontToe) {
    payload.front_spec = {
      camber: frontCamber,
      toe: frontToe,
      caster: specRange("fs-caster-min", "fs-caster-max"),
      sai: specRange("fs-sai-min", "fs-sai-max"),
    };
  }

  if ($("include-rear").checked) {
    payload.rear = { left: corner("rl"), right: corner("rr") };
    const rearCamber = specRange("rs-camber-min", "rs-camber-max");
    const rearToe = specRange("rs-toe-min", "rs-toe-max");
    if (rearCamber && rearToe) {
      payload.rear_spec = { camber: rearCamber, toe: rearToe };
    }
  }

  return payload;
}

function severityRank(s) { return { Severe: 2, Moderate: 1, Minor: 0 }[s] ?? 0; }

function renderReport(report) {
  $("summary").textContent = report.summary;
  const structuralEl = $("structural");
  if (report.structural_flag) {
    structuralEl.hidden = false;
    structuralEl.textContent = "⚠ " + report.structural_explanation;
  } else {
    structuralEl.hidden = true;
  }

  const container = $("findings");
  container.innerHTML = "";
  if (report.findings.length === 0) {
    container.innerHTML = "<p>No out-of-spec findings.</p>";
  }
  for (const f of report.findings) {
    const div = document.createElement("div");
    div.className = `finding ${f.severity}`;
    const locBits = [f.axle, f.side].filter(Boolean).join(" ");
    div.innerHTML = `
      <div class="head">
        <span class="component">${f.component}</span>
        <span class="badge ${f.severity}">${f.severity} · ${Math.round(f.confidence * 100)}% confidence</span>
      </div>
      <div class="meta">${locBits ? locBits + " — " : ""}${f.issue}${f.measured !== null ? ` (measured ${f.measured}${f.spec ? ", spec " + f.spec : ""})` : ""}</div>
      <p class="explanation">${f.explanation}</p>
      ${f.recommended_inspection.length ? `<p class="inspect">Inspect: ${f.recommended_inspection.join(", ")}</p>` : ""}
    `;
    container.appendChild(div);
  }

  $("disclaimer").textContent = report.disclaimer;
  $("result").hidden = false;
}

$("reading-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("error-box").hidden = true;
  $("result").hidden = true;
  const btn = $("submit-btn");
  btn.disabled = true;
  btn.textContent = "Analyzing...";
  try {
    const payload = buildPayload();
    const report = await apiFetch("/v1/predict", { method: "POST", body: JSON.stringify(payload) });
    renderReport(report);
  } catch (err) {
    $("error-box").hidden = false;
    $("error-box").textContent = "Error: " + err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Predict suspension damage";
  }
});
