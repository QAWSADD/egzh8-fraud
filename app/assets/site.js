const el = id => document.getElementById(id);
const form = el('transaction-form');
const inputs = ['amount', 'time', 'count_10m', 'seconds_since_previous'].map(el);
const exampleButtons = Array.from(document.querySelectorAll('[data-example]'));
const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 });
const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 2 });
const metric = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const copy = {
  ru: {
    empty: 'Ожидает проверки', pending: 'Проверяем операцию…',
    clear: 'Операция без сигнала риска', review: 'Нужна ручная проверка',
    flagged: 'Подозрительная операция', invalid: 'Проверьте данные',
    choose: 'Выберите один из примеров или заполните форму.',
    offline: 'Не удалось обратиться к API. Проверьте, что сервер запущен.',
    threshold: 'Порог', holdout: 'Тестовые операции',
    precision: 'Точность', recall: 'Полнота', baseline: 'Доля мошенничества в тесте',
    amount: 'Сумма', correctField: 'Проверьте поле', percentagePoints: 'п. п.',
    caught: (tp, positives) => `Обнаружено ${tp} из ${positives} мошеннических операций.`,
  },
  kk: {
    empty: 'Тексеру күтілуде', pending: 'Операция тексерілуде…',
    clear: 'Қауіп белгісі анықталмады', review: 'Қолмен тексеру қажет',
    flagged: 'Күмәнді операция', invalid: 'Деректерді тексеріңіз',
    choose: 'Мысалды таңдаңыз немесе өрістерді толтырыңыз.',
    offline: 'API қолжетімсіз. Сервердің іске қосылғанын тексеріңіз.',
    threshold: 'Шек', holdout: 'Тест операциялары',
    precision: 'Дәлдік', recall: 'Толықтық', baseline: 'Тесттегі алаяқтық үлесі',
    amount: 'Сома', correctField: 'Өрісті тексеріңіз', percentagePoints: 'п. т.',
    caught: (tp, positives) => `${positives} алаяқтық операцияның ${tp}-сы анықталды.`,
  },
};
const rulesKk = [
  '',
  'Өрістердің құрылымы мен түрлерін тексеріңіз.',
  'Сома 0 мен 100 000 000 аралығында болуы керек.',
  'Уақыт теріс емес бүтін секундпен көрсетіледі.',
  'Модельге 28 жасырын компонент беріледі.',
  '10 минуттағы операция саны 1–10 000 аралығында болуы керек.',
  'Алдыңғы операциядан кейінгі уақытты тексеріңіз.',
  'Алдыңғы операцияның аралығы 10 минуттағы операция санына сәйкес келмейді.',
  'V1–V28 компоненттері сан немесе бос мән болуы керек.',
  'Операция оқу бақылау тізімінен табылды.',
  'Операциялар жиі және қысқа аралықпен жасалған.',
  'Операция сомасы үлкен және операция жиілігі жоғары.',
  'Модель бағалау үшін жасырын компоненттер жеткіліксіз.',
  'Баға шекке жақын. Қолмен тексеру қажет.',
  'Модель бағасы шектен жоғары. Операцияны тексеру қажет.',
  'Модель бағасы шектен төмен, қосымша белгі анықталмады.',
  'Сома оқыту жиынының 99,5-процентилінен жоғары.',
  'Уақыт оқу жиынының екі күндік аралығынан тыс.',
  'Алдыңғы операциямен аралығы қысқа.',
  'Он минутта жасалған операция саны жоғары.',
  'Бос компоненттер оқыту медианасымен толтырылды.',
];

let language = 'ru';
let examples = [];
let evaluation = null;
let currentState = 'empty';
let note = '';
let selected = '';
let revision = 0;
let busy = false;
const componentFields = [];
for (let i = 1; i <= 28; i++) {
  const label = document.createElement('label');
  label.textContent = `V${i}`;
  const input = document.createElement('input');
  input.type = 'number';
  input.step = 'any';
  input.inputMode = 'decimal';
  label.append(input);
  el('component-grid').append(label);
  componentFields.push(input);
}

const translated = [
  ...Array.from(document.querySelectorAll('[data-kk]'), node => ({
    node, property: 'textContent', ru: node.textContent, kk: node.dataset.kk,
  })),
  ...Array.from(document.querySelectorAll('[data-kk-placeholder]'), node => ({
    node, property: 'placeholder', ru: node.placeholder, kk: node.dataset.kkPlaceholder,
  })),
];

