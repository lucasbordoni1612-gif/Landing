// Teste de stress do Aragog: POST /api/v1/search do "processing" (pendente) até "concluded",
// somando quantas buscas cada crawler (gontijo, guanabara, jca) retornou viagens.
//
// Uso:
//   ARAGOG_TOKEN=<bearer> k6 run k6/aragog-search-stress.js
//
// Variáveis opcionais (-e NOME=valor ou ambiente):
//   BASE_URL          URL do Aragog (padrão: prod)
//   CRAWLERS          lista separada por vírgula (padrão: gontijo,guanabara,jca)
//   RPM               buscas novas iniciadas por minuto no pico (padrão: 400)
//   RAMP_UP           tempo de rampa de 0 até RPM (padrão: 1m)
//   HOLD              tempo sustentando RPM (padrão: 5m)
//   STAGES            sobrescreve a rampa: "duração:rpm,..." (ex.: 1m:200,3m:400,3m:800,1m:0)
//   MAX_VUS           teto de VUs para sustentar a taxa (padrão: 1000)
//   POLL_INTERVAL_MS  intervalo entre polls (padrão: 1000)
//   MAX_WAIT_MS       tempo máximo esperando "concluded" (padrão: 60000)
//   DATE_FROM/DATE_TO janela de datas sorteadas (padrão: 2026-12-01 a 2027-01-31)
//
// Cada iteração é UMA busca completa (primeiro POST + polls até "concluded"). Como cada busca
// faz ~3 polls, 400 buscas/min geram na ordem de 1.300+ requisições HTTP/min.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = (__ENV.BASE_URL || 'https://aragog-prod-826349623958.southamerica-east1.run.app').replace(/\/$/, '');
const TOKEN = __ENV.ARAGOG_TOKEN;
const CRAWLERS = (__ENV.CRAWLERS || 'gontijo,guanabara,jca').split(',').map((c) => c.trim()).filter(Boolean);
const POLL_INTERVAL_MS = Number(__ENV.POLL_INTERVAL_MS || 1000);
const MAX_WAIT_MS = Number(__ENV.MAX_WAIT_MS || 60000);
const RPM = Number(__ENV.RPM || 400);
const MAX_VUS = Number(__ENV.MAX_VUS || 1000);
const DATE_FROM = __ENV.DATE_FROM || '2026-12-01';
const DATE_TO = __ENV.DATE_TO || '2027-01-31';

// IDs do catálogo GET /api/v1/stations do Aragog.
const STATIONS = {
  SAO: '1', // São Paulo, SP - Rodoviária do Tietê
  BHZ: '61', // Belo Horizonte, MG - Terminal Gov. Israel Pinheiro (Tergip)
  RIO: '55', // Rio de Janeiro, RJ - Novo Rio
  CWB: '53', // Curitiba, PR - Rodoviária
  CPQ: '3', // Campinas, SP - Terminal Ramos de Azevedo
  FLN: '65', // Florianópolis, SC - Rodoviária
  SSA: '73', // Salvador, BA - Rodoviária
  JOI: '192', // Joinville, SC - Terminal Harold Nielson
  RAO: '5', // Ribeirão Preto, SP - Rodoviária
  RCG: '124', // Rio de Janeiro, RJ - Campo Grande
  // Extras (estações conhecidas, fora da lista de volume)
  BSB: '72', // Brasília, DF - Terminal Interestadual
  GYN: '350', // Goiânia, GO - Rodoviária
  VIX: '888', // Vitória, ES - Rodoviária
  JDF: '57', // Juiz de Fora, MG - Terminal São Dimas
  UDI: '392', // Uberlândia, MG - Rodoviária
  LDB: '837', // Londrina, PR - Terminal José Garcia Villar
  SSZ: '2', // Santos, SP - Rodoviária
  SJK: '29', // São José dos Campos, SP - Rodoviária
  POA: '380', // Porto Alegre, RS - Terminal Veppo
  REC: '669', // Recife, PE - Rodoviária (TIP)
  BCU: '96', // Balneário Camboriú, SC - Rodoviária
};

