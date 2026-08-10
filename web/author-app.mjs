/**
 * Browser adapter for the canonical LateLetter author service.
 *
 * Ownership boundaries are deliberate:
 * - approved wording arrives from /api/author/questionnaire;
 * - accepted-paint authority filters gift choices before that response;
 * - this module owns transient form interaction and draft adaptation only;
 * - author_service.py validates and seals every exported bundle;
 * - passphrases never enter draft state, autosave, storage, URLs, or logs.
 */

import {
  layoutWithLines,
  prepareWithSegments,
} from './vendor/pretext/layout.js';


const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

let questionnaire = null;
let rows = new Map();
let stages = [];
let giftChoices = [];
let passphraseMinimum = 4;
let csrfToken = '';
let revision = 0;
let draft = null;
let activeStage = 'resume';
let activeLetterId = null;
let maxVisitedStage = 0;
let draftVersion = 0;
let savedVersion = 0;
let saveTimer = null;
let saveChain = Promise.resolve();
let conflictOpen = false;
let previewPrepared = null;
let previewPreparedText = null;
let adviceTimer = null;
let appendBundleText = null;


function randomId(prefix) {
  if (typeof crypto.randomUUID === 'function') {
    return `${prefix}.${crypto.randomUUID().replaceAll('-', '')}`;
  }
  const words = new Uint32Array(4);
  crypto.getRandomValues(words);
  return `${prefix}.${[...words].map(value => value.toString(16)).join('')}`;
}


function newGardenSeed() {
  const value = new Uint32Array(1);
  crypto.getRandomValues(value);
  return Number(value[0] || 1);
}


function newLetter(source = {}) {
  return {
    id: typeof source.id === 'string' ? source.id : randomId('letter'),
    date: typeof source.date === 'string' ? source.date : '',
    label: typeof source.label === 'string' ? source.label : '',
    body: typeof source.body === 'string' ? source.body : '',
    shape: typeof source.shape === 'string' ? source.shape : '',
    used_prompt_ids: Array.isArray(source.used_prompt_ids)
      ? source.used_prompt_ids.filter(value => typeof value === 'string') : [],
    permission_opt_in: source.permission_opt_in === true,
  };
}


function newGift(source = {}) {
  return {
    id: typeof source.id === 'string' ? source.id : randomId('gift'),
    catalog_id: typeof source.catalog_id === 'string' ? source.catalog_id : '',
    date: typeof source.date === 'string' ? source.date : '',
    yearly: source.yearly === true,
    letter_id: typeof source.letter_id === 'string' ? source.letter_id : '',
  };
}


function normalizeDraft(source) {
  const value = source && typeof source === 'object' ? source : {};
  const oldAuthor = value.author && typeof value.author === 'object' ? value.author : {};
  const oldRecipient = value.recipient && typeof value.recipient === 'object'
    ? value.recipient : {};
  const rawLetters = Array.isArray(value.letters)
    ? value.letters : (Array.isArray(value.messages) ? value.messages : []);
  const letters = rawLetters.map(newLetter);
  if (letters.length === 0) letters.push(newLetter());
  const seed = Number(value.garden_seed);
  return {
    author_name: String(value.author_name ?? oldAuthor.name ?? ''),
    author_relationship: String(
      value.author_relationship ?? oldAuthor.relationship ?? '',
    ),
    recipient_name: String(value.recipient_name ?? oldRecipient.name ?? ''),
    recipient_relationship: String(
      value.recipient_relationship ?? oldRecipient.relationship ?? '',
    ),
    author_timezone: String(
      value.author_timezone ?? oldAuthor.timezone
      ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC',
    ),
    passphrase_hint: String(value.passphrase_hint ?? ''),
    garden_seed: Number.isSafeInteger(seed) && seed >= 0 ? seed : newGardenSeed(),
    letters,
    gifts: Array.isArray(value.gifts) ? value.gifts.map(newGift) : [],
    garden_story_enabled: value.garden_story_enabled === true,
    rabbit_name: typeof value.rabbit_name === 'string' && value.rabbit_name.trim()
      ? value.rabbit_name : 'Clover',
  };
}


function copyDraft(value = draft) {
  return JSON.parse(JSON.stringify(value));
}


function row(id) {
  const value = rows.get(id);
  if (!value) throw new Error(`approved questionnaire row ${id} is missing`);
  return value;
}


function setSaveState(state, text) {
  const element = $('#save-state');
  element.dataset.state = state;
  element.textContent = text;
}


function showBanner(message, tone = 'error', actions = []) {
  const host = $('#banner-host');
  host.replaceChildren();
  const banner = document.createElement('div');
  banner.className = 'banner';
  banner.dataset.tone = tone;
  const copy = document.createElement('p');
  copy.textContent = message;
  banner.append(copy);
  if (actions.length) {
    const actionHost = document.createElement('div');
    actionHost.className = 'banner-actions';
    for (const action of actions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn';
      button.textContent = action.label;
      button.addEventListener('click', action.run);
      actionHost.append(button);
    }
    banner.append(actionHost);
  }
  host.append(banner);
}


function clearBanner() {
  $('#banner-host').replaceChildren();
}


function markChanged() {
  draftVersion += 1;
  setSaveState('unsaved', 'changes not saved');
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => queueSave(), 450);
  renderResumeSummary();
}


