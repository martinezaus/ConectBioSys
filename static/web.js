(() => {
  const csrf = window.CSRF_TOKEN;
  const appRoot = window.APP_ROOT || "";
  const jobs = document.querySelector("#jobs");
  const selected = new Set();
  let queryId = null;
  let totalRows = 0;
  let pageSize = 20;
  let pageOffset = 0;
  let selectAllResults = false;
  let pageRows = [];

  async function api(url, options = {}) {
    const response = await fetch(`${appRoot}${url}`, {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.method && options.method !== "GET" ? { "X-CSRF-Token": csrf } : {}),
        ...(options.headers || {}),
      },
    });
    const contentType = response.headers.get("content-type") || "";
    if (!response.ok) {
      const body = contentType.includes("application/json") ? await response.json() : {};
      throw new Error(body.error || `Error HTTP ${response.status}.`);
    }
    return contentType.includes("application/json") ? response.json() : response;
  }

  function showNotice(target, text, isError = false) {
    target.textContent = text;
    target.style.color = isError ? "#b93c4b" : "";
  }

  function addJob(jobId, title) {
    const element = document.createElement("article");
    element.className = "job";
    element.innerHTML = `<div class="job-head"><strong></strong><span class="job-state">Iniciando…</span></div><div class="progress-track"><span></span></div><div class="job-message muted"></div>`;
    element.querySelector("strong").textContent = title;
    jobs.prepend(element);
    const timer = window.setInterval(async () => {
      try {
        const state = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
        const label = state.status === "running" ? "En curso" : state.status === "error" ? "Error" : "Completado";
        element.querySelector(".job-state").textContent = label;
        element.querySelector(".job-message").textContent = state.error || state.message || "";
        const bar = element.querySelector(".progress-track span");
        bar.style.width = state.progress < 0 ? "32%" : `${state.progress}%`;
        if (state.status === "error" || state.status === "completed") {
          window.clearInterval(timer);
          element.classList.add(state.status === "error" ? "error" : "complete");
          if (state.status === "completed" && state.result && state.result.download_url) {
            const link = document.createElement("a");
            link.href = state.result.download_url;
            link.textContent = "Descargar Excel";
            link.className = "muted";
            link.style.display = "inline-block";
            link.style.marginTop = "8px";
            element.append(link);
          } else if (state.status === "completed" && state.result && state.kind === "download") {
            element.querySelector(".job-message").textContent =
              `Guardadas: ${state.result[0]}. Ya existentes: ${state.result[1]}. ${state.result[2].join(" ")}`;
          } else if (state.status === "completed" && state.result && state.kind === "send") {
            element.querySelector(".job-message").textContent =
              `Insertadas: ${state.result[0]}. Duplicadas omitidas: ${state.result[1]}. Errores: ${state.result[2]}. ${state.result[3].join(" ")}`;
          } else if (state.status === "completed" && state.result && typeof state.result === "object") {
            element.querySelector(".job-message").textContent =
              `Insertadas: ${state.result[0]}. Con error o duplicadas: ${state.result[1]}.`;
          } else if (state.status === "completed" && typeof state.result === "string") {
            element.querySelector(".job-message").textContent = state.result;
          }
        }
      } catch (error) {
        window.clearInterval(timer);
        element.classList.add("error");
        element.querySelector(".job-state").textContent = "Error";
        element.querySelector(".job-message").textContent = error.message;
      }
    }, 1200);
  }

  async function startDownload(period, title, range = null) {
    try {
      const result = await api("/api/download", {
        method: "POST",
        body: JSON.stringify(range ? { period, since: range.since, until: range.until } : { period }),
      });
      addJob(result.job_id, `${title} · ${result.since} a ${result.until}`);
    } catch (error) {
      showNotice(document.querySelector("#download-message"), error.message, true);
    }
  }

  async function renderPage(offset) {
    const result = await api(`/api/query/${encodeURIComponent(queryId)}?offset=${offset}`);
    pageOffset = result.offset;
    pageRows = result.rows;
    pageSize = result.page_size || pageSize;
    const body = document.querySelector("#rows");
    body.replaceChildren();
    pageRows.forEach((row, rowIndex) => {
      const globalIndex = pageOffset + rowIndex;
      const tr = document.createElement("tr");
      const checkboxCell = document.createElement("td");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selectAllResults ? !selected.has(globalIndex) : selected.has(globalIndex);
      checkbox.setAttribute("aria-label", `Seleccionar marcación ${globalIndex + 1}`);
      checkbox.addEventListener("change", () => {
        if (selectAllResults) {
          if (checkbox.checked) selected.delete(globalIndex);
          else selected.add(globalIndex);
        } else if (checkbox.checked) selected.add(globalIndex);
        else selected.delete(globalIndex);
        updateSelectionUi();
      });
      checkboxCell.append(checkbox);
      tr.append(checkboxCell);
      row.forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value == null ? "" : String(value);
        tr.append(cell);
      });
      body.append(tr);
    });
    document.querySelector("#page-label").textContent =
      `Página ${Math.floor(pageOffset / pageSize) + 1} de ${Math.max(1, Math.ceil(totalRows / pageSize))}`;
    document.querySelector("#previous-page").disabled = pageOffset === 0;
    document.querySelector("#next-page").disabled = pageOffset + pageSize >= totalRows;
    document.querySelector("#check-page").checked = pageRows.length > 0 && pageRows.every((_, i) => {
      const index = pageOffset + i;
      return selectAllResults ? !selected.has(index) : selected.has(index);
    });
  }

  function formatCount(value) {
    return new Intl.NumberFormat("es-AR").format(value);
  }

  function selectedCount() {
    return selectAllResults ? totalRows - selected.size : selected.size;
  }

  function updateSelectionUi() {
    const count = selectedCount();
    document.querySelector("#result-count").textContent = formatCount(totalRows);
    document.querySelector("#selected-count").textContent = `· ${formatCount(count)} seleccionadas`;
    document.querySelector("#select-all").textContent = selectAllResults
      ? `Quitar selección total (${formatCount(count)})`
      : `Seleccionar las ${formatCount(totalRows)} marcaciones`;
    const master = document.querySelector("#check-page");
    master.checked = pageRows.length > 0 && pageRows.every((_, i) => {
      const index = pageOffset + i;
      return selectAllResults ? !selected.has(index) : selected.has(index);
    });
  }

  function selectionPayload() {
    return {
      query_id: queryId,
      all: selectAllResults,
      indices: Array.from(selected),
    };
  }

  document.querySelectorAll("[data-download]").forEach((button) => {
    button.addEventListener("click", () => {
      const period = button.dataset.download;
      startDownload(period, period === "previous_month" ? "Mes anterior" : "Últimos 7 días");
    });
  });

  document.querySelector("#custom-download-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const since = String(form.get("since") || "");
    const until = String(form.get("until") || "");
    if (since > until) {
      showNotice(document.querySelector("#download-message"), "La fecha inicial debe ser anterior o igual a la fecha final.", true);
      return;
    }
    showNotice(document.querySelector("#download-message"), "Iniciando descarga…");
    startDownload("custom", "Rango personalizado", { since, until });
  });

  document.querySelector("#search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const message = document.querySelector("#query-message");
    showNotice(message, "Buscando marcaciones…");
    try {
      const result = await api("/api/query", {
        method: "POST",
        body: JSON.stringify({
          since: form.get("since"),
          until: form.get("until"),
          card: form.get("card"),
        }),
      });
      queryId = result.query_id;
      totalRows = result.total;
      selected.clear();
      selectAllResults = false;
      pageOffset = 0;
      pageRows = [];
      pageSize = result.page_size || 20;
      document.querySelector("#results").hidden = !totalRows;
      showNotice(message, totalRows ? "" : "No hay marcaciones para los filtros seleccionados.");
      if (totalRows) await renderPage(0);
      updateSelectionUi();
    } catch (error) {
      showNotice(message, error.message, true);
    }
  });

  document.querySelector("#previous-page").addEventListener("click", () => renderPage(Math.max(0, pageOffset - pageSize)));
  document.querySelector("#next-page").addEventListener("click", () => renderPage(pageOffset + pageSize));
  document.querySelector("#check-page").addEventListener("change", (event) => {
    pageRows.forEach((_, i) => {
      const index = pageOffset + i;
      if (selectAllResults) {
        if (event.currentTarget.checked) selected.delete(index);
        else selected.add(index);
      } else if (event.currentTarget.checked) selected.add(index);
      else selected.delete(index);
    });
    updateSelectionUi();
    renderPage(pageOffset);
  });
  document.querySelector("#select-page").addEventListener("click", () => {
    pageRows.forEach((_, i) => {
      const index = pageOffset + i;
      if (selectAllResults) selected.delete(index);
      else selected.add(index);
    });
    updateSelectionUi();
    renderPage(pageOffset);
  });
  document.querySelector("#select-all").addEventListener("click", () => {
    selectAllResults = !selectAllResults;
    selected.clear();
    updateSelectionUi();
    renderPage(pageOffset);
  });

  async function runSelection(endpoint, title) {
    if (!queryId || (!selectAllResults && selected.size === 0)) {
      showNotice(document.querySelector("#query-message"), "Seleccioná al menos una marcación.", true);
      return;
    }
    try {
      const result = await api(endpoint, { method: "POST", body: JSON.stringify(selectionPayload()) });
      addJob(result.job_id, title);
    } catch (error) {
      showNotice(document.querySelector("#query-message"), error.message, true);
    }
  }
  document.querySelector("#export-excel").addEventListener("click", () => runSelection("/api/export", "Exportando Excel"));
  document.querySelector("#send-db").addEventListener("click", () => {
    if (window.confirm(`Se enviarán ${formatCount(selectedCount())} marcaciones a la base de asistencias. ¿Continuar?`)) {
      runSelection("/api/send", "Enviando marcaciones");
    }
  });

  document.querySelector("#clean-buffers").addEventListener("click", async () => {
    if (!window.confirm("Esta operación borrará definitivamente las marcaciones que aún estén en la memoria de los relojes y no se hayan descargado. ¿Querés continuar?")) return;
    const confirmation = window.prompt("Para confirmar, escribí BORRAR en mayúsculas:");
    if (confirmation !== "BORRAR") return;
    try {
      const result = await api("/api/clean-buffers", {
        method: "POST",
        body: JSON.stringify({ confirmation }),
      });
      addJob(result.job_id, "Limpiando buffers de los relojes");
    } catch (error) {
      showNotice(document.querySelector("#query-message"), error.message, true);
    }
  });

  if (document.querySelector("#settings")) {
    const settingsMessage = (id) => document.querySelector(`#${id}`);
    const connectionForm = document.querySelector("#connection-form");
    const connectionEngine = document.querySelector("#connection-engine");
    let settingsCache = null;

    document.querySelectorAll("[data-settings-tab]").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll("[data-settings-tab]").forEach((item) => {
          const active = item === tab;
          item.classList.toggle("active", active);
          item.setAttribute("aria-selected", String(active));
          document.querySelector(`#${item.getAttribute("aria-controls")}`).hidden = !active;
        });
      });
    });

    function updateConnectionFields() {
      const sqlite = connectionEngine.value === "sqlite";
      document.querySelector("#network-fields").hidden = sqlite;
      document.querySelector("#sqlite-fields").hidden = !sqlite;
      connectionForm.elements.host.required = !sqlite;
      connectionForm.elements.puerto.required = !sqlite;
      connectionForm.elements.usuario.required = !sqlite;
      connectionForm.elements.base_datos.required = !sqlite;
      connectionForm.elements.archivo_sqlite.required = sqlite;
      if (settingsCache?.engines?.[connectionEngine.value]) {
        const defaults = { mysql: 3306, postgresql: 5432, sqlserver: 1433 };
        if (!connectionForm.elements.puerto.value || connectionForm.elements.puerto.dataset.engine !== connectionEngine.value) {
          connectionForm.elements.puerto.value = defaults[connectionEngine.value] || "";
        }
        connectionForm.elements.puerto.dataset.engine = connectionEngine.value;
      }
    }
    connectionEngine.addEventListener("change", updateConnectionFields);

    function connectionPayload() {
      const form = new FormData(connectionForm);
      return Object.fromEntries(["motor", "host", "puerto", "usuario", "password", "base_datos", "archivo_sqlite"].map((key) => [key, form.get(key)]));
    }

    function populateMappingForm(form, config = {}) {
      Object.entries(config).forEach(([name, value]) => {
        const field = form.elements.namedItem(name);
        if (field && "value" in field) field.value = value ?? "";
      });
    }
    async function loadOrganizations(selected) {
      const select = document.querySelector("#employee-organization");
      const result = await api("/api/settings/organizations");
      select.replaceChildren();
      result.rows.forEach(([id, name]) => {
        const option = document.createElement("option");
        option.value = id;
        option.textContent = `${id} — ${name}`;
        select.append(option);
      });
      if (selected && [...select.options].some((option) => option.value === String(selected))) select.value = String(selected);
      return result.rows.length;
    }

    function renderClocks(clocks = []) {
      const list = document.querySelector("#clock-list");
      list.replaceChildren();
      clocks.forEach((clock) => addClockCard(clock));
    }

    function addClockCard(clock = { tipo: "zkteco", params: {} }) {
      const list = document.querySelector("#clock-list");
      const card = document.createElement("article");
      card.className = "clock-card";
      const kind = clock.tipo || "zkteco";
      const params = clock.params || {};
      card.innerHTML = `<div class="clock-card-head"><strong>Reloj</strong><button type="button" class="danger-outline small-button" data-remove-clock>Quitar</button></div><div class="clock-fields"><label>Tipo<select data-clock-field="tipo"><option value="zkteco">ZKTeco</option><option value="hikvision">Hikvision</option></select></label><label>Nombre / ID de dispositivo<input data-clock-field="dispositivo_id" required></label><label>Dirección IP<input data-clock-field="ip" required></label><label data-zkteco>Puerto<input data-clock-field="puerto" type="number" min="1" max="65535"></label><label class="checkbox-label" data-zkteco><input data-clock-field="force_udp" type="checkbox"> Forzar UDP</label><label data-hikvision>Usuario<input data-clock-field="usuario" autocomplete="username"></label><label data-hikvision>Contraseña<input data-clock-field="password" type="password" autocomplete="new-password" placeholder="Vacío conserva la guardada"></label><label class="checkbox-label" data-hikvision><input data-clock-field="usar_https" type="checkbox"> Usar HTTPS</label></div>`;
      const typeSelect = card.querySelector('[data-clock-field="tipo"]');
      typeSelect.value = kind;
      card.querySelector('[data-clock-field="dispositivo_id"]').value = params.dispositivo_id || "";
      card.querySelector('[data-clock-field="ip"]').value = params.ip || "";
      card.querySelector('[data-clock-field="puerto"]').value = params.puerto || 4370;
      card.querySelector('[data-clock-field="force_udp"]').checked = params.force_udp !== false;
      card.querySelector('[data-clock-field="usuario"]').value = params.usuario || "admin";
      card.querySelector('[data-clock-field="usar_https"]').checked = Boolean(params.usar_https);
      typeSelect.addEventListener("change", () => {
        card.querySelectorAll("[data-zkteco]").forEach((field) => { field.hidden = typeSelect.value !== "zkteco"; });
        card.querySelectorAll("[data-hikvision]").forEach((field) => { field.hidden = typeSelect.value !== "hikvision"; });
      });
      card.querySelector("[data-remove-clock]").addEventListener("click", () => card.remove());
      typeSelect.dispatchEvent(new Event("change"));
      list.append(card);
    }

    function collectClocks() {
      return [...document.querySelectorAll(".clock-card")].map((card) => {
        const value = (name) => card.querySelector(`[data-clock-field="${name}"]`);
        const tipo = value("tipo").value;
        const params = { ip: value("ip").value.trim(), dispositivo_id: value("dispositivo_id").value.trim() };
        if (tipo === "zkteco") Object.assign(params, { puerto: value("puerto").value, force_udp: value("force_udp").checked });
        else Object.assign(params, { usuario: value("usuario").value.trim(), password: value("password").value, usar_https: value("usar_https").checked });
        return { tipo, params };
      });
    }

    async function loadSettings() {
      settingsCache = await api("/api/settings");
      connectionEngine.replaceChildren();
      Object.entries(settingsCache.engines).forEach(([value, label]) => {
        const option = document.createElement("option"); option.value = value; option.textContent = label; connectionEngine.append(option);
      });
      const connection = settingsCache.connection || {};
      connectionEngine.value = connection.motor || "mysql";
      ["host", "puerto", "usuario", "password", "base_datos", "archivo_sqlite"].forEach((key) => { connectionForm.elements[key].value = key === "password" ? "" : (connection[key] ?? ""); });
      document.querySelector("#connection-password-state").textContent = connection.password_configured ? "Hay una contraseña guardada. Dejá el campo vacío para conservarla." : "";
      connectionForm.elements.puerto.dataset.engine = connection.motor || "mysql";
      updateConnectionFields();
      renderClocks(settingsCache.clocks || []);
      populateMappingForm(document.querySelector("#employees-form"), settingsCache.employees || {});
      populateMappingForm(document.querySelector("#assistances-form"), settingsCache.assistances || {});
      try { await loadOrganizations(settingsCache.employees?.organizacion_id); } catch (error) { showNotice(settingsMessage("employees-message"), error.message, true); }
    }


    document.querySelector("#add-clock").addEventListener("click", () => addClockCard());
    document.querySelector("#save-clocks").addEventListener("click", async () => {
      try {
        const result = await api("/api/settings", { method: "POST", body: JSON.stringify({ section: "clocks", clocks: collectClocks() }) });
        showNotice(settingsMessage("clocks-message"), result.message);
      } catch (error) { showNotice(settingsMessage("clocks-message"), error.message, true); }
    });

    connectionForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const result = await api("/api/settings", { method: "POST", body: JSON.stringify({ section: "connection", connection: connectionPayload() }) });
        showNotice(settingsMessage("connection-message"), result.message);
        await loadSettings();
      } catch (error) { showNotice(settingsMessage("connection-message"), error.message, true); }
    });
    document.querySelector("#test-connection").addEventListener("click", async () => {
      try {
        const result = await api("/api/settings/test-connection", { method: "POST", body: JSON.stringify({ connection: connectionPayload() }) });
        addJob(result.job_id, "Probando conexión a la base de datos");
      } catch (error) { showNotice(settingsMessage("connection-message"), error.message, true); }
    });

    async function saveMapping(form, section, payloadName, messageId) {
      try {
        const payload = Object.fromEntries(new FormData(form).entries());
        const result = await api("/api/settings", { method: "POST", body: JSON.stringify({ section, [payloadName]: payload }) });
        showNotice(settingsMessage(messageId), result.message);
        settingsCache[ payloadName ] = { ...settingsCache[payloadName], ...payload };
      } catch (error) { showNotice(settingsMessage(messageId), error.message, true); }
    }
    document.querySelector("#employees-form").addEventListener("submit", (event) => { event.preventDefault(); saveMapping(event.currentTarget, "employees", "employees", "employees-message"); });
    document.querySelector("#assistances-form").addEventListener("submit", (event) => { event.preventDefault(); saveMapping(event.currentTarget, "assistances", "assistances", "assistances-message"); });
    document.querySelector("#load-organizations").addEventListener("click", async () => {
      try { const count = await loadOrganizations(); showNotice(settingsMessage("employees-message"), `${count} organizaciones encontradas.`); }
      catch (error) { showNotice(settingsMessage("employees-message"), error.message, true); }
    });
    loadSettings().catch((error) => showNotice(settingsMessage("connection-message"), error.message, true));
  }

  const smtpForm = document.querySelector("#smtp-form");
  if (smtpForm) {
    const smtpMessage = document.querySelector("#smtp-message");
    const smtpPasswordState = document.querySelector("#smtp-password-state");
    async function loadSmtpSettings() {
      const result = await api("/api/settings");
      const smtp = result.smtp;
      smtpForm.elements.host.value = smtp.host || "";
      smtpForm.elements.port.value = smtp.port || 587;
      smtpForm.elements.sender.value = smtp.sender || "";
      smtpForm.elements.username.value = smtp.username || "";
      smtpForm.elements.password.value = "";
      smtpForm.elements.tls_mode.value = smtp.tls_mode || "starttls";
      smtpForm.elements.clear_password.checked = false;
      smtpPasswordState.textContent = smtp.password_configured ? "Hay una contraseña SMTP guardada. Dejá el campo vacío para conservarla." : "No hay una contraseña SMTP guardada.";
    }
    function smtpPayload() {
      const form = new FormData(smtpForm);
      return { host: form.get("host"), port: form.get("port"), sender: form.get("sender"), username: form.get("username"), password: form.get("password"), tls_mode: form.get("tls_mode"), clear_password: form.get("clear_password") === "on" };
    }
    smtpForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const payload = smtpPayload();
        const result = await api("/api/settings", { method: "POST", body: JSON.stringify({ section: "smtp", smtp: payload, clear_password: payload.clear_password }) });
        showNotice(smtpMessage, result.message); await loadSmtpSettings();
      } catch (error) { showNotice(smtpMessage, error.message, true); }
    });
    document.querySelector("#test-smtp").addEventListener("click", async () => {
      try {
        const payload = smtpPayload();
        const result = await api("/api/settings/test-smtp", { method: "POST", body: JSON.stringify({ smtp: payload, clear_password: payload.clear_password }) });
        showNotice(smtpMessage, result.message);
      } catch (error) { showNotice(smtpMessage, error.message, true); }
    });
    loadSmtpSettings().catch((error) => showNotice(smtpMessage, error.message, true));
  }
  const userManagement = document.querySelector("#user-management");
  if (userManagement) {
    const usersList = document.querySelector("#users-list");
    const usersMessage = document.querySelector("#users-message");
    const temporaryPassword = document.querySelector("#temporary-password");

    function showTemporaryPassword(username, password) {
      temporaryPassword.hidden = false;
      temporaryPassword.textContent =
        `Clave temporal para ${username}: ${password}. Copiala ahora; no se volverá a mostrar.`;
    }

    async function loadUsers() {
      const result = await api("/api/users");
      usersList.replaceChildren();
      result.users.forEach((user) => {
        const row = document.createElement("tr");
        row.dataset.user = user.username;

        const usernameCell = document.createElement("td");
        const usernameInput = document.createElement("input");
        usernameInput.value = user.username;
        usernameInput.minLength = 3;
        usernameInput.maxLength = 50;
        usernameInput.pattern = "[A-Za-z0-9_.@-]+";
        usernameInput.setAttribute("aria-label", `Nombre de usuario ${user.username}`);
        usernameCell.append(usernameInput);

        const emailCell = document.createElement("td");
        const emailInput = document.createElement("input");
        emailInput.type = "email";
        emailInput.value = user.email;
        emailInput.maxLength = 254;
        emailInput.setAttribute("aria-label", `Correo electrónico de ${user.username}`);
        emailCell.append(emailInput);
        if (user.protected) {
          usernameInput.disabled = true;
          emailInput.disabled = true;
        }

        const roleCell = document.createElement("td");
        const roleSelect = document.createElement("select");
        roleSelect.setAttribute("aria-label", `Perfil de ${user.username}`);
        [["operator", "Operador"], ["admin", "Administrador"]].forEach(([value, label]) => {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = label;
          option.selected = value === user.role;
          roleSelect.append(option);
        });
        roleCell.append(roleSelect);
        if (user.protected) roleSelect.disabled = true;

        const statusCell = document.createElement("td");
        const enabledLabel = document.createElement("label");
        const enabledInput = document.createElement("input");
        enabledInput.type = "checkbox";
        enabledInput.checked = user.enabled;
        enabledInput.setAttribute("aria-label", `Usuario ${user.username} activo`);
        enabledLabel.append(enabledInput, document.createTextNode(" Activo"));
        if (user.protected) enabledInput.disabled = true;
        statusCell.append(enabledLabel);

        const actionsCell = document.createElement("td");
        const saveButton = document.createElement("button");
        saveButton.type = "button";
        saveButton.className = "secondary small-button";
        saveButton.dataset.userAction = "update";
        saveButton.textContent = "Guardar";
        const resetButton = document.createElement("button");
        resetButton.type = "button";
        resetButton.className = "secondary small-button";
        resetButton.dataset.userAction = "reset";
        resetButton.textContent = "Restablecer clave";
        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "danger-outline small-button";
        deleteButton.dataset.userAction = "delete";
        deleteButton.textContent = "Eliminar";
        if (user.protected) {
          actionsCell.textContent = "Protegido: solo cambia su clave desde su sesión.";
          actionsCell.className = "muted";
        } else {
          actionsCell.append(saveButton, resetButton, deleteButton);
        }
        row.append(usernameCell, emailCell, roleCell, statusCell, actionsCell);
        usersList.append(row);
      });
    }

    async function manageUser(payload) {
      usersMessage.textContent = "";
      temporaryPassword.hidden = true;
      const result = await api("/api/users", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      showNotice(usersMessage, result.message);
      if (result.temporary_password) {
        showTemporaryPassword(result.username, result.temporary_password);
      }
      if (result.acting_user_changed) {
        if (!result.temporary_password) {
          showNotice(usersMessage, `${result.message} Iniciá sesión nuevamente.`);
        }
        const loginLink = document.createElement("a");
        loginLink.href = `${appRoot}/login`;
        loginLink.textContent = "Iniciar sesión";
        loginLink.style.marginLeft = "10px";
        (result.temporary_password ? temporaryPassword : usersMessage).append(loginLink);
        return;
      }
      await loadUsers();
    }

    document.querySelector("#create-user-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      try {
        await manageUser({
          action: "create",
          username: form.get("username"),
          email: form.get("email"),
          role: form.get("role"),
        });
        event.currentTarget.reset();
      } catch (error) {
        showNotice(usersMessage, error.message, true);
      }
    });

    usersList.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-user-action]");
      if (!button) return;
      const row = button.closest("tr");
      const targetUsername = row.dataset.user;
      try {
        if (button.dataset.userAction === "reset") {
          if (!window.confirm(`¿Restablecer la clave de ${targetUsername}?`)) return;
          await manageUser({ action: "reset_password", target_username: targetUsername });
        } else if (button.dataset.userAction === "delete") {
          if (!window.confirm(`¿Eliminar definitivamente al usuario ${targetUsername}?`)) return;
          await manageUser({ action: "delete", target_username: targetUsername });
        } else {
          await manageUser({
            action: "update",
            target_username: targetUsername,
            username: row.querySelector("td:first-child input").value,
            email: row.querySelector("td:nth-child(2) input").value,
            role: row.querySelector("td:nth-child(3) select").value,
            enabled: row.querySelector("td:nth-child(4) input").checked,
          });
        }
      } catch (error) {
        showNotice(usersMessage, error.message, true);
      }
    });

    userManagement.addEventListener("toggle", () => {
      if (!userManagement.open) return;
      loadUsers().catch((error) => showNotice(usersMessage, error.message, true));
    });
  }

  async function refreshStatus() {
    try {
      const status = await api("/api/status");
      document.querySelector("#clock-count").textContent = status.configured_clocks;
    } catch (_) {
      document.querySelector("#server-status").textContent = "Sin conexión";
    }
  }
  refreshStatus();
})();