function setExample(id) {
  selected = id;
  for (const button of exampleButtons) {
    button.setAttribute('aria-pressed', String(button.dataset.example === selected));
  }
}

function fill(example) {
  for (const field of inputs) {
    field.value = example.payload[field.id] ?? '';
    field.removeAttribute('aria-invalid');
  }
  componentFields.forEach((field, i) => { field.value = example.payload.components?.[i] ?? ''; });
  el('watchlist_match').checked = example.payload.watchlist_match ?? false;
  setExample(example.id);
}

function payload() {
  const values = Object.fromEntries(inputs.map(field => [field.id, field.value === '' ? null : field.valueAsNumber]));
  return {
    ...values, watchlist_match: el('watchlist_match').checked,
    components: componentFields.map(field => field.value === '' ? null : field.valueAsNumber),
  };
}

function textRule(rule) {
  return language === 'kk' ? rulesKk[Number(rule.id.slice(1))] || rule.reason : rule.reason;
}

function renderList(id, values) {
  el(id).replaceChildren(...values.map(value => {
    const item = document.createElement('li');
    item.textContent = value;
    return item;
  }));
}

function renderResult() {
  const labels = copy[language];
  const rules = evaluation?.rules ?? [];
  const risk = evaluation?.probability;
  el('result').dataset.status = currentState;
  el('decision').textContent = labels[currentState];
  el('reason').textContent = rules[0] ? textRule(rules[0]) : note || (currentState === 'empty' ? labels.choose : '');
  el('reason-title').hidden = rules.length === 0;
  el('risk').hidden = risk == null;
  el('risk-label').hidden = risk == null;
  el('risk-scale').hidden = risk == null;
  if (risk != null) {
    el('risk').textContent = risk > 0 && risk < 0.00005 ? '< 0,01%' : percent.format(risk);
    const { threshold, review_width } = evaluation;
    const rail = el('risk-scale').querySelector('.rail');
    // Show low probability bands clearly while keeping the numeric labels exact.
    const position = value => Math.log1p(1000 * Math.max(0, Math.min(1, value))) / Math.log(1001) * 100 + '%';
    rail.style.setProperty('--score', position(risk));
    rail.style.setProperty('--low', position(threshold - review_width));
    rail.style.setProperty('--high', position(threshold + review_width));
    el('threshold-label').textContent = `${labels.threshold} ${percent.format(threshold)}`;
  }
  el('trace').hidden = !evaluation;
  if (!evaluation) el('trace').open = false;
  renderList('rules', rules.map(rule => `${rule.id} · ${textRule(rule)}`));
  const contributions = evaluation?.top_features ?? [];
  el('features').hidden = contributions.length === 0;
  renderList('feature-list', contributions.map(({ feature, impact }) =>
    `${feature === 'Amount' ? labels.amount : feature}: ${impact > 0 ? '+' : ''}${number.format(impact * 100)} ${labels.percentagePoints}`
  ));
  el('json').textContent = evaluation ? JSON.stringify(evaluation, null, 2) : '';
}

async function run({ demo = false, focus = true } = {}) {
  if (busy) return;
  const invalid = demo ? null : [...inputs, ...componentFields].find(field => !field.validity.valid);
  if (invalid) {
    if (el('advanced').contains(invalid)) el('advanced').open = true;
    invalid.setAttribute('aria-invalid', 'true');
    currentState = 'invalid';
    evaluation = null;
    note = `${copy[language].correctField} «${invalid.labels[0].textContent.trim()}».`;
    renderResult();
    invalid.reportValidity();
    invalid.focus();
    return;
  }

  busy = true;
  const requestRevision = revision;
  const values = payload();
  evaluation = null;
  currentState = 'pending';
  note = '';
  el('predict-button').disabled = true;
  exampleButtons.forEach(button => { button.disabled = true; });
  renderResult();
  if (focus) el('result-title').focus();

  try {
    const response = await fetch('/predict', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
    });
    if (!response.ok && response.status !== 422) throw Error(String(response.status));
    const next = await response.json();
    if (revision !== requestRevision) return;
    evaluation = next;
    currentState = next.status;
  } catch {
    if (revision !== requestRevision) return;
    currentState = 'empty';
    note = copy[language].offline;
  } finally {
    busy = false;
    el('predict-button').disabled = false;
    exampleButtons.forEach(button => { button.disabled = !examples.length; });
    renderResult();
  }
}