function queueSave() {
  window.clearTimeout(saveTimer);
  saveTimer = null;
  saveChain = saveChain.then(saveDraft).catch(error => {
    setSaveState('offline', 'could not save');
    showBanner(`The local author service could not save this draft: ${error.message}`);
  });
  return saveChain;
}


async function saveDraft() {
  if (conflictOpen || draftVersion === savedVersion) return;
  const versionBeingSaved = draftVersion;
  const localSnapshot = copyDraft();
  setSaveState('saving', 'saving…');
  const response = await fetch('/api/author/session', {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'X-LateLetter-CSRF': csrfToken,
    },
    body: JSON.stringify({draft: localSnapshot, revision}),
  });
  const payload = await response.json();
  if (response.status === 409) {
    conflictOpen = true;
    setSaveState('conflict', 'newer draft found');
    const serverDraft = normalizeDraft(payload.draft);
    showBanner(
      'Another tab saved a newer version of this draft. Choose which version stays on this desk.',
      'error',
      [
        {
          label: 'load newer draft',
          run: () => {
            draft = serverDraft;
            revision = payload.revision;
            activeLetterId = draft.letters[0].id;
            conflictOpen = false;
            draftVersion += 1;
            savedVersion = draftVersion;
            clearBanner();
            renderAll();
            setSaveState('saved', 'newer draft loaded');
          },
        },
        {
          label: 'keep this draft',
          run: () => {
            revision = payload.revision;
            conflictOpen = false;
            clearBanner();
            queueSave();
          },
        },
      ],
    );
    return;
  }
  if (!response.ok) throw new Error(payload.error || `save failed (${response.status})`);
  revision = payload.revision;
  savedVersion = Math.max(savedVersion, versionBeingSaved);
  if (draftVersion === savedVersion) {
    setSaveState('saved', 'saved on this machine');
  } else {
    setSaveState('unsaved', 'changes not saved');
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => queueSave(), 50);
  }
}


async function flushSave() {
  window.clearTimeout(saveTimer);
  saveTimer = null;
  await saveChain;
  if (!conflictOpen && draftVersion !== savedVersion) await queueSave();
}


function hasMeaningfulDraft() {
  return Boolean(
    draft.author_name.trim() || draft.recipient_name.trim()
    || draft.passphrase_hint.trim() || draft.gifts.length || draft.garden_story_enabled
    || draft.letters.some(letter => letter.date || letter.label || letter.body),
  );
}


function renderResumeSummary() {
  if (!draft) return;
  const host = $('#resume-summary');
  const complete = completeLetters();
  host.replaceChildren();
  const entries = [
    ['author', draft.author_name || 'not named yet'],
    ['recipient', draft.recipient_name || 'not named yet'],
    ['letters on desk', String(draft.letters.length)],
    ['ready to export', String(complete.length)],
    ['scheduled gifts', String(draft.gifts.length)],
  ];
  for (const [name, value] of entries) {
    const term = document.createElement('dt');
    term.textContent = name;
    const description = document.createElement('dd');
    description.textContent = value;
    host.append(term, description);
  }
  $('#btn-resume').hidden = !hasMeaningfulDraft();
  $('#btn-start-fresh').textContent = hasMeaningfulDraft()
    ? 'start again from empty' : 'begin a new letter';
}


function applyCanonicalCopy() {
  for (const element of $$('[data-row-label]')) {
    element.textContent = row(element.dataset.rowLabel).prompt;
  }
  for (const element of $$('[data-row-note]')) {
    element.textContent = row(element.dataset.rowNote).note || '';
  }
  const fieldMap = {
    P1: '#f-author-name', P2: '#f-author-relationship',
    P3: '#f-recipient-name', P4: '#f-recipient-relationship',
    X2: '#f-hint', L2: '#f-letter-label',
  };
  for (const [id, selector] of Object.entries(fieldMap)) {
    const element = $(selector);
    element.placeholder = row(id).placeholder || '';
  }
}


function populateTimezones() {
  const select = $('#f-timezone');
  let names = [];
  try {
    names = Intl.supportedValuesOf('timeZone');
  } catch (_error) {
    names = ['UTC', 'America/New_York', 'Europe/London', 'Asia/Tokyo'];
  }
  if (!names.includes('UTC')) names.unshift('UTC');
  if (draft.author_timezone && !names.includes(draft.author_timezone)) {
    names.unshift(draft.author_timezone);
  }
  select.replaceChildren(...names.map(name => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    return option;
  }));
}


function renderProgress() {
  const list = $('#stage-list');
  list.replaceChildren();
  stages.forEach((stage, index) => {
    const item = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'step';
    button.dataset.stage = stage.id;
    button.dataset.visited = index < maxVisitedStage ? 'yes' : 'no';
    button.disabled = index > maxVisitedStage + 1;
    if (activeStage === stage.id) button.setAttribute('aria-current', 'step');
    const number = document.createElement('span');
    number.className = 'step-num';
    number.textContent = String(index + 1);
    const label = document.createElement('span');
    label.textContent = stage.label;
    button.append(number, label);
    button.addEventListener('click', () => showStage(stage.id));
    item.append(button);
    list.append(item);
  });
}