// [origem, destino, volume]. O sorteio dos trechos é proporcional ao volume.
const LISTED_ROUTES = [
  ['BHZ', 'SAO', 1114],
  ['SAO', 'BHZ', 797],
  ['RIO', 'SAO', 792],
  ['SAO', 'RIO', 548],
  ['CWB', 'SAO', 528],
  ['SAO', 'CWB', 507],
  ['CPQ', 'SAO', 417],
  ['SAO', 'CPQ', 307],
  ['BHZ', 'RIO', 306],
  ['RIO', 'BHZ', 275], // volume não informado: assumido
  ['FLN', 'CWB', 247],
  ['CWB', 'FLN', 243],
  ['SSA', 'SAO', 230],
  ['JOI', 'CWB', 221],
  ['BHZ', 'CWB', 217],
  ['SAO', 'SSA', 208],
  ['SAO', 'RAO', 194],
  ['SAO', 'RCG', 192],
  ['CPQ', 'BHZ', 190], // volume não informado: assumido
  // Extras: sem volume real, peso baixo (o inverso é gerado automaticamente).
  ['SAO', 'BSB', 100],
  ['BSB', 'GYN', 100],
  ['BHZ', 'VIX', 100],
  ['RIO', 'VIX', 100],
  ['RIO', 'JDF', 100],
  ['SAO', 'UDI', 100],
  ['SAO', 'LDB', 100],
  ['SAO', 'SSZ', 100],
  ['SAO', 'SJK', 100],
  ['RIO', 'SJK', 100],
  ['CWB', 'POA', 100],
  ['FLN', 'POA', 100],
  ['CWB', 'BCU', 100],
  ['SSA', 'REC', 100],
  ['BHZ', 'BSB', 100],
];

// Trecho listado sem o sentido inverso ganha o inverso automaticamente, com o mesmo volume.
function buildRoutes() {
  const routes = LISTED_ROUTES.map(([from, to, weight]) => ({ from, to, weight }));
  const known = new Set(routes.map((r) => `${r.from}-${r.to}`));
  for (const [from, to, weight] of LISTED_ROUTES) {
    if (!known.has(`${to}-${from}`)) {
      known.add(`${to}-${from}`);
      routes.push({ from: to, to: from, weight });
    }
  }
  return routes.map((r) => ({
    key: `${r.from}-${r.to}`,
    origin: STATIONS[r.from],
    destination: STATIONS[r.to],
    weight: r.weight,
  }));
}
const ROUTES = buildRoutes();
const TOTAL_WEIGHT = ROUTES.reduce((sum, r) => sum + r.weight, 0);

const searchesStarted = new Counter('searches_started');
const searchesConcluded = new Counter('searches_concluded');
const searchesTimedOut = new Counter('searches_timed_out');
const searchesFailed = new Counter('searches_failed');
const searchConcludedRate = new Rate('search_concluded_rate');
const timeToConcluded = new Trend('search_time_to_concluded', true);
const pollsPerSearch = new Trend('search_polls');
// Por crawler (tag crawler) e por trecho (tag route):
const crawlerReturned = new Counter('crawler_returned'); // buscas concluídas em que o crawler trouxe >= 1 viagem
const crawlerEmpty = new Counter('crawler_empty'); // buscas concluídas em que o crawler não trouxe nada
const crawlerTrips = new Counter('crawler_trips'); // total de viagens trazidas
const crawlerReturnRate = new Rate('crawler_return_rate');
const crawlerFirstResult = new Trend('crawler_time_to_first_result', true);

function parseStages(spec) {
  return spec.split(',').map((s) => {
    const [duration, target] = s.split(':');
    return { duration: duration.trim(), target: Number(target) };
  });
}

// Limiares "sempre verdadeiros" só para o k6 expor os sub-métricos por tag no resumo.
function tagThresholds() {
  const t = {};
  for (const c of CRAWLERS) {
    t[`crawler_returned{crawler:${c}}`] = ['count>=0'];
    t[`crawler_empty{crawler:${c}}`] = ['count>=0'];
    t[`crawler_trips{crawler:${c}}`] = ['count>=0'];
    t[`crawler_time_to_first_result{crawler:${c}}`] = ['p(95)>=0'];
    for (const r of ROUTES) t[`crawler_returned{crawler:${c},route:${r.key}}`] = ['count>=0'];
  }
  for (const r of ROUTES) t[`searches_concluded{route:${r.key}}`] = ['count>=0'];
  return t;
}