function svgNode(name, attributes, text) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (text) node.textContent = text;
  return node;
}

function renderCurve(info) {
  const labels = copy[language];
  const curve = el('pr-curve');
  const x = v => 44 + v * 536;
  const y = v => 174 - v * 153;
  const pieces = [];
  for (let i = 0; i <= 5; i++) {
    const tick = i / 5;
    const text = number.format(tick);
    pieces.push(
      svgNode('line', { x1: x(tick), x2: x(tick), y1: y(0), y2: y(1), class: 'gridline' }),
      svgNode('line', { x1: x(0), x2: x(1), y1: y(tick), y2: y(tick), class: 'gridline' }),
      svgNode('text', { x: x(tick), y: 190, 'text-anchor': 'middle' }, text),
      svgNode('text', { x: 36, y: y(tick) + 4, 'text-anchor': 'end' }, text),
    );
  }
  pieces.push(
    svgNode('path', { d: `M${x(0)} ${y(1)}V${y(0)}H${x(1)}`, class: 'axis', fill: 'none' }),
    svgNode('line', { x1: x(0), x2: x(1), y1: y(info.test_prevalence), y2: y(info.test_prevalence), class: 'baseline' }),
    svgNode('polyline', { points: info.pr_curve.map(([recall, precision]) => `${x(recall)},${y(precision)}`).join(' '), class: 'curve-line' }),
    svgNode('text', { x: 312, y: 206, 'text-anchor': 'middle' }, `${labels.recall} (Recall)`),
    svgNode('text', { x: 13, y: 94, 'text-anchor': 'middle', transform: 'rotate(-90 13 94)' }, `${labels.precision} (Precision)`),
  );
  curve.replaceChildren(...pieces);
}

let benchmark;
function renderMetrics() {
  if (!benchmark) return;
  const { dataset, test, splits, test_prevalence, threshold } = benchmark;
  const labels = copy[language];
  el('prevalence').textContent = percent.format(dataset.prevalence);
  el('metric-ap').textContent = metric.format(test.average_precision);
  el('metric-recall').textContent = metric.format(test.recall);
  el('metric-precision').textContent = metric.format(test.precision);
  for (const key of ['tn', 'fp', 'fn', 'tp']) el(key).textContent = number.format(test[key]);
  el('metrics-caption').textContent = `${labels.holdout}: ${number.format(splits.test.rows)}. ${labels.caught(test.tp, test.tp + test.fn)} ${labels.baseline}: ${percent.format(test_prevalence)}. ${labels.threshold}: ${percent.format(threshold)}.`;
  renderCurve(benchmark);
}

function setLanguage(value) {
  language = value;
  document.documentElement.lang = language;
  for (const item of translated) item.node[item.property] = item[language];
  for (const button of document.querySelectorAll('[data-language]')) {
    button.setAttribute('aria-pressed', String(button.dataset.language === language));
  }
  renderMetrics();
  renderResult();
}

form.addEventListener('input', event => {
  event.target.removeAttribute('aria-invalid');
  revision++;
  setExample('');
  evaluation = null;
  currentState = 'empty';
  note = '';
  renderResult();
});
form.addEventListener('submit', event => { event.preventDefault(); run(); });
for (const button of exampleButtons) button.addEventListener('click', () => {
  fill(examples.find(example => example.id === button.dataset.example));
  run({ demo: true });
});
for (const button of document.querySelectorAll('[data-language]')) {
  button.addEventListener('click', () => setLanguage(button.dataset.language));
}

async function get(path) {
  const response = await fetch(path);
  if (!response.ok) throw Error(String(response.status));
  return response.json();
}

get('/metrics').then(data => {
  benchmark = data;
  renderMetrics();
}).catch(() => {});
get('/examples').then(data => {
  examples = data;
  exampleButtons.forEach(button => { button.disabled = busy; });
  if (revision === 0 && !busy) {
    fill(examples.find(example => example.id === 'normal'));
    run({ demo: true, focus: false });
  }
}).catch(() => {
  if (currentState === 'empty') {
    note = copy[language].offline;
    renderResult();
  }
});