async function showStage(stageId) {
  if (activeStage === 'people' && stageId !== 'resume' && !validatePeople()) return;
  if (activeStage !== 'resume') await flushSave();
  activeStage = stageId;
  for (const section of $$('.stage')) section.hidden = section.dataset.stage !== stageId;
  const resume = stageId === 'resume';
  $('#progress').hidden = resume;
  $('#desk-foot').hidden = resume;
  if (!resume) {
    const index = stages.findIndex(stage => stage.id === stageId);
    maxVisitedStage = Math.max(maxVisitedStage, index);
    $('#btn-back').disabled = index === 0;
    $('#btn-next').hidden = index === stages.length - 1;
    $('#stage-hint').textContent = `${index + 1} of ${stages.length}`;
    if (stageId === 'letters') renderLetterEditor();
    if (stageId === 'gifts') renderGifts();
    if (stageId === 'review') renderReview();
    if (stageId === 'export') renderExport();
  } else {
    renderResumeSummary();
  }
  renderProgress();
  const title = $(`[data-stage="${stageId}"] .stage-title`);
  title?.focus();
}


function moveStage(offset) {
  const index = stages.findIndex(stage => stage.id === activeStage);
  const target = stages[index + offset];
  if (target) showStage(target.id);
}


function setPeopleError(id, message) {
  $(id).textContent = message;
}


function validatePeople() {
  setPeopleError('#e-author-name', '');
  setPeopleError('#e-recipient-name', '');
  setPeopleError('#e-hint', '');
  let ok = true;
  if (!draft.author_name.trim()) {
    setPeopleError('#e-author-name', 'Please say what they call you.');
    ok = false;
  }
  if (!draft.recipient_name.trim()) {
    setPeopleError('#e-recipient-name', 'Please name who the letters are for.');
    ok = false;
  }
  if (!draft.passphrase_hint.trim()) {
    setPeopleError('#e-hint', 'A passphrase reminder is required.');
    ok = false;
  }
  return ok;
}


function bindPeopleInputs() {
  const fields = {
    '#f-author-name': 'author_name',
    '#f-author-relationship': 'author_relationship',
    '#f-recipient-name': 'recipient_name',
    '#f-recipient-relationship': 'recipient_relationship',
    '#f-timezone': 'author_timezone',
    '#f-hint': 'passphrase_hint',
  };
  for (const [selector, key] of Object.entries(fields)) {
    const element = $(selector);
    element.addEventListener('input', () => {
      draft[key] = element.value;
      markChanged();
      if (key === 'recipient_name' || key === 'recipient_relationship') {
        renderLetterEditor();
      }
    });
  }
}


function renderPeople() {
  const fields = {
    '#f-author-name': draft.author_name,
    '#f-author-relationship': draft.author_relationship,
    '#f-recipient-name': draft.recipient_name,
    '#f-recipient-relationship': draft.recipient_relationship,
    '#f-timezone': draft.author_timezone,
    '#f-hint': draft.passphrase_hint,
    '#f-seed': String(draft.garden_seed),
  };
  for (const [selector, value] of Object.entries(fields)) $(selector).value = value;
}


function currentLetter() {
  let letter = draft.letters.find(value => value.id === activeLetterId);
  if (!letter) {
    letter = draft.letters[0];
    activeLetterId = letter.id;
  }
  return letter;
}


function isCompleteLetter(letter) {
  return /^\d{4}-\d{2}-\d{2}$/.test(letter.date) && Boolean(letter.body.trim());
}


function completeLetters() {
  return draft.letters.filter(isCompleteLetter);
}


function displayLetterName(letter, index) {
  return letter.label.trim() || letter.date || `letter ${index + 1}`;
}


function renderLetterTabs() {
  const host = $('#letter-tabs');
  host.replaceChildren();
  draft.letters.forEach((letter, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'letter-tab';
    button.setAttribute('aria-pressed', String(letter.id === activeLetterId));
    button.textContent = `${displayLetterName(letter, index)}${isCompleteLetter(letter) ? ' ✓' : ''}`;
    button.addEventListener('click', () => {
      activeLetterId = letter.id;
      renderLetterEditor();
    });
    host.append(button);
  });
  $('#btn-remove-letter').disabled = draft.letters.length === 1;
}


function resolvedPrompt(seed) {
  if (seed.id === 'A2' && /\b(child|daughter|son)\b/i.test(draft.recipient_relationship)) {
    return seed.child_prompt;
  }
  return seed.prompt.replaceAll('{recipient}', draft.recipient_name || 'them');
}


function isPartnerRelationship() {
  return /\b(partner|spouse|wife|husband|fianc(?:é|e)|girlfriend|boyfriend)\b/i
    .test(draft.recipient_relationship);
}


function appendSeedBand(host, title, seedRows, {collapsed = false, note = ''} = {}) {
  const available = seedRows.filter(seed => (
    seed.status !== 'removed_mvp'
    && !currentLetter().used_prompt_ids.includes(seed.id)
  ));
  if (!available.length && !note) return;
  const wrapper = collapsed ? document.createElement('details') : document.createElement('div');
  wrapper.className = 'question-band';
  if (collapsed) {
    const summary = document.createElement('summary');
    summary.textContent = title;
    wrapper.append(summary);
  } else {
    const heading = document.createElement('h3');
    heading.textContent = title;
    wrapper.append(heading);
  }
  if (note) {
    const copy = document.createElement('p');
    copy.className = 'note';
    copy.textContent = note;
    wrapper.append(copy);
  }
  const list = document.createElement('div');
  list.className = 'seed-list';
  for (const seed of available) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'seed-button';
    button.dataset.questionId = seed.id;
    button.textContent = resolvedPrompt(seed);
    button.addEventListener('click', () => insertPrompt(seed));
    list.append(button);
  }
  wrapper.append(list);
  host.append(wrapper);
}


