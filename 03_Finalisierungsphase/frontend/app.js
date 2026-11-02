/* BookBridge Phase 3 — local application, no third-party browser dependencies. */
'use strict';
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { user: null, csrf: '', sessionReady: false, addresses: [], meta: { genres: [], languages: [] },
    loans: [], notifications: [], page: 1, loanFilter: 'all', catalogSequence: 0, sessionSequence: 0,
    memberSequences: { books: 0, loans: 0, notifications: 0 } };
  const weekdays = ['', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'];
  const conditions = { new: 'Neuwertig', very_good: 'Sehr gut', good: 'Gut', used: 'Gebraucht' };
  const statuses = { requested: 'Angefragt', accepted: 'Angenommen', outbound: 'Auf dem Hinweg', active: 'Ausgeliehen',
    returning: 'Rückgabe läuft', completed: 'Abgeschlossen', rejected: 'Abgelehnt', cancelled: 'Storniert',
    pending: 'Offen', approved: 'Genehmigt', withdrawn: 'Zurückgezogen', reported: 'Zahlung gemeldet',
    confirmed: 'Portoeingang bestätigt', prepared: 'Vorbereitet', sent: 'Versendet', received: 'Eingegangen' };
  const documentNames = { loan_confirmation: 'Ausleihbestätigung', shipment_summary: 'Versandübersicht', return_confirmation: 'Rückgabebestätigung' };
  let fieldSequence = 0;
  let lastDialogFocus = null;
  let dialogSequence = 0;
  const dialog = $('#app-dialog');

  // All server-provided text is inserted as text, never interpreted as markup.
  function el(tag, className = '', text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function button(text, action, primary = false) {
    const node = el('button', `button button-${primary ? 'primary' : 'secondary'}`, text);
    node.type = 'button';
    if (action) node.addEventListener('click', action);
    return node;
  }
  function link(text, href, className = '') {
    const node = el('a', className, text);
    node.href = href;
    return node;
  }
  function status(text, good = false) { return el('span', `status ${good ? 'status-available' : 'status-borrowed'}`, text); }
  function empty(root, text, login = false) {
    root.replaceChildren();
    const box = el('div', 'empty-state');
    box.append(el('p', '', text));
    if (login) box.append(link('Anmelden oder registrieren', '#account', 'button button-primary'));
    root.append(box);
  }
  function notice(text, error = false) {
    const node = $('#app-message');
    node.textContent = text;
    node.classList.toggle('is-error', error);
    node.hidden = false;
  }
  function formFeedback(form, text, success = false) {
    let node = $('.form-feedback', form);
    if (!node) { node = el('p', 'form-feedback'); node.setAttribute('role', 'alert'); form.append(node); }
    node.textContent = text;
    node.classList.toggle('success', success);
    node.hidden = !text;
    if (text && !success) { node.tabIndex = -1; node.focus(); }
  }
  function value(form, name) { return form.elements.namedItem(name)?.value.trim() || ''; }
  function number(form, name) { return Number(value(form, name)); }
  function isChecked(form, name) { return !!form.elements.namedItem(name)?.checked; }
  function safeId(value) {
    if (!/^\d+$/.test(String(value))) throw new Error('Dieser Eintrag ist nicht mehr verfügbar. Bitte aktualisiere die Ansicht.');
    return encodeURIComponent(String(value));
  }
  function activeMember() { return !!state.user && state.user.is_active !== false; }
  function activeAdmin() { return activeMember() && state.user.role === 'admin'; }
  function updateAccountLabel() { $('#account-link').textContent = state.user ? activeMember() ? `Hallo, ${state.user.first_name}` : 'Konto deaktiviert' : 'Mein Konto'; }
  async function api(path, options = {}) {
    const method = options.method || 'GET';
    const session = state.sessionSequence;
    const headers = { Accept: 'application/json' };
    if (method !== 'GET') { headers['Content-Type'] = 'application/json'; headers['X-CSRF-Token'] = state.csrf; }
    let response;
    try { response = await fetch(path, { method, credentials: 'same-origin', headers,
      ...(method !== 'GET' ? { body: JSON.stringify(options.body || {}) } : {}) }); }
    catch { throw new Error('Die Verbindung zu BookBridge ist unterbrochen. Prüfe, ob die Anwendung läuft, und versuche es erneut.'); }
    let data;
    try { data = await response.json(); }
    catch { throw new Error('BookBridge konnte die Antwort nicht lesen. Bitte lade die Seite neu.'); }
    if (data.csrf_token && session === state.sessionSequence) state.csrf = data.csrf_token;
    if (!response.ok) {
      if (response.status === 401 && !options.skipSessionRecovery && state.user && session === state.sessionSequence) {
        state.user = null; state.addresses = []; state.csrf = ''; state.sessionReady = false; state.sessionSequence++;
        if (dialog.open) closeDialog();
        renderAccount(); renderAddressPicker(); renderLoginStates();
        // The expired request may have received a fresh anonymous cookie.
        // Synchronize its CSRF token before exposing the login form again.
        // Only this safe GET is repeated; the original action is never retried.
        await loadSession();
      }
      throw new Error(data.error || 'Die Aktion konnte nicht ausgeführt werden. Bitte aktualisiere die Ansicht.');
    }
    return data;
  }
  function bindSubmit(form, handler) {
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (form.dataset.busy === 'true' || !form.reportValidity()) return;
      const submits = $$('button[type="submit"]', form);
      const previous = submits.map(node => node.disabled);
      form.dataset.busy = 'true'; form.setAttribute('aria-busy', 'true');
      submits.forEach(node => { node.disabled = true; });
      formFeedback(form, '');
      try { await handler(form); }
      catch (error) { formFeedback(form, error.message); }
      finally {
        form.dataset.busy = 'false'; form.removeAttribute('aria-busy');
        submits.forEach((node, index) => { node.disabled = previous[index]; });
      }
    });
  }
  function field(form, label, name, options = {}) {
    const wrapper = el('div', `form-group${options.type === 'checkbox' ? ' form-checkbox' : ''}`);
    const id = `field-${++fieldSequence}`;
    const control = el(options.choices ? 'select' : options.type === 'textarea' ? 'textarea' : 'input');
    control.id = id; control.name = name;
    if (!options.choices && options.type !== 'textarea') control.type = options.type || 'text';
    for (const key of ['required', 'min', 'max', 'step', 'maxLength', 'minLength', 'autocomplete', 'placeholder', 'rows']) {
      if (options[key] !== undefined) control[key] = options[key];
    }
    if (options.choices) for (const [idValue, title] of options.choices) {
      const option = el('option', '', title); option.value = idValue; control.append(option);
    }
    if (options.value !== undefined) control.value = options.value;
    if (options.checked !== undefined) control.checked = options.checked;
    const labelNode = el('label', '', label + (options.required ? ' *' : '')); labelNode.htmlFor = id;
    if (options.type === 'checkbox') wrapper.append(control, labelNode); else wrapper.append(labelNode, control);
    if (options.help) { const help = el('small', 'helper', options.help); help.id = `${id}-help`; control.setAttribute('aria-describedby', help.id); wrapper.append(help); }
    form.append(wrapper);
    return control;
  }
  function submitActions(form, text, cancel = false) {
    const actions = el('div', 'form-actions');
    const submit = button(text, null, true); submit.type = 'submit'; actions.append(submit);
    if (cancel) actions.append(button('Abbrechen', closeDialog));
    form.append(actions);
    return submit;
  }
  function openDialog(title) {
    if (!dialog.open) lastDialogFocus = document.activeElement;
    dialogSequence++;
    $('#dialog-title').textContent = title;
    const content = $('#dialog-content'); content.replaceChildren();
    if (!dialog.open) dialog.showModal();
    return content;
  }
  function closeDialog() { dialogSequence++; dialog.close(); }
  dialog.addEventListener('close', () => {
    if (dialog.open) return;
    dialogSequence++;
    if (lastDialogFocus?.isConnected) lastDialogFocus.focus();
    else $('#main-content').focus({ preventScroll: true });
  });
  $('#dialog-close').addEventListener('click', closeDialog);
  function dialogForm(title, text = '') {
    const body = openDialog(title);
    const form = el('form', 'dialog-form');
    if (text) form.append(el('p', '', text));
    body.append(form);
    return form;
  }
  function formatDate(raw, time = false) {
    if (!raw) return '–';
    const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(raw) ? `${raw}T12:00:00Z` : raw);
    if (Number.isNaN(date.getTime())) return String(raw);
    return new Intl.DateTimeFormat('de-DE', { timeZone: 'Europe/Berlin', dateStyle: 'medium', ...(time ? { timeStyle: 'short' } : {}) }).format(date);
  }
  function money(raw) { return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(Number(raw || 0)); }
  function addressText(address) { return `${address.street}, ${address.postal_code} ${address.city}, ${address.country_code}`; }
  function hasCoordinates(address) { return address.latitude !== null && address.latitude !== undefined && address.longitude !== null && address.longitude !== undefined; }
  function cover(item, className = 'book-cover') {
    const box = el('div', className);
    if (typeof item.cover_url === 'string' && /^\/pictures\/[a-z0-9._-]+\.(jpg|jpeg|png|webp)$/i.test(item.cover_url)) {
      const img = el('img'); img.src = item.cover_url; img.alt = `Buchcover: ${item.title}`; img.loading = 'lazy'; img.decoding = 'async';
      img.addEventListener('error', () => { box.replaceChildren(placeholder(item.title)); }, { once: true }); box.append(img);
    } else box.append(placeholder(item.title));
    return box;
  }
  function placeholder(title) { const node = el('div', 'cover-placeholder', title); node.append(el('small', '', 'Kein Cover hinterlegt')); return node; }
  function facts(entries, className = 'book-details') {
    const dl = el('dl', className);
    for (const [name, text] of entries) if (text !== null && text !== undefined && text !== '') {
      const div = el('div'); div.append(el('dt', '', name), el('dd', '', text)); dl.append(div);
    }
    return dl;
  }
  function bookCard(item, own = false) {
    const article = el('article', 'book-card');
    article.append(cover(item));
    const content = el('div', 'book-card-content');
    content.append(status(own && !item.is_active ? 'Angebot pausiert' : item.available ? 'Verfügbar' : 'Zurzeit vergeben', item.available && item.is_active !== false));
    content.append(el('h3', '', item.title), el('p', 'book-author', Array.isArray(item.authors) ? item.authors.join(', ') : item.authors || 'Autor nicht angegeben'));
    const modes = [item.allow_pickup && 'Abholung', item.allow_shipping && 'Versand'].filter(Boolean).join(' / ');
    content.append(facts([['Genre', item.genre], ['Sprache', item.language], ['Zustand', conditions[item.condition] || item.condition],
      ['Ort', [item.postal_code, item.city].filter(Boolean).join(' ')], ['Leihdauer', `Bis zu ${item.max_loan_days} Tage`],
      ['Übergabe', modes], ['Entfernung', item.distance_km !== undefined && item.distance_km !== null ? `${Number(item.distance_km).toLocaleString('de-DE', { maximumFractionDigits: 1 })} km` : null]]));
    if (own) {
      const actions = el('div', 'form-actions');
      const toggle = button(item.is_active ? 'Pausieren' : 'Aktivieren', () => toggleOffer(item));
      toggle.disabled = !activeMember();
      if (toggle.disabled) toggle.title = 'Dein Konto muss zuerst durch eine Administration reaktiviert werden.';
      actions.append(button('Bearbeiten', () => editOffer(item)), toggle);
      content.append(actions);
    } else {
      const details = button('Details & Ausleihe', () => openBook(item.copy_id), true);
      details.setAttribute('aria-label', `Details und Ausleihe: ${item.title}`); content.append(details);
    }
    article.append(content); return article;
  }

  async function loadCatalog(page = 1) {
    const form = $('#search-form');
    const params = new URLSearchParams({ page: String(page), available_only: String(isChecked(form, 'available_only')) });
    for (const name of ['query', 'genre_id', 'language_id', 'city']) if (value(form, name)) params.set(name, value(form, name));
    if (value(form, 'radius')) {
      if (!value(form, 'latitude') || !value(form, 'longitude')) {
        $('.search-origin', form).open = true;
        throw new Error('Bitte ergänze für die Umkreissuche beide Koordinaten oder übernimm deinen Standort.');
      }
      for (const name of ['radius', 'latitude', 'longitude']) params.set(name, value(form, name));
    }
    const sequence = ++state.catalogSequence;
    const root = $('#book-list'); root.setAttribute('aria-busy', 'true'); root.classList.add('busy');
    $('#catalog-count').textContent = 'Bücher werden geladen …';
    try {
      const data = await api(`/api/catalog?${params}`);
      if (sequence !== state.catalogSequence) return;
      state.page = Number(data.page || page);
      root.replaceChildren(...(data.items || []).map(item => bookCard(item)));
      if (!data.items?.length) empty(root, 'Keine passenden Bücher gefunden. Versuche einen anderen Suchbegriff oder erweitere deine Filter.');
      const total = Number(data.total || 0);
      $('#catalog-count').textContent = `${total} ${total === 1 ? 'Buch gefunden' : 'Bücher gefunden'}`;
      const pagination = $('#catalog-pages'); pagination.replaceChildren();
      const pages = Math.max(1, Math.ceil(total / Number(data.page_size || 12)));
      if (pages > 1) {
        const previous = button('← Zurück', () => navigateCatalog(state.page - 1)); previous.disabled = state.page <= 1;
        const next = button('Weiter →', () => navigateCatalog(state.page + 1)); next.disabled = state.page >= pages;
        pagination.append(previous, el('span', '', `Seite ${state.page} von ${pages}`), next);
      }
    } catch (error) {
      if (sequence !== state.catalogSequence) return;
      empty(root, error.message); root.firstChild.append(button('Erneut versuchen', () => navigateCatalog(page)));
      $('#catalog-count').textContent = 'Katalog konnte nicht geladen werden.'; $('#catalog-pages').replaceChildren();
      throw error;
    } finally { if (sequence === state.catalogSequence) { root.setAttribute('aria-busy', 'false'); root.classList.remove('busy'); } }
  }
  async function navigateCatalog(page) {
    try { await loadCatalog(page); $('#books-title').tabIndex = -1; $('#books-title').focus(); }
    catch (error) { formFeedback($('#search-form'), error.message); }
  }
  async function openBook(copyId) {
    const body = openDialog('Buch wird geladen …'); body.append(el('p', 'helper', 'Einen Moment bitte.'));
    const sequence = dialogSequence;
    try {
      const data = await api(`/api/catalog/${safeId(copyId)}`);
      if (!dialog.open || sequence !== dialogSequence) return;
      const item = data.item; $('#dialog-title').textContent = item.title; body.replaceChildren();
      body.append(cover(item, 'dialog-cover'), el('p', 'book-author', Array.isArray(item.authors) ? item.authors.join(', ') : item.authors));
      body.append(facts([['Genre', item.genre], ['Sprache', item.language], ['Zustand', conditions[item.condition]], ['Ort', [item.postal_code, item.city].filter(Boolean).join(' ')], ['Leihdauer', `Bis zu ${item.max_loan_days} Tage`]]));
      if (item.description) body.append(el('p', 'dialog-book-description', item.description));
      if (item.notes) body.append(el('p', 'helper', item.notes));
      const clear = el('div', 'dialog-clear'); body.append(clear);
      if (data.pickup_slots?.length) {
        clear.append(el('h3', '', 'Wöchentliche Abholzeiten'));
        for (const slot of data.pickup_slots) clear.append(el('p', 'helper', `${weekdays[slot.weekday]} · ${slot.start_time.slice(0, 5)}–${slot.end_time.slice(0, 5)} Uhr (Deutschland)`));
      }
      if (!state.user) {
        const login = button('Zum Ausleihen anmelden', () => { closeDialog(); location.hash = 'account'; $('#login-email')?.focus(); }, true); clear.append(login);
      } else if (String(item.owner_id) === String(state.user.user_id)) clear.append(el('p', 'helper', 'Das ist dein eigenes Angebot. Du kannst es unter „Meine Bücher“ bearbeiten.'));
      else if (!activeMember()) clear.append(el('p', 'helper', 'Dein Konto ist deaktiviert. Neue Ausleihanfragen sind nach einer Reaktivierung durch eine Administration wieder möglich. Deine laufenden Ausleihen findest du unter „Meine Ausleihen“.'));
      else if (!item.available) clear.append(el('p', 'helper', 'Dieses Buch ist zurzeit vergeben. Du kannst später erneut nachsehen.'));
      else {
        const form = el('form', 'dialog-form');
        field(form, 'Gewünschte Leihdauer (Tage)', 'days', { type: 'number', min: 1, max: item.max_loan_days, step: 1, value: Math.min(14, item.max_loan_days), required: true });
        const choices = []; if (item.allow_pickup) choices.push(['pickup', 'Persönlich abholen']); if (item.allow_shipping) choices.push(['shipping', 'Versand per Post']);
        field(form, 'Übergabe', 'mode', { choices, required: true });
        form.append(el('p', 'helper', 'Die Anfrage wird erst nach Annahme verbindlich. Den Abholtermin oder das Porto vereinbart ihr im nächsten Schritt.'));
        submitActions(form, 'Ausleihe anfragen', true);
        bindSubmit(form, async () => {
          const requestSequence = dialogSequence;
          await api('/api/loans', { method: 'POST', body: { copy_id: Number(item.copy_id), days: number(form, 'days'), mode: value(form, 'mode') } });
          if (requestSequence === dialogSequence) closeDialog(); notice('Deine Ausleihanfrage wurde gesendet. Du findest sie unter „Meine Ausleihen“.'); await refreshMember();
        }); clear.append(form);
      }
      clear.append(el('h3', 'subheading', 'Bewertungen'));
      const reviews = el('ul', 'review-list');
      for (const review of data.reviews || []) { const li = el('li'); li.append(el('strong', '', `${review.rating} von 5 Sternen · ${review.first_name || 'Mitglied'}`)); if (review.comment) li.append(el('p', '', review.comment)); reviews.append(li); }
      if (!reviews.children.length) clear.append(el('p', 'helper', 'Für dieses Buch gibt es noch keine Bewertungen.')); else clear.append(reviews);
    } catch (error) {
      if (!dialog.open || sequence !== dialogSequence) return;
      $('#dialog-title').textContent = 'Buch nicht verfügbar'; body.replaceChildren(el('p', 'form-feedback', error.message), button('Schließen', closeDialog));
    }
  }

  function fillMeta() {
    for (const [selector, collection, key, placeholder] of [
      ['#filter-genre', 'genres', 'genre_id', 'Alle Genres'], ['#book-genre', 'genres', 'genre_id', 'Bitte auswählen'],
      ['#filter-language', 'languages', 'language_id', 'Alle Sprachen'], ['#book-language', 'languages', 'language_id', 'Bitte auswählen']]) {
      const control = $(selector); control.replaceChildren();
      const first = el('option', '', placeholder); first.value = ''; control.append(first);
      for (const item of state.meta[collection]) { const option = el('option', '', item.name); option.value = item[key]; control.append(option); }
    }
  }
  function renderAddressPicker() {
    const select = $('#book-address'); const previous = select.value;
    const first = el('option', '', 'Adresse mit Standort auswählen'); first.value = ''; select.replaceChildren(first);
    for (const address of state.addresses) {
      const option = el('option', '', `${addressText(address)}${!hasCoordinates(address) ? ' (Standort fehlt)' : ''}`);
      option.value = address.address_id; option.disabled = !hasCoordinates(address); select.append(option);
    }
    if ([...select.options].some(option => option.value === previous && !option.disabled)) select.value = previous;
    else if (state.addresses.filter(hasCoordinates).length === 1) select.value = state.addresses.filter(hasCoordinates)[0].address_id;
    $('#offer-fields').disabled = !activeMember(); $('#save-book').disabled = !activeMember();
    const note = $('#offer-login-note'); note.replaceChildren();
    if (!state.user) note.append(link('Melde dich an, um Bücher anzubieten.', '#account'));
    else if (!activeMember()) note.append(link('Dein Konto ist deaktiviert. Laufende Ausleihen kannst du weiterhin abschließen.', '#my-loans'));
    else if (!state.addresses.some(hasCoordinates)) note.append(link('Bitte speichere zuerst eine Adresse mit Standort.', '#addresses'));
  }
  function addSlot(root = $('#pickup-slots'), slot = {}, form = $('#add-book-form'), addControl = $('#add-slot')) {
    if (root.children.length >= 14) { formFeedback(form, 'Du kannst bis zu 14 Abholfenster anlegen.'); return; }
    const row = el('div', 'slot-row');
    field(row, 'Wochentag', 'weekday', { choices: weekdays.slice(1).map((day, index) => [String(index + 1), day]), value: slot.weekday || 1, required: true });
    field(row, 'Von', 'start_time', { type: 'time', value: slot.start_time?.slice(0, 5) || '17:00', required: true });
    field(row, 'Bis', 'end_time', { type: 'time', value: slot.end_time?.slice(0, 5) || '19:00', required: true });
    const remove = button('Entfernen', () => {
      const next = row.nextElementSibling || row.previousElementSibling;
      row.remove(); (next ? $('select', next) : addControl).focus();
    });
    remove.setAttribute('aria-label', 'Dieses Abholfenster entfernen'); row.append(remove); root.append(row);
  }
  function readSlots(root, allowPickup) {
    const slots = allowPickup ? $$('.slot-row', root).map(row => ({ weekday: Number($('[name="weekday"]', row).value), start_time: $('[name="start_time"]', row).value, end_time: $('[name="end_time"]', row).value })) : [];
    if (allowPickup && !slots.length) throw new Error('Bitte ergänze mindestens ein wöchentliches Abholfenster.');
    if (slots.some(slot => !slot.start_time || !slot.end_time || slot.end_time <= slot.start_time)) throw new Error('Jedes Abholfenster benötigt eine Endzeit nach der Startzeit am selben Tag.');
    return slots;
  }
  function togglePickup() {
    const visible = $('#allow-pickup').checked; $('#pickup-options').hidden = !visible;
    $$('input,select,button', $('#pickup-options')).forEach(control => { control.disabled = !visible; });
  }
  function coordinates(form, latitudeName = 'latitude', longitudeName = 'longitude') {
    const latitude = value(form, latitudeName); const longitude = value(form, longitudeName);
    if (!!latitude !== !!longitude) throw new Error('Bitte gib Breitengrad und Längengrad zusammen an.');
    return latitude && longitude ? { latitude: Number(latitude), longitude: Number(longitude) } : {};
  }
  async function geolocate(form, control) {
    if (!navigator.geolocation) { formFeedback(form, 'Dein Browser unterstützt keine Standortabfrage. Bitte trage die Koordinaten selbst ein.'); return; }
    control.disabled = true; const previous = control.textContent; control.textContent = 'Standort wird ermittelt …';
    navigator.geolocation.getCurrentPosition(position => {
      form.elements.namedItem('latitude').value = position.coords.latitude.toFixed(6);
      form.elements.namedItem('longitude').value = position.coords.longitude.toFixed(6);
      formFeedback(form, 'Standort übernommen. Du kannst die Koordinaten vor dem Speichern prüfen.', true);
      control.disabled = false; control.textContent = previous;
    }, () => {
      formFeedback(form, 'Der Standort konnte nicht übernommen werden. Erlaube den Standortzugriff im Browser oder trage die Koordinaten selbst ein.');
      control.disabled = false; control.textContent = previous;
    }, { enableHighAccuracy: false, timeout: 12000, maximumAge: 60000 });
  }
  function toggleOffer(item) {
    const form = dialogForm(item.is_active ? 'Angebot pausieren' : 'Angebot aktivieren', item.is_active ? `„${item.title}“ wird danach nicht mehr im Katalog angeboten. Laufende Ausleihen bleiben in deiner Übersicht.` : `„${item.title}“ wird wieder im Katalog angeboten.`);
    submitActions(form, item.is_active ? 'Angebot pausieren' : 'Angebot aktivieren', true);
    bindSubmit(form, async () => {
      const sequence = dialogSequence;
      await api(`/api/books/${safeId(item.copy_id)}`, { method: 'PATCH', body: { is_active: !item.is_active } });
      if (sequence === dialogSequence) closeDialog(); notice('Dein Angebot wurde aktualisiert.'); await Promise.allSettled([loadMyBooks(), loadCatalog(state.page)]);
    });
  }
  function editOffer(item) {
    const form = dialogForm('Angebot bearbeiten', item.title);
    field(form, 'Zustand', 'condition', { choices: Object.entries(conditions), value: item.condition, required: true });
    field(form, 'Maximale Leihdauer (Tage)', 'max_loan_days', { type: 'number', min: 1, max: 90, step: 1, value: item.max_loan_days, required: true });
    field(form, 'Hinweise zur Übergabe / Zustand', 'notes', { type: 'textarea', maxLength: 500, value: item.notes || '' });
    const addresses = state.addresses.filter(address => !item.is_active || hasCoordinates(address));
    field(form, 'Eigene Adresse', 'address_id', { choices: [['', 'Bitte auswählen'], ...addresses.map(address => [address.address_id, addressText(address)])], value: item.pickup_address_id || item.address_id || '', required: true });
    form.append(el('p', 'helper', 'Aktive Angebote benötigen eine Adresse mit Standort. Eine neue Adresse kannst du in deinem Konto speichern.'));
    const pickup = field(form, 'Persönliche Abholung anbieten', 'allow_pickup', { type: 'checkbox', checked: item.allow_pickup });
    const options = el('div', 'offer-pickup-editor');
    options.append(el('p', 'helper', 'Wöchentliche Abholzeiten in Europe/Berlin. Für Abholung ist mindestens ein Zeitfenster nötig.'));
    const slotsRoot = el('div'); const add = button('Weiteres Zeitfenster', () => addSlot(slotsRoot, {}, form, add)); options.append(slotsRoot, add); form.append(options);
    for (const slot of item.pickup_slots || []) addSlot(slotsRoot, slot, form, add);
    if (!slotsRoot.children.length) addSlot(slotsRoot, {}, form, add);
    const toggle = () => { options.hidden = !pickup.checked; $$('input,select,button', options).forEach(control => { control.disabled = !pickup.checked; }); };
    pickup.addEventListener('change', toggle); toggle();
    field(form, 'Versand per Post anbieten', 'allow_shipping', { type: 'checkbox', checked: item.allow_shipping });
    form.append(el('p', 'helper', 'Änderungen gelten für künftige Vereinbarungen. Bereits angenommene Ausleihen behalten ihre gespeicherte Adresse, Abholzeit und Leihfrist. Frühere Zeitfenster bleiben in der Historie erhalten.'));
    submitActions(form, 'Änderungen speichern', true);
    bindSubmit(form, async () => {
      if (!isChecked(form, 'allow_pickup') && !isChecked(form, 'allow_shipping')) throw new Error('Bitte biete mindestens eine Übergabeart an: Abholung oder Versand.');
      if (!addresses.some(address => String(address.address_id) === value(form, 'address_id'))) throw new Error('Bitte wähle eine eigene Adresse; aktive Angebote benötigen beide Koordinaten.');
      const slots = readSlots(slotsRoot, isChecked(form, 'allow_pickup'));
      const sequence = dialogSequence;
      await api(`/api/books/${safeId(item.copy_id)}`, { method: 'PATCH', body: { condition: value(form, 'condition'), max_loan_days: number(form, 'max_loan_days'), notes: value(form, 'notes'), address_id: number(form, 'address_id'), allow_pickup: isChecked(form, 'allow_pickup'), allow_shipping: isChecked(form, 'allow_shipping'), pickup_slots: slots } });
      if (sequence === dialogSequence) closeDialog(); notice('Dein Angebot wurde gespeichert.'); await Promise.allSettled([loadMyBooks(), loadCatalog(state.page)]);
    });
  }

  function renderAccount() {
    const root = $('#account-content'); root.replaceChildren();
    updateAccountLabel();
    $('#account-intro').textContent = state.user ? 'Verwalte dein Profil und deine privaten Adressen.' : 'Melde dich an oder werde Teil der BookBridge-Nachbarschaft.';
    if (!state.sessionReady) { empty(root, 'Dein Konto wird geladen …'); return; }
    if (!state.user) {
      const grid = el('div', 'account-grid');
      const login = el('form', 'panel'); login.id = 'login-form'; login.append(el('h3', '', 'Willkommen zurück'));
      const email = field(login, 'E-Mail-Adresse', 'email', { type: 'email', maxLength: 254, autocomplete: 'username', required: true }); email.id = 'login-email'; $('label', email.parentNode).htmlFor = email.id;
      field(login, 'Passwort', 'password', { type: 'password', autocomplete: 'current-password', required: true });
      submitActions(login, 'Anmelden');
      bindSubmit(login, async () => { const data = await api('/api/login', { method: 'POST', body: { email: value(login, 'email'), password: login.elements.password.value } }); await applySession(data); notice('Du bist angemeldet. Willkommen bei BookBridge.'); });
      const register = el('form', 'panel'); register.id = 'register-form'; register.append(el('h3', '', 'Neu bei BookBridge?'));
      field(register, 'Vorname', 'first_name', { maxLength: 80, autocomplete: 'given-name', required: true });
      field(register, 'Nachname', 'last_name', { maxLength: 80, autocomplete: 'family-name', required: true });
      field(register, 'E-Mail-Adresse', 'email', { type: 'email', maxLength: 254, autocomplete: 'username', required: true });
      field(register, 'Passwort', 'password', { type: 'password', minLength: 12, maxLength: 128, autocomplete: 'new-password', required: true, help: 'Mindestens 12 Zeichen. Verwende ein eigenes Passwort für BookBridge.' });
      field(register, 'Passwort wiederholen', 'password_repeat', { type: 'password', minLength: 12, maxLength: 128, autocomplete: 'new-password', required: true });
      submitActions(register, 'Konto erstellen');
      bindSubmit(register, async () => {
        if (register.elements.password.value !== register.elements.password_repeat.value) throw new Error('Die beiden Passwörter stimmen nicht überein.');
        const data = await api('/api/register', { method: 'POST', body: { first_name: value(register, 'first_name'), last_name: value(register, 'last_name'), email: value(register, 'email'), password: register.elements.password.value } });
        await applySession(data); notice('Dein Konto wurde erstellt. Ergänze nun eine Adresse, um ein Buch anzubieten.');
      });
      grid.append(login, register); root.append(grid); return;
    }
    const toolbar = el('div', 'account-toolbar'); toolbar.append(el('p', '', `Angemeldet als ${state.user.first_name} ${state.user.last_name} · ${state.user.email}`));
    toolbar.append(link('Meine Mitteilungen', '#notifications', 'button button-secondary'));
    toolbar.append(button('Abmelden', async event => {
      const control = event.currentTarget; control.disabled = true;
      try { const data = await api('/api/logout', { method: 'POST' }); await applySession(data); notice('Du bist abgemeldet.'); }
      catch (error) { notice(error.message, true); control.disabled = false; }
    })); root.append(toolbar);
    if (!activeMember()) {
      const message = el('p', 'account-state-message'); message.setAttribute('role', 'status');
      message.textContent = 'Dein Konto ist deaktiviert. Deine Angebote sind pausiert und neue Anfragen sind gesperrt. Laufende Ausleihen, Rückgaben, Porto, Versand und Bewertungen kannst du weiter bearbeiten. Eine Administration kann dein Konto reaktivieren; Angebote aktivierst du danach einzeln.';
      root.append(message);
    }
    const grid = el('div', 'account-grid');
    const profile = el('form', 'panel'); profile.id = 'profile-form'; profile.append(el('h3', '', 'Mein Profil'));
    field(profile, 'Vorname', 'first_name', { value: state.user.first_name, maxLength: 80, autocomplete: 'given-name', required: true });
    field(profile, 'Nachname', 'last_name', { value: state.user.last_name, maxLength: 80, autocomplete: 'family-name', required: true });
    submitActions(profile, 'Profil speichern');
    bindSubmit(profile, async () => {
      const data = await api('/api/profile', { method: 'PATCH', body: { first_name: value(profile, 'first_name'), last_name: value(profile, 'last_name') } });
      state.user = data.user; updateAccountLabel(); renderAddressPicker();
      toolbar.firstChild.textContent = `Angemeldet als ${state.user.first_name} ${state.user.last_name} · ${state.user.email}`;
      formFeedback(profile, 'Dein Profil wurde gespeichert.', true);
    });
    const password = el('form', 'panel'); password.id = 'password-form'; password.append(el('h3', '', 'Passwort ändern'));
    field(password, 'Bisheriges Passwort', 'current_password', { type: 'password', autocomplete: 'current-password', required: true });
    field(password, 'Neues Passwort', 'new_password', { type: 'password', minLength: 12, maxLength: 128, autocomplete: 'new-password', required: true });
    field(password, 'Neues Passwort wiederholen', 'password_repeat', { type: 'password', minLength: 12, maxLength: 128, autocomplete: 'new-password', required: true });
    submitActions(password, 'Passwort ändern');
    bindSubmit(password, async () => {
      if (password.elements.new_password.value !== password.elements.password_repeat.value) throw new Error('Die beiden neuen Passwörter stimmen nicht überein.');
      await api('/api/password', { method: 'POST', body: { current_password: password.elements.current_password.value, new_password: password.elements.new_password.value } });
      password.reset(); formFeedback(password, 'Dein Passwort wurde geändert. Andere angemeldete Sitzungen wurden beendet.', true);
    });
    grid.append(profile, password); root.append(grid);
    if (activeMember()) {
      const accountControl = el('div', 'panel account-control'); accountControl.append(el('h3', '', 'Konto deaktivieren'));
      accountControl.append(el('p', 'helper', 'Du kannst dein Konto vorübergehend deaktivieren. Deine Angebote werden dabei pausiert. Die Reaktivierung erfolgt durch eine Administration; laufende Ausleihen bleiben für dich zugänglich.'));
      accountControl.append(button('Konto deaktivieren', deactivateAccount)); root.append(accountControl);
    }
    const addressPanel = el('div', 'panel address-panel'); addressPanel.id = 'addresses'; addressPanel.append(el('h3', '', 'Meine Adressen'));
    addressPanel.append(el('p', 'helper', 'Deine Straße ist im öffentlichen Katalog nicht sichtbar. Für ein Buchangebot werden beide Koordinaten benötigt. Eine Lieferadresse darf auch ohne Koordinaten gespeichert werden.'));
    const addressList = el('div', 'address-list'); addressList.id = 'address-list'; addressPanel.append(addressList); renderAddresses(addressList);
    const addressForm = el('form'); addressForm.id = 'address-form'; addressForm.append(el('h3', '', 'Adresse hinzufügen'));
    addressFields(addressForm);
    const locationButton = button('Meinen Standort übernehmen', () => geolocate(addressForm, locationButton)); locationButton.classList.add('address-location'); addressForm.append(locationButton);
    submitActions(addressForm, 'Adresse speichern');
    bindSubmit(addressForm, async () => {
      await api('/api/addresses', { method: 'POST', body: addressBody(addressForm) });
      const result = await api('/api/addresses'); state.addresses = result.addresses || []; renderAddresses(addressList); renderAddressPicker();
      addressForm.reset(); formFeedback(addressForm, 'Deine Adresse wurde gespeichert.', true);
    }); addressPanel.append(addressForm); root.append(addressPanel);
    if (activeAdmin()) renderAdmin(root);
  }
  function deactivateAccount() {
    const form = dialogForm('Konto deaktivieren', 'Dein Konto wird deaktiviert und alle deine Angebote werden pausiert. Du kannst dich weiterhin anmelden, um bestehende Ausleihen abzuschließen. Neue Angebote und Ausleihanfragen sind gesperrt. Nur eine Administration kann dein Konto später reaktivieren. Deine bisherigen Daten und Vereinbarungen bleiben erhalten.');
    submitActions(form, 'Konto jetzt deaktivieren', true);
    bindSubmit(form, async () => {
      const sequence = dialogSequence;
      const data = await api('/api/account/deactivate', { method: 'POST' });
      if (sequence === dialogSequence) closeDialog();
      await applySession({ user: data.user, addresses: state.addresses });
      notice('Dein Konto ist deaktiviert. Deine laufenden Ausleihen bleiben zugänglich.'); await loadCatalog(state.page);
    });
  }
  function renderAdmin(root) {
    const panel = el('section', 'panel admin-panel'); panel.id = 'admin-panel'; panel.setAttribute('aria-labelledby', 'admin-title');
    const heading = el('div', 'section-toolbar'); const intro = el('div'); const title = el('h3', '', 'Administration'); title.id = 'admin-title';
    intro.append(title, el('p', 'helper', 'Mitglieder und Angebote aktivieren oder deaktivieren. Vereinbarte Ausleihen bleiben erhalten.'));
    const refresh = button('Aktualisieren', () => loadAdmin(panel)); refresh.setAttribute('aria-label', 'Administration aktualisieren');
    heading.append(intro, refresh); panel.append(heading);
    const content = el('div', 'admin-content'); panel.append(content); root.append(panel); loadAdmin(panel);
  }
  async function loadAdmin(panel) {
    if (!activeAdmin() || !panel.isConnected) return;
    const content = $('.admin-content', panel); const control = $('button', panel); const session = state.sessionSequence;
    const sequence = Number(panel.dataset.sequence || 0) + 1; panel.dataset.sequence = String(sequence);
    panel.setAttribute('aria-busy', 'true'); control.disabled = true;
    const current = () => activeAdmin() && panel.isConnected && session === state.sessionSequence && panel.dataset.sequence === String(sequence);
    if (!content.children.length) content.append(el('p', 'helper', 'Mitglieder und Angebote werden geladen …'));
    try {
      const [users, offers] = await Promise.all([api('/api/admin/users'), api('/api/admin/offers')]);
      if (!current()) return;
      content.replaceChildren();
      for (const [kind, title, items] of [['users', 'Mitglieder', users.items || []], ['offers', 'Buchangebote', offers.items || []]]) {
        const group = el('details', 'admin-group'); group.open = true; group.append(el('summary', '', `${title} (${items.length})`));
        const list = el('div', 'admin-list');
        for (const item of items) {
          const row = el('article', 'admin-row'); const info = el('div');
          const name = kind === 'users' ? `${item.first_name} ${item.last_name}` : item.title;
          info.append(el('h4', '', name), el('p', 'helper', kind === 'users' ? `${item.email} · ${item.role === 'admin' ? 'Administration' : 'Mitglied'} · Nr. ${item.user_id}` : `${item.owner_name} · Angebot Nr. ${item.copy_id}`));
          info.append(status(item.is_active ? 'Aktiv' : 'Deaktiviert', item.is_active));
          const toggle = button(item.is_active ? 'Deaktivieren' : 'Aktivieren', () => moderateItem(panel, kind, item, name));
          toggle.setAttribute('aria-label', `${name}: ${item.is_active ? 'deaktivieren' : 'aktivieren'}`); row.append(info, toggle); list.append(row);
        }
        if (!items.length) list.append(el('p', 'helper', 'Hier gibt es noch keine Einträge.'));
        group.append(list); content.append(group);
      }
    } catch (error) {
      if (current()) { content.replaceChildren(el('p', 'form-feedback', error.message)); content.append(button('Erneut versuchen', () => loadAdmin(panel))); }
    } finally { if (current()) { panel.setAttribute('aria-busy', 'false'); control.disabled = false; } }
  }
  function moderateItem(panel, kind, item, name) {
    const activate = !item.is_active; const title = `${kind === 'users' ? 'Mitglied' : 'Angebot'} ${activate ? 'aktivieren' : 'deaktivieren'}`;
    const text = kind === 'users' ? activate ? 'Das Mitglied kann danach wieder neue Anfragen und Angebote erstellen. Bisher pausierte Angebote bleiben pausiert und müssen einzeln aktiviert werden.' : 'Das Mitglied wird deaktiviert und seine Angebote werden pausiert. Es kann sich weiterhin anmelden, um laufende Ausleihen abzuschließen. Eine Administration kann es später reaktivieren.' : activate ? 'Das Angebot wird wieder im Katalog sichtbar, wenn das Konto der verleihenden Person aktiv ist. Laufende Ausleihen bleiben erhalten.' : 'Das Angebot wird aus dem öffentlichen Katalog genommen. Laufende Ausleihen bleiben erhalten. Das Angebot kann später wieder aktiviert werden.';
    const form = dialogForm(title, `${name}\n\n${text}`); submitActions(form, title, true);
    bindSubmit(form, async () => {
      const sequence = dialogSequence; const id = kind === 'users' ? item.user_id : item.copy_id;
      const data = await api(`/api/admin/${kind}/${safeId(id)}`, { method: 'PATCH', body: { is_active: activate } });
      if (sequence === dialogSequence) closeDialog();
      if (kind === 'users' && String(item.user_id) === String(state.user?.user_id)) await applySession({ user: data.user, addresses: state.addresses });
      else await Promise.allSettled([loadAdmin(panel), refreshMember()]);
      notice(`${title}: gespeichert.`); await loadCatalog(state.page);
    });
  }
  function renderAddresses(root) {
    root.replaceChildren();
    if (!state.addresses.length) { root.append(el('p', 'helper', 'Du hast noch keine Adresse gespeichert.')); return; }
    for (const address of state.addresses) {
      const item = el('div', 'address-item'); const info = el('div');
      info.append(el('p', '', addressText(address)), el('small', '', hasCoordinates(address) ? 'Mit Standort – für Abholung und Versand nutzbar' : 'Ohne Standort – als Lieferadresse nutzbar'));
      const edit = button('Bearbeiten', () => editAddress(address)); edit.setAttribute('aria-label', `Adresse bearbeiten: ${addressText(address)}`);
      item.append(info, edit); root.append(item);
    }
  }
  function addressFields(form, address = {}) {
    const grid = el('div', 'form-grid');
    field(grid, 'Straße und Hausnummer', 'street', { value: address.street || '', maxLength: 200, autocomplete: 'street-address', required: true });
    field(grid, 'Postleitzahl', 'postal_code', { value: address.postal_code || '', maxLength: 20, autocomplete: 'postal-code', required: true });
    field(grid, 'Stadt', 'city', { value: address.city || '', maxLength: 100, autocomplete: 'address-level2', required: true });
    field(grid, 'Länderkürzel', 'country_code', { value: address.country_code || 'DE', minLength: 2, maxLength: 2, autocomplete: 'country', required: true, help: 'Zwei Buchstaben, zum Beispiel DE oder AT.' });
    field(grid, 'Breitengrad (optional)', 'latitude', { value: address.latitude ?? '', type: 'number', min: -90, max: 90, step: 'any', placeholder: 'z. B. 51.20' });
    field(grid, 'Längengrad (optional)', 'longitude', { value: address.longitude ?? '', type: 'number', min: -180, max: 180, step: 'any', placeholder: 'z. B. 6.69' });
    form.append(grid);
  }
  function addressBody(form) {
    const body = { street: value(form, 'street'), postal_code: value(form, 'postal_code'), city: value(form, 'city'), country_code: value(form, 'country_code').toUpperCase(), latitude: null, longitude: null, ...coordinates(form) };
    if (!/^[A-Z]{2}$/.test(body.country_code)) throw new Error('Bitte gib ein Länderkürzel mit zwei Buchstaben an, zum Beispiel DE.');
    return body;
  }
  function editAddress(address) {
    const form = dialogForm('Adresse bearbeiten', 'Die Änderung gilt für künftige Vereinbarungen und Versandvorbereitungen. Bereits gespeicherte Abhol- und Versandanschriften laufender Ausleihen bleiben unverändert. Für Adressen in aktiven Buchangeboten müssen beide Koordinaten erhalten bleiben.');
    addressFields(form, address);
    const location = button('Meinen Standort übernehmen', () => geolocate(form, location)); form.append(location);
    submitActions(form, 'Adresse speichern', true);
    bindSubmit(form, async () => {
      const sequence = dialogSequence;
      await api(`/api/addresses/${safeId(address.address_id)}`, { method: 'PATCH', body: addressBody(form) });
      const result = await api('/api/addresses'); state.addresses = result.addresses || [];
      if (sequence === dialogSequence) closeDialog();
      const list = $('#address-list'); if (list) renderAddresses(list); renderAddressPicker();
      notice('Deine Adresse wurde aktualisiert. Bereits vereinbarte Anschriften bleiben erhalten.');
      await Promise.allSettled([refreshMember(), loadCatalog(state.page)]);
    });
  }
  function renderLoginStates() {
    if (state.user) return;
    empty($('#my-books-list'), 'Melde dich an, um deine Buchangebote zu verwalten.', true);
    empty($('#my-loans-list'), 'Melde dich an, um deine Anfragen und Ausleihen zu sehen.', true);
    empty($('#notification-list'), 'Deine Mitteilungen erscheinen nach der Anmeldung.', true);
    for (const selector of ['#my-books-list', '#my-loans-list', '#notification-list']) $(selector).setAttribute('aria-busy', 'false');
    $('#my-books-count').textContent = ''; $('#my-loans-count').textContent = '';
    $('#unread-count').textContent = ''; state.loans = []; state.notifications = [];
  }
  async function applySession(data) {
    state.sessionReady = true; state.user = data.user; state.csrf = data.csrf_token || state.csrf; state.addresses = data.addresses || [];
    state.sessionSequence++; state.loanFilter = 'all';
    renderAccount(); renderAddressPicker(); renderLoginStates(); updateLoanFilterButtons();
    if (state.user) await refreshMember();
  }
  function beginMemberLoad(key, root, message) {
    const request = { sequence: ++state.memberSequences[key], session: state.sessionSequence };
    root.setAttribute('aria-busy', 'true');
    if (!root.children.length || $('.empty-state', root)) empty(root, message);
    return request;
  }
  function currentMemberLoad(key, request) {
    return !!state.user && request.session === state.sessionSequence && request.sequence === state.memberSequences[key];
  }
  async function loadMyBooks() {
    if (!state.user) return;
    const root = $('#my-books-list'); const request = beginMemberLoad('books', root, 'Deine Bücher werden geladen …');
    try {
      const data = await api('/api/my-books'); if (!currentMemberLoad('books', request)) return;
      root.replaceChildren(...(data.items || []).map(item => bookCard(item, true)));
      const count = data.items?.length || 0;
      $('#my-books-count').textContent = `${count} ${count === 1 ? 'eigenes Buch' : 'eigene Bücher'}`;
      if (!data.items?.length) empty(root, 'Dein Bücherregal wartet auf die erste Geschichte. Biete oben ein Buch an.');
    } catch (error) { if (currentMemberLoad('books', request)) { empty(root, error.message); root.firstChild.append(button('Erneut versuchen', loadMyBooks)); $('#my-books-count').textContent = 'Deine Bücher konnten nicht geladen werden.'; } }
    finally { if (currentMemberLoad('books', request)) root.setAttribute('aria-busy', 'false'); }
  }

  async function loanAction(loan, action, fields = {}) {
    const sequence = dialogSequence;
    await api(`/api/loans/${safeId(loan.loan_id)}/actions`, { method: 'POST', body: { action, ...fields } });
    if (sequence === dialogSequence) closeDialog(); notice('Die Ausleihe wurde aktualisiert.');
    await Promise.allSettled([refreshMember(), loadCatalog(state.page)]);
  }
  function confirmAction(loan, action, title, text, fields = {}, submitText = 'Bestätigen') {
    const form = dialogForm(title, text); submitActions(form, submitText, true);
    bindSubmit(form, () => loanAction(loan, action, fields));
  }
  function daysAction(loan, action, title, max, initial = 7) {
    if (action === 'propose' && !activeMember()) { notice('Dein Konto ist deaktiviert. Neue Gegenvorschläge sind erst nach einer Reaktivierung möglich.', true); return; }
    const form = dialogForm(title, loan.title);
    field(form, action === 'request_extension' ? 'Zusätzliche Tage' : 'Vorgeschlagene Leihdauer (Tage)', 'days', { type: 'number', min: 1, max, step: 1, value: Math.min(initial, max), required: true });
    if (action === 'request_extension') form.append(el('p', 'helper', `Innerhalb der vereinbarten Höchstdauer sind noch ${max} zusätzliche Tage möglich. Die Verlängerung gilt erst nach Zustimmung.`));
    submitActions(form, action === 'request_extension' ? 'Verlängerung anfragen' : 'Gegenvorschlag senden', true);
    bindSubmit(form, () => loanAction(loan, action, { days: number(form, 'days') }));
  }
  function acceptAction(loan, proposal = null) {
    if (!activeMember()) { notice('Dein Konto ist deaktiviert. Neue Ausleihen sind erst nach einer Reaktivierung möglich.', true); return; }
    const form = dialogForm(proposal ? 'Gegenvorschlag annehmen' : 'Anfrage annehmen', `„${loan.title}“ · ${proposal ? proposal.proposed_days : loan.requested_days} Tage`);
    const availableSlots = (loan.pickup_slots || []).filter(slot => slot.next_start_at && slot.next_end_at && new Date(slot.next_start_at) > new Date());
    if (loan.handover_mode === 'pickup') {
      if (!availableSlots.length) {
        form.append(el('p', 'form-feedback', 'Für dieses Buch ist kein zukünftiges Abholfenster verfügbar. Bitte aktualisiere die Ansicht oder lehne die Anfrage ab.'));
        form.append(button('Schließen', closeDialog)); return;
      }
      field(form, 'Verbindliches Abholfenster', 'slot_id', { choices: availableSlots.map(slot => [slot.slot_id, `${weekdays[slot.weekday]} · ${formatDate(slot.next_start_at, true)}–${new Intl.DateTimeFormat('de-DE', { timeZone: 'Europe/Berlin', timeStyle: 'short' }).format(new Date(slot.next_end_at))} Uhr`]), required: true });
      form.append(el('p', 'helper', 'Alle Termine gelten in der Zeitzone Europe/Berlin. Die genaue Abholadresse wird nach Annahme sichtbar.'));
    } else form.append(el('p', 'helper', 'Nach Annahme legt die verleihende Person das Porto fest. Danach können Hin- und Rückversand vorbereitet werden.'));
    submitActions(form, 'Verbindlich annehmen', true);
    bindSubmit(form, () => {
      const body = proposal ? { proposal_id: Number(proposal.proposal_id), decision: 'accepted' } : {};
      if (loan.handover_mode === 'pickup') {
        const slot = availableSlots.find(candidate => String(candidate.slot_id) === value(form, 'slot_id'));
        if (!slot) throw new Error('Bitte wähle ein gültiges Abholfenster.');
        body.slot_id = Number(slot.slot_id); body.start_at = slot.next_start_at; body.end_at = slot.next_end_at;
      }
      return loanAction(loan, proposal ? 'decide_proposal' : 'accept', body);
    });
  }
  function postageAction(loan) {
    const form = dialogForm('Porto vereinbaren', 'Lege die Kosten für Hin- und Rückversand fest. Die ausleihende Person meldet anschließend ihre Zahlung; du bestätigst den Eingang.');
    field(form, 'Hinporto (EUR)', 'outbound_fee', { type: 'number', min: 0, max: 9999, step: '.01', value: '0.00', required: true });
    field(form, 'Rückporto (EUR)', 'return_fee', { type: 'number', min: 0, max: 9999, step: '.01', value: '0.00', required: true });
    form.append(el('p', 'helper', 'BookBridge dokumentiert eure Vereinbarung. Eine Überweisung oder Abbuchung wird hier nicht ausgeführt.'));
    submitActions(form, 'Porto festlegen', true);
    bindSubmit(form, () => loanAction(loan, 'create_postage', { outbound_fee: number(form, 'outbound_fee'), return_fee: number(form, 'return_fee') }));
  }
  function shipmentAction(loan, direction) {
    const form = dialogForm(direction === 'outbound' ? 'Hinversand vorbereiten' : 'Rückversand vorbereiten', loan.title);
    const senders = loan.sender_addresses || state.addresses; const recipients = loan.recipient_addresses || [];
    if (!senders.length || !recipients.length) {
      form.append(el('p', 'form-feedback', !senders.length ? 'Bitte speichere zuerst eine eigene Versandadresse in deinem Konto.' : 'Die andere Person hat noch keine Lieferadresse gespeichert. Sie muss diese zuerst in ihrem Konto ergänzen.'));
      if (!senders.length) form.append(link('Adresse hinzufügen', '#addresses', 'button button-primary'));
      const addressLink = $('a', form); addressLink?.addEventListener('click', closeDialog);
      form.append(button('Schließen', closeDialog)); return;
    }
    field(form, 'Absenderadresse (deine Adresse)', 'sender_address_id', { choices: senders.map(address => [address.address_id, addressText(address)]), required: true });
    field(form, 'Empfängeradresse', 'recipient_address_id', { choices: recipients.map(address => [address.address_id, addressText(address)]), required: true });
    field(form, 'Versanddienst (optional)', 'carrier', { maxLength: 80, placeholder: 'z. B. DHL' });
    field(form, 'Sendungsnummer (optional)', 'tracking_number', { maxLength: 120 });
    form.append(el('p', 'helper', 'Prüfe die Anschriften. Nach dem Vorbereiten werden sie für diese Sendung festgehalten. Bestätige den Versand erst, wenn das Buch tatsächlich unterwegs ist.'));
    submitActions(form, 'Sendung vorbereiten', true);
    bindSubmit(form, () => loanAction(loan, 'prepare_shipment', { direction, sender_address_id: number(form, 'sender_address_id'), recipient_address_id: number(form, 'recipient_address_id'), carrier: value(form, 'carrier') || null, tracking_number: value(form, 'tracking_number') || null }));
  }
  function reviewAction(loan) {
    const form = dialogForm('Ausleihe bewerten', `Wie war der Austausch zu „${loan.title}“?`);
    field(form, 'Bewertung', 'rating', { choices: [[5, '5 Sterne – ausgezeichnet'], [4, '4 Sterne – gut'], [3, '3 Sterne – in Ordnung'], [2, '2 Sterne – weniger gut'], [1, '1 Stern – schlecht']], required: true });
    field(form, 'Kommentar (optional)', 'comment', { type: 'textarea', maxLength: 1000, rows: 3 });
    submitActions(form, 'Bewertung abgeben', true);
    bindSubmit(form, () => loanAction(loan, 'review', { rating: number(form, 'rating'), comment: value(form, 'comment') || null }));
  }
  function loanSection(card, title) {
    const section = el('div', 'loan-subsection'); section.append(el('h4', '', title)); card.append(section); return section;
  }
  function loanCard(loan) {
    const card = el('article', 'loan-card'); card.id = `loan-${loan.loan_id}`;
    card.tabIndex = -1;
    const owner = loan.role === 'owner'; const shipping = loan.handover_mode === 'shipping';
    const heading = el('div', 'loan-heading'); const intro = el('div');
    intro.append(el('h3', '', loan.title), el('p', '', `${owner ? `Du verleihst an ${loan.borrower_name}` : `Du leihst von ${loan.owner_name}`} · ${shipping ? 'Versand per Post' : 'Persönliche Abholung'} · Nr. ${loan.loan_id}`));
    heading.append(intro, status(statuses[loan.status] || loan.status, ['active', 'completed'].includes(loan.status))); card.append(heading);
    card.append(facts([['Angefragt', formatDate(loan.requested_at)], ['Gewünscht', `${loan.requested_days} Tage`], ['Vereinbart', loan.agreed_days ? `${loan.agreed_days} Tage` : null], ['Rückgabe bis', loan.due_date ? formatDate(loan.due_date) : null]], 'loan-facts'));
    if (loan.due_date && ['active', 'returning'].includes(loan.status)) {
      const parts = new Intl.DateTimeFormat('de-DE', { timeZone: 'Europe/Berlin', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
      const dateParts = Object.fromEntries(parts.map(part => [part.type, part.value]));
      const today = `${dateParts.year}-${dateParts.month}-${dateParts.day}`;
      const days = Math.round((Date.parse(`${loan.due_date}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86400000);
      if (Number.isFinite(days) && days <= 3) {
        const reminder = el('p', `loan-reminder${days < 0 ? ' overdue' : ''}`, days < 0 ? `Rückgabe seit ${Math.abs(days)} ${days === -1 ? 'Tag' : 'Tagen'} überfällig.` : days === 0 ? 'Die Rückgabe ist heute fällig.' : `Die Rückgabe ist in ${days} ${days === 1 ? 'Tag' : 'Tagen'} fällig.`);
        card.append(reminder);
      }
    }
    if (loan.pickup_address_snapshot && loan.accepted_at) {
      const section = loanSection(card, 'Vereinbarte Abholung'); section.append(el('p', '', `${formatDate(loan.pickup_start_at, true)} bis ${formatDate(loan.pickup_end_at, true)} Uhr (Deutschland)`));
      section.append(el('p', 'private-address', loan.pickup_address_snapshot));
    }
    const actions = el('div', 'form-actions'); card.append(actions);
    const pendingProposal = (loan.proposals || []).find(proposal => proposal.status === 'pending');
    if (loan.status === 'requested') {
      if (owner) {
        if (!pendingProposal && activeMember()) {
          actions.append(button('Anfrage annehmen', () => acceptAction(loan), true));
          actions.append(button('Andere Leihdauer vorschlagen', () => daysAction(loan, 'propose', 'Leihdauer vorschlagen', Number(loan.max_loan_days || 90), Math.min(7, loan.requested_days))));
        }
        actions.append(button('Anfrage ablehnen', () => confirmAction(loan, 'reject', 'Anfrage ablehnen', `Möchtest du die Anfrage von ${loan.borrower_name} für „${loan.title}“ ablehnen?`, {}, 'Anfrage ablehnen')));
      } else actions.append(button('Anfrage zurückziehen', () => confirmAction(loan, 'cancel', 'Anfrage zurückziehen', `Möchtest du deine Anfrage für „${loan.title}“ zurückziehen?`, {}, 'Anfrage zurückziehen')));
    }
    if (loan.status === 'accepted' && !(loan.shipments || []).some(shipment => ['sent', 'received'].includes(shipment.status))) {
      actions.append(button('Ausleihe stornieren', () => confirmAction(loan, 'cancel', 'Ausleihe stornieren', `Möchtest du die angenommene Ausleihe für „${loan.title}“ stornieren?`, {}, 'Ausleihe stornieren')));
    }
    if (!owner && !shipping && loan.status === 'accepted') actions.prepend(button('Buch erhalten', () => confirmAction(loan, 'receive_pickup', 'Übergabe bestätigen', `Bestätige erst, wenn du „${loan.title}“ persönlich erhalten hast. Ab dieser Bestätigung beginnt die Leihfrist.`, {}, 'Erhalt bestätigen'), true));
    if (!owner && loan.status === 'active') {
      const remaining = Number(loan.max_loan_days_snapshot || 0) - Number(loan.agreed_days || 0) - (loan.extensions || []).filter(extension => extension.status === 'approved').reduce((sum, extension) => sum + Number(extension.extra_days), 0);
      if (remaining > 0 && !(loan.extensions || []).some(extension => extension.status === 'pending')) actions.append(button('Verlängerung anfragen', () => daysAction(loan, 'request_extension', 'Ausleihe verlängern', remaining)));
      if (!shipping) actions.append(button('Rückgabe beginnen', () => confirmAction(loan, 'start_return', 'Rückgabe beginnen', 'Bestätige, dass du das Buch jetzt persönlich zurückgibst. Anschließend bestätigt die verleihende Person den Rückerhalt.', {}, 'Rückgabe beginnen'), true));
    }
    if (owner && !shipping && loan.status === 'returning') actions.append(button('Buch zurückerhalten', () => confirmAction(loan, 'confirm_return', 'Rückerhalt bestätigen', `Hast du „${loan.title}“ zurückerhalten? Deine Bestätigung schließt die Ausleihe ab.`, {}, 'Rückerhalt bestätigen'), true));
    if (loan.status === 'completed' && !(loan.reviews || []).some(review => String(review.reviewer_id) === String(state.user.user_id))) actions.append(button('Ausleihe bewerten', () => reviewAction(loan), true));
    if (!actions.children.length) actions.remove();
    if (loan.status === 'requested' && !activeMember()) card.append(el('p', 'helper', 'Dein Konto ist deaktiviert. Du kannst diese Anfrage zurückziehen oder ablehnen; neue Vereinbarungen sind erst nach einer Reaktivierung möglich.'));
    if (loan.status === 'requested' && !owner && !pendingProposal) card.append(el('p', 'helper', 'Deine Anfrage wartet auf eine Antwort.'));
    if (loan.status === 'accepted' && !shipping && owner) card.append(el('p', 'helper', 'Die ausleihende Person bestätigt den Erhalt nach der persönlichen Übergabe.'));
    if (loan.proposals?.length) {
      const section = loanSection(card, 'Vorschläge zur Leihdauer');
      for (const proposal of loan.proposals) {
        section.append(el('p', 'history-line', `${proposal.proposed_days} Tage · ${statuses[proposal.status] || proposal.status}`));
        if (loan.status === 'requested' && proposal.status === 'pending' && !owner) {
          const row = el('div', 'form-actions'); if (activeMember()) row.append(button('Vorschlag annehmen', () => acceptAction(loan, proposal), true));
          row.append(button('Vorschlag ablehnen', () => confirmAction(loan, 'decide_proposal', 'Gegenvorschlag ablehnen', `Möchtest du den Vorschlag über ${proposal.proposed_days} Tage ablehnen? Deine ursprüngliche Anfrage bleibt offen.`, { proposal_id: Number(proposal.proposal_id), decision: 'rejected' }, 'Vorschlag ablehnen'))); section.append(row);
        } else if (loan.status === 'requested' && proposal.status === 'pending' && owner) {
          section.append(el('p', 'helper', 'Dein Gegenvorschlag wartet auf eine Antwort.'));
          section.append(button('Gegenvorschlag zurückziehen', () => confirmAction(loan, 'decide_proposal', 'Gegenvorschlag zurückziehen', 'Dein Vorschlag wird zurückgezogen. Die ursprüngliche Ausleihanfrage bleibt offen.', { proposal_id: Number(proposal.proposal_id), decision: 'withdrawn' }, 'Gegenvorschlag zurückziehen')));
        }
      }
    }
    if (loan.extensions?.length) {
      const section = loanSection(card, 'Verlängerungen');
      for (const extension of loan.extensions) {
        section.append(el('p', 'history-line', `${extension.extra_days} zusätzliche Tage · ${statuses[extension.status] || extension.status}${extension.new_due_date ? ` · Neue Frist: ${formatDate(extension.new_due_date)}` : ''}`));
        if (owner && loan.status === 'active' && extension.status === 'pending') {
          const row = el('div', 'form-actions');
          for (const [decision, title] of [['approved', 'Verlängerung genehmigen'], ['rejected', 'Verlängerung ablehnen']]) row.append(button(title, () => confirmAction(loan, 'decide_extension', title, `${extension.extra_days} zusätzliche Tage für „${loan.title}“.`, { extension_id: Number(extension.extension_id), decision }, title), decision === 'approved'));
          section.append(row);
        } else if (!owner && loan.status === 'active' && extension.status === 'pending') {
          section.append(button('Verlängerungsanfrage zurückziehen', () => confirmAction(loan, 'decide_extension', 'Verlängerungsanfrage zurückziehen', 'Die angefragten zusätzlichen Tage werden zurückgezogen. Deine bestehende Rückgabefrist bleibt bestehen.', { extension_id: Number(extension.extension_id), decision: 'withdrawn' }, 'Verlängerungsanfrage zurückziehen')));
        }
      }
    }
    if (shipping && loan.accepted_at && !['cancelled', 'rejected'].includes(loan.status)) renderShipping(card, loan, owner);
    if (loan.reviews?.length) {
      const section = loanSection(card, 'Bewertungen');
      for (const review of loan.reviews) section.append(el('p', 'history-line', `${review.rating} von 5 Sternen${String(review.reviewer_id) === String(state.user.user_id) ? ' · Deine Bewertung' : ''}${review.comment ? ` · ${review.comment}` : ''}`));
    }
    if (loan.documents?.length) {
      const section = loanSection(card, 'Deine Dokumente'); const links = el('div', 'document-list');
      for (const doc of loan.documents) {
        // Recipient access is checked again by the server for every download.
        if (doc.recipient_user_id && String(doc.recipient_user_id) !== String(state.user.user_id)) continue;
        const anchor = link(`${documentNames[doc.document_type] || 'Dokument'} · PDF ↗`, `/api/documents/${safeId(doc.document_id)}/download`);
        anchor.setAttribute('aria-label', `${documentNames[doc.document_type] || 'Dokument'} als PDF in neuem Tab öffnen`);
        anchor.target = '_blank'; anchor.rel = 'noopener'; links.append(anchor);
      }
      section.append(links); if (!links.children.length) section.remove();
    }
    return card;
  }
  function renderShipping(card, loan, owner) {
    const postage = loanSection(card, 'Porto');
    if (!loan.payments?.length) {
      postage.append(el('p', 'helper', owner ? 'Vereinbare zuerst die Kosten für Hin- und Rückversand.' : 'Die verleihende Person legt als Nächstes das Porto fest.'));
      if (owner && loan.status === 'accepted') postage.append(button('Porto festlegen', () => postageAction(loan), true));
    }
    let confirmed = false;
    for (const payment of loan.payments || []) {
      if (payment.status === 'confirmed') confirmed = true;
      postage.append(el('p', '', `Hinporto ${money(payment.outbound_fee)} + Rückporto ${money(payment.return_fee)} = ${money(Number(payment.outbound_fee) + Number(payment.return_fee))}`), el('p', 'history-line', statuses[payment.status] || payment.status));
      if (loan.status === 'accepted' && !owner && payment.status === 'pending') postage.append(button('Portozahlung melden', () => confirmAction(loan, 'report_postage', 'Portozahlung melden', 'Bestätige, dass du das vereinbarte Porto außerhalb von BookBridge bezahlt hast. Diese Meldung führt keine Zahlung aus. Die verleihende Person bestätigt danach den Eingang.', { payment_id: Number(payment.payment_id) }, 'Zahlung als geleistet melden'), true));
      if (loan.status === 'accepted' && owner && payment.status === 'reported') postage.append(button('Portoeingang bestätigen', () => confirmAction(loan, 'confirm_postage', 'Portoeingang bestätigen', 'Prüfe zuerst den tatsächlichen Zahlungseingang. Deine Bestätigung gibt den Hinversand frei.', { payment_id: Number(payment.payment_id) }, 'Portoeingang bestätigen'), true));
    }
    const shipments = loanSection(card, 'Hin- und Rückversand');
    for (const shipment of loan.shipments || []) {
      const row = el('div', 'loan-subsection'); row.append(el('h4', '', shipment.direction === 'outbound' ? 'Hinversand' : 'Rückversand'));
      row.append(el('p', 'history-line', `${statuses[shipment.status] || shipment.status}${shipment.carrier ? ` · ${shipment.carrier}` : ''}${shipment.tracking_number ? ` · Sendungsnummer: ${shipment.tracking_number}` : ''}`));
      if (shipment.sender_address_snapshot) row.append(el('p', 'private-address', `Absender\n${shipment.sender_address_snapshot}`));
      if (shipment.recipient_address_snapshot) row.append(el('p', 'private-address', `Empfänger\n${shipment.recipient_address_snapshot}`));
      const sender = shipment.direction === 'outbound' ? owner : !owner;
      if (shipment.status === 'prepared' && sender && ((shipment.direction === 'outbound' && loan.status === 'accepted') || (shipment.direction === 'return' && loan.status === 'active'))) {
        const dispatch = button('Versand bestätigen', () => confirmAction(loan, 'send_shipment', 'Versand bestätigen', `Bestätige erst, wenn das Buch für den ${shipment.direction === 'outbound' ? 'Hinversand' : 'Rückversand'} tatsächlich aufgegeben wurde.`, { shipment_id: Number(shipment.shipment_id) }, 'Versand bestätigen'), true);
        if (shipment.direction === 'outbound' && !confirmed) { dispatch.disabled = true; row.append(el('p', 'helper', 'Der Hinversand wird nach bestätigtem Portoeingang freigegeben.')); }
        row.append(dispatch);
      }
      if (shipment.status === 'sent' && !sender && ((shipment.direction === 'outbound' && loan.status === 'outbound') || (shipment.direction === 'return' && loan.status === 'returning'))) row.append(button('Empfang bestätigen', () => confirmAction(loan, 'receive_shipment', 'Sendung erhalten', shipment.direction === 'outbound' ? 'Bestätige, dass das Buch bei dir eingegangen ist. Jetzt beginnt die Leihfrist.' : 'Bestätige, dass du dein Buch zurückerhalten hast. Die Ausleihe wird damit abgeschlossen.', { shipment_id: Number(shipment.shipment_id) }, 'Empfang bestätigen'), true));
      shipments.append(row);
    }
    if (owner && loan.status === 'accepted' && !(loan.shipments || []).some(shipment => shipment.direction === 'outbound')) shipments.append(button('Hinversand vorbereiten', () => shipmentAction(loan, 'outbound')));
    if (!owner && loan.status === 'active' && !(loan.shipments || []).some(shipment => shipment.direction === 'return')) shipments.append(button('Rückversand vorbereiten', () => shipmentAction(loan, 'return'), true));
    if (!shipments.children.length || shipments.children.length === 1) shipments.append(el('p', 'helper', 'Hier erscheinen die vereinbarten Sendungen.'));
  }
  function renderLoans() {
    const root = $('#my-loans-list');
    if (!state.user) { renderLoginStates(); return; }
    const loans = state.loans.filter(loan => state.loanFilter === 'all' || loan.role === state.loanFilter);
    root.replaceChildren(...loans.map(loanCard));
    $('#my-loans-count').textContent = `${loans.length} ${loans.length === 1 ? 'Ausleihe' : 'Ausleihen'}${state.loanFilter !== 'all' ? ` von ${state.loans.length}` : ''}`;
    if (!loans.length) empty(root, state.loanFilter === 'all' ? 'Hier erscheinen deine gesendeten und erhaltenen Ausleihanfragen. Entdecke im Katalog dein nächstes Buch.' : 'In dieser Ansicht gibt es noch keine Ausleihen.');
  }
  function updateLoanFilterButtons() {
    $$('[data-loan-filter]').forEach(control => { const active = control.dataset.loanFilter === state.loanFilter; control.setAttribute('aria-pressed', String(active)); control.classList.toggle('button-primary', active); control.classList.toggle('button-secondary', !active); });
  }
  async function loadLoans() {
    if (!state.user) return;
    const root = $('#my-loans-list'); const request = beginMemberLoad('loans', root, 'Deine Ausleihen werden geladen …');
    try { const data = await api('/api/loans'); if (!currentMemberLoad('loans', request)) return; state.loans = data.items || []; renderLoans(); }
    catch (error) { if (currentMemberLoad('loans', request)) { empty(root, error.message); root.firstChild.append(button('Erneut versuchen', loadLoans)); $('#my-loans-count').textContent = 'Deine Ausleihen konnten nicht geladen werden.'; } }
    finally { if (currentMemberLoad('loans', request)) root.setAttribute('aria-busy', 'false'); }
  }
  function renderNotifications() {
    const root = $('#notification-list'); root.replaceChildren();
    const unread = state.notifications.filter(item => !item.read_at).length;
    $('#unread-count').textContent = unread ? `(${unread} ungelesen)` : '';
    for (const item of state.notifications) {
      const card = el('article', `notification${!item.read_at ? ' unread' : ''}`); const text = el('div');
      text.append(el('p', '', item.message)); const time = el('time', '', formatDate(item.created_at, true)); time.dateTime = item.created_at; text.append(time);
      if (item.loan_id) {
        const anchor = link('Zur Ausleihe', `#loan-${item.loan_id}`, 'notification-loan-link');
        anchor.addEventListener('click', () => {
          state.loanFilter = 'all'; updateLoanFilterButtons(); renderLoans();
          $(`#loan-${safeId(item.loan_id)}`)?.focus();
        }); text.append(anchor);
      } card.append(text);
      if (!item.read_at) card.append(button('Als gelesen markieren', async event => {
        const control = event.currentTarget; control.disabled = true;
        try { await api(`/api/notifications/${safeId(item.notification_id)}/read`, { method: 'POST' }); await loadNotifications(); }
        catch (error) { notice(error.message, true); control.disabled = false; }
      })); root.append(card);
    }
    if (!state.notifications.length) empty(root, 'Du bist auf dem Laufenden. Neue Antworten und Bestätigungen erscheinen hier.');
  }
  async function loadNotifications() {
    if (!state.user) return;
    const root = $('#notification-list'); const request = beginMemberLoad('notifications', root, 'Deine Mitteilungen werden geladen …');
    try { const data = await api('/api/notifications'); if (!currentMemberLoad('notifications', request)) return; state.notifications = data.items || []; renderNotifications(); }
    catch (error) { if (currentMemberLoad('notifications', request)) { empty(root, error.message); root.firstChild.append(button('Erneut versuchen', loadNotifications)); } }
    finally { if (currentMemberLoad('notifications', request)) root.setAttribute('aria-busy', 'false'); }
  }
  async function refreshMember() { if (state.user) await Promise.allSettled([loadMyBooks(), loadLoans(), loadNotifications()]); }
  function refreshButton(selector, loader) {
    $(selector).addEventListener('click', async event => {
      if (!state.user) { location.hash = 'account'; $('#login-email')?.focus(); return; }
      const control = event.currentTarget; const text = control.textContent; control.disabled = true; control.textContent = 'Wird aktualisiert …';
      try { await loader(); } finally { control.disabled = false; control.textContent = text; }
    });
  }
  bindSubmit($('#search-form'), () => loadCatalog(1));
  $('#search-form').addEventListener('invalid', event => { const origin = event.target.closest('.search-origin'); if (origin) origin.open = true; }, true);
  $('#search-form').addEventListener('reset', () => { setTimeout(() => { formFeedback($('#search-form'), ''); navigateCatalog(1); }, 0); });
  $('#origin-location').addEventListener('click', event => geolocate($('#search-form'), event.currentTarget));
  $('#add-slot').addEventListener('click', () => addSlot());
  $('#allow-pickup').addEventListener('change', togglePickup);
  $('#add-book-form').addEventListener('reset', () => { setTimeout(() => { $('#pickup-slots').replaceChildren(); addSlot(); togglePickup(); renderAddressPicker(); formFeedback($('#add-book-form'), ''); }, 0); });
  bindSubmit($('#add-book-form'), async form => {
    if (!state.user) throw new Error('Bitte melde dich an, um ein Buch anzubieten.');
    if (!activeMember()) throw new Error('Dein Konto ist deaktiviert. Neue Angebote sind erst nach einer Reaktivierung durch eine Administration möglich.');
    if (!state.addresses.some(address => String(address.address_id) === value(form, 'address_id') && hasCoordinates(address))) throw new Error('Bitte wähle eine eigene Adresse mit Standort. Ergänze sie bei Bedarf in deinem Konto.');
    const allowPickup = isChecked(form, 'allow_pickup'); const allowShipping = isChecked(form, 'allow_shipping');
    if (!allowPickup && !allowShipping) throw new Error('Bitte biete mindestens eine Übergabeart an: Abholung oder Versand.');
    const slots = readSlots($('#pickup-slots'), allowPickup);
    const body = { title: value(form, 'title'), author: value(form, 'author'), publisher: value(form, 'publisher') || null,
      publication_year: value(form, 'publication_year') ? number(form, 'publication_year') : null, isbn: value(form, 'isbn') || null,
      genre_id: number(form, 'genre_id'), language_id: number(form, 'language_id'), condition: value(form, 'condition'), max_loan_days: number(form, 'max_loan_days'),
      address_id: number(form, 'address_id'), allow_pickup: allowPickup, allow_shipping: allowShipping, notes: value(form, 'notes') || null,
      description: value(form, 'description') || null, pickup_slots: slots };
    await api('/api/books', { method: 'POST', body }); form.reset(); notice('Dein Buch ist jetzt im Katalog. Du findest es auch unter „Meine Bücher“.');
    await Promise.allSettled([loadMyBooks(), loadCatalog(1)]);
  });
  $$('[data-loan-filter]').forEach(control => control.addEventListener('click', () => { state.loanFilter = control.dataset.loanFilter; updateLoanFilterButtons(); renderLoans(); }));
  refreshButton('#refresh-books', loadMyBooks); refreshButton('#refresh-loans', loadLoans); refreshButton('#refresh-notifications', loadNotifications);
  addSlot(); renderAccount(); renderAddressPicker(); renderLoginStates();
  async function loadSession() {
    const sequence = state.sessionSequence;
    try {
      const data = await api('/api/session', { skipSessionRecovery: true });
      if (sequence !== state.sessionSequence) return;
      await applySession(data);
    }
    catch (error) {
      if (sequence !== state.sessionSequence) return;
      notice(`${error.message} Anmeldung und Änderungen sind vorübergehend nicht verfügbar.`, true);
      empty($('#account-content'), 'Dein Konto konnte nicht geladen werden.');
      $('#account-content').firstChild.append(button('Erneut versuchen', loadSession));
    }
  }
  (async () => {
    await Promise.allSettled([loadSession(), (async () => {
      try { state.meta = await api('/api/meta'); fillMeta(); }
      catch (error) { notice(`Genres und Sprachen konnten nicht geladen werden. ${error.message}`, true); }
    })(), loadCatalog(1)]);
  })();
})();