export const options = {
  scenarios: {
    stress: {
      // Taxa de chegada fixa (modelo aberto): o k6 inicia RPM buscas por minuto mesmo que o
      // Aragog fique lento, em vez de desacelerar junto com ele.
      executor: 'ramping-arrival-rate',
      startRate: 0,
      timeUnit: '1m',
      preAllocatedVUs: Math.min(MAX_VUS, Math.max(50, Math.ceil(RPM / 2))),
      maxVUs: MAX_VUS,
      stages: parseStages(__ENV.STAGES || `${__ENV.RAMP_UP || '1m'}:${RPM},${__ENV.HOLD || '5m'}:${RPM},30s:0`),
      gracefulStop: `${Math.ceil(MAX_WAIT_MS / 1000) + 10}s`,
    },
  },
  thresholds: Object.assign(
    {
      dropped_iterations: ['count==0'], // > 0 = faltou VU para sustentar a taxa (aumente MAX_VUS)
      search_concluded_rate: ['rate>0.95'],
      search_time_to_concluded: ['p(95)<30000'],
      http_req_failed: ['rate<0.05'],
    },
    tagThresholds(),
  ),
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function pickRoute() {
  let n = Math.random() * TOTAL_WEIGHT;
  for (const r of ROUTES) {
    n -= r.weight;
    if (n < 0) return r;
  }
  return ROUTES[ROUTES.length - 1];
}

const DAY_MS = 86400000;
function randomDate() {
  const from = Date.parse(`${DATE_FROM}T00:00:00Z`);
  const days = Math.round((Date.parse(`${DATE_TO}T00:00:00Z`) - from) / DAY_MS) + 1;
  return new Date(from + Math.floor(Math.random() * days) * DAY_MS).toISOString().slice(0, 10);
}

export function setup() {
  if (!TOKEN) throw new Error('Defina ARAGOG_TOKEN (bearer token do Aragog).');
}

export default function () {
  const route = pickRoute();
  const body = JSON.stringify({
    crawlers: CRAWLERS,
    origin: route.origin,
    destination: route.destination,
    departure_date: randomDate(),
  });
  const params = {
    headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
    tags: { route: route.key },
    timeout: '60s',
  };
  const routeTag = { route: route.key };

  const startedAt = Date.now();
  const firstSeen = {};
  let polls = 0;
  let outcome = 'timeout';
  let results = [];
  searchesStarted.add(1, routeTag);

  // A busca é assíncrona: o mesmo POST é repetido até o status sair de "processing".
  while (Date.now() - startedAt < MAX_WAIT_MS) {
    const res = http.post(`${BASE_URL}/api/v1/search`, body, params);
    polls++;
    let data = null;
    if (res.status === 200) {
      try {
        data = res.json();
      } catch (_) {
        data = null;
      }
    }
    if (!check(res, { 'search respondeu 200 com JSON': () => data !== null })) {
      outcome = 'failed';
      break;
    }
    results = data.results || [];
    const elapsed = Date.now() - startedAt;
    for (const trip of results) {
      if (firstSeen[trip.crawler] === undefined) {
        firstSeen[trip.crawler] = elapsed;
        crawlerFirstResult.add(elapsed, { crawler: trip.crawler, route: route.key });
      }
    }
    if (data.status === 'concluded') {
      outcome = 'concluded';
      break;
    }
    if (data.status !== 'processing' && data.status !== 'pending') {
      outcome = 'failed';
      break;
    }
    sleep(POLL_INTERVAL_MS / 1000);
  }

  pollsPerSearch.add(polls, routeTag);
  searchConcludedRate.add(outcome === 'concluded', routeTag);
  if (outcome === 'concluded') {
    searchesConcluded.add(1, routeTag);
    timeToConcluded.add(Date.now() - startedAt, routeTag);
    const tripsByCrawler = {};
    for (const trip of results) tripsByCrawler[trip.crawler] = (tripsByCrawler[trip.crawler] || 0) + 1;
    for (const c of CRAWLERS) {
      const tags = { crawler: c, route: route.key };
      const n = tripsByCrawler[c] || 0;
      crawlerReturnRate.add(n > 0, tags);
      if (n > 0) {
        crawlerReturned.add(1, tags);
        crawlerTrips.add(n, tags);
      } else {
        crawlerEmpty.add(1, tags);
      }
    }
  } else if (outcome === 'timeout') {
    searchesTimedOut.add(1, routeTag);
  } else {
    searchesFailed.add(1, routeTag);
  }
}

export function handleSummary(data) {
  const m = data.metrics;
  const count = (name) => (m[name] && m[name].values.count) || 0;
  const trend = (name, stat) => (m[name] && m[name].values[stat] !== undefined ? m[name].values[stat] : null);
  const ms = (v) => (v === null ? '-' : v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${Math.round(v)}ms`);
  const pct = (a, b) => (b ? `${((100 * a) / b).toFixed(1)}%` : '-');
  const pad = (s, n) => String(s).padEnd(n);
  const padL = (s, n) => String(s).padStart(n);

  const concluded = count('searches_concluded');
  const lines = [];
  lines.push('');
  lines.push('===== Aragog /api/v1/search — processing -> concluded =====');
  const minutes = data.state.testRunDurationMs / 60000;
  lines.push(`Buscas iniciadas : ${count('searches_started')} (média ${(count('searches_started') / minutes).toFixed(0)}/min; não iniciadas por falta de VU: ${count('dropped_iterations')})`);
  lines.push(`Concluídas       : ${concluded} (${pct(concluded, count('searches_started'))})`);
  lines.push(`Timeout (>${MAX_WAIT_MS / 1000}s)   : ${count('searches_timed_out')}`);
  lines.push(`Falhas           : ${count('searches_failed')}`);
  lines.push(
    `Tempo até concluded: avg ${ms(trend('search_time_to_concluded', 'avg'))} | med ${ms(trend('search_time_to_concluded', 'med'))}` +
      ` | p95 ${ms(trend('search_time_to_concluded', 'p(95)'))} | p99 ${ms(trend('search_time_to_concluded', 'p(99)'))}` +
      ` | max ${ms(trend('search_time_to_concluded', 'max'))}`,
  );
  lines.push(`Polls por busca  : avg ${(trend('search_polls', 'avg') || 0).toFixed(1)} | max ${trend('search_polls', 'max') || 0}`);
  lines.push(
    `HTTP             : ${count('http_reqs')} reqs (${(count('http_reqs') / minutes).toFixed(0)}/min) | falha ${(((m.http_req_failed && m.http_req_failed.values.rate) || 0) * 100).toFixed(2)}%` +
      ` | duração p95 ${ms(trend('http_req_duration', 'p(95)'))}`,
  );

  lines.push('');
  lines.push('--- Retorno por crawler (sobre buscas concluídas) ---');
  lines.push(`${pad('crawler', 12)}${padL('retornou', 10)}${padL('vazio', 8)}${padL('% retorno', 11)}${padL('viagens', 10)}${padL('1º result. p95', 16)}`);
  for (const c of CRAWLERS) {
    const ret = count(`crawler_returned{crawler:${c}}`);
    const empty = count(`crawler_empty{crawler:${c}}`);
    lines.push(
      `${pad(c, 12)}${padL(ret, 10)}${padL(empty, 8)}${padL(pct(ret, ret + empty), 11)}${padL(count(`crawler_trips{crawler:${c}}`), 10)}` +
        `${padL(ms(trend(`crawler_time_to_first_result{crawler:${c}}`, 'p(95)')), 16)}`,
    );
  }

  lines.push('');
  lines.push('--- Buscas concluídas em que cada crawler retornou, por trecho ---');
  lines.push(`${pad('trecho', 10)}${padL('concluídas', 12)}${CRAWLERS.map((c) => padL(c, 12)).join('')}`);
  for (const r of ROUTES) {
    lines.push(
      `${pad(r.key, 10)}${padL(count(`searches_concluded{route:${r.key}}`), 12)}` +
        CRAWLERS.map((c) => padL(count(`crawler_returned{crawler:${c},route:${r.key}}`), 12)).join(''),
    );
  }

  const failed = Object.keys(m).filter((name) => {
    const th = m[name].thresholds || {};
    return Object.keys(th).some((k) => !th[k].ok);
  });
  lines.push('');
  lines.push(failed.length ? `Thresholds violados: ${failed.join(', ')}` : 'Thresholds: todos ok');
  lines.push('');

  return {
    stdout: lines.join('\n'),
    'aragog-search-summary.json': JSON.stringify(data, null, 2),
  };
}