function renderQuestionDrawer() {
  const host = $('#question-list');
  host.replaceChildren();
  const seeds = [...rows.values()].filter(value => value.role === 'seed');
  const letter = currentLetter();
  appendSeedBand(host, 'begin with something concrete', seeds.filter(value => value.band === 'grounding'));
  if (letter.shape) {
    appendSeedBand(
      host,
      'for this kind of letter',
      seeds.filter(value => value.band === 'occasion' && value.route === letter.shape && !value.heavy),
    );
  }
  const hardSeeds = seeds.filter(value => value.band === 'hard');
  if (letter.shape === 'first') {
    hardSeeds.unshift(...seeds.filter(value => value.id === 'B9'));
  }
  appendSeedBand(host, 'the four hard ones', hardSeeds, {
    collapsed: true,
    note: 'Open these when you want them, not before. Forgiveness is never owed.',
  });

  const permissionWrapper = document.createElement('details');
  permissionWrapper.className = 'question-band';
  const permissionSummary = document.createElement('summary');
  permissionSummary.textContent = 'the ones nobody writes';
  permissionWrapper.append(permissionSummary);
  const permissionNote = document.createElement('p');
  permissionNote.className = 'note';
  permissionNote.textContent = 'Optional permission prompts. They are never a rule for the recipient.';
  permissionWrapper.append(permissionNote);
  if (isPartnerRelationship()) {
    const gateLabel = document.createElement('label');
    gateLabel.className = 'note';
    const gate = document.createElement('input');
    gate.type = 'checkbox';
    gate.checked = letter.permission_opt_in;
    gate.addEventListener('change', () => {
      letter.permission_opt_in = gate.checked;
      markChanged();
      renderQuestionDrawer();
    });
    gateLabel.append(gate, ' This may be read after my death; show the partner-specific permission prompt.');
    permissionWrapper.append(gateLabel);
  }
  const permissionList = document.createElement('div');
  permissionList.className = 'seed-list';
  const permissionSeeds = seeds.filter(seed => (
    seed.band === 'permission'
    && !letter.used_prompt_ids.includes(seed.id)
    && (!seed.partner_only || (isPartnerRelationship() && letter.permission_opt_in))
  ));
  for (const seed of permissionSeeds) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'seed-button';
    button.dataset.questionId = seed.id;
    button.textContent = resolvedPrompt(seed);
    button.addEventListener('click', () => insertPrompt(seed));
    permissionList.append(button);
  }
  permissionWrapper.append(permissionList);
  host.append(permissionWrapper);
  appendSeedBand(host, 'before you finish', seeds.filter(value => value.band === 'closer'));
}


function insertPrompt(seed) {
  const letter = currentLetter();
  const prompt = resolvedPrompt(seed);
  letter.body = letter.body.trimEnd()
    ? `${letter.body.trimEnd()}\n\n${prompt}\n`
    : `${prompt}\n`;
  letter.used_prompt_ids.push(seed.id);
  $('#f-letter-body').value = letter.body;
  markChanged();
  renderLetterTabs();
  renderLetterShape();
  renderQuestionDrawer();
  renderLetterPreview();
  $('#f-letter-body').focus();
}


function renderLetterShape() {
  const host = $('#letter-shape-host');
  host.replaceChildren();
  host.hidden = Boolean(currentLetter().body.trim());
  if (host.hidden) return;
  const shapeRow = row('L0');
  const heading = document.createElement('h3');
  heading.textContent = shapeRow.prompt;
  host.append(heading);
  const options = document.createElement('div');
  options.className = 'chip-set';
  for (const choice of shapeRow.options) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'letter-tab';
    button.setAttribute('aria-pressed', String(currentLetter().shape === choice.value));
    button.title = choice.note;
    button.textContent = choice.label;
    button.addEventListener('click', () => {
      currentLetter().shape = choice.value;
      markChanged();
      renderLetterShape();
      renderQuestionDrawer();
    });
    options.append(button);
  }
  host.append(options);
}


function renderLetterEditor() {
  const letter = currentLetter();
  renderLetterTabs();
  renderLetterShape();
  $('#f-letter-date').value = letter.date;
  $('#f-letter-label').value = letter.label;
  $('#f-letter-body').value = letter.body;
  $('#letter-counter').textContent = `${letter.body.length.toLocaleString()} characters`;
  renderQuestionDrawer();
  renderLetterPreview();
}


