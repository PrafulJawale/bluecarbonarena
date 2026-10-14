# Testing
Backend: `pytest backend/tests -q` (calc known-value, invalid inputs, auth, project flow, issuance guard, cross-user). Frontend: `npm run build` (strict TS). Browser E2E journeys are described in PRESENTATION_GUIDE; Playwright not run in this sandbox — manual verification via live preview + curl integration checks documented in README.
