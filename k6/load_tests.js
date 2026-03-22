import { check } from 'k6';
import http from 'k6/http';

export const options = {
    vus: 100, // Virtual Users
    duration: '30s', // Duration of the load test
    thresholds: {
        'http_req_duration': ['p(95)<200'], // 95% of requests must complete below 200ms
    },
};

export default function () {
    const res = http.get('https://api.example.com/endpoint');
    check(res, {
        'status is 200': (r) => r.status === 200,
    });
}