function renderLetterPreview() {
  const letter = currentLetter();
  $('#preview-from').textContent = draft.author_name ? `from ${draft.author_name}` : '';
  $('#preview-label').textContent = letter.label || 'untitled letter';
  $('#preview-date').textContent = letter.date || 'date not chosen yet';
  const host = $('#letter-preview');
  const text = letter.body || '';
  host.replaceChildren();
  if (!text) {
    $('#preview-mode').textContent = 'waiting for words';
    $('#preview-mode').dataset.mode = 'pending';
    previewPrepared = null;
    previewPreparedText = null;
    return;
  }
  try {
    const style = getComputedStyle(host);
    const font = style.font || `${style.fontSize} ${style.fontFamily}`;
    if (previewPreparedText !== text) {
      previewPrepared = prepareWithSegments(text, font, {whiteSpace: 'pre-wrap'});
      previewPreparedText = text;
    }
    const width = Math.max(180, host.clientWidth || 420);
    const lineHeight = Number.parseFloat(style.lineHeight) || 21;
    const result = layoutWithLines(previewPrepared, width, lineHeight);
    for (const line of result.lines) {
      const element = document.createElement('span');
      element.className = 'll';
      element.textContent = line.text;
      host.append(element);
    }
    $('#preview-mode').textContent = `${result.lineCount} lines · recipient line breaks`;
    $('#preview-mode').dataset.mode = 'ready';
  } catch (_error) {
    for (const line of text.split('\n')) {
      const element = document.createElement('span');
      element.className = 'll';
      element.textContent = line;
      host.append(element);
    }
    $('#preview-mode').textContent = 'exact preview unavailable';
    $('#preview-mode').dataset.mode = 'unavailable';
  }
}


function bindLetterInputs() {
  const fields = {
    '#f-letter-date': 'date',
    '#f-letter-label': 'label',
    '#f-letter-body': 'body',
  };
  for (const [selector, key] of Object.entries(fields)) {
    const element = $(selector);
    element.addEventListener('input', () => {
      currentLetter()[key] = element.value;
      markChanged();
      if (key === 'body') {
        $('#letter-counter').textContent = `${element.value.length.toLocaleString()} characters`;
        previewPreparedText = null;
        renderLetterShape();
        renderLetterPreview();
      } else {
        renderLetterTabs();
        renderLetterPreview();
      }
    });
  }
  $('#btn-add-letter').addEventListener('click', () => {
    const letter = newLetter();
    draft.letters.push(letter);
    activeLetterId = letter.id;
    markChanged();
    renderLetterEditor();
  });
  $('#btn-remove-letter').addEventListener('click', () => {
    if (draft.letters.length === 1) return;
    const index = draft.letters.findIndex(letter => letter.id === activeLetterId);
    const [removed] = draft.letters.splice(index, 1);
    draft.gifts = draft.gifts.filter(gift => gift.letter_id !== removed.id);
    activeLetterId = draft.letters[Math.max(0, index - 1)].id;
    markChanged();
    renderLetterEditor();
  });
}


function setGiftValue(gift, key, value) {
  gift[key] = value;
  markChanged();
}


function renderGifts() {
  $('#f-story-arc').checked=draft.garden_story_enabled;
  $('#f-rabbit-name').value=draft.rabbit_name;
  $('#f-rabbit-name').disabled=!draft.garden_story_enabled;
  const host = $('#gift-list');
  host.replaceChildren();
  if (draft.gifts.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'note';
    empty.textContent = 'No gifts scheduled. The Garden and letters still work.';
    host.append(empty);
  }
  const complete = completeLetters();
  draft.gifts.forEach((gift, index) => {
    const card = document.createElement('div');
    card.className = 'card gift-card';
    const header = document.createElement('div');
    header.className = 'card-head';
    const heading = document.createElement('h3');
    heading.textContent = `gift ${index + 1}`;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn quiet remove-gift';
    remove.textContent = 'remove';
    remove.addEventListener('click', () => {
      draft.gifts = draft.gifts.filter(value => value.id !== gift.id);
      markChanged();
      renderGifts();
    });
    header.append(heading, remove);
    card.append(header);

    const grid = document.createElement('div');
    grid.className = 'field-grid';
    const assetField = document.createElement('div');
    assetField.className = 'field';
    const assetLabel = document.createElement('label');
    assetLabel.textContent = row('G2').prompt;
    const assetSelect = document.createElement('select');
    const blankAsset = document.createElement('option');
    blankAsset.value = '';
    blankAsset.textContent = 'choose an accepted drawing';
    assetSelect.append(blankAsset);
    for (const choice of giftChoices) {
      const option = document.createElement('option');
      option.value = choice.asset_id;
      option.textContent = choice.label;
      assetSelect.append(option);
    }
    assetSelect.value = gift.catalog_id;
    assetSelect.addEventListener('change', () => setGiftValue(gift, 'catalog_id', assetSelect.value));
    assetLabel.append(assetSelect);
    assetField.append(assetLabel);

    const dateField = document.createElement('div');
    dateField.className = 'field';
    const dateLabel = document.createElement('label');
    dateLabel.textContent = row('G3').prompt;
    const dateInput = document.createElement('input');
    dateInput.type = 'date';
    dateInput.value = gift.date;
    dateInput.addEventListener('input', () => setGiftValue(gift, 'date', dateInput.value));
    dateLabel.append(dateInput);
    dateField.append(dateLabel);

    const letterField = document.createElement('div');
    letterField.className = 'field';
    const letterLabel = document.createElement('label');
    letterLabel.textContent = row('G5').prompt;
    const letterSelect = document.createElement('select');
    const blankLetter = document.createElement('option');
    blankLetter.value = '';
    blankLetter.textContent = complete.length ? 'choose a ready letter' : 'finish a letter first';
    letterSelect.append(blankLetter);
    for (const letter of complete) {
      const option = document.createElement('option');
      option.value = letter.id;
      option.textContent = displayLetterName(letter, draft.letters.indexOf(letter));
      letterSelect.append(option);
    }
    letterSelect.value = gift.letter_id;
    letterSelect.addEventListener('change', () => setGiftValue(gift, 'letter_id', letterSelect.value));
    letterLabel.append(letterSelect);
    letterField.append(letterLabel);

    const repeatField = document.createElement('div');
    repeatField.className = 'field';
    const repeatLabel = document.createElement('label');
    const repeat = document.createElement('input');
    repeat.type = 'checkbox';
    repeat.checked = gift.yearly;
    repeat.addEventListener('change', () => setGiftValue(gift, 'yearly', repeat.checked));
    repeatLabel.append(repeat, ` ${row('G4').prompt}`);
    repeatField.append(repeatLabel);
    grid.append(assetField, dateField, letterField, repeatField);
    card.append(grid);
    host.append(card);
  });
  $('#btn-add-gift').disabled = giftChoices.length === 0;
}


