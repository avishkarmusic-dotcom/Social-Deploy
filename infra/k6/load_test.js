/**
 * k6 load test — Tryvanta Social
 * SLOs: inbox p95 < 300ms, error rate < 2%, AI p99 < 5s
 *
 * Run:
 *   k6 run --env BASE=https://api.tryvanta.social \
 *          --env TOKEN=your-session-jwt \
 *          infra/k6/load_test.js
 */
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

const BASE  = __ENV.BASE  || "http://localhost:8000";
const TOKEN = __ENV.TOKEN || "dev-token";
const H = { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" };

const inboxP95 = new Trend("inbox_p95");
const aiP99    = new Trend("assistant_p99");
const errors   = new Rate("error_rate");

export const options = {
  stages: [
    { duration: "2m",  target: 50  },   // ramp
    { duration: "10m", target: 50  },   // hold
    { duration: "2m",  target: 150 },   // spike
    { duration: "5m",  target: 150 },   // hold spike
    { duration: "2m",  target: 0   },   // ramp down
  ],
  thresholds: {
    inbox_p95:       ["p(95)<300"],    // 300ms inbox SLO
    assistant_p99:   ["p(99)<5000"],   // 5s AI SLO
    error_rate:      ["rate<0.02"],    // <2% errors
    http_req_failed: ["rate<0.02"],
  },
};

export default function () {
  const roll = Math.random();

  if (roll < 0.50) {
    // Inbox — the hot path, must be fast
    const r = http.get(`${BASE}/v1/inbox?sort=opportunity&limit=50`, { headers: H });
    inboxP95.add(r.timings.duration);
    check(r, { "inbox 200": (x) => x.status === 200 }) || errors.add(1);

  } else if (roll < 0.65) {
    // Search
    const terms = ["investor", "recruiter", "review", "client", "proposal"];
    const q = terms[Math.floor(Math.random() * terms.length)];
    const r = http.get(`${BASE}/v1/search?q=${q}&limit=20`, { headers: H });
    check(r, { "search 200": (x) => x.status === 200 }) || errors.add(1);

  } else if (roll < 0.80) {
    // Contacts — CRM load
    const r = http.get(`${BASE}/v1/contacts?sort=decay_risk&limit=50`, { headers: H });
    check(r, { "contacts 200": (x) => x.status === 200 }) || errors.add(1);

  } else if (roll < 0.92) {
    // Health checks (LB simulation)
    http.get(`${BASE}/healthz`);

  } else {
    // AI Assistant — expensive, ~10% mix is realistic
    const questions = [
      "What should I answer first today?",
      "Which clients have gone quiet?",
      "Summarise what needs my attention",
    ];
    const q = questions[Math.floor(Math.random() * questions.length)];
    const r = http.post(
      `${BASE}/v1/ai/assistant`,
      JSON.stringify({ question: q }),
      { headers: H, timeout: "12s" }
    );
    aiP99.add(r.timings.duration);
    check(r, { "assistant 200": (x) => x.status === 200 }) || errors.add(1);
  }

  sleep(Math.random() * 2 + 0.5);  // 0.5–2.5s think time
}
