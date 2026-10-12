import http from 'k6/http';
import { check, sleep, fail } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 50 }, // Ramp up to 50 users
    { duration: '1m', target: 50 },  // Stay at 50 users
    { duration: '30s', target: 0 },  // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'], // 95% of requests must complete below 500ms
    http_req_failed: ['rate<0.01'],   // Error rate must be less than 1%
  },
};

const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8000').replace(/\/$/, '') + '/v1';
const QUERY = __ENV.SEARCH_QUERY || 'tax';

export function setup() {
  const response = http.get(`${BASE_URL}/search/professionals?q=${encodeURIComponent(QUERY)}`);
  if (response.status !== 200) fail(`Search readiness failed: HTTP ${response.status}`);
  const body = response.json();
  if (!Array.isArray(body.items)) fail('Search returned an unexpected response schema');
  if (__ENV.REQUIRE_RESULTS === 'true' && body.items.length === 0) fail('Seed representative published profiles before measuring search');
}


export default function () {
  // Simulate professional searching
  const res = http.get(`${BASE_URL}/search/professionals?q=${encodeURIComponent(QUERY)}`);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'transaction time OK': (r) => r.timings.duration < 500,
  });

  sleep(1);
}