function giftIsComplete(gift, completeIds = new Set(completeLetters().map(letter => letter.id))) {
  return giftChoices.some(choice => choice.asset_id === gift.catalog_id)
    && /^\d{4}-\d{2}-\d{2}$/.test(gift.date)
    && completeIds.has(gift.letter_id);
}


function buildExportDraft() {
  const complete = completeLetters();
  const completeIds = new Set(complete.map(letter => letter.id));
  // author_service owns message IDs and accepts zero-based MESSAGE_N
  // placeholders while constructing the bundle. Keep that substitution there;
  // the browser must never mint a second family of recipient message IDs.
  const ordinal = new Map(complete.map((letter, index) => [letter.id, index]));
  const gifts = draft.gifts.filter(gift => giftIsComplete(gift, completeIds));
  const entities = gifts.map(gift => ({
    id: gift.id,
    kind: 'fixture',
    catalog_id: gift.catalog_id,
    initial_state: {revealed: false},
  }));
  const beats = gifts.map(gift => ({
    id: `${gift.id}.delivery`,
    when: {fact: 'visit.total', op: '>=', value: 0},
    schedule: {
      start: `${gift.date}T09:00:00`,
      timezone: draft.author_timezone,
      recurrence: gift.yearly ? {
        frequency: 'yearly', interval: 1, by_weekday: [],
        intentional_unbounded: true, dst_gap: 'shift_forward', dst_fold: 'first',
      } : null,
      exceptions: [],
      missed: 'deliver_on_next_visit',
    },
    occurrence: gift.yearly ? 'recurring' : 'once',
    priority: 0,
    actions: [
      // Placement is deliberately omitted. G6 has no approved browser owner;
      // the canonical materializer resolves an unspecified position.
      {type: 'entity.reveal', target: gift.id, params: {state: 'ready'}},
      {type: 'letter.present', target: null, params: {letter_id: `MESSAGE_${ordinal.get(gift.letter_id)}`}},
    ],
  }));
  const exported = {
    author_name: draft.author_name.trim(),
    author_relationship: draft.author_relationship.trim(),
    recipient_name: draft.recipient_name.trim(),
    recipient_relationship: draft.recipient_relationship.trim(),
    bundle_name: `${draft.recipient_name.trim() || 'letter'}-from-${draft.author_name.trim() || 'author'}`,
    passphrase_hint: draft.passphrase_hint.trim(),
    garden_seed: draft.garden_seed,
    messages: complete.map(letter => ({
      date: letter.date, label: letter.label, body: letter.body,
    })),
  };
  if(draft.garden_story_enabled){
    exported.garden_template={
      kind:'letter_rabbit_autumn',letter_index:0,
      rabbit_name:draft.rabbit_name.trim()||'Clover',
    };
  }else{
    exported.garden_beats={
      author_timezone:draft.author_timezone,
      variables:{},entities,animals:[],beats,
    };
  }
  return exported;
}


function clientBlockers() {
  const problems = [];
  if (!draft.author_name.trim()) problems.push('Say what the recipient calls you.');
  if (!draft.recipient_name.trim()) problems.push('Name who the letters are for.');
  if (!draft.passphrase_hint.trim()) problems.push('Write the required passphrase reminder.');
  if (!draft.author_timezone) problems.push('Choose the timezone used for delivery dates.');
  if (completeLetters().length === 0) problems.push('Finish and date at least one letter.');
  const completeIds = new Set(completeLetters().map(letter => letter.id));
  draft.gifts.forEach((gift, index) => {
    if (!giftIsComplete(gift, completeIds)) {
      problems.push(`Gift ${index + 1} needs an accepted drawing, a date, and a ready letter.`);
    }
  });
  if(draft.garden_story_enabled&&draft.gifts.length)
    problems.push('Use either the living Garden story or scheduled gifts, not both.');
  if(draft.garden_story_enabled&&!draft.rabbit_name.trim())
    problems.push('Name the rabbit in the living Garden story.');
  return problems;
}


function renderReview() {
  const complete = completeLetters();
  const excluded = draft.letters.length - complete.length;
  const host = $('#review-summary-host');
  host.replaceChildren();
  const block = document.createElement('div');
  block.className = 'review-block';
  const heading = document.createElement('h3');
  heading.textContent = 'what will be sealed';
  const list = document.createElement('dl');
  const entries = [
    ['recipient', draft.recipient_name || 'not named'],
    ['ready letters', String(complete.length)],
    ['incomplete drafts staying on desk', String(excluded)],
    ['scheduled gifts', String(draft.gifts.length)],
    ['living Garden story', draft.garden_story_enabled?'rabbit · third visit · autumn gift':'not added'],
    ['timezone', draft.author_timezone],
  ];
  for (const [name, value] of entries) {
    const term = document.createElement('dt');
    term.textContent = name;
    const description = document.createElement('dd');
    description.textContent = value;
    list.append(term, description);
  }
  block.append(heading, list);
  host.append(block);
  const warnings = clientBlockers();
  if (excluded) {
    warnings.push(`${excluded} incomplete letter draft${excluded === 1 ? '' : 's'} will stay on this desk and will not enter the file.`);
  }
  renderErrorList($('#review-errors'), warnings);
}


function renderErrorList(list, messages) {
  list.replaceChildren(...messages.map(message => {
    const item = document.createElement('li');
    item.textContent = message;
    return item;
  }));
}


async function validateWithService() {
  await flushSave();
  $('#validate-state').textContent = 'checking…';
  const response = await fetch('/api/author/validate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-LateLetter-CSRF': csrfToken},
    body: JSON.stringify({draft: buildExportDraft()}),
  });
  const payload = await response.json();
  if (!response.ok) {
    $('#validate-state').textContent = payload.error || 'check failed';
    return;
  }
  const errors = [...clientBlockers(), ...(payload.errors || [])];
  renderErrorList($('#review-errors'), errors);
  const story=payload.preview?.garden_story_preview;
  const storyHost=$('#garden-story-preview'),stageHost=$('#garden-story-preview-stages');
  stageHost.replaceChildren();storyHost.hidden=!story;
  if(story){
    for(const stage of story.stages){
      const item=document.createElement('li');
      item.textContent=`${stage.name}: ${stage.applied_events.join(', ')||'waiting'}`;
      stageHost.append(item);
    }
    storyHost.dataset.trace=JSON.stringify(story.trace);
  }else delete storyHost.dataset.trace;
  $('#validate-state').textContent = errors.length
    ? `${errors.length} thing${errors.length === 1 ? '' : 's'} to attend to`
    : `${payload.preview.message_count} letter${payload.preview.message_count === 1 ? '' : 's'} ready`;
}


async function appendLater(){
  const state=$('#append-state');
  const passphrase=$('#append-passphrase').value;
  const message={
    date:$('#append-date').value,
    label:$('#append-label').value,
    body:$('#append-body').value,
  };
  if(!appendBundleText||!message.date||!message.body.trim()||passphrase.length<passphraseMinimum){
    state.textContent='Choose the existing file, date and letter, then enter its passphrase.';
    return;
  }
  state.textContent='verifying and appending…';
  const response=await fetch('/api/author/append',{
    method:'POST',headers:{'Content-Type':'application/json','X-LateLetter-CSRF':csrfToken},
    body:JSON.stringify({bundle:appendBundleText,messages:[message],passphrase}),
  });
  $('#append-passphrase').value='';
  if(!response.ok){
    const payload=await response.json();
    state.textContent=(payload.issues||[payload.error||'append failed']).join(' ');
    return;
  }
  const blob=await response.blob();
  appendBundleText=await blob.text();
  const url=URL.createObjectURL(new Blob([appendBundleText],{type:'application/json'}));
  const anchor=document.createElement('a');
  anchor.href=url;anchor.download='LateLetter-appended.lateletter';anchor.click();
  URL.revokeObjectURL(url);
  $('#append-body').value='';$('#append-label').value='';
  state.textContent='updated file saved; the earlier encrypted letters were preserved.';
}


function renderExport() {
  $('#f-reminder-check').textContent = draft.passphrase_hint || '—';
  renderErrorList($('#export-blockers'), clientBlockers());
  updateExportGate();
}


function updateExportGate() {
  const passphrase = $('#pp-new').value;
  const confirmation = $('#pp-confirm').value;
  const mismatch = confirmation && passphrase !== confirmation;
  $('#e-passphrase').textContent = mismatch ? 'The two passphrases do not match.' : '';
  const length = passphrase.length;
  let level = 0;
  if (length >= passphraseMinimum) level = 1;
  if (length >= 8) level = 2;
  if (length >= 16) level = 3;
  if (length >= 24) level = 4;
  $('#pp-strength').dataset.level = String(level);
  $('#btn-export').disabled = Boolean(
    clientBlockers().length || length < passphraseMinimum
    || passphrase !== confirmation,
  );
  $('#btn-export-package').disabled=$('#btn-export').disabled;
  window.clearTimeout(adviceTimer);
  if (!passphrase) {
    $('#pp-advice').textContent = row('X1').note;
    return;
  }
  adviceTimer = window.setTimeout(async () => {
    try {
      const response = await fetch('/api/author/passphrase-advice', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-LateLetter-CSRF': csrfToken},
        body: JSON.stringify({passphrase}),
      });
      const payload = await response.json();
      if ($('#pp-new').value !== passphrase) return;
      $('#pp-advice').textContent = payload.warning || row('X1').note;
    } catch (_error) {
      $('#pp-advice').textContent = row('X1').note;
    }
  }, 220);
}


async function exportBundle(packageMode=false) {
  const passphraseInput = $('#pp-new');
  const confirmationInput = $('#pp-confirm');
  const passphrase = passphraseInput.value;
  const confirmation = confirmationInput.value;
  if (clientBlockers().length || passphrase.length < passphraseMinimum
      || passphrase !== confirmation) {
    updateExportGate();
    return;
  }
  await flushSave();
  $('#export-state').textContent = 'sealing and opening it again to verify…';
  try {
    const response = await fetch(packageMode?'/api/author/export-package':'/api/author/export', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-LateLetter-CSRF': csrfToken},
      body: JSON.stringify({draft: buildExportDraft(), passphrase, passphrase_confirm: confirmation}),
    });
    if (!response.ok) {
      const payload = await response.json();
      const problems = payload.issues || [payload.error || 'The file could not be made.'];
      renderErrorList($('#export-blockers'), problems);
      $('#export-state').textContent = 'not exported';
      return;
    }
    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const matched = disposition.match(/filename="([^"]+)"/);
    const anchor = document.createElement('a');
    const url = URL.createObjectURL(blob);
    anchor.href = url;
    anchor.download = matched ? matched[1] : 'letter.lateletter';
    anchor.hidden = true;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    const excluded = draft.letters.length - completeLetters().length;
    $('#export-state').textContent = `${packageMode?'handoff package':'file'} saved; ${completeLetters().length} ready letter${completeLetters().length === 1 ? '' : 's'} sealed${excluded ? `; ${excluded} incomplete draft${excluded === 1 ? '' : 's'} stayed on this desk` : ''}. Tell one person this file exists.`;
  } catch (error) {
    $('#export-state').textContent = `export failed: ${error.message}`;
  } finally {
    passphraseInput.value = '';
    confirmationInput.value = '';
    updateExportGate();
  }
}


function bindControls() {
  bindPeopleInputs();
  bindLetterInputs();
  $('#btn-back').addEventListener('click', () => moveStage(-1));
  $('#btn-next').addEventListener('click', () => moveStage(1));
  $('#btn-resume').addEventListener('click', () => showStage('people'));
  $('#btn-start-fresh').addEventListener('click', async () => {
    if (hasMeaningfulDraft() && !window.confirm('Clear the draft on this desk and start again?')) return;
    draft = normalizeDraft({});
    activeLetterId = draft.letters[0].id;
    maxVisitedStage = 0;
    markChanged();
    renderAll();
    await flushSave();
    showStage('people');
  });
  $('#btn-add-gift').addEventListener('click', () => {
    draft.gifts.push(newGift());
    markChanged();
    renderGifts();
  });
  $('#f-story-arc').addEventListener('change',event=>{
    draft.garden_story_enabled=event.currentTarget.checked;
    markChanged();renderGifts();
  });
  $('#f-rabbit-name').addEventListener('input',event=>{
    draft.rabbit_name=event.currentTarget.value;
    markChanged();
  });
  $('#btn-validate').addEventListener('click', validateWithService);
  $('#pp-new').addEventListener('input', updateExportGate);
  $('#pp-confirm').addEventListener('input', updateExportGate);
  $('#btn-export').addEventListener('click',()=>exportBundle(false));
  $('#btn-export-package').addEventListener('click',()=>exportBundle(true));
  $('#append-file').addEventListener('change',async event=>{
    const file=event.currentTarget.files?.[0]||null;
    appendBundleText=file?await file.text():null;
    $('#append-state').textContent=file?`ready to append to ${file.name}`:'';
  });
  $('#btn-append').addEventListener('click',()=>appendLater().catch(error=>{
    $('#append-passphrase').value='';
    $('#append-state').textContent=`append failed: ${error.message}`;
  }));
  new ResizeObserver(() => {
    if (activeStage === 'letters') renderLetterPreview();
  }).observe($('#letter-preview'));
}


function renderAll() {
  renderPeople();
  renderResumeSummary();
  renderLetterEditor();
  renderGifts();
  renderReview();
  renderExport();
  renderProgress();
}


async function init() {
  const [questionnaireResponse, sessionResponse] = await Promise.all([
    fetch('/api/author/questionnaire'),
    fetch('/api/author/session'),
  ]);
  if (!questionnaireResponse.ok) throw new Error('approved questionnaire could not be loaded');
  if (!sessionResponse.ok) throw new Error('author session could not be loaded');
  questionnaire = await questionnaireResponse.json();
  const session = await sessionResponse.json();
  rows = new Map(questionnaire.rows.map(value => [value.id, value]));
  stages = questionnaire.stages;
  giftChoices = row('G2').options;
  passphraseMinimum = questionnaire.passphrase_policy.minimum_length;
  csrfToken = session.csrf_token;
  revision = session.revision;
  draft = normalizeDraft(session.draft);
  activeLetterId = draft.letters[0].id;
  draftVersion = 1;
  savedVersion = 1;
  applyCanonicalCopy();
  populateTimezones();
  bindControls();
  renderAll();
  setSaveState('saved', hasMeaningfulDraft() ? 'saved on this machine' : 'empty desk');
  showStage('resume');
}


init().catch(error => {
  setSaveState('offline', 'author desk unavailable');
  showBanner(`The author desk could not start: ${error.message}`);
});
